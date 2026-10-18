using System.Diagnostics;
using System.Security.AccessControl;
using System.Security.Principal;

namespace Zagent.Setup;

public sealed class CoreInstallInitializer : IInstallInitializer
{
    public async Task InitializeAsync(
        string targetRoot,
        string dataRoot,
        string filesProfile,
        string productVersion,
        CancellationToken cancellationToken)
    {
        var core = Path.Combine(
            targetRoot,
            "Zagent.Core.exe");

        if (!File.Exists(core))
        {
            throw new FileNotFoundException(
                "Installed Zagent.Core.exe was not found.",
                core);
        }

        // CurrentUser credentials and DPAPI keys must not inherit permissive parent ACLs.
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Windows installer only.");
        var owner = WindowsIdentity.GetCurrent().User ?? throw new InvalidOperationException("Windows owner SID missing.");
        foreach (var directory in new[] { dataRoot, Path.Combine(dataRoot, "config"), Path.Combine(dataRoot, "dashboard-keys") })
        {
            for (DirectoryInfo? ancestor = new DirectoryInfo(Path.GetFullPath(directory)); ancestor is not null; ancestor = ancestor.Parent)
            {
                if (ancestor.Exists && (ancestor.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidOperationException("Installer data/config path must not traverse reparse points.");
            }
            var infoDirectory = Directory.CreateDirectory(directory);
            var acl = new DirectorySecurity();
            acl.SetOwner(owner);
            acl.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
            acl.AddAccessRule(new FileSystemAccessRule(owner, FileSystemRights.FullControl,
                InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                PropagationFlags.None, AccessControlType.Allow));
            infoDirectory.SetAccessControl(acl);
        }

        var info = new ProcessStartInfo
        {
            FileName = core,
            WorkingDirectory = targetRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };

        foreach (var arg in new[]
        {
            "--initialize-install",
            "--root",
            targetRoot,
            "--data-root",
            dataRoot,
            "--files-profile",
            filesProfile,
            "--product-version",
            productVersion
        })
        {
            info.ArgumentList.Add(arg);
        }

        using var process =
            Process.Start(info) ??
            throw new InvalidOperationException(
                "Could not start Zagent.Core install initializer.");

        var stdoutTask =
            process.StandardOutput.ReadToEndAsync(
                cancellationToken);
        var stderrTask =
            process.StandardError.ReadToEndAsync(
                cancellationToken);

        await process.WaitForExitAsync(
            cancellationToken);

        var stdout = await stdoutTask;
        var stderr = await stderrTask;

        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException(
                "Zagent Core install initialization failed: " +
                (string.IsNullOrWhiteSpace(stderr)
                    ? stdout
                    : stderr));
        }
        ArcMapAddInIntegration.Install(targetRoot, dataRoot);
    }
}