namespace Zagent.Shared.Configuration;

public sealed record PluginAccessConfiguration(
    string SchemaVersion,
    string Audience,
    string DisplayName,
    string Mode,
    string Enforcement,
    string FallbackPlugin,
    string ParentAudience)
{
    public const string CurrentSchemaVersion = "1.0";
}
