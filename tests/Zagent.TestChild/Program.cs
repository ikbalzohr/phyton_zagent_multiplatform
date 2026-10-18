using System.Diagnostics;
using System.Reflection;

var mode = GetOption("--mode") ?? "hang";
var pidFile = GetOption("--pid-file");

if (!string.IsNullOrWhiteSpace(pidFile))
{
    var fullPath = Path.GetFullPath(pidFile);
    Directory.CreateDirectory(
        Path.GetDirectoryName(fullPath)
        ?? throw new InvalidOperationException("PID file has no directory."));
    File.WriteAllText(fullPath, Environment.ProcessId.ToString());
}

var delayMs = ParseInt("--delay-ms", 0);
if (delayMs > 0)
{
    await Task.Delay(delayMs);
}

if (string.Equals(mode, "exit", StringComparison.Ordinal))
{
    return ParseInt("--exit-code", 0);
}

if (string.Equals(mode, "spawn-child-exit", StringComparison.Ordinal))
{
    var childPidFile = GetOption("--child-pid-file")
        ?? throw new ArgumentException(
            "--child-pid-file is required for spawn-child-exit.");

    var dotnet = Environment.ProcessPath
        ?? throw new InvalidOperationException(
            "Current process executable path is unavailable.");
    var assembly = Assembly.GetExecutingAssembly().Location;

    var startInfo = new ProcessStartInfo
    {
        FileName = dotnet,
        UseShellExecute = false,
        CreateNoWindow = true
    };
    startInfo.ArgumentList.Add(assembly);
    startInfo.ArgumentList.Add("--mode");
    startInfo.ArgumentList.Add("hang");
    startInfo.ArgumentList.Add("--pid-file");
    startInfo.ArgumentList.Add(childPidFile);

    using var childProcess = Process.Start(startInfo)
        ?? throw new InvalidOperationException(
            "Failed to start descendant test process.");

    var parentDelayMs = ParseInt("--parent-delay-ms", 500);
    await WaitForFileAsync(
        childPidFile,
        TimeSpan.FromSeconds(5));

    if (parentDelayMs > 0)
    {
        await Task.Delay(parentDelayMs);
    }

    return ParseInt("--exit-code", 9);
}

if (!string.Equals(mode, "hang", StringComparison.Ordinal))
{
    Console.Error.WriteLine($"Unknown mode '{mode}'.");
    return 64;
}

await Task.Delay(Timeout.InfiniteTimeSpan);
return 0;

string? GetOption(string name)
{
    var index = Array.IndexOf(args, name);
    if (index < 0 || index + 1 >= args.Length)
    {
        return null;
    }

    return args[index + 1];
}

int ParseInt(string name, int fallback) =>
    int.TryParse(GetOption(name), out var value)
        ? value
        : fallback;

static async Task WaitForFileAsync(
    string path,
    TimeSpan timeout)
{
    var deadline = DateTime.UtcNow + timeout;
    while (DateTime.UtcNow < deadline)
    {
        if (File.Exists(path))
        {
            return;
        }

        await Task.Delay(25);
    }

    throw new TimeoutException(
        $"File '{path}' was not created within {timeout}.");
}
