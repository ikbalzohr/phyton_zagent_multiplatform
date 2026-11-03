using System.Diagnostics;
using System.Text.Json;
using Zagent.Core;
using Zagent.Core.Agents.Web;
using Zagent.Core.Paths;
using Zagent.Core.Supervision;
using Zagent.Core.Manager;
using Zagent.Core.Configuration;
using Zagent.Core.Identity;
using Zagent.Shared;
using Zagent.Shared.Contracts;
using Zagent.Shared.Installation;
using Zagent.Core.Network;
using Zagent.Shared.Manager;

// Ignore inherited OAuth credentials for this process and all incidental children.
// Only the Router factory receives the owner-validated DPAPI credential explicitly.
Environment.SetEnvironmentVariable(OAuthIntrospectionCredentialStore.EnvironmentName, null);

if (args.Contains("--version", StringComparer.Ordinal))
{
    Console.WriteLine($"{ZagentProductInfo.ProductName} Core {ZagentProductInfo.CoreVersion}");
    return 0;
}

if (args.Contains("--self-test", StringComparer.Ordinal))
{
    return CoreSelfTest.Run(Console.Out);
}

if (args.Contains("--initialize-install", StringComparer.Ordinal))
{
    var root = GetOptionValue(args, "--root");

    if (string.IsNullOrWhiteSpace(root))
    {
        Console.Error.WriteLine(
            "--initialize-install requires --root <InstallRoot>.");
        return 2;
    }

    var installRoot = Path.GetFullPath(root);
    var dataRoot =
        GetOptionValue(args, "--data-root") ??
        Path.Combine(installRoot, "data");
    var filesProfile =
        GetOptionValue(args, "--files-profile") ??
        Path.Combine(installRoot, "workspace");
    var productVersion =
        GetOptionValue(args, "--product-version") ??
        ZagentProductInfo.CoreVersion;

    var engine = new ZagentConfigurationEngine();
    var bootstrapper =
        new ZagentConfigurationBootstrapper(
            engine: engine);

    var snapshot =
        await bootstrapper.BootstrapAsync(
            installRoot,
            filesProfile,
            dataRoot);

    var identityStore =
        new MachineIdentityStore(
            Path.Combine(
                snapshot.Paths.ConfigRoot,
                MachineIdentityStore.FileName));

    var machineIdentity = await identityStore.EnsureAsync();
    var displayName = GetOptionValue(args, "--device-display-name");
    if (!string.IsNullOrWhiteSpace(displayName)) machineIdentity = await identityStore.RenameAliasAsync(displayName);

    var bridgeSync =
        await new ChromeBridgeConfigurationSynchronizer()
            .SyncAsync(
                snapshot.Paths.InstallRoot,
                snapshot.Machine.BindHost,
                snapshot.Machine.WebPort,
                "PRODUCTION");

    var components = new[]
    {
        new InstalledComponent(
            "core",
            ZagentProductInfo.CoreVersion,
            "Zagent.Core.exe"),
        new InstalledComponent(
            "ui",
            ZagentProductInfo.UiVersion,
            "Zagent.Core.exe"),
        new InstalledComponent(
            "setup",
            ZagentProductInfo.CoreVersion,
            "Zagent.Setup.exe"),
        new InstalledComponent(
            "tunnel",
            ReadComponentVersion(
                installRoot,
                Path.Combine(
                    "agents",
                    "tunnel",
                    "tunnel.component.json"),
                "1.0.0"),
            Path.Combine("agents", "tunnel")),
        new InstalledComponent(
            "files",
            ReadComponentVersion(
                installRoot,
                Path.Combine(
                    "agents",
                    "files",
                    "files.component.json"),
                "1.0.0"),
            Path.Combine("agents", "files")),
        new InstalledComponent(
            "web",
            ReadComponentVersion(
                installRoot,
                Path.Combine(
                    "agents",
                    "web",
                    "web.component.json"),
                "1.0.0"),
            Path.Combine("agents", "web")),
        new InstalledComponent(
            "arcmap",
            ReadComponentVersion(
                installRoot,
                Path.Combine(
                    "agents",
                    "arcmap",
                    "arcmap.component.json"),
                "1.0.0"),
            Path.Combine("agents", "arcmap"))
    };

    var manifest =
        engine.CreateInstalledManifest(
            snapshot.Paths,
            productVersion,
            components);

    await engine.SaveInstalledManifestAsync(
        snapshot.Paths,
        manifest);

    Console.WriteLine(
        JsonSerializer.Serialize(
            new
            {
                ok = true,
                machineConfiguration =
                    snapshot.MachineConfigurationPath,
                installedManifest =
                    snapshot.InstalledManifestPath,
                installRoot =
                    snapshot.Paths.InstallRoot,
                 dataRoot =
                    snapshot.Paths.DataRoot,
                filesDefaultProfile =
                    snapshot.Paths.FilesDefaultProfile,
                deviceIdentity =
                    identityStore.PathOnDisk,
                deviceId =
                    machineIdentity.DeviceId,
                deviceName =
                    machineIdentity.DeviceName,
                bindHost =
                    snapshot.Machine.BindHost,
                ports = new
                {
                    core = snapshot.Machine.CorePort,
                    tunnel = snapshot.Machine.TunnelPort,
                    tunnelHealth = snapshot.Machine.TunnelHealthPort,
                    files = snapshot.Machine.FilesPort,
                    web = snapshot.Machine.WebPort,
                    arcMap = snapshot.Machine.ArcMapPort
                },
                chromeBridgeEndpoint =
                    bridgeSync.DefaultBase,
                productVersion
            },
            new JsonSerializerOptions
            {
                WriteIndented = true
            }));

    return 0;
}

if (args.Contains("--provision-dashboard", StringComparer.Ordinal))
{
    Zagent.Core.Dashboard.DashboardOptions.ProvisionLocalOwner(
        GetOptionValue(args, "--dashboard-config") ?? throw new ArgumentException("--dashboard-config required"),
        GetOptionValue(args, "--dashboard-url") ?? throw new ArgumentException("--dashboard-url required"),
        GetOptionValue(args, "--certificate-thumbprint") ?? throw new ArgumentException("--certificate-thumbprint required"),
        GetOptionValue(args, "--workspace-id") ?? throw new ArgumentException("--workspace-id required"));
    return 0;
}

if (args.Contains("--dashboard", StringComparer.Ordinal))
{
    var root = GetOptionValue(args, "--root");
    if (string.IsNullOrWhiteSpace(root))
    {
        Console.Error.WriteLine("--dashboard requires --root <ZagentRoot>.");
        return 2;
    }

    var fullRoot = Path.GetFullPath(root);
    var dataRoot = GetOptionValue(args, "--data-root") ??
        Path.Combine(fullRoot, "data");

    // Fresh install fail-closed: config must be provisioned by D before launch.
    var dashboardConfig = GetOptionValue(args, "--dashboard-config") ??
        Path.Combine(dataRoot, "config", "dashboard.json");
    if (!File.Exists(dashboardConfig))
    {
        Console.Error.WriteLine(
            "--dashboard requires a provisioned dashboard config; " +
            "dashboard.json not found: " + dashboardConfig);
        return 2;
    }

    // Reuse existing Core lease: if another Core owns the supervisor lease,
    // open the dashboard origin in the browser and exit without launching.
    var leaseName = ZagentInstanceScope.SupervisorLeaseName(fullRoot);
    if (!SupervisorInstanceLease.TryAcquire(leaseName, out var probeLease))
    {
        var options = Zagent.Core.Dashboard.DashboardOptions.Load(dashboardConfig);
        var url = options.Origin.GetLeftPart(UriPartial.Authority);
        try
        {
            Zagent.Core.Dashboard.DashboardChromeBrowser.Open(options.Origin);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine("Failed to open dashboard browser: " + ex.Message);
            return 1;
        }
        return 0;
    }

    probeLease?.Dispose();

    // No running Core: rewrite to --serve-dashboard and fall through to the
    // canonical handler (alias). Inject default config so --dashboard-config
    // remains optional for the launcher.
    var rewritten = new List<string>(args);
    var dashboardIndex = rewritten.IndexOf("--dashboard");
    if (dashboardIndex >= 0)
    {
        rewritten[dashboardIndex] = "--serve-dashboard";
    }
    if (!rewritten.Contains("--dashboard-config", StringComparer.Ordinal))
    {
        rewritten.Add("--dashboard-config");
        rewritten.Add(dashboardConfig);
    }
    args = rewritten.ToArray();
}

if (args.Contains("--serve-dashboard", StringComparer.Ordinal))
{
    var root = GetOptionValue(args, "--root");
    if (string.IsNullOrWhiteSpace(root))
    {
        Console.Error.WriteLine("--serve-dashboard requires --root <ZagentRoot>.");
        return 2;
    }

    var dataRoot =
        GetOptionValue(args, "--data-root") ??
        Path.Combine(
            Path.GetFullPath(root),
            "data");

    var filesProfile =
        GetOptionValue(args, "--files-profile") ??
        InferFilesProfileRoot(
            Path.GetFullPath(root));

    // Validate security provisioning before creating any child runtime.
    var dashboardConfig = GetOptionValue(args, "--dashboard-config") ??
        throw new ArgumentException("--dashboard-config is required; no unauthenticated fallback exists.");
    var dashboardOptions = Zagent.Core.Dashboard.DashboardOptions.Load(dashboardConfig);
    if (!OperatingSystem.IsWindows() || !Environment.UserInteractive)
        throw new InvalidOperationException("Core1 requires an interactive per-user Windows desktop.");
    using (var certificate = dashboardOptions.LoadCertificate()) { }
    Zagent.Core.Manager.InternalSecretStore.ValidatePrivatePath(dashboardConfig, directory: false);
    var requestedPipe = GetOptionValue(args, "--pipe");

    var managerEnvironment =
        ReadAgentEnvironment();

    var machineSnapshot =
        await new ZagentConfigurationBootstrapper()
            .BootstrapAsync(
                Path.GetFullPath(root),
                filesProfile,
                dataRoot);

    var machine =
        machineSnapshot.Machine;

    var development =
        managerEnvironment == AgentEnvironment.Development;
    var devRuntimeStart = machine.DevelopmentPortStart + 100;
    var pipeName = requestedPipe ??
        (development ? "Zagent.Manager.Development" :
            ManagerProtocol.ForRoot(Path.GetFullPath(root)));

    var bindHost =
        development
            ? Environment.GetEnvironmentVariable(
                  "ZAGENT_BIND_HOST") ??
              machine.BindHost
            : machine.BindHost;

    var tunnelPort =
        development
            ? ReadPortEnvironment(
                "ZAGENT_TUNNEL_PORT",
                devRuntimeStart + 10)
            : machine.TunnelPort;

    var tunnelHealthPort =
        development
            ? ReadPortEnvironment(
                "ZAGENT_TUNNEL_HEALTH_PORT",
                devRuntimeStart + 11)
            : machine.TunnelHealthPort;

    var filesPort =
        development
            ? ReadPortEnvironment(
                "ZAGENT_FILES_PORT",
                devRuntimeStart + 20)
            : machine.FilesPort;

    var webPort =
        development
            ? ReadPortEnvironment(
                "ZAGENT_WEB_PORT",
                devRuntimeStart + 30)
            : machine.WebPort;

    var arcMapPort =
        development
            ? ReadPortEnvironment(
                "ZAGENT_ARCMAP_PORT",
                devRuntimeStart + 40)
            : machine.ArcMapPort;

    await new ChromeBridgeConfigurationSynchronizer()
        .SyncAsync(
            Path.GetFullPath(root),
            bindHost,
            webPort,
            development
                ? "DEVELOPMENT"
                : "PRODUCTION");

    var hostOptions = new ManagerCoreHostOptions(
        ZagentRoot: root,
        DataRoot: dataRoot,
        FilesDefaultProfile: filesProfile,
        PipeName: pipeName,
        FilesPython:
            Environment.GetEnvironmentVariable(
                "ZAGENT_FILES_PYTHON"),
        TunnelPython:
            Environment.GetEnvironmentVariable(
                "ZAGENT_TUNNEL_PYTHON"),
        WebNode:
            Environment.GetEnvironmentVariable(
                "ZAGENT_WEB_NODE"),
        ArcMapPython:
            Environment.GetEnvironmentVariable(
                "ZAGENT_ARCMAP_PYTHON"),
        BindHost: bindHost,
        TunnelPort: tunnelPort,
        TunnelHealthPort: tunnelHealthPort,
        FilesPort: filesPort,
        WebPort: webPort,
        ArcMapPort: arcMapPort,
        SupervisorLeaseName:
            Environment.GetEnvironmentVariable(
                "ZAGENT_SUPERVISOR_LEASE_NAME") ??
                (development ? @"Local\Zagent.Dev.Supervisor" :
                    ZagentInstanceScope.SupervisorLeaseName(Path.GetFullPath(root))),
        Environment: managerEnvironment,
        WorkspaceId: dashboardOptions.WorkspaceId,
        DevelopmentGatewayStart: machine.DevelopmentPortStart,
        DevelopmentGatewayEnd: machine.DevelopmentPortEnd);

    await using var host =
        await ManagerCoreHost.CreateAsync(hostOptions);

    // Core starts agents in a predictable order, with Tunnel last. Each agent
    // remains independently operable: an unavailable peer is reported, not a
    // reason to withhold Tunnel or prevent other agents from starting.
    var runtimeStart = await host.ControlService.StartManagedRuntimeAsync();
    if (!runtimeStart.Success)
    {
        host.ControlService.Logs.Write(
            "WARN", "Core", "startup.partial", runtimeStart.Message);
        Console.Error.WriteLine(
            "One or more agents failed to start; other agents and the Tunnel " +
            "were attempted independently. Inspect Dashboard agent status.");
    }

    // Product host owns Core/UI; the private diagnostic pipe is created only for shutdown compatibility.
    await Zagent.Core.Dashboard.DashboardHost.RunAsync(host, dashboardOptions, dashboardConfig);
    return 0;
}

if (args.Contains("--status", StringComparer.Ordinal))
{
    var runtime = ZagentCoreRuntime.CreateDefault();
    Console.WriteLine(
        JsonSerializer.Serialize(
            runtime.GetSnapshot(),
            new JsonSerializerOptions { WriteIndented = true }));
    return 0;
}

var pathsIndex = Array.IndexOf(args, "--paths");
if (pathsIndex >= 0)
{
    if (pathsIndex + 1 >= args.Length ||
        string.IsNullOrWhiteSpace(args[pathsIndex + 1]))
    {
        Console.Error.WriteLine("--paths requires an InstallRoot argument.");
        return 2;
    }

    var installRoot = args[pathsIndex + 1];
    var profile = GetOptionValue(args, "--files-profile");
    var dataRoot = GetOptionValue(args, "--data-root");

    var resolver = new BasePathResolver();
    var layout = resolver.Resolve(installRoot, profile, dataRoot);

    Console.WriteLine(
        JsonSerializer.Serialize(
            layout,
            new JsonSerializerOptions { WriteIndented = true }));
    return 0;
}

Console.WriteLine(
    $"{ZagentProductInfo.ProjectName} / {ZagentProductInfo.ProductName} Core " +
    $"{ZagentProductInfo.CoreVersion}");
Console.WriteLine(
    "Use --self-test, --status, --version, --initialize-install --root <InstallRoot>, " +
    "--serve-dashboard --root <ZagentRoot> --dashboard-config <Path>, or --paths <InstallRoot> " +
    "[--files-profile <Path>] [--data-root <Path>].");
return 0;

static string? GetOptionValue(string[] arguments, string option)
{
    var index = Array.IndexOf(arguments, option);
    if (index < 0)
    {
        return null;
    }

    if (index + 1 >= arguments.Length ||
        string.IsNullOrWhiteSpace(arguments[index + 1]))
    {
        throw new ArgumentException($"{option} requires a path argument.");
    }

    return arguments[index + 1];
}

static AgentEnvironment ReadAgentEnvironment()
{
    var raw = Environment.GetEnvironmentVariable(
        "ZAGENT_ENVIRONMENT");

    if (string.IsNullOrWhiteSpace(raw))
    {
        return AgentEnvironment.Production;
    }

    if (Enum.TryParse<AgentEnvironment>(
            raw,
            ignoreCase: true,
            out var environment))
    {
        return environment;
    }

    throw new ArgumentException(
        "ZAGENT_ENVIRONMENT must be DEVELOPMENT, STAGING, or PRODUCTION.");
}

static int ReadPortEnvironment(
    string variableName,
    int fallback)
{
    var raw =
        Environment.GetEnvironmentVariable(
            variableName);

    if (string.IsNullOrWhiteSpace(raw))
    {
        return fallback;
    }

    if (!int.TryParse(
            raw,
            out var port) ||
        port is < 1 or > 65535)
    {
        throw new ArgumentException(
            $"{variableName} must be an integer between 1 and 65535.");
    }

    return port;
}

static string InferFilesProfileRoot(string zagentRoot)
{
    var current = new DirectoryInfo(zagentRoot);

    while (current is not null)
    {
        if (string.Equals(
                current.Name,
                "appBridge",
                StringComparison.OrdinalIgnoreCase))
        {
            return current.FullName;
        }

        current = current.Parent;
    }

    return Path.Combine(zagentRoot, "workspace");
}

static string ReadComponentVersion(
    string installRoot,
    string relativeManifestPath,
    string fallback)
{
    try
    {
        var path = Path.Combine(
            installRoot,
            relativeManifestPath);

        using var document =
            JsonDocument.Parse(
                File.ReadAllText(path));

        return document.RootElement
            .GetProperty("version")
            .GetString() ??
            fallback;
    }
    catch
    {
        return fallback;
    }
}