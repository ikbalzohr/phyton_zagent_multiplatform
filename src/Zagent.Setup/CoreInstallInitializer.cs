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
            var previousAcl = infoDirectory.GetAccessControl();
            if (!owner.Equals(previousAcl.GetOwner(typeof(SecurityIdentifier))))
                throw new InvalidOperationException("Refusing to adopt a data/config directory owned by another Windows identity.");
            var acl = new DirectorySecurity();
            acl.SetOwner(owner);
            acl.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
            acl.AddAccessRule(new FileSystemAccessRule(owner, FileSystemRights.FullControl,
                InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit,
                PropagationFlags.None, AccessControlType.Allow));
            infoDirectory.SetAccessControl(acl);
            var actualAcl = infoDirectory.GetAccessControl();
            var rules = actualAcl.GetAccessRules(true, true, typeof(SecurityIdentifier));
            if (!actualAcl.AreAccessRulesProtected || !owner.Equals(actualAcl.GetOwner(typeof(SecurityIdentifier))) ||
                rules.Count != 1 || rules[0] is not FileSystemAccessRule actualRule ||
                !owner.Equals(actualRule.IdentityReference) || actualRule.IsInherited ||
                actualRule.AccessControlType != AccessControlType.Allow || actualRule.FileSystemRights != FileSystemRights.FullControl ||
                actualRule.InheritanceFlags != (InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit) ||
                actualRule.PropagationFlags != PropagationFlags.None)
                throw new InvalidOperationException("Owner-only data/config ACL read-back failed.");
        }

        // Initialization is not dashboard enrollment. The interactive owner must separately run
        // Provision-WindowsDashboard.ps1 for localhost TLS, DPAPI internal secrets and password.
        // Do not prompt through the redirected installer process or provision external OAuth here.
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