using Zagent.Shared;
using Zagent.Shared.Contracts;

namespace Zagent.Core.Agents.Tunnel;

public static class TunnelAgentManifestFactory
{
    public const string AgentId = "system.tunnel";

    public static AgentManifest Create(
        string version,
        string bindHost,
        int routerPort,
        AgentEnvironment environment = AgentEnvironment.Production)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(version);
        ArgumentException.ThrowIfNullOrWhiteSpace(bindHost);

        return new AgentManifest(
            ProtocolVersion: ZagentProductInfo.AgentProtocolVersion,
            Agent: new AgentIdentity(
                Id: AgentId,
                Name: "Zagent Tunnel",
                Version: version),
            Environment: environment,
            Runtime: new AgentRuntimeDescriptor(
                Language: "python",
                Version: "3.11",
                Entrypoint: "router.server"),
            Transport: new AgentTransportDescriptor(
                Kind: "http-mcp",
                BindHost: bindHost,
                Port: routerPort,
                Path: "/mcp",
                LocalOnly: true),
            Lifecycle: new AgentLifecycleDescriptor(
                GracefulShutdownSeconds: 5),
            Health: new AgentHealthDescriptor(
                Probe: "http",
                Target: $"http://{bindHost}:{routerPort}/healthz",
                IntervalSeconds: 10,
                TimeoutSeconds: 3),
            Capabilities:
            [
                Capability(
                    "system.tunnel.status",
                    CapabilityAccess.Read,
                    CapabilityExecution.Fast,
                    supportsCancel: false),
                Capability(
                    "system.tunnel.refresh",
                    CapabilityAccess.Action,
                    CapabilityExecution.Background,
                    supportsCancel: true),
                Capability(
                    "system.task.submit",
                    CapabilityAccess.Action,
                    CapabilityExecution.Background,
                    supportsCancel: true),
                Capability(
                    "system.task.status",
                    CapabilityAccess.Read,
                    CapabilityExecution.Fast,
                    supportsCancel: false),
                Capability(
                    "system.task.result",
                    CapabilityAccess.Read,
                    CapabilityExecution.Fast,
                    supportsCancel: false),
                Capability(
                    "system.task.cancel",
                    CapabilityAccess.Action,
                    CapabilityExecution.Fast,
                    supportsCancel: false),
                Capability(
                    "system.task.list",
                    CapabilityAccess.Read,
                    CapabilityExecution.Fast,
                    supportsCancel: false),
                Capability(
                    "system.telemetry.status",
                    CapabilityAccess.Read,
                    CapabilityExecution.Fast,
                    supportsCancel: false)
            ]);
    }

    private static CapabilityDescriptor Capability(
        string name,
        CapabilityAccess access,
        CapabilityExecution execution,
        bool supportsCancel) =>
        new(
            Name: name,
            Description: name,
            Access: access,
            Execution: execution,
            Approval: CapabilityApproval.None,
            SupportsCancel: supportsCancel);
}
