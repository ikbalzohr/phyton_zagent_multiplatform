using Zagent.Launcher;
using System.Diagnostics;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text.Json;

if (args.Length > 1 && args[0] == "--fake-child")
{
    File.WriteAllText(args[1], JsonSerializer.Serialize(args.Skip(2)));
    Environment.Exit(7);
}

if (args.Length == 3 && args[0] == "--preflight-existing")
{
    Environment.Exit(LauncherApplication.Run(args[1], args[2], _ =>
    {
        Console.WriteLine("PASS product-bound enrollment and runtime preflight; activation suppressed");
        return 0;
    }));
}

if (args.Length == 4 && args[0] == "--preflight-published")
{
    var assembly = System.Reflection.Assembly.LoadFile(Path.GetFullPath(args[1]));
    var type = assembly.GetType("Zagent.Launcher.LauncherApplication", true)!;
    Func<ProcessStartInfo, int?> suppress = _ =>
    {
        Console.WriteLine("PASS published launcher product-bound preflight; Core activation suppressed");
        return 0;
    };
    Environment.Exit((int)type.GetMethod("Run")!.Invoke(null, new object?[] { args[2], args[3], suppress })!);
}

var tempRoot = Path.Combine(Path.GetTempPath(), "Zagent-LauncherTests-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(tempRoot);
var count = 0;
void Check(bool valid, string description)
{
    if (!valid) throw new Exception(description);
    count++;
    Console.WriteLine("PASS " + description);
}
void Reject(Action action, string expected, string name)
{
    try { action(); }
    catch (InvalidOperationException ex) when (ex.Message == expected)
    {
        Check(true, name);
        return;
    }
    throw new Exception("Expected " + expected + ": " + name);
}
void Private(string path, bool directory)
{
    var user = WindowsIdentity.GetCurrent().User!;
    FileSystemSecurity acl = directory ? new DirectorySecurity() : new FileSecurity();
    acl.SetOwner(user);
    acl.SetAccessRuleProtection(true, false);
    acl.AddAccessRule(new FileSystemAccessRule(user, FileSystemRights.FullControl,
        directory ? InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit : InheritanceFlags.None,
        PropagationFlags.None, AccessControlType.Allow));
    if (directory) new DirectoryInfo(path).SetAccessControl((DirectorySecurity)acl);
    else new FileInfo(path).SetAccessControl((FileSecurity)acl);
}
void Enroll(string install, string data, bool installed)
{
    var config = Path.Combine(data, "config");
    Directory.CreateDirectory(config);
    File.WriteAllText(Path.Combine(config, "zagent.machine.json"),
        JsonSerializer.Serialize(new { InstallRoot = install, DataRoot = data }));
    File.WriteAllText(Path.Combine(config, "dashboard.json"), "{}");
    File.WriteAllText(Path.Combine(config, "internal-secrets.dpapi.json"), "encrypted fixture only");
    if (installed)
        File.WriteAllText(Path.Combine(config, "installed-manifest.json"),
            JsonSerializer.Serialize(new { installRoot = install, dataRoot = data }));
    Private(data, true); Private(config, true);
    foreach (var f in Directory.GetFiles(config)) Private(f, false);
}
void FileFixture(string path)
{
    Directory.CreateDirectory(Path.GetDirectoryName(path)!);
    File.WriteAllText(path, "fixture never executed");
}
void Runtimes(ProcessStartInfo start, string root, bool installed)
{
    FileFixture(start.FileName);
    FileFixture(Path.Combine(root, "agents", "web", "engine", "dist", "index.js"));
    foreach (var key in new[] { "ZAGENT_FILES_PYTHON", "ZAGENT_TUNNEL_PYTHON",
             "ZAGENT_WEB_NODE", "ZAGENT_ARCMAP_PYTHON" })
        FileFixture(start.Environment[key]!);
    if (!installed)
    {
        foreach (var suffix in new[] { ".dll", ".runtimeconfig.json", ".deps.json" })
            FileFixture(Path.ChangeExtension(start.FileName, suffix));
        FileFixture(Path.Combine(start.Environment["DOTNET_ROOT"]!, "dotnet.exe"));
    }
}
var oldEnv = new Dictionary<string, string?>();
void SetEnv(string key, string? value)
{
    if (!oldEnv.ContainsKey(key)) oldEnv[key] = Environment.GetEnvironmentVariable(key);
    Environment.SetEnvironmentVariable(key, value);
}
try
{
    // Real installer layout with payload marker and fully local runtimes.
    var install = Path.Combine(tempRoot, "install with spaces", "Zagent");
    Directory.CreateDirectory(install);
    FileFixture(Path.Combine(install, "payload-manifest.json"));
    FileFixture(Path.Combine(install, "Zagent.Core.exe"));
    var data = Path.Combine(install, "data");
    Enroll(install, data, installed: true);

    Check(LaunchPlan.DiscoverDataRoot(install) == data, "installation defaults to its own DataRoot");
    Check(LaunchPlan.DiscoverDataRoot(install, data) == data, "explicit matching DataRoot is accepted");
    var nested = Directory.CreateDirectory(Path.Combine(install, "artifacts", "launcher-win-x64")).FullName;
    Check(LauncherApplication.FindInstallRoot(nested) == install, "published nested launcher detects install root");
    var start = LaunchPlan.Create(install, data);
    Check(start.FileName == Path.Combine(install, "Zagent.Core.exe"), "installed Core executable selected");
    Check(start.ArgumentList.SequenceEqual(new[] { "--dashboard", "--root", install,
        "--data-root", data, "--dashboard-config", Path.Combine(data, "config", "dashboard.json") }),
        "installed Core dashboard arguments remain exact");
    Check(!start.UseShellExecute && start.CreateNoWindow, "installed Core is a direct child, no console");
    Check(!start.Environment.ContainsKey("DOTNET_ROOT"), "self-contained installation does not rely on sibling .NET runtime");

    SetEnv("ZAGENT_PLUGIN_AUDIENCE", "other-product");
    SetEnv("ZAGENT_INTERNAL_TOKEN", "other-product-secret");
    SetEnv("ZAGENT_ENVIRONMENT", "Development");
    var isolated = LaunchPlan.Create(install, data);
    Check(!isolated.Environment.ContainsKey("ZAGENT_PLUGIN_AUDIENCE") &&
          !isolated.Environment.ContainsKey("ZAGENT_INTERNAL_TOKEN") &&
          isolated.Environment["ZAGENT_ENVIRONMENT"] == "Production",
          "inherited sibling authority is stripped from child environment");

    var activations = 0;
    int? Fake(ProcessStartInfo actual)
    {
        activations++;
        Check(actual.FileName == start.FileName && actual.ArgumentList.SequenceEqual(start.ArgumentList),
            "fake activation receives approved installed Core arguments");
        return 0;
    }
    Reject(() => LauncherApplication.Run(install, null, Fake), "REQUIRED_RUNTIME_MISSING",
        "missing bundled runtimes prevent Core startup");
    Check(activations == 0, "failed runtime preflight never dispatches child");
    Runtimes(start, install, installed: true);
    Check(LauncherApplication.Run(install, null, Fake) == 0, "valid installed ACL and runtime preflight succeeds");
    Check(LauncherApplication.Run(install, null, Fake) == 0 && activations == 2,
        "duplicate activation delegates to existing Core single-instance lease");
    Reject(() => LauncherApplication.Run(install, null, _ => 7), "CORE_START_FAILED",
        "early Core failure is not counted as success");
    Check(LauncherApplication.Run(install, null, _ => null) == 0,
        "bounded observation allows Core lifetime to continue");

    var unrelated = Path.Combine(tempRoot, "other Zagent", "data");
    Enroll(install, unrelated, installed: true);
    Check(LaunchPlan.DiscoverDataRoot(install, unrelated) == unrelated,
        "explicit external DataRoot is accepted when bound to this install");
    Check(LaunchPlan.DiscoverDataRoot(install, null, _ => unrelated) == unrelated,
        "per-install Windows registration resolves custom bound DataRoot");
    Reject(() => LaunchPlan.DiscoverDataRoot(install, null, _ => Path.Combine(tempRoot, "not-enrolled")),
        "ENROLLMENT_SELECTION_REQUIRED", "unprovisioned registry DataRoot fails closed");
    File.WriteAllText(Path.Combine(unrelated, "config", "zagent.machine.json"),
        JsonSerializer.Serialize(new { InstallRoot = Path.Combine(tempRoot, "wrong-install"),
            DataRoot = unrelated }));
    Reject(() => LaunchPlan.DiscoverDataRoot(install, unrelated), "ENROLLMENT_INSTALL_MISMATCH",
        "DataRoot binding rejects a mismatched install root");
    var otherInstall = Path.Combine(tempRoot, "foreign", "Zagent");
    Directory.CreateDirectory(otherInstall);
    FileFixture(Path.Combine(otherInstall, "payload-manifest.json"));
    FileFixture(Path.Combine(otherInstall, "Zagent.Core.exe"));
    Enroll(otherInstall, Path.Combine(otherInstall, "data"), installed: true);
    Reject(() => LaunchPlan.DiscoverDataRoot(install, Path.Combine(otherInstall, "data")),
        "ENROLLMENT_INSTALL_MISMATCH", "foreign installation enrollment cannot be selected");
    File.Delete(Path.Combine(data, "config", "installed-manifest.json"));
    Reject(() => LaunchPlan.DiscoverDataRoot(install), "ENROLLMENT_SELECTION_REQUIRED",
        "missing installed manifest fails closed");
    Enroll(install, data, installed: true);
    File.WriteAllText(Path.Combine(data, "config", "zagent.machine.json"), "not-json");
    Reject(() => LaunchPlan.DiscoverDataRoot(install), "ENROLLMENT_INSTALL_MISMATCH",
        "malformed machine configuration fails closed");
    Enroll(install, data, installed: true);
    var insecure = new DirectorySecurity();
    insecure.SetOwner(WindowsIdentity.GetCurrent().User!);
    insecure.SetAccessRuleProtection(false, false);
    new DirectoryInfo(Path.Combine(data, "config")).SetAccessControl(insecure);
    Reject(() => LauncherApplication.Run(install, null, Fake), "OWNER_ACL_REQUIRED",
        "unsafe inherited ACL is rejected");
    Enroll(install, data, installed: true);

    // Source checkout is an explicit local development mode, no appBridge/sibling
    // install discovery. All four runtimes and .NET root require explicit paths.
    var source = Path.Combine(tempRoot, "checkout with spaces");
    Directory.CreateDirectory(source);
    FileFixture(Path.Combine(source, "component-manifest.json"));
    FileFixture(Path.Combine(source, "src", "Zagent.Core", "Zagent.Core.csproj"));
    var sourceData = Path.Combine(source, "data");
    Enroll(source, sourceData, installed: false);
    SetEnv("ZAGENT_LAUNCHER_DOTNET_ROOT", null);
    Reject(() => LaunchPlan.Create(source, sourceData), "REQUIRED_RUNTIME_MISSING",
        "source mode fails without explicitly chosen runtimes");
    SetEnv("ZAGENT_LAUNCHER_DOTNET_ROOT", Path.Combine(source, "tools", "dotnet"));
    SetEnv("ZAGENT_LAUNCHER_FILES_PYTHON", Path.Combine(source, "tools", "files-python.exe"));
    SetEnv("ZAGENT_LAUNCHER_TUNNEL_PYTHON", Path.Combine(source, "tools", "tunnel-python.exe"));
    SetEnv("ZAGENT_LAUNCHER_WEB_NODE", Path.Combine(source, "tools", "node.exe"));
    SetEnv("ZAGENT_LAUNCHER_ARCMAP_PYTHON", Path.Combine(source, "tools", "arcmap-python.exe"));
    var sourceStart = LaunchPlan.Create(source, sourceData);
    Check(sourceStart.FileName == Path.Combine(source, "src", "Zagent.Core", "bin", "Debug", "net10.0", "Zagent.Core.exe"),
        "source checkout uses only its own Core build");
    Check(sourceStart.Environment["DOTNET_ROOT"] == Path.Combine(source, "tools", "dotnet"),
        "source SDK is explicitly chosen instead of sibling appBridge");
    Runtimes(sourceStart, source, installed: false);
    Check(LauncherApplication.Run(source, null, _ => 0) == 0,
        "isolated checkout preflight passes with explicit runtime inputs");
    Check(LauncherApplication.FindInstallRoot(Path.Combine(source, "src", "Zagent.Core")) == source,
        "checkout root discovery does not require historic PowerShell launcher");
    Reject(() => LaunchPlan.DiscoverDataRoot(source, Path.Combine(otherInstall, "data")),
        "ENROLLMENT_INSTALL_MISMATCH", "source cannot import a foreign product enrollment");

    var lease = @"Local\Zagent.LauncherTests." + Guid.NewGuid().ToString("N");
    Check(Zagent.Core.Supervision.SupervisorInstanceLease.TryAcquire(lease, out var firstLease),
        "isolated Core instance lease acquired");
    using (firstLease)
        Check(!Zagent.Core.Supervision.SupervisorInstanceLease.TryAcquire(lease, out _),
            "Core rejects duplicate instance lease");
    Check(Zagent.Core.Supervision.SupervisorInstanceLease.TryAcquire(lease, out var released),
        "Core lease released after fixture");
    released!.Dispose();

    var receipt = Path.Combine(tempRoot, "fake-child-args.json");
    var dotnet = new ProcessStartInfo(args.Length == 1 ? args[0] :
        throw new InvalidOperationException("Pass approved dotnet host path as fixture argument"))
    { UseShellExecute = false, CreateNoWindow = true };
    foreach (var arg in new[] { typeof(Program).Assembly.Location, "--fake-child", receipt }
        .Concat(sourceStart.ArgumentList)) dotnet.ArgumentList.Add(arg);
    Check(LauncherApplication.Activate(dotnet) == 7, "bounded real fake-child exit is detected");
    Check(JsonSerializer.Deserialize<string[]>(File.ReadAllText(receipt))!.SequenceEqual(sourceStart.ArgumentList),
        "real fake-child preserves all arguments");
    Console.WriteLine($"LAUNCHER_TEST_PASS passed={count}; Core activation never executed");
}
finally
{
    foreach (var item in oldEnv) Environment.SetEnvironmentVariable(item.Key, item.Value);
    Directory.Delete(tempRoot, recursive: true);
}
