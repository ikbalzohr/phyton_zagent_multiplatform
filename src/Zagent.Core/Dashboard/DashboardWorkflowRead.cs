using System.Text.Json;

namespace Zagent.Core.Dashboard;

public static class DashboardWorkflowRead
{
    public static async Task<JsonElement> ReadAsync(Manager.TunnelManagerReadModel tunnel, string principalId, string workspaceId, string? runId, CancellationToken token)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(principalId);
        ArgumentException.ThrowIfNullOrWhiteSpace(workspaceId);
        if (principalId.Length > 256 || workspaceId.Length > 256) throw new ArgumentException("Invalid management scope.");
        return await tunnel.GetManagementWorkflowsAsync(principalId, workspaceId, runId, token);
    }
}
