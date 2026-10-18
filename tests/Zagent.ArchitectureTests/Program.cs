using Zagent.Core;
using Zagent.Core.Configuration;
using Zagent.Core.Network;
using Zagent.Core.Paths;
using Zagent.Core.Registry;
using Zagent.Shared;
using Zagent.Shared.Contracts;
using Zagent.Shared.Installation;

var passed = 0;
var failed = 0;

Run("product identity", () =>
{
    Equal("Zagent", ZagentProductInfo.ProductName);
    Equal("1.0", ZagentProductInfo.AgentProtocolVersion);
});

Run("valid development manifest", () =>
{
    var validator = new AgentManifestValidator();
    var result = validator.Validate(SampleManifests.CreateDevelopmentEchoAgent());
    True(result.IsValid, string.Join("; ", result.Errors));
});

Run("invalid agent id rejected", () =>
{
    var validator = new AgentManifestValidator();
    var result = validator.Validate(
        SampleManifests.CreateDevelopmentEchoAgent("Invalid Agent"));
    False(result.IsValid, "Invalid agent id was accepted.");
});

Run("invalid protocol rejected", () =>
{
    var validator = new AgentManifestValidator();
    var manifest = SampleManifests.CreateDevelopmentEchoAgent() with
    {
        ProtocolVersion = "999"
    };
    False(
        validator.Validate(manifest).IsValid,
        "Unsupported protocol was accepted.");
});

Run("duplicate capability rejected", () =>
{
    var validator = new AgentManifestValidator();
    var source = SampleManifests.CreateDevelopmentEchoAgent();
    var duplicate = source.Capabilities[0];
    var manifest = source with
    {
        Capabilities = new[] { duplicate, duplicate }
    };
    False(
        validator.Validate(manifest).IsValid,
        "Duplicate capability was accepted.");
});

Run("development registration succeeds", () =>
{
    var registry = new CapabilityRegistry();
    var result = registry.Register(
        SampleManifests.CreateDevelopmentEchoAgent());
    True(result.Success, string.Join("; ", result.Errors));
    Equal(1, registry.Snapshot().Count);
});

Run("duplicate agent registration rejected", () =>
{
    var registry = new CapabilityRegistry();
    var manifest = SampleManifests.CreateDevelopmentEchoAgent();
    True(registry.Register(manifest).Success, "Initial registration failed.");
    False(registry.Register(manifest).Success, "Duplicate agent was accepted.");
});

Run("production requires explicit approval", () =>
{
    var manifest = SampleManifests.CreateDevelopmentEchoAgent("prod.echo") with
    {
        Environment = AgentEnvironment.Production
    };
    False(
        new CapabilityRegistry().Register(manifest).Success,
        "Production agent registered without approval.");

    var approved = new CapabilityRegistry().Register(
        manifest,
        productionApproved: true);
    True(approved.Success, string.Join("; ", approved.Errors));
    True(
        approved.RegisteredAgent?.ProductionApproved == true,
        "Production approval flag was not retained.");
});

Run("health update is registry-owned", () =>
{
    var registry = new CapabilityRegistry();
    var manifest = SampleManifests.CreateDevelopmentEchoAgent();
    True(registry.Register(manifest).Success, "Registration failed.");
    True(
        registry.TrySetHealth(manifest.Agent.Id, AgentHealthState.Ready),
        "Health update failed.");
    True(
        registry.TryGet(manifest.Agent.Id, out var registered),
        "Registered agent not found.");
    Equal(AgentHealthState.Ready, registered?.Health);
});

Run("capability ownership lookup", () =>
{
    var registry = new CapabilityRegistry();
    var manifest = SampleManifests.CreateDevelopmentEchoAgent();
    True(registry.Register(manifest).Success, "Registration failed.");
    var owners = registry.FindOwners("dev.echo.ping");
    Equal(1, owners.Count);
    Equal("dev.echo", owners[0].Manifest.Agent.Id);
});

Run("development port policy boundaries", () =>
{
    False(
        ZagentNetworkPolicy.IsDevelopmentPort(18899),
        "Port below development range was accepted.");
    True(
        ZagentNetworkPolicy.IsDevelopmentPort(18900),
        "Development range start was rejected.");
    True(
        ZagentNetworkPolicy.IsDevelopmentPort(18999),
        "Development range end was rejected.");
    False(
        ZagentNetworkPolicy.IsDevelopmentPort(19000),
        "Port above development range was accepted.");
});

Run("Master and User install identities, ports and IPC are independent", () =>
{
    var master = ZagentNetworkPolicy.For("Master");
    var user = ZagentNetworkPolicy.For("User");
    Equal("Master", ZagentInstallationProfile.FromAudience("zagent-production"));
    Equal("User", ZagentInstallationProfile.FromAudience("tryplugin"));
    Equal("Zagent Master", ZagentInstallationProfile.DisplayName("Ikbal"));
    Equal("Zagent User", ZagentInstallationProfile.DisplayName("Harry"));
    Equal("Zagent.Manager.Master.v1", ZagentInstallationProfile.PipeName("Primary"));
    Equal("Zagent.Manager.User.v1", ZagentInstallationProfile.PipeName("Secondary"));
    False(ZagentInstallationProfile.SupervisorLeaseName("Master") ==
          ZagentInstallationProfile.SupervisorLeaseName("User"),
          "Supervisor leases must not overlap.");
    Equal(18800, master.Core);
    Equal(19100, user.Core);
    Equal(18900, master.DevelopmentGatewayStart);
    Equal(19200, user.DevelopmentGatewayStart);
    Equal(19000, master.DevRuntimeStart);
    Equal(19300, user.DevRuntimeStart);
    True(master.ProductionEnd < user.ProductionStart,
         "Master/User production ranges overlap.");
    False(ZagentNetworkPolicy.IsDevelopmentPort(user.DevelopmentGatewayStart, "Master"),
          "User development port was accepted in Master profile.");
    True(ZagentNetworkPolicy.IsDevelopmentPort(user.DevelopmentGatewayStart, "User"),
         "User development gateway start rejected.");
    var parent = ValidationPath("role-install-roots", "base");
    Equal(Path.Combine(parent, "Zagent Master"),
          InstallTargetResolver.ResolveFromBaseFolder(parent, "Master"));
    Equal(Path.Combine(parent, "Zagent User"),
          InstallTargetResolver.ResolveFromBaseFolder(parent, "User"));
});

Run("User configuration allocator and bootstrap reject Master ports", () =>
{
    var root = ValidationPath("role-user-bootstrap", "Zagent User");
    var layout = new BasePathResolver().Resolve(root);
    var engine = new ZagentConfigurationEngine();
    var user = engine.CreateDefaultMachineConfiguration(layout, "User");
    Equal("User", user.InstallationRole);
    Equal(19130, user.WebPort);
    var allocator = new ZagentPortAllocator((_, port) => port != 19130);
    var allocated = allocator.Allocate(user);
    Equal(19131, allocated.WebPort);
    True(new[] { allocated.CorePort, allocated.TunnelPort, allocated.TunnelHealthPort,
                 allocated.FilesPort, allocated.WebPort, allocated.ArcMapPort }
         .All(port => port >= 19100 && port <= 19199),
         "One of the User ports escaped the reserved range.");
    var rejected = false;
    try
    {
        engine.SaveMachineConfigurationAsync(layout, allocated with { ArcMapPort = 18840 })
              .GetAwaiter().GetResult();
    }
    catch (InvalidDataException)
    {
        rejected = true;
    }
    True(rejected, "User profile accepted a Master ArcMap port.");
    var snapshot = new ZagentConfigurationBootstrapper(portAllocator: allocator)
        .BootstrapAsync(root, installationRole: "User")
        .GetAwaiter().GetResult();
    Equal("User", snapshot.Machine.InstallationRole);
    Equal(19131, snapshot.Machine.WebPort);
});

Run("user selected install root is preserved exactly", () =>
{
    var resolver = new BasePathResolver();
    var layout = resolver.Resolve(
        @"D:\My Apps\Zagent",
        @"D:\3-Ikbalzohr\Agent\appBridge");

    Equal(@"D:\My Apps\Zagent", layout.InstallRoot);
    Equal(
        @"D:\3-Ikbalzohr\Agent\appBridge",
        layout.FilesDefaultProfile);
    Equal(
        @"D:\My Apps\Zagent\data",
        layout.DataRoot);
});

Run("default mutable data stays inside selected install root", () =>
{
    var resolver = new BasePathResolver();
    var layout = resolver.Resolve(@"E:\Portable Apps\Zagent");
    Equal(
        @"E:\Portable Apps\Zagent\data",
        layout.DataRoot);
    Equal(
        @"E:\Portable Apps\Zagent\workspace",
        layout.FilesDefaultProfile);
});

Run("custom data root is supported", () =>
{
    var resolver = new BasePathResolver();
    var layout = resolver.Resolve(
        @"E:\Apps\Zagent",
        @"E:\AgentWorkspace",
        @"F:\ZagentData");

    Equal(@"E:\Apps\Zagent", layout.InstallRoot);
    Equal(@"E:\AgentWorkspace", layout.FilesDefaultProfile);
    Equal(@"F:\ZagentData", layout.DataRoot);
});

Run("configuration engine persists authoritative machine config", () =>
{
    var resolver = new BasePathResolver();
    var installRoot = ValidationPath("phase2-config", "install");
    var profile = ValidationPath("phase2-config", "profile");
    var layout = resolver.Resolve(installRoot, profile);
    var engine = new ZagentConfigurationEngine(resolver);

    engine.EnsurePersistentDirectories(layout);
    var config = engine.CreateDefaultMachineConfiguration(layout);
    engine.SaveMachineConfigurationAsync(layout, config)
        .GetAwaiter()
        .GetResult();

    var loaded = engine.LoadMachineConfigurationAsync(layout)
        .GetAwaiter()
        .GetResult();

    Equal(layout.InstallRoot, loaded.InstallRoot);
    Equal(layout.FilesDefaultProfile, loaded.FilesDefaultProfile);
    Equal(layout.DataRoot, loaded.DataRoot);
    Equal(ZagentNetworkPolicy.DefaultBindHost, loaded.BindHost);
});

Run("configuration rejects duplicate fixed ports", () =>
{
    var resolver = new BasePathResolver();
    var layout = resolver.Resolve(
        ValidationPath("phase2-duplicate-port", "install"));
    var engine = new ZagentConfigurationEngine(resolver);
    var config = engine.CreateDefaultMachineConfiguration(layout) with
    {
        WebPort = ZagentNetworkPolicy.FilesPort
    };

    var rejected = false;
    try
    {
        engine.SaveMachineConfigurationAsync(layout, config)
            .GetAwaiter()
            .GetResult();
    }
    catch (InvalidDataException)
    {
        rejected = true;
    }

    True(rejected, "Duplicate fixed ports were accepted.");
});

Run("installed manifest stores exact selected install path", () =>
{
    var resolver = new BasePathResolver();
    var layout = resolver.Resolve(
        ValidationPath("phase2-installed-manifest", "custom-install"),
        ValidationPath("phase2-installed-manifest", "profile"));
    var engine = new ZagentConfigurationEngine(resolver);

    engine.EnsurePersistentDirectories(layout);
    var manifest = engine.CreateInstalledManifest(
        layout,
        "2.0.0-dev",
        new[]
        {
            new InstalledComponent(
                "core",
                "0.2.0-dev.1",
                Path.Combine("core", "Zagent.Core.exe"))
        });

    engine.SaveInstalledManifestAsync(layout, manifest)
        .GetAwaiter()
        .GetResult();

    var loaded = engine.LoadInstalledManifestAsync(layout)
        .GetAwaiter()
        .GetResult();

    Equal(layout.InstallRoot, loaded.InstallRoot);
    Equal(layout.DataRoot, loaded.DataRoot);
    Equal(layout.FilesDefaultProfile, loaded.FilesDefaultProfile);
    Equal(1, loaded.Components.Count);
});

Run("installed manifest rejects path traversal", () =>
{
    var resolver = new BasePathResolver();
    var layout = resolver.Resolve(
        ValidationPath("phase2-traversal", "install"));
    var engine = new ZagentConfigurationEngine(resolver);
    var manifest = engine.CreateInstalledManifest(
        layout,
        "2.0.0-dev",
        new[]
        {
            new InstalledComponent(
                "escape",
                "1.0.0",
                Path.Combine("..", "..", "escape.exe"))
        });

    var rejected = false;
    try
    {
        engine.SaveInstalledManifestAsync(layout, manifest)
            .GetAwaiter()
            .GetResult();
    }
    catch (InvalidDataException)
    {
        rejected = true;
    }

    True(rejected, "Path traversal component was accepted.");
});

Run("corrupt machine configuration is rejected", () =>
{
    var resolver = new BasePathResolver();
    var layout = resolver.Resolve(
        ValidationPath("phase2-corrupt-json", "install"));
    var engine = new ZagentConfigurationEngine(resolver);

    engine.EnsurePersistentDirectories(layout);
    File.WriteAllText(
        engine.GetMachineConfigurationPath(layout),
        "{ invalid-json");

    var rejected = false;
    try
    {
        engine.LoadMachineConfigurationAsync(layout)
            .GetAwaiter()
            .GetResult();
    }
    catch (InvalidDataException)
    {
        rejected = true;
    }

    True(rejected, "Corrupt machine configuration was accepted.");
});

Run("configuration bootstrap creates persistent structure", () =>
{
    var installRoot = ValidationPath("phase2-bootstrap", "install");
    var profile = ValidationPath("phase2-bootstrap", "profile");
    var bootstrapper = new ZagentConfigurationBootstrapper();
    var snapshot = bootstrapper.BootstrapAsync(installRoot, profile)
        .GetAwaiter()
        .GetResult();

    True(Directory.Exists(snapshot.Paths.ConfigRoot), "ConfigRoot was not created.");
    True(Directory.Exists(snapshot.Paths.LogsRoot), "LogsRoot was not created.");
    True(Directory.Exists(snapshot.Paths.RuntimeRoot), "RuntimeRoot was not created.");
    True(Directory.Exists(snapshot.Paths.StateRoot), "StateRoot was not created.");
    True(Directory.Exists(snapshot.Paths.BackupRoot), "BackupRoot was not created.");
    True(Directory.Exists(snapshot.Paths.FilesDefaultProfile), "Files profile was not created.");
    True(File.Exists(snapshot.MachineConfigurationPath), "Machine config was not created.");
});

Run("first install allocates around occupied production ports and persists the result", () =>
{
    var scenarioRoot =
        ValidationPath("phase2-install-aware-ports", "install");

    if (Directory.Exists(scenarioRoot))
    {
        Directory.Delete(scenarioRoot, recursive: true);
    }

    var unavailable =
        ZagentNetworkPolicy.WebPort;

    var allocator =
        new ZagentPortAllocator(
            (_, port) =>
                port != unavailable);

    var bootstrapper =
        new ZagentConfigurationBootstrapper(
            portAllocator: allocator);

    var first = bootstrapper.BootstrapAsync(
            scenarioRoot)
        .GetAwaiter()
        .GetResult();

    Equal(ZagentNetworkPolicy.CorePort, first.Machine.CorePort);
    Equal(ZagentNetworkPolicy.TunnelPort, first.Machine.TunnelPort);
    Equal(ZagentNetworkPolicy.TunnelHealthPort, first.Machine.TunnelHealthPort);
    Equal(ZagentNetworkPolicy.FilesPort, first.Machine.FilesPort);
    Equal(18831, first.Machine.WebPort);
    Equal(ZagentNetworkPolicy.ArcMapPort, first.Machine.ArcMapPort);

    var preserveBootstrapper =
        new ZagentConfigurationBootstrapper(
            portAllocator:
                new ZagentPortAllocator(
                    (_, _) => false));

    var second =
        preserveBootstrapper.BootstrapAsync(
                scenarioRoot)
            .GetAwaiter()
            .GetResult();

    Equal(first.Machine.WebPort, second.Machine.WebPort);
    Equal(first.Machine.TunnelPort, second.Machine.TunnelPort);
});

Run("configuration bootstrap preserves valid existing configuration", () =>
{
    var installRoot = ValidationPath(
        "phase2-bootstrap-preserve",
        "install");
    var resolver = new BasePathResolver();
    var engine = new ZagentConfigurationEngine(resolver);
    var bootstrapper = new ZagentConfigurationBootstrapper(engine);

    var first = bootstrapper.BootstrapAsync(installRoot)
        .GetAwaiter()
        .GetResult();
    var customized = first.Machine with { BindHost = "127.0.0.4" };

    engine.SaveMachineConfigurationAsync(first.Paths, customized)
        .GetAwaiter()
        .GetResult();

    var second = bootstrapper.BootstrapAsync(installRoot)
        .GetAwaiter()
        .GetResult();

    Equal("127.0.0.4", second.Machine.BindHost);
});

Run("atomic configuration replacement creates backup", () =>
{
    var resolver = new BasePathResolver();
    var layout = resolver.Resolve(
        ValidationPath("phase2-atomic-backup", "install"));
    var engine = new ZagentConfigurationEngine(resolver);

    engine.EnsurePersistentDirectories(layout);
    var first = engine.CreateDefaultMachineConfiguration(layout);
    engine.SaveMachineConfigurationAsync(layout, first)
        .GetAwaiter()
        .GetResult();

    var second = first with { BindHost = "127.0.0.5" };
    engine.SaveMachineConfigurationAsync(layout, second)
        .GetAwaiter()
        .GetResult();

    var configPath = engine.GetMachineConfigurationPath(layout);
    True(File.Exists(configPath + ".bak"), "Backup file was not created.");

    var loaded = engine.LoadMachineConfigurationAsync(layout)
        .GetAwaiter()
        .GetResult();
    Equal("127.0.0.5", loaded.BindHost);
});

Run("concurrent configuration writes remain valid", () =>
{
    var resolver = new BasePathResolver();
    var layout = resolver.Resolve(
        ValidationPath("phase2-concurrent-write", "install"));
    var engine = new ZagentConfigurationEngine(resolver);

    engine.EnsurePersistentDirectories(layout);
    var baseline = engine.CreateDefaultMachineConfiguration(layout);

    var tasks = Enumerable.Range(0, 8)
        .Select(index =>
        {
            var config = baseline with
            {
                BindHost = $"127.0.0.{10 + index}"
            };
            return engine.SaveMachineConfigurationAsync(layout, config);
        })
        .ToArray();

    Task.WhenAll(tasks).GetAwaiter().GetResult();

    var loaded = engine.LoadMachineConfigurationAsync(layout)
        .GetAwaiter()
        .GetResult();

    True(
        loaded.BindHost.StartsWith("127.0.0.", StringComparison.Ordinal),
        "Concurrent writes produced an invalid final configuration.");
});

Run("core runtime snapshot reflects registry", () =>
{
    var registry = new CapabilityRegistry();
    var runtime = new ZagentCoreRuntime(registry);

    Equal(0, runtime.GetSnapshot().RegisteredAgents);
    True(
        registry.Register(SampleManifests.CreateDevelopmentEchoAgent()).Success,
        "Registration failed.");
    var snapshot = runtime.GetSnapshot();

    Equal("Zagent", snapshot.ProductName);
    Equal(ZagentProductInfo.CoreVersion, snapshot.CoreVersion);
    Equal(1, snapshot.RegisteredAgents);
});

Console.WriteLine(
    failed == 0
        ? $"ARCH_TEST_PASS passed={passed} failed={failed}"
        : $"ARCH_TEST_FAIL passed={passed} failed={failed}");

return failed == 0 ? 0 : 1;

string ValidationPath(string scenario, string leaf) =>
    Path.GetFullPath(
        Path.Combine(
            AppContext.BaseDirectory,
            "..",
            "..",
            "..",
            "..",
            "..",
            "_validation",
            scenario,
            leaf));

void Run(string name, Action test)
{
    try
    {
        test();
        passed++;
        Console.WriteLine($"PASS {name}");
    }
    catch (Exception ex)
    {
        failed++;
        Console.WriteLine($"FAIL {name}: {ex.Message}");
    }
}

static void True(bool condition, string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
}

static void False(bool condition, string message) =>
    True(!condition, message);

static void Equal<T>(T expected, T actual)
{
    if (!EqualityComparer<T>.Default.Equals(expected, actual))
    {
        throw new InvalidOperationException(
            $"Expected '{expected}', actual '{actual}'.");
    }
}
