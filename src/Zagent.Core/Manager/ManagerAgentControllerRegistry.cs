using Zagent.Shared.Contracts;
using Zagent.Shared.Manager;

namespace Zagent.Core.Manager;

public sealed record ManagerAgentController(
    string AgentId,
    string ProcessId,
    Func<CancellationToken, Task<LifecycleOperationResult>> Start,
    Func<CancellationToken, Task<LifecycleOperationResult>> Stop,
    Func<CancellationToken, Task<LifecycleOperationResult>> Restart,
    Func<CancellationToken, Task<ManagerOperationResult>> Refresh);

public sealed class ManagerAgentControllerRegistry
{
    private readonly Dictionary<string, ManagerAgentController> _controllers =
        new(StringComparer.Ordinal);

    public void Register(ManagerAgentController controller)
    {
        ArgumentNullException.ThrowIfNull(controller);

        if (!_controllers.TryAdd(controller.AgentId, controller))
        {
            throw new InvalidOperationException(
                $"Manager controller '{controller.AgentId}' is already registered.");
        }
    }

    public bool TryGet(
        string agentId,
        out ManagerAgentController? controller) =>
        _controllers.TryGetValue(agentId, out controller);

    public IReadOnlyList<ManagerAgentController> Snapshot() =>
        _controllers.Values
            .OrderBy(
                item => item.AgentId,
                StringComparer.Ordinal)
            .ToArray();
}
