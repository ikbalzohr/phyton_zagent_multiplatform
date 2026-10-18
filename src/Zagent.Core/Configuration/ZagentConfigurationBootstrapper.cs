using Zagent.Core.Network;
using Zagent.Shared.Configuration;
using Zagent.Shared.Installation;

namespace Zagent.Core.Configuration;

public sealed class ZagentConfigurationBootstrapper
{
    private readonly ZagentConfigurationEngine _engine;
    private readonly AtomicJsonFileStore _store;
    private readonly TimeProvider _timeProvider;
    private readonly ZagentPortAllocator _portAllocator;

    public ZagentConfigurationBootstrapper(
        ZagentConfigurationEngine? engine = null,
        AtomicJsonFileStore? store = null,
        TimeProvider? timeProvider = null,
        ZagentPortAllocator? portAllocator = null)
    {
        _store = store ?? new AtomicJsonFileStore();
        _engine = engine ?? new ZagentConfigurationEngine(store: _store);
        _timeProvider = timeProvider ?? TimeProvider.System;
        _portAllocator = portAllocator ?? new ZagentPortAllocator();
    }

    public async Task<ZagentConfigurationSnapshot> BootstrapAsync(
        string installRoot,
        string? filesDefaultProfile = null,
        string? dataRoot = null,
        CancellationToken cancellationToken = default,
        string? installationRole = null,
        bool allowRoleMigration = false)
    {
        var layout = _engine.ResolveLayout(
            installRoot,
            filesDefaultProfile,
            dataRoot);

        _engine.EnsurePersistentDirectories(layout);

        var configPath = _engine.GetMachineConfigurationPath(layout);

        var requestedRole = installationRole is null
            ? null : ZagentInstallationProfile.Normalize(installationRole);
        ZagentMachineConfiguration configuration;
        if (_store.Exists(configPath))
        {
            configuration = await _engine.LoadMachineConfigurationAsync(
                layout,
                cancellationToken);
            if (requestedRole is not null &&
                !string.Equals(configuration.InstallationRole, requestedRole,
                    StringComparison.OrdinalIgnoreCase))
            {
                if (!allowRoleMigration)
                    throw new InvalidOperationException(
                        "Installation role migration requires an explicit install initializer.");
                // Never copy the previous role's ports into the new profile.
                var preferredMigration = _engine.CreateDefaultMachineConfiguration(
                    layout, requestedRole);
                configuration = _portAllocator.Allocate(preferredMigration);
                await _engine.SaveMachineConfigurationAsync(
                    layout, configuration, cancellationToken);
            }
        }
        else
        {
            var preferred =
                _engine.CreateDefaultMachineConfiguration(
                    layout, requestedRole ?? ZagentInstallationProfile.InferRole(installRoot));

            configuration =
                _portAllocator.Allocate(preferred);

            await _engine.SaveMachineConfigurationAsync(
                layout,
                configuration,
                cancellationToken);
        }

        var manifestPath = _engine.GetInstalledManifestPath(layout);

        return new ZagentConfigurationSnapshot(
            Paths: layout,
            Machine: configuration,
            MachineConfigurationPath: configPath,
            InstalledManifestPath: manifestPath,
            InstalledManifestPresent: _store.Exists(manifestPath),
            CapturedAtUtc: _timeProvider.GetUtcNow());
    }
}
