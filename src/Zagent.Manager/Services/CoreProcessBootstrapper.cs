using System.IO;
using System.Diagnostics;

namespace Zagent.Manager.Services;

public sealed class CoreProcessBootstrapper : IDisposable
{
    private Process? _ownedProcess;
    private int _disposed;

    public bool OwnsCoreProcess =>
        _ownedProcess is { HasExited: false };

    public async Task EnsureCoreAsync(
        ManagerPipeClient client,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(client);

        if (await client.IsAvailableAsync(
                cancellationToken))
        {
            return;
        }

        var root = ResolveZagentRoot();
        var coreExe = ResolveCoreExecutable(root);

        var dataRoot =
            Environment.GetEnvironmentVariable(
                "ZAGENT_DATA_ROOT") ??
            Path.Combine(root, "data");

        var filesProfile =
            Environment.GetEnvironmentVariable(
                "ZAGENT_FILES_DEFAULT_PROFILE") ??
            InferAppBridge(root);

        var startInfo = new ProcessStartInfo
        {
            FileName = coreExe,
            WorkingDirectory = root,
            UseShellExecute = false,
            CreateNoWindow = true
        };

        startInfo.ArgumentList.Add("--serve-manager");
        startInfo.ArgumentList.Add("--root");
        startInfo.ArgumentList.Add(root);
        startInfo.ArgumentList.Add("--data-root");
        startInfo.ArgumentList.Add(dataRoot);
        startInfo.ArgumentList.Add("--files-profile");
        startInfo.ArgumentList.Add(filesProfile);
        startInfo.ArgumentList.Add("--pipe");
        startInfo.ArgumentList.Add(client.PipeName);

        _ownedProcess = Process.Start(startInfo) ??
            throw new InvalidOperationException(
                "Could not start Zagent Core.");

        for (var attempt = 0;
            attempt < 80;
            attempt++)
        {
            cancellationToken.ThrowIfCancellationRequested();

            if (_ownedProcess.HasExited)
            {
                throw new InvalidOperationException(
                    $"Zagent Core exited with code {_ownedProcess.ExitCode}.");
            }

            if (await client.IsAvailableAsync(
                    cancellationToken))
            {
                return;
            }

            await Task.Delay(
                TimeSpan.FromMilliseconds(100),
                cancellationToken);
        }

        throw new TimeoutException(
            "Zagent Core did not expose the Manager control pipe.");
    }

    public void Dispose()
    {
        if (Interlocked.Exchange(
                ref _disposed,
                1) != 0)
        {
            return;
        }

        _ownedProcess?.Dispose();
    }

    private static string ResolveZagentRoot()
    {
        var fromEnvironment =
            Environment.GetEnvironmentVariable(
                "ZAGENT_ROOT");

        if (!string.IsNullOrWhiteSpace(
                fromEnvironment) &&
            Directory.Exists(fromEnvironment))
        {
            return Path.GetFullPath(fromEnvironment);
        }

        var args = Environment.GetCommandLineArgs();
        var index = Array.IndexOf(args, "--root");

        if (index >= 0 &&
            index + 1 < args.Length &&
            Directory.Exists(args[index + 1]))
        {
            return Path.GetFullPath(args[index + 1]);
        }

        var current = new DirectoryInfo(
            AppContext.BaseDirectory);

        while (current is not null)
        {
            if (Directory.Exists(
                    Path.Combine(
                        current.FullName,
                        "agents")) &&
                File.Exists(
                    Path.Combine(
                        current.FullName,
                        "component-manifest.json")))
            {
                return current.FullName;
            }

            current = current.Parent;
        }

        throw new DirectoryNotFoundException(
            "Zagent root could not be resolved. Set ZAGENT_ROOT.");
    }

    private static string ResolveCoreExecutable(
        string root)
    {
        var explicitPath =
            Environment.GetEnvironmentVariable(
                "ZAGENT_CORE_EXE");

        var candidates = new[]
        {
            explicitPath,
            Path.Combine(
                AppContext.BaseDirectory,
                "Zagent.Core.exe"),
            Path.Combine(
                root,
                "Zagent.Core.exe"),
            Path.Combine(
                root,
                "src",
                "Zagent.Core",
                "bin",
                "Debug",
                "net10.0",
                "Zagent.Core.exe"),
            Path.Combine(
                root,
                "src",
                "Zagent.Core",
                "bin",
                "Release",
                "net10.0",
                "Zagent.Core.exe")
        };

        foreach (var candidate in candidates)
        {
            if (!string.IsNullOrWhiteSpace(candidate) &&
                File.Exists(candidate))
            {
                return Path.GetFullPath(candidate);
            }
        }

        throw new FileNotFoundException(
            "Zagent.Core.exe was not found. Set ZAGENT_CORE_EXE.");
    }

    private static string InferAppBridge(
        string root)
    {
        var current = new DirectoryInfo(root);

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

        return Path.Combine(root, "workspace");
    }
}