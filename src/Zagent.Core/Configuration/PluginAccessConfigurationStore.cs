using Zagent.Shared.Configuration;
using Zagent.Shared.Contracts;

namespace Zagent.Core.Configuration;

public sealed class PluginAccessConfigurationStore
{
    public const string FileName = "plugin-access.json";

    private readonly AtomicJsonFileStore _store;

    public PluginAccessConfigurationStore(
        AtomicJsonFileStore? store = null)
    {
        _store = store ?? new AtomicJsonFileStore();
    }

    public string GetPath(string configRoot) =>
        Path.Combine(
            Path.GetFullPath(configRoot),
            FileName);

    public async Task<PluginAccessConfiguration> EnsureAsync(
        string configRoot,
        AgentEnvironment environment,
        CancellationToken cancellationToken = default)
    {
        var path = GetPath(configRoot);

        if (_store.Exists(path))
        {
            var existing =
                await _store.LoadAsync<PluginAccessConfiguration>(
                    path,
                    cancellationToken);

            Validate(existing);
            return existing;
        }

        var created = CreateFromEnvironment(environment);
        await _store.SaveAsync(
            path,
            created,
            cancellationToken);
        return created;
    }

    public async Task<PluginAccessConfiguration> SaveFromEnvironmentAsync(
        string configRoot,
        AgentEnvironment environment,
        CancellationToken cancellationToken = default)
    {
        var value = CreateFromEnvironment(environment);
        await _store.SaveAsync(
            GetPath(configRoot),
            value,
            cancellationToken);
        return value;
    }

    public static PluginAccessConfiguration CreateFromEnvironment(
        AgentEnvironment environment)
    {
        var configuredAudience =
            Environment.GetEnvironmentVariable(
                "ZAGENT_PLUGIN_AUDIENCE");

        var audience =
            !string.IsNullOrWhiteSpace(configuredAudience)
                ? configuredAudience.Trim().ToLowerInvariant()
                : environment == AgentEnvironment.Development
                    ? "zagent-dev"
                    : "zagent-production";

        var displayName =
            Environment.GetEnvironmentVariable(
                "ZAGENT_PLUGIN_DISPLAY_NAME");

        if (string.IsNullOrWhiteSpace(displayName))
        {
            displayName = audience switch
            {
                "zagent-dev" => "Zagent Dev Plugin",
                "tryplugin" => "TryPlugin",
                _ => "Zagent"
            };
        }

        var mode =
            Environment.GetEnvironmentVariable(
                "ZAGENT_PLUGIN_ACCESS_MODE");

        if (string.IsNullOrWhiteSpace(mode))
        {
            mode = audience == "zagent-dev"
                ? "production-grant"
                : "manager-approval";
        }

        var fallback =
            Environment.GetEnvironmentVariable(
                "ZAGENT_PLUGIN_FALLBACK");

        if (fallback is null)
        {
            fallback = audience switch
            {
                "zagent-production" => "tryplugin",
                "tryplugin" => "zagent",
                _ => ""
            };
        }

        var value =
            new PluginAccessConfiguration(
                PluginAccessConfiguration.CurrentSchemaVersion,
                audience,
                displayName.Trim(),
                mode.Trim().ToLowerInvariant(),
                (
                    Environment.GetEnvironmentVariable(
                        "ZAGENT_PLUGIN_ACCESS_ENFORCEMENT")
                    ?? "mandatory"
                ).Trim().ToLowerInvariant(),
                fallback.Trim(),
                (
                    Environment.GetEnvironmentVariable(
                        "ZAGENT_PLUGIN_PARENT_AUDIENCE")
                    ?? "zagent-production"
                ).Trim().ToLowerInvariant());

        Validate(value);
        return value;
    }

    public static void Validate(
        PluginAccessConfiguration value)
    {
        if (!string.Equals(
                value.SchemaVersion,
                PluginAccessConfiguration.CurrentSchemaVersion,
                StringComparison.Ordinal))
        {
            throw new InvalidDataException(
                $"Unsupported plugin access configuration schema '{value.SchemaVersion}'.");
        }

        if (value.Audience is not
            ("zagent-production" or "zagent-dev" or "tryplugin"))
        {
            throw new InvalidDataException(
                $"Unsupported plugin audience '{value.Audience}'.");
        }

        if (value.Mode is not
            ("manager-approval" or "production-grant"))
        {
            throw new InvalidDataException(
                $"Unsupported plugin access mode '{value.Mode}'.");
        }

        if (value.Audience == "zagent-dev" &&
            value.Mode != "production-grant")
        {
            throw new InvalidDataException(
                "Zagent Dev must use production-grant access mode.");
        }

        if (string.IsNullOrWhiteSpace(value.DisplayName))
        {
            throw new InvalidDataException(
                "Plugin display name is required.");
        }
    }
}
