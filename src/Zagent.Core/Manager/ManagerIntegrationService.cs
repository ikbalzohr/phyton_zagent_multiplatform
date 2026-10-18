using System.Diagnostics;
using System.Text.Json;
using Zagent.Core.Abstractions;
using Zagent.Core.Agents.ArcMap;
using Zagent.Core.Agents.Web;
using Zagent.Shared.Contracts;
using Zagent.Shared.Manager;

namespace Zagent.Core.Manager;

public sealed class ManagerIntegrationService
{
    private readonly string _zagentRoot;
    private readonly string _dataRoot;
    private readonly AgentEnvironment _environment;
    private readonly ICapabilityRegistry _registry;
    private readonly ManagerAgentControllerRegistry _controllers;
    private readonly WebManagerReadModel _web;
    private readonly ManagerTechnicalLogStore _logs;

    public ManagerIntegrationService(
        string zagentRoot,
        string dataRoot,
        AgentEnvironment environment,
        ICapabilityRegistry registry,
        ManagerAgentControllerRegistry controllers,
        WebManagerReadModel web,
        ManagerTechnicalLogStore logs)
    {
        _zagentRoot = Path.GetFullPath(zagentRoot);
        _dataRoot = Path.GetFullPath(dataRoot);
        _environment = environment;
        _registry = registry;
        _controllers = controllers;
        _web = web;
        _logs = logs;
    }

    public async Task<ManagerIntegrationSnapshot> SnapshotAsync(
        CancellationToken cancellationToken = default)
    {
        _registry.TryGet(
            WebAgentManifestFactory.AgentId,
            out var webAgent);
        _registry.TryGet(
            ArcMapAgentManifestFactory.AgentId,
            out var arcMapAgent);

        WebBridgeManagerStatus webStatus;

        if (webAgent?.Health == AgentHealthState.Ready)
        {
            try
            {
                webStatus = await _web.GetBridgeStatusAsync(
                    cancellationToken);
            }
            catch
            {
                webStatus = EmptyWebBridgeStatus();
            }
        }
        else
        {
            webStatus = EmptyWebBridgeStatus();
        }

        var extensionRoot = Path.Combine(
            _zagentRoot,
            "agents",
            "web",
            "engine",
            "extension");
        var extensionManifest = Path.Combine(
            extensionRoot,
            "manifest.json");

        var chromeProfile = string.Join(
            " / ",
            new[]
            {
                webStatus.ProfileDirectory,
                webStatus.ProfileName
            }.Where(item => !string.IsNullOrWhiteSpace(item)));

        var chromeRunning = IsChromeRunning();

        var chromeExtensionStatus =
            webStatus.ProfileBound ||
            webStatus.PairedOriginKnown ||
            webStatus.Connected
                ? string.IsNullOrWhiteSpace(chromeProfile)
                    ? "Loaded"
                    : $"Loaded - {chromeProfile}"
                : File.Exists(extensionManifest)
                    ? chromeRunning &&
                      webAgent?.Health == AgentHealthState.Ready &&
                      !webStatus.ExtensionHeartbeatDetected
                        ? $"Bridge installed/running but no heartbeat at {webStatus.ExpectedBridgeEndpoint} ({webStatus.BridgeEnvironment})."
                        : _environment == AgentEnvironment.Development
                            ? "DEV source ready - not paired"
                            : "Package present - not paired"
                    : "Not installed";

        if (!webStatus.ProfileBound &&
            webStatus.ExtensionHeartbeatDetected)
        {
            chromeExtensionStatus =
                "Extension detected - " +
                webStatus.ObservedExtensionCount.ToString() +
                " profile(s); not yet approved";
        }

        var chromeNativeBridgeStatus =
            webAgent?.Health == AgentHealthState.Ready
                ? _environment == AgentEnvironment.Development
                    ? "DEV Web Bridge Ready"
                    : "Ready"
                : webAgent?.Health.ToString() ??
                    "Not detected";

        var arcMapExecutable = FindArcMapExecutable();
        var arcMapRunning = Process.GetProcessesByName("ArcMap")
            .Length > 0;

        var arcMapDesktopStatus = arcMapRunning
            ? "Running - ArcMap 10.6.1"
            : arcMapExecutable is not null
                ? "Detected - ArcMap 10.6.1"
                : "Not detected";

        var addIn = FindFirstFile(
            Path.Combine(
                _zagentRoot,
                "agents",
                "arcmap"),
            "*.esriaddin");

        var toolbox = Path.Combine(
            _zagentRoot,
            "agents",
            "arcmap",
            "engine",
            "arcmap_bridge",
            "ArcMapAgent.pyt");

        var arcMapMcpStatus =
            arcMapAgent?.Health switch
            {
                AgentHealthState.Ready => "Ready",
                AgentHealthState.Degraded => "Ready - bridge offline",
                null => "Not detected",
                _ => arcMapAgent.Health.ToString()
            };

        var bridgeConnected =
            arcMapAgent?.Health == AgentHealthState.Ready;

        return new ManagerIntegrationSnapshot(
            ChromeExtensionStatus:
                chromeExtensionStatus,
            ChromeNativeBridgeStatus:
                chromeNativeBridgeStatus,
            ChromeConnected:
                webStatus.Connected,
            ChromeAuthorized:
                webStatus.Authorized,
            ChromeNativeAttached:
                webStatus.NativeAttached,
            ChromeProfileBound:
                webStatus.ProfileBound,
            ChromeProfile:
                chromeProfile,
            ArcMapDesktopStatus:
                arcMapDesktopStatus,
            ArcMapAddInStatus:
                addIn is null
                    ? "Add-In package missing"
                    : "Packaged",
            ArcMapToolsStatus:
                File.Exists(toolbox)
                    ? "ArcMapAgent.pyt Ready"
                    : "Missing",
            ArcMapMcpStatus:
                arcMapMcpStatus,
            ArcMapBridgeStatus:
                bridgeConnected
                    ? "Connected"
                    : "Disconnected",
            ArcMapCurrentMxdStatus:
                bridgeConnected
                    ? "Reachable"
                    : "Not attached",
            CapturedAtUtc:
                DateTimeOffset.UtcNow)
        {
            ChromePersistentConsent = webStatus.PersistentConsent,
            ChromeReconnectAvailable = webStatus.ReconnectAvailable,
            ChromeApprovedTabCount = webStatus.ApprovedTabCount,
            ChromeProfileOptions = webStatus.ProfileOptions
        };
    }

    public async Task<ManagerIntegrationActionResult> RunAsync(
        ManagerIntegrationActionRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);

        var action = request.Action.Trim();

        try
        {
            var message = action switch
            {
                "chrome.check" =>
                    "Chrome integration status refreshed.",

                "chrome.open_setup" =>
                    OpenChromeSetup(),

                "chrome.repair_bridge" =>
                    await RestartAgentAsync(
                        WebAgentManifestFactory.AgentId,
                        "Chrome/Web bridge restarted.",
                        cancellationToken),

                "chrome.request_access" =>
                    await RequestChromeAccessAsync(
                        request.ChromeProfile, cancellationToken),

                "chrome.disconnect" =>
                    await _web.DisconnectTrustedProfileAsync(cancellationToken),

                "chrome.pair" =>
                    await PairChromeAsync(
                        cancellationToken),

                "chrome.authorize" =>
                    await AuthorizeChromeAsync(
                        cancellationToken),

                "arcmap.check" =>
                    await RefreshAgentAsync(
                        ArcMapAgentManifestFactory.AgentId,
                        "ArcMap integration status refreshed.",
                        cancellationToken),

                "arcmap.open_setup" =>
                    PrepareArcMapSetup(),

                "arcmap.repair_bridge" =>
                    await RepairArcMapAsync(
                        cancellationToken),

                _ => throw new InvalidOperationException(
                    $"Unknown integration action '{action}'.")
            };

            var snapshot = await SnapshotAsync(
                cancellationToken);

            _logs.Write(
                "INFO",
                "Integrations",
                action,
                message);

            return new ManagerIntegrationActionResult(
                true,
                action,
                message,
                snapshot);
        }
        catch (Exception ex)
        {
            _logs.Write(
                "ERROR",
                "Integrations",
                action,
                ex.Message);

            return new ManagerIntegrationActionResult(
                false,
                action,
                ex.Message,
                await SnapshotAsync(
                    CancellationToken.None));
        }
    }

    private async Task<string> RequestChromeAccessAsync(
        string? profile,
        CancellationToken cancellationToken)
    {
        var selected = profile?.Trim() ?? "";
        if (string.IsNullOrWhiteSpace(selected))
        {
            throw new InvalidOperationException(
                "Select a Chrome profile before requesting access.");
        }

        var choices = await _web.GetInstalledBridgeProfilesAsync(
            cancellationToken);
        if (!choices.Contains(
                selected, StringComparer.OrdinalIgnoreCase))
        {
            throw new InvalidOperationException(
                "Selected Chrome profile does not have the installed " +
                "Zagent Bridge extension. Refresh Integrations first.");
        }

        var existing = await _web.GetBridgeStatusAsync(cancellationToken);
        if (existing.ProfileBound)
        {
            var sameProfile =
                selected.Equals(existing.ProfileName,
                    StringComparison.OrdinalIgnoreCase) ||
                selected.Equals(existing.ProfileDirectory,
                    StringComparison.OrdinalIgnoreCase);

            if (sameProfile &&
                existing.Connected && existing.Authorized &&
                existing.PersistentConsent)
            {
                return "Chrome " + selected +
                    " already has persistent access until Disconnect.";
            }
            if (!sameProfile)
            {
                // Explicit new-profile request replaces the previous
                // trusted binding, including its durable reconnect secret.
                await _web.DisconnectTrustedProfileAsync(cancellationToken);
            }
        }

        return await _web.RequestPersistentAccessAsync(
            selected, cancellationToken);
    }

    private async Task<string> PairChromeAsync(
        CancellationToken cancellationToken)
    {
        var startup =
            await EnsureChromeRunningAsync(
                cancellationToken);

        var result =
            await _web.PairOrReconnectAsync(
                cancellationToken);

        return $"{startup} Pair/Reconnect: {result}.";
    }

    private async Task<string> AuthorizeChromeAsync(
        CancellationToken cancellationToken)
    {
        var startup =
            await EnsureChromeRunningAsync(
                cancellationToken);

        var status =
            await _web.GetBridgeStatusAsync(
                cancellationToken);

        if (!status.ProfileBound)
        {
            throw new InvalidOperationException(
                "Chrome profile is not paired. Run Pair / Reconnect first.");
        }

        var reconnectMessage = "";

        if (!status.Connected)
        {
            reconnectMessage =
                await _web.PairOrReconnectAsync(
                    cancellationToken);

            status =
                await _web.GetBridgeStatusAsync(
                    cancellationToken);
        }

        if (!status.Connected)
        {
            throw new InvalidOperationException(
                "Chrome is running but the trusted profile has not reconnected yet. Open the Zagent Chrome Bridge popup in the paired Chrome profile, then retry Authorize.");
        }

        var authorization =
            await _web.RequestAuthorizationAsync(
                cancellationToken);

        return string.IsNullOrWhiteSpace(
                reconnectMessage)
            ? $"{startup} Authorization: {authorization}."
            : $"{startup} Reconnect: {reconnectMessage}. Authorization: {authorization}.";
    }

    private async Task<string> EnsureChromeRunningAsync(
        CancellationToken cancellationToken)
    {
        WebBridgeManagerStatus? status = null;

        try
        {
            status =
                await _web.GetBridgeStatusAsync(
                    cancellationToken);
        }
        catch
        {
        }

        if (status?.Connected == true)
        {
            return string.IsNullOrWhiteSpace(
                    status.ProfileDirectory)
                ? "Chrome Bridge is already connected."
                : $"Chrome profile '{status.ProfileDirectory}' is already connected.";
        }

        var chrome = FindChromeExecutable();

        if (chrome is null)
        {
            throw new FileNotFoundException(
                "Google Chrome executable was not found.");
        }

        var profileDirectory =
            status?.ProfileDirectory?.Trim() ?? "";
        var chromeWasRunning =
            IsChromeRunning();

        if (chromeWasRunning &&
            string.IsNullOrWhiteSpace(
                profileDirectory))
        {
            return "Chrome was already running. No trusted profile binding exists yet.";
        }

        var arguments =
            string.IsNullOrWhiteSpace(
                profileDirectory)
                ? ""
                : $"--profile-directory=\"{profileDirectory}\" --new-window chrome://newtab";

        Process.Start(
            new ProcessStartInfo
            {
                FileName = chrome,
                Arguments = arguments,
                UseShellExecute = true
            });

        var deadline =
            DateTimeOffset.UtcNow.AddSeconds(10);

        while (DateTimeOffset.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();

            if (IsChromeRunning())
            {
                await Task.Delay(
                    TimeSpan.FromSeconds(2),
                    cancellationToken);

                if (string.IsNullOrWhiteSpace(
                        profileDirectory))
                {
                    return "Chrome started automatically.";
                }

                return chromeWasRunning
                    ? $"Chrome was already running in another profile; trusted profile '{profileDirectory}' activation was requested."
                    : $"Chrome started automatically with trusted profile '{profileDirectory}'.";
            }

            await Task.Delay(
                TimeSpan.FromMilliseconds(250),
                cancellationToken);
        }

        throw new InvalidOperationException(
            "Chrome launch was requested but chrome.exe did not start within 10 seconds.");
    }

    private static bool IsChromeRunning()
    {
        try
        {
            return Process.GetProcessesByName(
                    "chrome")
                .Length > 0;
        }
        catch
        {
            return false;
        }
    }

    private string OpenChromeSetup()
    {
        var extensionRoot = Path.Combine(
            _zagentRoot,
            "agents",
            "web",
            "engine",
            "extension");

        if (!File.Exists(
                Path.Combine(
                    extensionRoot,
                    "manifest.json")))
        {
            throw new FileNotFoundException(
                "Chrome extension manifest was not found.");
        }

        var chrome = FindChromeExecutable();

        if (chrome is not null)
        {
            Process.Start(
                new ProcessStartInfo
                {
                    FileName = chrome,
                    Arguments = "chrome://extensions/",
                    UseShellExecute = true
                });
        }

        Process.Start(
            new ProcessStartInfo
            {
                FileName = "explorer.exe",
                Arguments = $"\"{extensionRoot}\"",
                UseShellExecute = true
            });

        return "Chrome extensions page and Zagent extension folder opened.";
    }

    private string PrepareArcMapSetup()
    {
        EnsureArcMapRuntimeLocator();

        var toolbox = Path.Combine(
            _zagentRoot,
            "agents",
            "arcmap",
            "engine",
            "arcmap_bridge",
            "ArcMapAgent.pyt");

        if (!File.Exists(toolbox))
        {
            throw new FileNotFoundException(
                "ArcMapAgent.pyt was not found.",
                toolbox);
        }

        Process.Start(
            new ProcessStartInfo
            {
                FileName = "explorer.exe",
                Arguments = $"/select,\"{toolbox}\"",
                UseShellExecute = true
            });

        return "ArcMap runtime locator prepared. Install the packaged Zagent ArcMap Add-In and reopen ArcMap to attach automatically.";
    }

    private async Task<string> RepairArcMapAsync(
        CancellationToken cancellationToken)
    {
        EnsureArcMapRuntimeLocator();

        return await RestartAgentAsync(
            ArcMapAgentManifestFactory.AgentId,
            "ArcMap MCP restarted and runtime locator repaired. External ArcMap remains open.",
            cancellationToken);
    }

    private async Task<string> RestartAgentAsync(
        string agentId,
        string successMessage,
        CancellationToken cancellationToken)
    {
        if (!_controllers.TryGet(
                agentId,
                out var controller) ||
            controller is null)
        {
            throw new InvalidOperationException(
                $"Agent '{agentId}' is not registered.");
        }

        var result = await controller.Restart(
            cancellationToken);

        if (!result.Success)
        {
            throw new InvalidOperationException(
                result.Message);
        }

        return successMessage;
    }

    private async Task<string> RefreshAgentAsync(
        string agentId,
        string successMessage,
        CancellationToken cancellationToken)
    {
        if (!_controllers.TryGet(
                agentId,
                out var controller) ||
            controller is null)
        {
            throw new InvalidOperationException(
                $"Agent '{agentId}' is not registered.");
        }

        var result = await controller.Refresh(
            cancellationToken);

        if (!result.Success)
        {
            throw new InvalidOperationException(
                result.Message);
        }

        return successMessage;
    }

    private void EnsureArcMapRuntimeLocator()
    {
        var dataRoot = Path.Combine(
            _dataRoot,
            "arcmap");
        var configRoot = Path.Combine(
            dataRoot,
            "config");
        var ipcRoot = Path.Combine(
            dataRoot,
            "ipc");

        Directory.CreateDirectory(dataRoot);
        Directory.CreateDirectory(configRoot);
        Directory.CreateDirectory(ipcRoot);

        var bridgeRoot = Path.Combine(
            _zagentRoot,
            "agents",
            "arcmap",
            "engine",
            "arcmap_bridge");

        Directory.CreateDirectory(bridgeRoot);

        var locator = Path.Combine(
            bridgeRoot,
            "bridge_runtime.json");

        var json = JsonSerializer.Serialize(
            new
            {
                schema_version = "1.0",
                environment =
                    _environment.ToString().ToUpperInvariant(),
                data_root = dataRoot,
                config_dir = configRoot,
                ipc_root = ipcRoot,
                generated_by =
                    "Zagent Manager Integrations"
            },
            new JsonSerializerOptions
            {
                WriteIndented = true
            });

        File.WriteAllText(locator, json);
    }

    private static WebBridgeManagerStatus EmptyWebBridgeStatus() =>
        new(
            false,
            false,
            false,
            false,
            false,
            false,
            0,
            "",
            "",
            "",
            "");

    private static string? FindChromeExecutable()
    {
        try
        {
            foreach (var process in
                Process.GetProcessesByName("chrome"))
            {
                try
                {
                    var fileName =
                        process.MainModule?.FileName;

                    if (!string.IsNullOrWhiteSpace(
                            fileName) &&
                        File.Exists(fileName))
                    {
                        return fileName;
                    }
                }
                catch
                {
                }
            }
        }
        catch
        {
        }

        var candidates = new[]
        {
            Path.Combine(
                Environment.GetFolderPath(
                    Environment.SpecialFolder.ProgramFiles),
                "Google",
                "Chrome",
                "Application",
                "chrome.exe"),
            Path.Combine(
                Environment.GetFolderPath(
                    Environment.SpecialFolder.ProgramFilesX86),
                "Google",
                "Chrome",
                "Application",
                "chrome.exe"),
            Path.Combine(
                Environment.GetFolderPath(
                    Environment.SpecialFolder.LocalApplicationData),
                "Google",
                "Chrome",
                "Application",
                "chrome.exe")
        };

        return candidates.FirstOrDefault(
            File.Exists);
    }

    private static string? FindArcMapExecutable()
    {
        try
        {
            foreach (var process in
                Process.GetProcessesByName("ArcMap"))
            {
                try
                {
                    var fileName =
                        process.MainModule?.FileName;

                    if (!string.IsNullOrWhiteSpace(
                            fileName) &&
                        File.Exists(fileName))
                    {
                        return fileName;
                    }
                }
                catch
                {
                }
            }
        }
        catch
        {
        }

        var candidates = new[]
        {
            @"C:\Program Files (x86)\ArcGIS\Desktop10.6\bin\ArcMap.exe",
            @"C:\Program Files\ArcGIS\Desktop10.6\bin\ArcMap.exe"
        };

        return candidates.FirstOrDefault(
            File.Exists);
    }

    private static string? FindFirstFile(
        string root,
        string pattern)
    {
        try
        {
            return Directory.Exists(root)
                ? Directory.EnumerateFiles(
                    root,
                    pattern,
                    SearchOption.AllDirectories)
                    .FirstOrDefault()
                : null;
        }
        catch
        {
            return null;
        }
    }
}