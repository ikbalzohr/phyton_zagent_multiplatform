using System.Text.Json;

namespace Zagent.Core.Agents.Web;

public sealed class ChromeBridgeConfigurationSynchronizer
{
    public const string ConfigFileName = "bridge-config.json";

    public async Task<ChromeBridgeConfigurationSyncResult> SyncAsync(
        string zagentRoot,
        string bindHost,
        int webPort,
        string environment,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(zagentRoot);
        ArgumentException.ThrowIfNullOrWhiteSpace(bindHost);
        ArgumentException.ThrowIfNullOrWhiteSpace(environment);

        if (webPort is < 1 or > 65535)
        {
            throw new ArgumentOutOfRangeException(nameof(webPort));
        }

        var normalizedEnvironment =
            environment.Trim().ToUpperInvariant();

        if (normalizedEnvironment is not ("DEVELOPMENT" or "PRODUCTION"))
        {
            throw new ArgumentException(
                "Chrome Bridge environment must be DEVELOPMENT or PRODUCTION.",
                nameof(environment));
        }

        var defaultBase =
            $"http://{bindHost}:{webPort}/bridge/";

        var targets = new[]
        {
            Path.Combine(
                zagentRoot,
                "agents",
                "web",
                "engine",
                "extension"),
            Path.Combine(
                zagentRoot,
                "agents",
                "web",
                "engine",
                "artifacts",
                "chrome-bridge")
        };

        var written = new List<string>();

        foreach (var target in targets)
        {
            cancellationToken.ThrowIfCancellationRequested();

            if (!Directory.Exists(target))
            {
                continue;
            }

            var manifest = Path.Combine(target, "manifest.json");
            var background = Path.Combine(target, "background.js");

            if (!File.Exists(manifest) ||
                !File.Exists(background))
            {
                continue;
            }

            var configPath =
                Path.Combine(target, ConfigFileName);

            var legacyBases =
                BuildLegacyBases(
                    normalizedEnvironment,
                    defaultBase,
                    await ReadPreviousDefaultAsync(
                        configPath,
                        cancellationToken));

            var payload = new
            {
                schemaVersion = 2,
                configured = true,
                environment = normalizedEnvironment,
                defaultBase,
                legacyBases,
                generatedBy =
                    "Zagent.Core runtime configuration",
                generatedFrom =
                    "zagent.machine.json"
            };

            var json = JsonSerializer.Serialize(
                payload,
                new JsonSerializerOptions
                {
                    WriteIndented = true
                });

            var current =
                File.Exists(configPath)
                    ? await File.ReadAllTextAsync(
                        configPath,
                        cancellationToken)
                    : null;

            if (!string.Equals(
                    Normalize(current),
                    Normalize(json),
                    StringComparison.Ordinal))
            {
                await File.WriteAllTextAsync(
                    configPath,
                    json,
                    new System.Text.UTF8Encoding(false),
                    cancellationToken);
            }

            written.Add(configPath);
        }

        if (written.Count == 0)
        {
            throw new DirectoryNotFoundException(
                "No Zagent Chrome Bridge extension root was found.");
        }

        return new ChromeBridgeConfigurationSyncResult(
            normalizedEnvironment,
            bindHost,
            webPort,
            defaultBase,
            written);
    }

    private static async Task<string?> ReadPreviousDefaultAsync(
        string path,
        CancellationToken cancellationToken)
    {
        if (!File.Exists(path))
        {
            return null;
        }

        try
        {
            using var doc = JsonDocument.Parse(
                await File.ReadAllTextAsync(
                    path,
                    cancellationToken));

            if (doc.RootElement.TryGetProperty(
                    "defaultBase",
                    out var value) &&
                value.ValueKind == JsonValueKind.String)
            {
                return value.GetString();
            }
        }
        catch
        {
        }

        return null;
    }

    private static string[] BuildLegacyBases(
        string environment,
        string defaultBase,
        string? previousDefault)
    {
        // Never fail over to another Zagent installation's listener.
        // The active extension is paired to exactly this installation's endpoint.
        // A legacy endpoint must be migrated by explicit re-pairing, not by
        // auto-discovery of Master, User, or Development ports.
        return Array.Empty<string>();
    }

    private static string Normalize(string? value) =>
        (value ?? "")
            .Replace("\r\n", "\n", StringComparison.Ordinal)
            .Trim();
}

public sealed record ChromeBridgeConfigurationSyncResult(
    string Environment,
    string BindHost,
    int WebPort,
    string DefaultBase,
    IReadOnlyList<string> WrittenPaths);
