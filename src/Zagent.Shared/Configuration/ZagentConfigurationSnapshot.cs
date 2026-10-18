using Zagent.Shared.Paths;

namespace Zagent.Shared.Configuration;

public sealed record ZagentConfigurationSnapshot(
    ZagentPathLayout Paths,
    ZagentMachineConfiguration Machine,
    string MachineConfigurationPath,
    string InstalledManifestPath,
    bool InstalledManifestPresent,
    DateTimeOffset CapturedAtUtc);
