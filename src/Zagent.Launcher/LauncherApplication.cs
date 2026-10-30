using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;

namespace Zagent.Launcher;

public static class LauncherApplication
{
    public static string FindInstallRoot(string directory)
    {
        for (var current = new DirectoryInfo(directory); current is not null; current = current.Parent)
            if (File.Exists(Path.Combine(current.FullName, "src", "Zagent.Core", "Zagent.Core.csproj")) &&
                File.Exists(Path.Combine(current.FullName, "packaging", "scripts", "Start-OwnerCore.ps1"))) return current.FullName;
        throw new InvalidOperationException("INSTALL_ROOT_NOT_FOUND");
    }

    // No credential parsing, enrollment, ACL repair, startup registration, or lifecycle control.
    // Core remains the sole authority for DPAPI/certificate validation and the supervisor lease.
    public static int Run(string install, string local, Func<ProcessStartInfo, int?>? activate = null)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        if (!Environment.UserInteractive) throw new InvalidOperationException("INTERACTIVE_OWNER_REQUIRED");
        using var identity = WindowsIdentity.GetCurrent();
        if (identity.IsSystem || identity.IsAnonymous) throw new InvalidOperationException("INTERACTIVE_OWNER_REQUIRED");
        var data = LaunchPlan.DiscoverDataRoot(install, local);
        var start = LaunchPlan.Create(install, data, local);
        ValidatePrivatePath(data, true);
        ValidatePrivatePath(Path.Combine(data, "config"), true);
        ValidatePrivatePath(Path.Combine(data, "config", "dashboard.json"), false);
        ValidatePrivatePath(Path.Combine(data, "config", "internal-secrets.dpapi.json"), false);
        foreach (var path in new[] { start.FileName, Path.ChangeExtension(start.FileName, ".dll"),
            Path.ChangeExtension(start.FileName, ".runtimeconfig.json"), Path.ChangeExtension(start.FileName, ".deps.json"), Path.Combine(start.Environment["DOTNET_ROOT"]!, "dotnet.exe"),
            start.Environment["ZAGENT_FILES_PYTHON"]!, start.Environment["ZAGENT_TUNNEL_PYTHON"]!,
            Path.Combine(install, "agents", "web", "engine", "dist", "index.js") })
        {
            if (!File.Exists(path)) throw new InvalidOperationException("REQUIRED_RUNTIME_MISSING");
            ValidatePlainPath(path);
        }
        var result = (activate ?? Activate)(start);
        if (result is not null and not 0) throw new InvalidOperationException("CORE_START_FAILED");
        return 0;
    }

    public static int? Activate(ProcessStartInfo start)
    {
        using var process = Process.Start(start) ?? throw new InvalidOperationException("CORE_START_FAILED");
        // Bound observation, not Core lifetime. Never kill or restart an existing/new Core.
        return process.WaitForExit(2000) ? process.ExitCode : null;
    }

    private static void ValidatePlainPath(string path)
    {
        for (var current = Path.GetFullPath(path); current is not null; current = Path.GetDirectoryName(current))
            if ((File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidOperationException("REPARSE_PATH_REJECTED");
    }

    // Same strict owner-only contract as Core InternalSecretStore.ValidatePrivatePath.
    public static void ValidatePrivatePath(string path, bool directory)
    {
        ValidatePlainPath(path);
        using var identity = WindowsIdentity.GetCurrent();
        var owner = identity.User ?? throw new InvalidOperationException("OWNER_SID_UNAVAILABLE");
        FileSystemSecurity acl = directory
            ? new DirectoryInfo(path).GetAccessControl(AccessControlSections.Owner | AccessControlSections.Access)
            : new FileInfo(path).GetAccessControl(AccessControlSections.Owner | AccessControlSections.Access);
        var rules = acl.GetAccessRules(true, true, typeof(SecurityIdentifier)).Cast<FileSystemAccessRule>().ToArray();
        if (!owner.Equals(acl.GetOwner(typeof(SecurityIdentifier))) || !acl.AreAccessRulesProtected || rules.Length != 1 ||
            !owner.Equals(rules[0].IdentityReference) || rules[0].AccessControlType != AccessControlType.Allow ||
            rules[0].IsInherited || rules[0].FileSystemRights != FileSystemRights.FullControl ||
            rules[0].PropagationFlags != PropagationFlags.None ||
            rules[0].InheritanceFlags != (directory ? InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit : InheritanceFlags.None))
            throw new InvalidOperationException("OWNER_ACL_REQUIRED");
    }
}

internal static class Program
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "MessageBoxTimeoutW")]
    private static extern int MessageBoxTimeout(IntPtr owner, string text, string caption, uint type, ushort language, uint milliseconds);

    [STAThread]
    private static int Main()
    {
        try
        {
            return LauncherApplication.Run(LauncherApplication.FindInstallRoot(AppContext.BaseDirectory),
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData));
        }
        catch (Exception)
        {
            // Fixed, bounded diagnostic: never display private configuration or exception contents.
            MessageBoxTimeout(IntPtr.Zero,
                "Zagent could not open the existing owner dashboard. Check the existing enrollment, owner-only permissions and built Core/runtime files. No settings were changed. If startup failed after this window closed, inspect the existing Core diagnostics. Do not delete or reprovision data.",
                "Zagent launcher", 0x10, 0, 15000);
            return 1;
        }
    }
}
