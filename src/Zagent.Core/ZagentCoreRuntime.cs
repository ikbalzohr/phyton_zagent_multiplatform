using Zagent.Core.Abstractions;
using Zagent.Core.Registry;
using Zagent.Shared;
using Zagent.Shared.Contracts;

namespace Zagent.Core;

public sealed class ZagentCoreRuntime
{
    private readonly TimeProvider _timeProvider;

    public ZagentCoreRuntime(
        ICapabilityRegistry registry,
        TimeProvider? timeProvider = null)
    {
        Registry = registry ?? throw new ArgumentNullException(nameof(registry));
        _timeProvider = timeProvider ?? TimeProvider.System;
    }

    public ICapabilityRegistry Registry { get; }

    public static ZagentCoreRuntime CreateDefault() =>
        new(new CapabilityRegistry());

    public CoreRuntimeSnapshot GetSnapshot()
    {
        return new CoreRuntimeSnapshot(
            ProductName: ZagentProductInfo.ProductName,
            CoreVersion: ZagentProductInfo.CoreVersion,
            AgentProtocolVersion: ZagentProductInfo.AgentProtocolVersion,
            CapabilityRegistryVersion: ZagentProductInfo.CapabilityRegistryVersion,
            RegisteredAgents: Registry.Snapshot().Count,
            CapturedAtUtc: _timeProvider.GetUtcNow());
    }
}
