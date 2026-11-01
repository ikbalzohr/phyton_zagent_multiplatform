using Zagent.Core.Network;
using Zagent.Core.Paths;
using Zagent.Shared.Configuration;
using Zagent.Shared.Installation;
using Zagent.Shared.Paths;

namespace Zagent.Core.Configuration;

public sealed class ZagentConfigurationEngine
{
    public const string MachineConfigFileName = "zagent.machine.json";
    public const string InstalledManifestFileName = "installed-manifest.json";

    private readonly IBasePathResolver _pathResolver;
    private readonly AtomicJsonFileStore _store;
    private readonly TimeProvider _timeProvider;

    public ZagentConfigurationEngine(
        IBasePathResolver? pathResolver = null,
        AtomicJsonFileStore? store = null,
        TimeProvider? timeProvider = null)
    {
        _pathResolver = pathResolver ?? new BasePathResolver();
        _store = store ?? new AtomicJsonFileStore();
        _timeProvider = timeProvider ?? TimeProvider.System;
    }

    public ZagentPathLayout ResolveLayout(
        string installRoot,
        string? filesDefaultProfile = null,
        string? dataRoot = null) =>
        _pathResolver.Resolve(
            installRoot,
            filesDefaultProfile,
            dataRoot);

    public void EnsurePersistentDirectories(ZagentPathLayout layout)
    {
        BasePathResolver.Validate(layout);

        Directory.CreateDirectory(layout.DataRoot);
        Directory.CreateDirectory(layout.ConfigRoot);
        Directory.CreateDirectory(layout.LogsRoot);
        Directory.CreateDirectory(layout.RuntimeRoot);
        Directory.CreateDirectory(layout.StateRoot);
        Directory.CreateDirectory(layout.BackupRoot);
        Directory.CreateDirectory(layout.FilesDefaultProfile);
    }

    public ZagentMachineConfiguration CreateDefaultMachineConfiguration(
        ZagentPathLayout layout)
    {
        BasePathResolver.Validate(layout);
        var ports = ZagentNetworkPolicy.For();

        return new ZagentMachineConfiguration(
            SchemaVersion: ZagentMachineConfiguration.CurrentSchemaVersion,
            InstallRoot: layout.InstallRoot,
            FilesDefaultProfile: layout.FilesDefaultProfile,
            DataRoot: layout.DataRoot,
            BindHost: ZagentNetworkPolicy.DefaultBindHost,
            CorePort: ports.Core,
            TunnelPort: ports.Tunnel,
            TunnelHealthPort: ports.TunnelHealth,
            FilesPort: ports.Files,
            WebPort: ports.Web,
            ArcMapPort: ports.ArcMap,
            DevelopmentPortStart: ports.DevelopmentGatewayStart,
            DevelopmentPortEnd: ports.DevelopmentGatewayEnd);
    }

    public ZagentInstalledManifest CreateInstalledManifest(
        ZagentPathLayout layout,
        string productVersion,
        IReadOnlyList<InstalledComponent> components)
    {
        BasePathResolver.Validate(layout);
        ArgumentException.ThrowIfNullOrWhiteSpace(productVersion);
        ArgumentNullException.ThrowIfNull(components);

        return new ZagentInstalledManifest(
            SchemaVersion: ZagentInstalledManifest.CurrentSchemaVersion,
            Product: "Zagent",
            ProductVersion: productVersion,
            InstallRoot: layout.InstallRoot,
            DataRoot: layout.DataRoot,
            FilesDefaultProfile: layout.FilesDefaultProfile,
            InstalledAtUtc: _timeProvider.GetUtcNow(),
            Components: components);
    }

    public string GetMachineConfigurationPath(ZagentPathLayout layout) =>
        Path.Combine(layout.ConfigRoot, MachineConfigFileName);

    public string GetInstalledManifestPath(ZagentPathLayout layout) =>
        Path.Combine(layout.ConfigRoot, InstalledManifestFileName);

    public Task SaveMachineConfigurationAsync(
        ZagentPathLayout layout,
        ZagentMachineConfiguration configuration,
        CancellationToken cancellationToken = default)
    {
        ValidateConfiguration(layout, configuration);
        return _store.SaveAsync(
            GetMachineConfigurationPath(layout),
            configuration,
            cancellationToken);
    }

    public async Task<ZagentMachineConfiguration> LoadMachineConfigurationAsync(
        ZagentPathLayout layout,
        CancellationToken cancellationToken = default)
    {
        var configuration = await _store.LoadAsync<ZagentMachineConfiguration>(
            GetMachineConfigurationPath(layout),
            cancellationToken);

        ValidateConfiguration(layout, configuration);
        return configuration;
    }

    public Task SaveInstalledManifestAsync(
        ZagentPathLayout layout,
        ZagentInstalledManifest manifest,
        CancellationToken cancellationToken = default)
    {
        ValidateInstalledManifest(layout, manifest);
        return _store.SaveAsync(
            GetInstalledManifestPath(layout),
            manifest,
            cancellationToken);
    }

    public async Task<ZagentInstalledManifest> LoadInstalledManifestAsync(
        ZagentPathLayout layout,
        CancellationToken cancellationToken = default)
    {
        var manifest = await _store.LoadAsync<ZagentInstalledManifest>(
            GetInstalledManifestPath(layout),
            cancellationToken);

        ValidateInstalledManifest(layout, manifest);
        return manifest;
    }

    private static void ValidateConfiguration(
        ZagentPathLayout layout,
        ZagentMachineConfiguration configuration)
    {
        if (!string.Equals(
                configuration.SchemaVersion,
                ZagentMachineConfiguration.CurrentSchemaVersion,
                StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                $"Unsupported machine configuration schema '{configuration.SchemaVersion}'.");
        }

        if (!PathsEqual(configuration.InstallRoot, layout.InstallRoot) ||
            !PathsEqual(configuration.FilesDefaultProfile, layout.FilesDefaultProfile) ||
            !PathsEqual(configuration.DataRoot, layout.DataRoot))
        {
            throw new InvalidDataException(
                "Machine configuration paths do not match resolved layout.");
        }

        if (!IsLoopback(configuration.BindHost))
        {
            throw new InvalidDataException(
                "Zagent machine configuration must bind to loopback.");
        }

        var fixedPorts = new[]
        {
            configuration.CorePort,
            configuration.TunnelPort,
            configuration.TunnelHealthPort,
            configuration.FilesPort,
            configuration.WebPort,
            configuration.ArcMapPort
        };

        if (fixedPorts.Any(port => port is < 1 or > 65535))
        {
            throw new InvalidDataException("Configuration contains an invalid port.");
        }

        if (fixedPorts.Distinct().Count() != fixedPorts.Length)
        {
            throw new InvalidDataException(
                "Configuration contains duplicate fixed ports.");
        }

        if (!ZagentNetworkPolicy.IsSupportedPortBlock(
                fixedPorts, configuration.DevelopmentPortStart,
                configuration.DevelopmentPortEnd))
        {
            throw new InvalidDataException(
                "Production ports and Development Gateway range must belong to a supported, non-overlapping block.");
        }

        if (configuration.DevelopmentPortStart < 1 ||
            configuration.DevelopmentPortEnd > 65535 ||
            configuration.DevelopmentPortStart > configuration.DevelopmentPortEnd)
        {
            throw new InvalidDataException(
                "Development port range is invalid.");
        }

        if (fixedPorts.Any(
                port => port >= configuration.DevelopmentPortStart &&
                        port <= configuration.DevelopmentPortEnd))
        {
            throw new InvalidDataException(
                "A fixed production port overlaps the Development Gateway range.");
        }
    }

    private static void ValidateInstalledManifest(
        ZagentPathLayout layout,
        ZagentInstalledManifest manifest)
    {
        if (!string.Equals(
                manifest.SchemaVersion,
                ZagentInstalledManifest.CurrentSchemaVersion,
                StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                $"Unsupported installed manifest schema '{manifest.SchemaVersion}'.");
        }

        if (!string.Equals(manifest.Product, "Zagent", StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                $"Unexpected installed product '{manifest.Product}'.");
        }

        if (!PathsEqual(manifest.InstallRoot, layout.InstallRoot) ||
            !PathsEqual(manifest.DataRoot, layout.DataRoot) ||
            !PathsEqual(manifest.FilesDefaultProfile, layout.FilesDefaultProfile))
        {
            throw new InvalidDataException(
                "Installed manifest path contract does not match resolved layout.");
        }

        var ids = new HashSet<string>(StringComparer.Ordinal);
        foreach (var component in manifest.Components)
        {
            if (string.IsNullOrWhiteSpace(component.Id) ||
                !ids.Add(component.Id))
            {
                throw new InvalidDataException(
                    "Installed manifest contains an invalid or duplicate component id.");
            }

            if (string.IsNullOrWhiteSpace(component.Version))
            {
                throw new InvalidDataException(
                    $"Installed component '{component.Id}' has no version.");
            }

            if (Path.IsPathRooted(component.RelativePath))
            {
                throw new InvalidDataException(
                    $"Installed component '{component.Id}' path must be relative.");
            }

            var combined = Path.GetFullPath(
                Path.Combine(layout.InstallRoot, component.RelativePath));
            var rootWithSeparator =
                Path.TrimEndingDirectorySeparator(layout.InstallRoot) +
                Path.DirectorySeparatorChar;

            if (!combined.StartsWith(
                    rootWithSeparator,
                    StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException(
                    $"Installed component '{component.Id}' escapes InstallRoot.");
            }
        }
    }

    private static bool PathsEqual(string left, string right) =>
        string.Equals(
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(left)),
            Path.TrimEndingDirectorySeparator(Path.GetFullPath(right)),
            StringComparison.OrdinalIgnoreCase);

    private static bool IsLoopback(string host) =>
        string.Equals(host, "localhost", StringComparison.OrdinalIgnoreCase) ||
        host.StartsWith("127.", StringComparison.Ordinal);
}
