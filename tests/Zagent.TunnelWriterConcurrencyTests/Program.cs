using System.Collections.Concurrent;
using System.Diagnostics;
using System.Reflection;
using System.Text.Json.Nodes;
using Zagent.Core.Agents.Tunnel;
using Zagent.Core.Configuration;

// Arguments: repository root, fresh disposable fixture root, optional --product-lock.
var repo = Path.GetFullPath(args[0]);
var root = Path.GetFullPath(args[1]);
if (Directory.Exists(root)) throw new InvalidOperationException("Fixture root must be fresh.");
Directory.CreateDirectory(root);
if (OperatingSystem.IsWindows())
{
    var owner = System.Security.Principal.WindowsIdentity.GetCurrent().User!;
    var acl = new System.Security.AccessControl.DirectorySecurity();
    acl.SetOwner(owner); acl.SetAccessRuleProtection(true, false);
    acl.AddAccessRule(new System.Security.AccessControl.FileSystemAccessRule(owner,
        System.Security.AccessControl.FileSystemRights.FullControl,
        System.Security.AccessControl.InheritanceFlags.ContainerInherit | System.Security.AccessControl.InheritanceFlags.ObjectInherit,
        System.Security.AccessControl.PropagationFlags.None, System.Security.AccessControl.AccessControlType.Allow));
    System.IO.FileSystemAclExtensions.SetAccessControl(new DirectoryInfo(root), acl);
}
var path = Path.Combine(root, "tunnel.json");
if (!OperatingSystem.IsWindows())
{
    using var initialLock = new FileStream(path + ".access.lock", new FileStreamOptions
    { Mode = FileMode.CreateNew, Access = FileAccess.ReadWrite, UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite });
}
await File.WriteAllTextAsync(path, """
{"resource_server":{"grants":[{"principal_id":"fixture","tools":["existing_tool"]}]},"unrelated":{"keep":true},"plugin":{"legacy":true}}
""");
var psi = new ProcessStartInfo(Environment.GetEnvironmentVariable("ZAGENT_TEST_PYTHON") ?? "python3")
{ RedirectStandardOutput = true, RedirectStandardError = true };
psi.ArgumentList.Add(Path.Combine(repo, "tests/Zagent.TunnelWriterConcurrencyTests/router_writer.py"));
psi.ArgumentList.Add(repo); psi.ArgumentList.Add(root);
if (args.Contains("--product-lock")) psi.ArgumentList.Add("--product-lock");
using var python = Process.Start(psi)!;
await WaitForFile("locked");
// Hold the real AtomicJsonFileStore publication semaphore: old Core reads stale
// config and waits here, fixed Core cannot read until Python releases its lock.
var locks = (ConcurrentDictionary<string, SemaphoreSlim>)typeof(AtomicJsonFileStore)
    .GetField("WriteLocks", BindingFlags.NonPublic | BindingFlags.Static)!.GetValue(null)!;
var publication = locks.GetOrAdd(path, _ => new SemaphoreSlim(1, 1));
await publication.WaitAsync();
var options = new TunnelIntegrationOptions("fixture", repo, root, Path.Combine(root, "runtime"), "", "127.0.0.1", 19876);
using (var cancelled = new CancellationTokenSource(150))
{
    try
    {
        await new TunnelConfigurationWriter().WriteAsync(options, Array.Empty<TunnelServiceDefinition>(), cancellationToken: cancelled.Token);
        throw new Exception("Contended writer ignored cancellation");
    }
    catch (OperationCanceledException) when (cancelled.IsCancellationRequested) { }
}
var core = new TunnelConfigurationWriter().WriteAsync(options, Array.Empty<TunnelServiceDefinition>());
await Task.Delay(600);
await File.WriteAllTextAsync(Path.Combine(root, "publish"), "");
await python.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(15));
await Task.Delay(200); // Core is now held inside the real publication store.
psi.ArgumentList.Add("--probe-lock");
using (var probe = Process.Start(psi)!)
{
    await probe.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(5));
    Require(probe.ExitCode == 0, "Core failed to hold lock through publication: " + await probe.StandardError.ReadToEndAsync());
    Console.Write(await probe.StandardOutput.ReadToEndAsync());
}
publication.Release();
var stderr = await python.StandardError.ReadToEndAsync();
if (python.ExitCode != 0) throw new Exception("Python fixture failed: " + stderr);
await core.WaitAsync(TimeSpan.FromSeconds(15));
var result = JsonNode.Parse(await File.ReadAllTextAsync(path))!;
var tools = result["resource_server"]!["grants"]![0]!["tools"]!.AsArray().Select(n => n!.GetValue<string>()).ToArray();
foreach (var name in new[] { "existing_tool", "files_allowlist_list", "files_allowlist_add", "files_allowlist_remove", "files_allowlist_replace" })
    Require(tools.Contains(name), "Core lost Router grant membership: " + name);
Require(result["router_marker"]?.GetValue<string>() == "published-by-router", "Core lost unrelated Router config edit");
Require(result["unrelated"]?["keep"]?.GetValue<bool>() == true, "Core lost unrelated original config");
Require(result["router"]?["port"]?.GetValue<int>() == 19876, "Core generated config missing");
Require(result["plugin"] is null, "Legacy plugin survived");
Console.WriteLine("PASS: Python byte-range lock excludes Core read/merge/publication; all four memberships and unrelated changes survive.");
if (!OperatingSystem.IsWindows())
{
    var before = await File.ReadAllBytesAsync(path);
    var lockPath = path + ".access.lock";
    File.SetUnixFileMode(lockPath, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.OtherWrite);
    await RequireRejected();
    File.SetUnixFileMode(lockPath, UnixFileMode.UserRead | UnixFileMode.UserWrite);
    File.Delete(lockPath); // fixture-only: production code never removes a lock.
    File.CreateSymbolicLink(lockPath, path);
    await RequireRejected();
    var afterRejected = await File.ReadAllBytesAsync(path);
    Require(before.SequenceEqual(afterRejected), "Rejected lock changed configuration");
    File.Delete(lockPath);
    await new TunnelConfigurationWriter().WriteAsync(options, Array.Empty<TunnelServiceDefinition>());
    Console.WriteLine("PASS: broad lock permissions and symlink lock rejected; gate released after failures.");
}

async Task RequireRejected()
{
    try
    {
        await new TunnelConfigurationWriter().WriteAsync(options, Array.Empty<TunnelServiceDefinition>());
        throw new Exception("Unsafe lock accepted");
    }
    catch (InvalidDataException) { }
}

async Task WaitForFile(string name)
{
    var deadline = Stopwatch.StartNew();
    while (!File.Exists(Path.Combine(root, name)))
    {
        if (python.HasExited || deadline.Elapsed > TimeSpan.FromSeconds(15))
            throw new Exception("Python fixture did not acquire lock: " + await python.StandardError.ReadToEndAsync());
        await Task.Delay(10);
    }
}
static void Require(bool condition, string message) { if (!condition) throw new Exception(message); }
