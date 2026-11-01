using Zagent.Core.Network;
using Zagent.Shared.Configuration;

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
        CancellationToken cancellationToken = default)
    {
        var layout = _engine.ResolveLayout(installRoot, filesDefaultProfile, dataRoot);
        _engine.EnsurePersistentDirectories(layout);
        var configPath = _engine.GetMachineConfigurationPath(layout);
        ZagentMachineConfiguration configuration;
        if (_store.Exists(configPath))
        {
            // Keep existing ports and data paths. Old JSON installation_role is
            // ignored by the current schema; never silently migrate live ports.
            configuration = await _engine.LoadMachineConfigurationAsync(
                layout, cancellationToken);
        }
        else
        {
            var preferred = _engine.CreateDefaultMachineConfiguration(layout);
            configuration = _portAllocator.Allocate(preferred);
            await _engine.SaveMachineConfigurationAsync(
                layout, configuration, cancellationToken);
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
