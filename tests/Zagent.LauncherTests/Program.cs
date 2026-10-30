using Zagent.Launcher;
using System.Diagnostics;
using System.Security.AccessControl;
using System.Security.Principal;

if (args.Length > 1 && args[0] == "--fake-child") { File.WriteAllText(args[1], System.Text.Json.JsonSerializer.Serialize(args.Skip(2))); Environment.Exit(7); }

if (args.Length == 3 && args[0] == "--preflight-existing") { Environment.Exit(LauncherApplication.Run(args[1], args[2], _ => { Console.WriteLine("PASS actual existing enrollment ACL/runtime preflight; Core activation suppressed"); return 0; })); }

if (args.Length == 4 && args[0] == "--preflight-published") { var assembly = System.Reflection.Assembly.LoadFile(Path.GetFullPath(args[1])); var type = assembly.GetType("Zagent.Launcher.LauncherApplication", true)!; Func<ProcessStartInfo, int?> suppress = _ => { Console.WriteLine("PASS published DLL actual enrollment ACL/runtime preflight; Core activation suppressed"); return 0; }; Environment.Exit((int)type.GetMethod("Run")!.Invoke(null, new object[] { args[2], args[3], suppress })!); }

var root = Path.Combine(Path.GetTempPath(), "Zagent-LauncherTests-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
var count = 0;
void Check(bool value, string name) { if (!value) throw new Exception(name); Console.WriteLine("PASS " + name); count++; }
void Reject(Action action, string code, string name) {
    try { action(); } catch (InvalidOperationException e) when (e.Message == code) { Check(true, name); return; }
    throw new Exception("Expected " + code + ": " + name);
}
void Private(string path, bool directory) {
    var sid = WindowsIdentity.GetCurrent().User!;
    FileSystemSecurity acl = directory ? new DirectorySecurity() : new FileSecurity();
    acl.SetOwner(sid); acl.SetAccessRuleProtection(true, false);
    acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl,
        directory ? InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit : InheritanceFlags.None,
        PropagationFlags.None, AccessControlType.Allow));
    if (directory) new DirectoryInfo(path).SetAccessControl((DirectorySecurity)acl);
    else new FileInfo(path).SetAccessControl((FileSecurity)acl);
}
try {
    var install = Path.Combine(root, "install with spaces");
    var local = Path.Combine(root, "local");
    var data = Path.Combine(local, "Zagent-Existing");
    var config = Path.Combine(data, "config");
    Directory.CreateDirectory(install); Directory.CreateDirectory(config);
    File.WriteAllText(Path.Combine(config, "dashboard.json"), "not parsed: fixture only");
    File.WriteAllText(Path.Combine(config, "internal-secrets.dpapi.json"), "not parsed: fixture only");
    Check(LaunchPlan.DiscoverDataRoot(install, local) == data, "existing enrollment path discovery; no secret parsing");
    var start = LaunchPlan.Create(install, data, local);
    Check(start.ArgumentList.SequenceEqual(new[] { "--dashboard", "--root", install, "--data-root", data, "--dashboard-config", Path.Combine(config, "dashboard.json") }), "exact canonical Core argument boundaries including spaces");
    Check(!start.UseShellExecute && start.CreateNoWindow && start.WorkingDirectory == install, "console-free direct activation plan");
    Directory.CreateDirectory(Path.Combine(install, "src", "Zagent.Core"));
    File.WriteAllText(Path.Combine(install, "src", "Zagent.Core", "Zagent.Core.csproj"), "fixture");
    Directory.CreateDirectory(Path.Combine(install, "packaging", "scripts"));
    File.WriteAllText(Path.Combine(install, "packaging", "scripts", "Start-OwnerCore.ps1"), "fixture");
    var nested = Directory.CreateDirectory(Path.Combine(install, "artifacts", "launcher-win-x64")).FullName;
    Check(LauncherApplication.FindInstallRoot(nested) == install, "published directory discovers enclosing installed checkout");
    foreach (var p in new[] { start.FileName, Path.Combine(start.Environment["DOTNET_ROOT"]!, "dotnet.exe"), start.Environment["ZAGENT_FILES_PYTHON"]!, start.Environment["ZAGENT_TUNNEL_PYTHON"]!, Path.Combine(install, "agents", "web", "engine", "dist", "index.js") }) {
        Directory.CreateDirectory(Path.GetDirectoryName(p)!); File.WriteAllText(p, "fixture never executed");
    }
    Private(data, true); Private(config, true);
    Private(Path.Combine(config, "dashboard.json"), false); Private(Path.Combine(config, "internal-secrets.dpapi.json"), false);
    var activations = 0;
    int? Fake(ProcessStartInfo actual) { activations++; Check(actual.ArgumentList.SequenceEqual(start.ArgumentList), "fake child receives unchanged dashboard arguments"); return 0; }
    Reject(() => LauncherApplication.Run(install, local, Fake), "REQUIRED_RUNTIME_MISSING", "incomplete Core managed payload fails before dispatch");
    Check(activations == 0, "failed preflight never dispatches a child");
    File.WriteAllText(Path.ChangeExtension(start.FileName, ".dll"), "fixture");
    File.WriteAllText(Path.ChangeExtension(start.FileName, ".runtimeconfig.json"), "fixture");
    File.WriteAllText(Path.ChangeExtension(start.FileName, ".deps.json"), "fixture");
    Check(LauncherApplication.Run(install, local, Fake) == 0, "owner ACL preflight and fake activation succeed");
    Check(LauncherApplication.Run(install, local, Fake) == 0 && activations == 2, "duplicate launcher activation delegates to existing Core single-instance path, no launcher mutex");
    Reject(() => LauncherApplication.Run(install, local, _ => 7), "CORE_START_FAILED", "early child failure is not success");
    Check(LauncherApplication.Run(install, local, _ => null) == 0, "bounded observation permits continuing Core lifetime");
    File.Delete(start.Environment["ZAGENT_FILES_PYTHON"]!);
    Reject(() => LauncherApplication.Run(install, local, Fake), "REQUIRED_RUNTIME_MISSING", "missing isolated Files Python rejected without dispatch");
    var other = Path.Combine(local, "Zagent-Other", "config"); Directory.CreateDirectory(other);
    File.WriteAllText(Path.Combine(other, "dashboard.json"), "fixture"); File.WriteAllText(Path.Combine(other, "internal-secrets.dpapi.json"), "fixture");
    Reject(() => LaunchPlan.DiscoverDataRoot(install, local), "ENROLLMENT_SELECTION_REQUIRED", "ambiguous enrollment fails closed");
    Directory.Delete(Path.GetDirectoryName(other)!, true);
    var insecure = new DirectorySecurity(); insecure.SetOwner(WindowsIdentity.GetCurrent().User!); insecure.SetAccessRuleProtection(false, false);
    new DirectoryInfo(config).SetAccessControl(insecure);
    Reject(() => LauncherApplication.Run(install, local, Fake), "OWNER_ACL_REQUIRED", "inherited configuration ACL rejected");
    var leaseName = @"Local\Zagent.LauncherTests." + Guid.NewGuid().ToString("N");
    Check(Zagent.Core.Supervision.SupervisorInstanceLease.TryAcquire(leaseName, out var fixtureLease), "isolated real Core supervisor lease acquired");
    using (fixtureLease) {
        Check(!Zagent.Core.Supervision.SupervisorInstanceLease.TryAcquire(leaseName, out _), "duplicate activation rejected by real Core lease without live Core");
    }
    Check(Zagent.Core.Supervision.SupervisorInstanceLease.TryAcquire(leaseName, out var releasedLease), "Core lease released after fixture completion");
    releasedLease!.Dispose();
    var receipt = Path.Combine(root, "fake child args.json");
    var fakeChild = new ProcessStartInfo(args.Length == 1 ? args[0] : throw new Exception("Pass the approved portable dotnet.exe as the fixture argument")) { UseShellExecute = false, CreateNoWindow = true };
    foreach (var arg in new[] { typeof(Program).Assembly.Location, "--fake-child", receipt }.Concat(start.ArgumentList)) fakeChild.ArgumentList.Add(arg);
    Check(LauncherApplication.Activate(fakeChild) == 7, "real bounded process activation observes fake child exit 7");
    Check(System.Text.Json.JsonSerializer.Deserialize<string[]>(File.ReadAllText(receipt))!.SequenceEqual(start.ArgumentList), "real fake child receives dashboard arguments losslessly");
    Console.WriteLine($"PASS {count} assertions; isolated Windows owner-ACL/fake-child fixtures; no live Core start");
}
finally { Directory.Delete(root, true); }
