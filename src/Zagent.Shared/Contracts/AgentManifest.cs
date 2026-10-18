namespace Zagent.Shared.Contracts;

public sealed record AgentIdentity(
    string Id,
    string Name,
    string Version,
    string? Build = null,
    string Vendor = "Zohr System Agent");

public sealed record AgentRuntimeDescriptor(
    string Language,
    string? Version,
    string Entrypoint,
    IReadOnlyList<string>? Arguments = null);

public sealed record AgentTransportDescriptor(
    string Kind,
    string? BindHost = null,
    int? Port = null,
    string? Path = null,
    bool LocalOnly = true);

public sealed record AgentLifecycleDescriptor(
    bool Start = true,
    bool Stop = true,
    bool Restart = true,
    bool Reload = false,
    bool Status = true,
    bool Diagnostics = true,
    int GracefulShutdownSeconds = 15);

public sealed record AgentHealthDescriptor(
    string Probe,
    string? Target = null,
    int IntervalSeconds = 10,
    int TimeoutSeconds = 5);

public sealed record AgentDependencyDescriptor(
    string Id,
    bool Required,
    string? MinimumVersion = null,
    bool External = false);

public sealed record AgentManifest(
    string ProtocolVersion,
    AgentIdentity Agent,
    AgentEnvironment Environment,
    AgentRuntimeDescriptor Runtime,
    AgentTransportDescriptor Transport,
    AgentLifecycleDescriptor Lifecycle,
    AgentHealthDescriptor Health,
    IReadOnlyList<CapabilityDescriptor> Capabilities,
    IReadOnlyList<AgentDependencyDescriptor>? Dependencies = null,
    IReadOnlyDictionary<string, string>? Metadata = null);
