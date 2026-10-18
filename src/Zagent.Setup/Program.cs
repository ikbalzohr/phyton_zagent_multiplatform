using System.Text.Json;
using Zagent.Setup;

if (args.Length == 0 ||
    args.Contains("--help", StringComparer.Ordinal))
{
    Console.WriteLine(
        "Zagent.Setup <install|repair|verify|uninstall> " +
        "--target <InstallRoot> [--source <PayloadRoot>] " +
        "[--data-root <Path>] [--files-profile <Path>] " +
        "[--product-version <Version>] [--installation-role Master|User] [--keep-data true|false]");
    return 0;
}

if (!Enum.TryParse<SetupMode>(
        args[0],
        ignoreCase: true,
        out var mode))
{
    Console.Error.WriteLine(
        $"Unknown setup mode '{args[0]}'.");
    return 2;
}

var target = Option("--target");
if (string.IsNullOrWhiteSpace(target))
{
    Console.Error.WriteLine(
        "--target is required.");
    return 2;
}

var source = Option("--source");
var keepDataText =
    Option("--keep-data") ?? "true";

if (!bool.TryParse(
        keepDataText,
        out var keepData))
{
    Console.Error.WriteLine(
        "--keep-data must be true or false.");
    return 2;
}

var selectedRole = Option("--installation-role");
if (!string.IsNullOrWhiteSpace(selectedRole))
{
    Environment.SetEnvironmentVariable("ZAGENT_INSTALLATION_ROLE",
        Zagent.Shared.Installation.ZagentInstallationProfile.Normalize(selectedRole));
}

var request = new SetupRequest(
    Mode: mode,
    TargetRoot: target,
    SourceRoot: source,
    DataRoot: Option("--data-root"),
    FilesProfile: Option("--files-profile"),
    ProductVersion: Option("--product-version"),
    KeepData: keepData);

var engine = new SetupEngine();

engine.Progress += (_, progress) =>
{
    Console.WriteLine(
        JsonSerializer.Serialize(
            new
            {
                type = "progress",
                percent = progress.Percent,
                stage = progress.Stage,
                message = progress.Message
            }));
};

try
{
    var result =
        await engine.ExecuteAsync(request);

    Console.WriteLine(
        JsonSerializer.Serialize(
            new
            {
                type = "result",
                result.Success,
                mode = result.Mode.ToString(),
                result.TargetRoot,
                result.FilesChanged,
                result.FilesVerified,
                result.Message,
                result.BackupRoot
            },
            new JsonSerializerOptions
            {
                WriteIndented = true
            }));

    return result.Success ? 0 : 1;
}
catch (Exception ex)
{
    Console.Error.WriteLine(
        JsonSerializer.Serialize(
            new
            {
                type = "error",
                error = ex.Message
            }));

    return 1;
}

string? Option(string name)
{
    var index =
        Array.IndexOf(
            args,
            name);

    if (index < 0)
    {
        return null;
    }

    if (index + 1 >= args.Length)
    {
        throw new ArgumentException(
            $"{name} requires a value.");
    }

    return args[index + 1];
}
