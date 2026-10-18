using Zagent.Shared;
using Zagent.Shared.Contracts;

namespace Zagent.Core;

/// <summary>Core1/UI1 ownership tests only; not sample runtime data or product registration.</summary>
public static class SampleManifests
{
    public static AgentManifest CreateDevelopmentEchoAgent(string agentId = "dev.echo") => new(
        ZagentProductInfo.AgentProtocolVersion,
        new AgentIdentity(agentId, "Development echo agent", "1.0.0"),
        AgentEnvironment.Development,
        new AgentRuntimeDescriptor("dotnet", "10.0", "dev-echo"),
        new AgentTransportDescriptor("internal", LocalOnly: true),
        new AgentLifecycleDescriptor(),
        new AgentHealthDescriptor("custom"),
        [new CapabilityDescriptor("dev.echo.ping", "Development registry contract check.", CapabilityAccess.Read,
            CapabilityExecution.Fast, CapabilityApproval.None, SupportsCancel: false)]);
}