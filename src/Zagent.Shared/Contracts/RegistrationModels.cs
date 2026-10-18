namespace Zagent.Shared.Contracts;

public sealed record RegisteredAgent(
    AgentManifest Manifest,
    RegistrationState RegistrationState,
    AgentHealthState Health,
    bool ProductionApproved,
    DateTimeOffset RegisteredAtUtc,
    string? LastError = null);

public sealed record ManifestValidationResult(
    bool IsValid,
    IReadOnlyList<string> Errors)
{
    public static ManifestValidationResult Success { get; } =
        new(true, Array.Empty<string>());

    public static ManifestValidationResult Failure(params string[] errors) =>
        new(false, errors);
}

public sealed record RegistrationResult(
    bool Success,
    RegisteredAgent? RegisteredAgent,
    IReadOnlyList<string> Errors)
{
    public static RegistrationResult Accepted(RegisteredAgent agent) =>
        new(true, agent, Array.Empty<string>());

    public static RegistrationResult Rejected(params string[] errors) =>
        new(false, null, errors);
}
