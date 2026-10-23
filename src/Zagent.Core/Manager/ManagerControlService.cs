using System.Text.Json;
using Zagent.Core.Abstractions;
using Zagent.Core.Identity;
using Zagent.Core.Supervision;
using Zagent.Shared;
using Zagent.Shared.Contracts;
using Zagent.Shared.Manager;

namespace Zagent.Core.Manager;

public sealed class ManagerControlService
{
    private readonly ICapabilityRegistry _registry;
    private readonly IAgentSupervisor _supervisor;
    private readonly ManagerAgentControllerRegistry _controllers;
    private readonly TunnelManagerReadModel? _tunnel;
    private readonly RouterManagerService? _routerManager;
    private readonly FilesManagerReadModel? _files;
    private readonly WebManagerReadModel? _web;
    private readonly ManagerTechnicalLogStore _logs;
    private readonly TunnelCredentialStore? _tunnelCredentials;
    private readonly DevelopmentAgentStore? _developmentAgents;
    private readonly MachineIdentityStore? _machineIdentity;
    private readonly ManagerIntegrationService? _integrations;
    private readonly ManagerVisualReadModel? _visual;

    public ManagerControlService(
        ICapabilityRegistry registry,
        IAgentSupervisor supervisor,
        ManagerAgentControllerRegistry controllers,
        TunnelManagerReadModel? tunnel = null,
        RouterManagerService? routerManager = null,
        FilesManagerReadModel? files = null,
        WebManagerReadModel? web = null,
        ManagerTechnicalLogStore? logs = null,
        TunnelCredentialStore? tunnelCredentials = null,
        DevelopmentAgentStore? developmentAgents = null,
        MachineIdentityStore? machineIdentity = null,
        ManagerIntegrationService? integrations = null,
        ManagerVisualReadModel? visual = null)
    {
        _registry = registry ??
            throw new ArgumentNullException(nameof(registry));
        _supervisor = supervisor ??
            throw new ArgumentNullException(nameof(supervisor));
        _controllers = controllers ??
            throw new ArgumentNullException(nameof(controllers));
        _tunnel = tunnel;
        _routerManager = routerManager;
        _files = files;
        _web = web;
        _logs = logs ?? new ManagerTechnicalLogStore();
        _tunnelCredentials = tunnelCredentials;
        _developmentAgents = developmentAgents;
        _machineIdentity = machineIdentity;
        _integrations = integrations;
        _visual = visual;
    }

    public ManagerTechnicalLogStore Logs => _logs;
    public CoreShutdownCoordinator Shutdown { get; } = new();
    public CoreCommandGate Commands { get; } = new();
    public async Task StopForShutdownAsync()
    {
        await using var lease = await Commands.DrainAsync();
        var result = await LifecycleAllAsync("stop", CancellationToken.None);
        if (!result.Success) throw new InvalidOperationException("Agent shutdown incomplete: " + result.Message);
    }

    public async Task<ManagerResponseEnvelope> HandleAsync(
        ManagerRequestEnvelope request, CancellationToken cancellationToken = default, string? expectedRevision = null)
    {
        // Read-only adapters are explicit; unknown methods cannot bypass mutation fencing.
        var query = request.Method is "manager.dashboard" or "registry.capabilities" or
            "monitoring.snapshot" or "arcmap.workflow.snapshot" or "arcmap.workflow.evidence" or
            "profiles.snapshot" or "router.snapshot" or "logs.snapshot" or "visual.latest" or
            "identity.snapshot" or "settings.tunnel.snapshot" or "integrations.snapshot" or "manager.health";
        if (query && !cancellationToken.IsCancellationRequested) return await HandleCoreAsync(request, cancellationToken);
        await using var lease = await Commands.EnterAsync(cancellationToken);
        if (expectedRevision is not null) {
            var snapshot = ManagerJson.ToElement(await BuildProfilesAsync(cancellationToken));
            if (Zagent.Core.Dashboard.DashboardRevision.Profiles(snapshot) != expectedRevision)
                return Error(request, "REVISION_CONFLICT");
        }
        return await HandleCoreAsync(request, cancellationToken);
    }

    private async Task<ManagerResponseEnvelope> HandleCoreAsync(
        ManagerRequestEnvelope request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);

        if (!string.Equals(
                request.ProtocolVersion,
                ManagerProtocol.Version,
                StringComparison.Ordinal))
        {
            return Error(
                request,
                $"Unsupported Manager protocol '{request.ProtocolVersion}'.");
        }

        try
        {
            var result = request.Method switch
            {
                "manager.dashboard" =>
                    ManagerJson.ToElement(
                        await BuildDashboardAsync(
                            cancellationToken)),
                "registry.capabilities" =>
                    ManagerJson.ToElement(
                        BuildCapabilities()),
                "monitoring.snapshot" =>
                    ManagerJson.ToElement(
                        await BuildMonitoringAsync(
                            ParseRefresh(request.Parameters),
                            cancellationToken)),
                "profiles.snapshot" =>
                    ManagerJson.ToElement(
                        await BuildProfilesAsync(
                            cancellationToken)),
                "router.snapshot" =>
                    ManagerJson.ToElement(
                        await BuildRouterSnapshotAsync(
                            cancellationToken)),
                "logs.snapshot" =>
                    ManagerJson.ToElement(
                        new ManagerLogsSnapshot(
                            _logs.Snapshot(),
                            DateTimeOffset.UtcNow)),
                "visual.latest" =>
                    ManagerJson.ToElement(
                        _visual is null
                            ? new ManagerVisualSnapshot(
                                Available: false, Id: null, Source: null, Kind: null, Label: null,
                                CapturedAtUtc: null, MimeType: null, Bytes: 0, DeviceId: null,
                                DeviceName: null, WorkspaceId: null, Sha256: null,
                                Error: "Visual store unavailable.")
                            : await _visual.GetLatestAsync(
                                cancellationToken)),
                "lifecycle.agent" =>
                    ManagerJson.ToElement(
                        await LifecycleAgentAsync(
                            Require<ManagerLifecycleRequest>(
                                request.Parameters),
                            cancellationToken)),
                "lifecycle.all" =>
                    ManagerJson.ToElement(
                        await LifecycleAllAsync(
                            Require<ManagerLifecycleRequest>(
                                request.Parameters).Operation,
                            cancellationToken)),
                "task.cancel" =>
                    ManagerJson.ToElement(
                        await CancelTaskAsync(
                            Require<ManagerTaskCancelRequest>(
                                request.Parameters),
                            cancellationToken)),
                "approval.resolve" =>
                    ManagerJson.ToElement(
                        await ResolveApprovalAsync(
                            Require<ManagerApprovalActionRequest>(
                                request.Parameters),
                            cancellationToken)),
                "profiles.add" =>
                    ManagerJson.ToElement(
                        await AddProfileAsync(
                            Require<ManagerProfileAddRequest>(
                                request.Parameters),
                            cancellationToken)),
                "profiles.remove" =>
                    ManagerJson.ToElement(
                        await RemoveProfileAsync(
                            Require<ManagerProfileRemoveRequest>(
                                request.Parameters),
                            cancellationToken)),
                "profiles.update" =>
                    ManagerJson.ToElement(
                        await UpdateProfileAsync(
                            Require<ManagerProfileUpdateRequest>(
                                request.Parameters),
                            cancellationToken)),
                "profiles.switch" =>
                    ManagerJson.ToElement(
                        await SwitchProfileAsync(
                            Require<ManagerProfileSwitchRequest>(
                                request.Parameters),
                            cancellationToken)),
                "identity.snapshot" =>
                    ManagerJson.ToElement(
                        await GetMachineIdentityAsync(
                            cancellationToken)),
                "identity.rename" =>
                    ManagerJson.ToElement(
                        await RenameMachineIdentityAsync(
                            Require<ManagerMachineIdentityRenameRequest>(
                                request.Parameters),
                            cancellationToken)),
                "settings.tunnel.snapshot" =>
                    ManagerJson.ToElement(
                        await GetTunnelSettingsAsync(
                            cancellationToken)),
                "settings.tunnel.save" =>
                    ManagerJson.ToElement(
                        await SaveTunnelSettingsAsync(
                            Require<ManagerTunnelSettingsUpdateRequest>(
                                request.Parameters),
                            cancellationToken)),
                "development.snapshot" =>
                    ManagerJson.ToElement(
                        await GetDevelopmentAgentsAsync(
                            cancellationToken)),
                "development.add" =>
                    ManagerJson.ToElement(
                        await AddDevelopmentAgentAsync(
                            Require<ManagerDevelopmentAgentRequest>(
                                request.Parameters),
                            cancellationToken)),
                "development.remove" =>
                    ManagerJson.ToElement(
                        await RemoveDevelopmentAgentAsync(
                            Require<ManagerDevelopmentAgentRemoveRequest>(
                                request.Parameters),
                            cancellationToken)),
                "integrations.snapshot" =>
                    ManagerJson.ToElement(
                        await GetIntegrationsAsync(
                            cancellationToken)),
                "integrations.action" =>
                    ManagerJson.ToElement(
                        await RunIntegrationActionAsync(
                            Require<ManagerIntegrationActionRequest>(
                                request.Parameters),
                            cancellationToken)),
                "manager.health" =>
                    ManagerJson.ToElement(
                        await BuildHealthSummaryAsync(
                            cancellationToken)),
                "system.shutdown" =>
                    ManagerJson.ToElement(
                        new ManagerOperationResult(
                            true,
                            "system.shutdown",
                            "core",
                            "Shutdown accepted.")),
                _ => throw new InvalidOperationException(
                    $"Unknown Manager method '{request.Method}'.")
            };

            return new ManagerResponseEnvelope(
                ManagerProtocol.Version,
                request.RequestId,
                true,
                result,
                null);
        }
        catch (Exception ex)
        {
            _logs.Write(
                "ERROR",
                "ManagerControl",
                request.Method,
                ex.Message);

            return Error(request, ex.Message);
        }
    }

    public async Task RefreshHealthAsync(
        CancellationToken cancellationToken = default)
    {
        var tasks = _controllers.Snapshot()
            .Select(
                async controller =>
                {
                    if (!IsAgentDesiredRunning(
                            controller.AgentId))
                    {
                        return;
                    }

                    try
                    {
                        var result = await controller.Refresh(
                            cancellationToken);

                        if (!result.Success)
                        {
                            _logs.Write(
                                "WARN",
                                controller.AgentId,
                                "health.refresh",
                                result.Message);
                        }
                    }
                    catch (Exception ex)
                    {
                        _logs.Write(
                            "WARN",
                            controller.AgentId,
                            "health.refresh",
                            ex.Message);
                    }
                });

        await Task.WhenAll(tasks);
    }

    private bool IsAgentDesiredRunning(
        string agentId)
    {
        if (!_controllers.TryGet(
                agentId,
                out var controller) ||
            controller is null)
        {
            return false;
        }

        if (!_supervisor.TryGetSnapshot(
                controller.ProcessId,
                out var process) ||
            process is null)
        {
            // Controller-only/mock/external registrations may not have a
            // supervisor slot yet. Preserve their historical refresh behavior.
            return true;
        }

        return
            process.DesiredState ==
                DesiredProcessState.Running &&
            process.State !=
                AgentProcessState.Stopped;
    }

    private async Task<ManagerDashboardSnapshot> BuildDashboardAsync(
        CancellationToken cancellationToken)
    {
        if (_registry.Snapshot().Count == 0) throw new InvalidOperationException("Core supervisor/registry is unavailable.");
        await RefreshHealthAsync(cancellationToken);

        var registrations = _registry.Snapshot();
        var processes = _supervisor.Snapshot()
            .ToDictionary(
                item => item.AgentId,
                item => item,
                StringComparer.Ordinal);

        var controllerByAgent = _controllers.Snapshot()
            .ToDictionary(
                item => item.AgentId,
                item => item,
                StringComparer.Ordinal);

        var rows = new List<ManagerAgentRow>();

        foreach (var registered in registrations)
        {
            controllerByAgent.TryGetValue(
                registered.Manifest.Agent.Id,
                out var controller);

            AgentProcessSnapshot? process = null;
            if (controller is not null)
            {
                processes.TryGetValue(
                    controller.ProcessId,
                    out process);
            }

            var transport =
                registered.Manifest.Transport;

            var endpoint =
                transport.BindHost is not null &&
                transport.Port is not null
                    ? $"{transport.Kind}://{transport.BindHost}:{transport.Port}{transport.Path}"
                    : transport.Kind;

            var detail =
                registered.Manifest.Agent.Id == "arcmap.service" &&
                registered.Health == AgentHealthState.Degraded
                    ? "ArcMap MCP ready; external CURRENT-MXD bridge offline."
                    : registered.LastError;

            rows.Add(
                new ManagerAgentRow(
                    registered.Manifest.Agent.Id,
                    registered.Manifest.Agent.Name,
                    registered.Manifest.Agent.Version,
                    registered.Manifest.Environment,
                    registered.RegistrationState,
                    registered.Health,
                    registered.ProductionApproved,
                    controller?.ProcessId ?? "",
                    process?.DesiredState.ToString() ?? "Stopped",
                    process?.State.ToString() ?? "Stopped",
                    process?.ProcessId,
                    process?.ProcessTreeOwned ?? false,
                    process?.RestartAttempts ?? 0,
                    endpoint,
                    registered.Manifest.Capabilities.Count,
                    registered.LastError,
                    detail));
        }

        var unavailable = new List<string>();
        var activeTasks = 0;
        var pendingApprovals = 0;

        if (_tunnel is null || !IsAgentDesiredRunning("system.tunnel")) unavailable.Add("Tunnel stopped or unavailable; active task count unknown.");
        if (_tunnel is not null &&
            IsAgentDesiredRunning("system.tunnel"))
        {
            try
            {
                var monitoring =
                    await _tunnel.GetMonitoringAsync(
                        100,
                        cancellationToken);

                activeTasks = monitoring.Tasks.Count(
                    task =>
                        task.State is not "succeeded" and
                        not "failed" and
                        not "cancelled");
            }
            catch (Exception ex)
            {
                unavailable.Add("Agent dependency query unavailable; task/approval totals are partial.");
                _logs.Write(
                    "WARN",
                    "Tunnel",
                    "dashboard.tasks",
                    ex.Message);
            }
        }

        if (_files is not null &&
            IsAgentDesiredRunning("files.service"))
        {
            try
            {
                var profiles =
                    await _files.GetProfilesAsync(
                        cancellationToken);
                pendingApprovals +=
                    profiles.PendingApprovals.Count;
            }
            catch (Exception ex)
            {
                unavailable.Add("Agent dependency query unavailable; task/approval totals are partial.");
                _logs.Write(
                    "WARN",
                    "Files",
                    "dashboard.approvals",
                    ex.Message);
            }
        }

        if (_web is not null &&
            IsAgentDesiredRunning("web.service"))
        {
            try
            {
                var web =
                    await _web.GetPendingRequestsAsync(
                        cancellationToken);
                pendingApprovals +=
                    web.Requests.Count;
            }
            catch (Exception ex)
            {
                unavailable.Add("Agent dependency query unavailable; task/approval totals are partial.");
                _logs.Write(
                    "WARN",
                    "Web",
                    "dashboard.user_actions",
                    ex.Message);
            }
        }

        return new ManagerDashboardSnapshot(
            ZagentProductInfo.ProductName,
            ZagentProductInfo.CoreVersion,
            registrations.Count,
            registrations.Sum(
                item =>
                    item.Manifest.Capabilities.Count),
            processes.Values.Count(
                item =>
                    item.State ==
                    AgentProcessState.Running),
            activeTasks,
            pendingApprovals,
            rows
                .OrderBy(
                    item => AgentOrder(item.AgentId))
                .ToArray(),
            DateTimeOffset.UtcNow) { UnavailableDependencies = unavailable };
    }

    private IReadOnlyList<ManagerCapabilityRow> BuildCapabilities()
    {
        return _registry.Snapshot()
            .SelectMany(
                agent =>
                    agent.Manifest.Capabilities.Select(
                        capability =>
                            new ManagerCapabilityRow(
                                agent.Manifest.Agent.Id,
                                agent.Manifest.Agent.Name,
                                agent.Manifest.Agent.Version,
                                capability.Name,
                                capability.Access,
                                capability.Execution,
                                capability.Approval,
                                capability.ResourcePolicy,
                                capability.SupportsCancel,
                                capability.SupportsProgress,
                                capability.SupportsResume,
                                agent.Manifest.Environment,
                                agent.Health)))
            .OrderBy(
                row => row.AgentId,
                StringComparer.Ordinal)
            .ThenBy(
                row => row.Capability,
                StringComparer.Ordinal)
            .ToArray();
    }

    private async Task<ManagerMonitoringSnapshot> BuildMonitoringAsync(
        ManagerRefreshRequest refresh,
        CancellationToken cancellationToken)
    {
        if (_tunnel is null ||
            !IsAgentDesiredRunning("system.tunnel"))
        {
            throw new InvalidOperationException("Tunnel monitoring unavailable.");
        }

        try
        {
            var snapshot =
                await _tunnel.GetMonitoringAsync(
                    refresh.TaskLimit,
                    cancellationToken);

            if (refresh.IncludeCompletedTasks)
            {
                return snapshot with
                {
                    Tasks = snapshot.Tasks
                        .Where(
                            item =>
                                item.State is not "succeeded" and
                                    not "failed" and
                                    not "cancelled")
                        .Concat(
                            snapshot.Tasks
                                .Where(
                                    item =>
                                        item.State is "succeeded" or
                                            "failed" or
                                            "cancelled")
                                .Take(60))
                        .ToArray()
                };
            }

            return snapshot with
            {
                Tasks = snapshot.Tasks
                    .Where(
                        item =>
                            item.State is not "succeeded" and
                                not "failed" and
                                not "cancelled")
                    .ToArray()
            };
        }
        catch (Exception ex)
        {
            _logs.Write(
                "WARN",
                "Tunnel",
                "monitoring.snapshot",
                ex.Message);

            throw new InvalidOperationException("Tunnel monitoring unavailable.");
        }
    }


    private async Task<ManagerProfilesSnapshot> BuildProfilesAsync(
        CancellationToken cancellationToken)
    {
        var filesSnapshot = EmptyProfiles();
        var unavailable = new List<string>();
        if (_files is null || !IsAgentDesiredRunning("files.service")) unavailable.Add("Files");
        if (_web is null || !IsAgentDesiredRunning("web.service")) unavailable.Add("Web");

        if (_files is not null)
        {
            try
            {
                filesSnapshot =
                    await _files.GetProfilesAsync(
                        cancellationToken, includeWorkspace: IsAgentDesiredRunning("files.service"));
                unavailable.AddRange(filesSnapshot.UnavailableDependencies);
            }
            catch (Exception ex)
            {
                unavailable.Add("Agent dependency query failed; profiles/approvals are partial.");
                _logs.Write(
                    "WARN",
                    "Files",
                    "profiles.snapshot",
                    ex.Message);
            }
        }

        var approvals =
            filesSnapshot.PendingApprovals.ToList();
        var webConnected = false;
        var webAuthorized = false;

        if (_web is not null &&
            IsAgentDesiredRunning("web.service"))
        {
            try
            {
                var web =
                    await _web.GetPendingRequestsAsync(
                        cancellationToken);

                approvals.AddRange(web.Requests);
                webConnected = web.Connected;
                webAuthorized = web.Authorized;
            }
            catch (Exception ex)
            {
                unavailable.Add("Agent dependency query failed; profiles/approvals are partial.");
                _logs.Write(
                    "WARN",
                    "Web",
                    "profiles.web_user_actions",
                    ex.Message);
            }
        }

        return filesSnapshot with
        {
            PendingApprovals = approvals
                .OrderBy(
                    item => item.Source,
                    StringComparer.Ordinal)
                .ThenBy(
                    item => item.Kind,
                    StringComparer.Ordinal)
                .ToArray(),
            CapturedAtUtc = DateTimeOffset.UtcNow,
            WebBridgeConnected = webConnected,
            UnavailableDependencies = unavailable,
            WebBridgeAuthorized = webAuthorized
        };
    }

    private async Task<ManagerRouterSnapshot> BuildRouterSnapshotAsync(
        CancellationToken cancellationToken)
    {
        if (_routerManager is null || _tunnel is null ||
            !IsAgentDesiredRunning("system.tunnel"))
        {
            return new ManagerRouterSnapshot(
                Array.Empty<ManagerRouterServiceRow>(),
                0,
                "Offline",
                DateTimeOffset.UtcNow);
        }

        try
        {
            var dashboard = await BuildDashboardAsync(
                cancellationToken);

            return await _tunnel.GetRouterSnapshotAsync(
                dashboard.Agents,
                cancellationToken);
        }
        catch (Exception ex)
        {
            _logs.Write(
                "WARN",
                "Router",
                "router.snapshot",
                ex.Message);

            return new ManagerRouterSnapshot(
                Array.Empty<ManagerRouterServiceRow>(),
                0,
                "Offline",
                DateTimeOffset.UtcNow);
        }
    }

    private async Task<ManagerOperationResult> LifecycleAgentAsync(
        ManagerLifecycleRequest request,
        CancellationToken cancellationToken)
    {
        if (!_controllers.TryGet(
                request.AgentId,
                out var controller) ||
            controller is null)
        {
            return new ManagerOperationResult(
                false,
                request.Operation,
                request.AgentId,
                "Agent is not registered for Manager lifecycle control.");
        }

        LifecycleOperationResult result;

        switch (request.Operation)
        {
            case "start":
                result = await controller.Start(
                    cancellationToken);
                break;
            case "stop":
                var requestedStop = await controller.Stop(
                    cancellationToken);
                var verifiedStop =
                    await EnsureAgentStoppedAsync(
                        request.AgentId,
                        cancellationToken);

                result = new LifecycleOperationResult(
                    verifiedStop.Success,
                    request.AgentId,
                    "stop",
                    requestedStop.Success
                        ? verifiedStop.Message
                        : verifiedStop.Success
                            ? "Stopped and verified after controller stop reported: " +
                                requestedStop.Message
                            : requestedStop.Message + "; " +
                                verifiedStop.Message);
                break;
            case "restart":
                result = await controller.Restart(
                    cancellationToken);
                break;
            case "refresh":
                return await controller.Refresh(
                    cancellationToken);
            default:
                return new ManagerOperationResult(
                    false,
                    request.Operation,
                    request.AgentId,
                    "Unsupported lifecycle operation.");
        }

        _logs.Write(
            result.Success ? "INFO" : "ERROR",
            request.AgentId,
            $"lifecycle.{request.Operation}",
            result.Message ?? "");

        return new ManagerOperationResult(
            result.Success,
            request.Operation,
            request.AgentId,
            result.Message ?? "");
    }

    private async Task<LifecycleOperationResult> EnsureAgentStoppedAsync(
        string agentId,
        CancellationToken cancellationToken)
    {
        if (!_controllers.TryGet(
                agentId,
                out var controller) ||
            controller is null)
        {
            return new LifecycleOperationResult(
                false,
                agentId,
                "stop",
                "Agent is not registered for Manager lifecycle control.");
        }

        bool IsOwned(AgentProcessSnapshot process)
        {
            if (string.Equals(
                    process.AgentId,
                    controller.ProcessId,
                    StringComparison.Ordinal))
            {
                return true;
            }

            return string.Equals(
                       agentId,
                       "system.tunnel",
                       StringComparison.Ordinal) &&
                   process.AgentId.StartsWith(
                       "system.tunnel.",
                       StringComparison.Ordinal);
        }

        var active = _supervisor.Snapshot()
            .Where(IsOwned)
            .Where(item =>
                item.DesiredState !=
                    DesiredProcessState.Stopped ||
                item.State !=
                    AgentProcessState.Stopped ||
                item.ProcessId is not null)
            .ToArray();

        foreach (var process in active)
        {
            var fallback = await _supervisor.StopAsync(
                process.AgentId,
                cancellationToken);

            if (!fallback.Success)
            {
                return new LifecycleOperationResult(
                    false,
                    agentId,
                    "stop",
                    $"Fallback stop failed for {process.AgentId}: {fallback.Message}");
            }
        }

        var remaining = _supervisor.Snapshot()
            .Where(IsOwned)
            .Where(item =>
                item.DesiredState !=
                    DesiredProcessState.Stopped ||
                item.State !=
                    AgentProcessState.Stopped ||
                item.ProcessId is not null)
            .ToArray();

        if (remaining.Length > 0)
        {
            return new LifecycleOperationResult(
                false,
                agentId,
                "stop",
                "Processes still active after stop: " +
                string.Join(
                    ", ",
                    remaining.Select(item =>
                        $"{item.AgentId}[state={item.State}, desired={item.DesiredState}, pid={item.ProcessId?.ToString() ?? "none"}]")));
        }

        _registry.TrySetHealth(
            agentId,
            AgentHealthState.Offline);

        return new LifecycleOperationResult(
            true,
            agentId,
            "stop",
            "Stopped and verified.");
    }

    private async Task<ManagerOperationResult> LifecycleAllAsync(
        string operation,
        CancellationToken cancellationToken)
    {
        var order = operation switch
        {
            "start" =>
                new[]
                {
                    "files.service",
                    "web.service",
                    "arcmap.service",
                    "system.tunnel"
                },
            "stop" =>
                new[]
                {
                    "system.tunnel",
                    "arcmap.service",
                    "web.service",
                    "files.service"
                },
            "restart" =>
                new[]
                {
                    "system.tunnel",
                    "arcmap.service",
                    "web.service",
                    "files.service"
                },
            "refresh" =>
                _controllers.Snapshot()
                    .Select(item => item.AgentId)
                    .ToArray(),
            _ => Array.Empty<string>()
        };

        if (order.Length == 0)
        {
            return new ManagerOperationResult(
                false,
                operation,
                "all",
                "Unsupported lifecycle operation.");
        }

        var errors = new List<string>();

        if (operation == "restart")
        {
            var stop = await LifecycleAllAsync(
                "stop",
                cancellationToken);

            if (!stop.Success)
            {
                return new ManagerOperationResult(
                    false,
                    "restart",
                    "all",
                    "Stop All failed: " + stop.Message);
            }

            return await LifecycleAllAsync(
                "start",
                cancellationToken);
        }

        foreach (var agentId in order)
        {
            cancellationToken.ThrowIfCancellationRequested();

            if (!_controllers.TryGet(
                    agentId,
                    out var controller) ||
                controller is null)
            {
                continue;
            }

            try
            {
                ManagerOperationResult item;

                if (operation == "refresh")
                {
                    item = await controller.Refresh(
                        cancellationToken);
                }
                else
                {
                    var lifecycle =
                        operation == "start"
                            ? await controller.Start(
                                cancellationToken)
                            : await controller.Stop(
                                cancellationToken);

                    item = new ManagerOperationResult(
                        lifecycle.Success,
                        operation,
                        agentId,
                        lifecycle.Message ?? "");
                }

                if (!item.Success)
                {
                    errors.Add(
                        $"{agentId}: {item.Message}");
                }
            }
            catch (Exception ex)
            {
                errors.Add($"{agentId}: {ex.Message}");
            }
        }

        if (operation == "stop")
        {
            var residual = _supervisor.Snapshot()
                .Where(item =>
                    item.DesiredState != DesiredProcessState.Stopped ||
                    item.State != AgentProcessState.Stopped ||
                    item.ProcessId is not null)
                .ToArray();

            foreach (var process in residual)
            {
                try
                {
                    var fallback = await _supervisor.StopAsync(
                        process.AgentId,
                        cancellationToken);

                    if (!fallback.Success)
                    {
                        errors.Add(
                            $"{process.AgentId}: fallback stop failed: {fallback.Message}");
                    }
                }
                catch (Exception ex)
                {
                    errors.Add(
                        $"{process.AgentId}: fallback stop failed: {ex.Message}");
                }
            }

            var remaining = _supervisor.Snapshot()
                .Where(item =>
                    item.DesiredState != DesiredProcessState.Stopped ||
                    item.State != AgentProcessState.Stopped ||
                    item.ProcessId is not null)
                .Select(item =>
                    $"{item.AgentId}[state={item.State}, desired={item.DesiredState}, pid={item.ProcessId?.ToString() ?? "none"}]")
                .ToArray();

            if (remaining.Length > 0)
            {
                errors.Add(
                    "Processes still active after Stop All: " +
                    string.Join(", ", remaining));
            }
        }

        var success = errors.Count == 0;
        var message = success
            ? $"{operation} all completed."
            : string.Join("; ", errors);

        _logs.Write(
            success ? "INFO" : "ERROR",
            "Manager",
            $"lifecycle.all.{operation}",
            message);

        return new ManagerOperationResult(
            success,
            operation,
            "all",
            message);
    }

    private async Task<ManagerOperationResult> CancelTaskAsync(
        ManagerTaskCancelRequest request,
        CancellationToken cancellationToken)
    {
        if (_tunnel is null)
        {
            return new ManagerOperationResult(
                false,
                "task.cancel",
                request.TaskId,
                "Tunnel task journal is unavailable.");
        }

        var result =
            await _tunnel.CancelTaskAsync(
                request.TaskId,
                cancellationToken);

        _logs.Write(
            result.Success ? "INFO" : "ERROR",
            "Monitoring",
            "task.cancel",
            $"{request.TaskId}: {result.Message}");

        return result;
    }

    private async Task<ManagerOperationResult> ResolveApprovalAsync(
        ManagerApprovalActionRequest request,
        CancellationToken cancellationToken)
    {
        if (_files is null)
        {
            return new ManagerOperationResult(
                false, "approval.resolve", request.RequestId,
                "Files approval service is unavailable.");
        }
        var result = await _files.ResolveApprovalAsync(request, cancellationToken);

        _logs.Write(
            result.Success ? "INFO" : "ERROR",
            "Approvals",
            $"approval.{request.Action}",
            $"{request.RequestId}: {result.Message}");

        return result;
    }

    private async Task<ManagerOperationResult> AddProfileAsync(
        ManagerProfileAddRequest request,
        CancellationToken cancellationToken)
    {
        if (_files is null)
        {
            return new ManagerOperationResult(
                false,
                "profiles.add",
                request.Name,
                "Files profile service is unavailable.");
        }

        var result = await _files.AddProfileAsync(
            request,
            cancellationToken);

        _logs.Write(
            result.Success ? "INFO" : "ERROR",
            "Files",
            "profiles.add",
            $"{request.Name}: {result.Message}");

        return result;
    }

    private async Task<ManagerOperationResult> RemoveProfileAsync(
        ManagerProfileRemoveRequest request,
        CancellationToken cancellationToken)
    {
        if (_files is null)
        {
            return new ManagerOperationResult(
                false,
                "profiles.remove",
                request.Name,
                "Files profile service is unavailable.");
        }

        var result = await _files.RemoveProfileAsync(
            request,
            cancellationToken);

        _logs.Write(
            result.Success ? "INFO" : "ERROR",
            "Files",
            "profiles.remove",
            $"{request.Name}: {result.Message}");

        return result;
    }

    private async Task<ManagerOperationResult> UpdateProfileAsync(
        ManagerProfileUpdateRequest request,
        CancellationToken cancellationToken)
    {
        if (_files is null)
        {
            return new ManagerOperationResult(
                false,
                "profiles.update",
                request.Name,
                "Files profile service is unavailable.");
        }

        var result = await _files.UpdateProfileAsync(
            request,
            cancellationToken);

        _logs.Write(
            result.Success ? "INFO" : "ERROR",
            "Files",
            "profiles.update",
            request.Name + ": " + result.Message);

        return result;
    }

    private async Task<ManagerOperationResult> SwitchProfileAsync(
        ManagerProfileSwitchRequest request,
        CancellationToken cancellationToken)
    {
        if (_files is null)
        {
            return new ManagerOperationResult(
                false,
                "profiles.switch",
                request.Name,
                "Files profile service is unavailable.");
        }

        var result = await _files.SwitchProfileAsync(
            request,
            cancellationToken);

        _logs.Write(
            result.Success ? "INFO" : "ERROR",
            "Files",
            "profiles.switch",
            request.Name + ": " + result.Message);

        return result;
    }

    private async Task<ManagerIntegrationSnapshot> GetIntegrationsAsync(
        CancellationToken cancellationToken)
    {
        if (_integrations is null)
        {
            throw new InvalidOperationException(
                "Integration service is unavailable.");
        }

        return await _integrations.SnapshotAsync(
            cancellationToken);
    }

    private async Task<ManagerIntegrationActionResult> RunIntegrationActionAsync(
        ManagerIntegrationActionRequest request,
        CancellationToken cancellationToken)
    {
        if (_integrations is null)
        {
            throw new InvalidOperationException(
                "Integration service is unavailable.");
        }

        return await _integrations.RunAsync(
            request,
            cancellationToken);
    }

    private async Task<ManagerMachineIdentitySnapshot> GetMachineIdentityAsync(
        CancellationToken cancellationToken)
    {
        if (_machineIdentity is null)
        {
            return new ManagerMachineIdentitySnapshot("", "", "", DateTimeOffset.MinValue, "unavailable", "Unavailable", "unavailable", TrustState: "unavailable");
        }

        var identity =
            await _machineIdentity.SnapshotAsync(
                cancellationToken);

        return new ManagerMachineIdentitySnapshot(identity.DeviceId, identity.DeviceName, identity.BindingFingerprint,
            identity.CreatedAtUtc, identity.BindingState, identity.Protection, "configured-installation", identity.DeviceAlias, identity.InstallationId, identity.ShortFingerprint, "local-proof-only");
    }


    private async Task<ManagerMachineIdentitySnapshot> RenameMachineIdentityAsync(
        ManagerMachineIdentityRenameRequest request,
        CancellationToken cancellationToken)
    {
        if (_machineIdentity is null)
        {
            throw new InvalidOperationException(
                "Machine identity service is unavailable.");
        }

        var updated =
            await _machineIdentity.RenameAliasAsync(
                request.DeviceAlias,
                cancellationToken);

        _logs.Write(
            "INFO",
            "Identity",
            "identity.alias.renamed",
            "Device alias changed. The device_id and protected identity secret were preserved.");

        if (_routerManager is not null)
        {
            try
            {
                await _routerManager.RenameIdentityAliasAsync(
                    updated.DeviceAlias,
                    cancellationToken);
            }
            catch
            {
                // The persisted alias remains authoritative and will be
                // applied automatically when the Tunnel router next starts.
            }
        }

        return await GetMachineIdentityAsync(
            cancellationToken);
    }

    private async Task<ManagerTunnelSettingsSnapshot> GetTunnelSettingsAsync(
        CancellationToken cancellationToken)
    {
        if (_tunnelCredentials is null)
        {
            return new ManagerTunnelSettingsSnapshot(
                "",
                false,
                "Not configured",
                false,
                "Unavailable");
        }

        return await _tunnelCredentials.SnapshotAsync(
            cancellationToken);
    }

    private async Task<ManagerTunnelSettingsSnapshot> SaveTunnelSettingsAsync(
        ManagerTunnelSettingsUpdateRequest request,
        CancellationToken cancellationToken)
    {
        if (_tunnelCredentials is null)
        {
            throw new InvalidOperationException(
                "Tunnel credential store is unavailable.");
        }

        var tunnelId = request.TunnelId.Trim();
        if (string.IsNullOrWhiteSpace(tunnelId))
        {
            throw new ArgumentException(
                "Tunnel ID is required.");
        }

        var existing = await _tunnelCredentials.LoadAsync(
            cancellationToken);

        var apiKey = string.IsNullOrWhiteSpace(
            request.ApiKey)
            ? existing?.ApiKey
            : request.ApiKey.Trim();

        if (string.IsNullOrWhiteSpace(apiKey))
        {
            throw new ArgumentException(
                "API key is required for the first Tunnel credential setup.");
        }

        await _tunnelCredentials.SaveAsync(
            new TunnelCredentials(
                tunnelId,
                apiKey),
            cancellationToken);

        _logs.Write(
            "INFO",
            "Settings",
            "tunnel.credentials.saved",
            "Tunnel credentials updated using Windows DPAPI CurrentUser protection. Core restart required to apply transport changes.");

        return await _tunnelCredentials.SnapshotAsync(
            cancellationToken);
    }

    private async Task<IReadOnlyList<ManagerDevelopmentAgentRow>> GetDevelopmentAgentsAsync(
        CancellationToken cancellationToken)
    {
        if (_developmentAgents is null)
        {
            return Array.Empty<ManagerDevelopmentAgentRow>();
        }

        return await _developmentAgents.SnapshotAsync(
            cancellationToken);
    }

    private async Task<ManagerOperationResult> AddDevelopmentAgentAsync(
        ManagerDevelopmentAgentRequest request,
        CancellationToken cancellationToken)
    {
        if (_developmentAgents is null)
        {
            return new ManagerOperationResult(
                false,
                "development.add",
                request.Namespace,
                "Development Agent store is unavailable.");
        }

        var row = await _developmentAgents.AddAsync(
            request,
            cancellationToken);

        var refresh = await RestartTunnelAfterDevelopmentChangeAsync(
            cancellationToken);

        _logs.Write(
            refresh.Success ? "INFO" : "WARN",
            "Development",
            "development.add",
            $"{row.Id} -> {row.Url}: {refresh.Message}");

        return new ManagerOperationResult(
            refresh.Success,
            "development.add",
            row.Id,
            refresh.Success
                ? $"Development Agent '{row.Name}' added and Tunnel refreshed."
                : $"Development Agent was saved, but Tunnel refresh failed: {refresh.Message}");
    }

    private async Task<ManagerOperationResult> RemoveDevelopmentAgentAsync(
        ManagerDevelopmentAgentRemoveRequest request,
        CancellationToken cancellationToken)
    {
        if (_developmentAgents is null)
        {
            return new ManagerOperationResult(
                false,
                "development.remove",
                request.Id,
                "Development Agent store is unavailable.");
        }

        var removed = await _developmentAgents.RemoveAsync(
            request.Id,
            cancellationToken);

        if (!removed)
        {
            return new ManagerOperationResult(
                false,
                "development.remove",
                request.Id,
                "Development Agent was not found.");
        }

        var refresh = await RestartTunnelAfterDevelopmentChangeAsync(
            cancellationToken);

        _logs.Write(
            refresh.Success ? "INFO" : "WARN",
            "Development",
            "development.remove",
            $"{request.Id}: {refresh.Message}");

        return new ManagerOperationResult(
            refresh.Success,
            "development.remove",
            request.Id,
            refresh.Success
                ? "Development Agent removed and Tunnel refreshed."
                : $"Development Agent removed, but Tunnel refresh failed: {refresh.Message}");
    }

    private async Task<ManagerOperationResult> RestartTunnelAfterDevelopmentChangeAsync(
        CancellationToken cancellationToken)
    {
        if (!_controllers.TryGet(
                "system.tunnel",
                out var controller) ||
            controller is null)
        {
            return new ManagerOperationResult(
                false,
                "restart",
                "system.tunnel",
                "Tunnel controller is unavailable.");
        }

        var result = await controller.Restart(
            cancellationToken);

        return new ManagerOperationResult(
            result.Success,
            "restart",
            "system.tunnel",
            result.Message ?? "");
    }

    private async Task<ManagerHealthSummary> BuildHealthSummaryAsync(
        CancellationToken cancellationToken)
    {
        await RefreshHealthAsync(cancellationToken);

        var agents = _registry.Snapshot()
            .ToDictionary(
                item => item.Manifest.Agent.Id,
                item => item,
                StringComparer.Ordinal);

        var routedTools = 0;

        if (_tunnel is not null)
        {
            try
            {
                using var status =
                    await _tunnel.GetRouterStatusAsync(
                        cancellationToken);

                routedTools = FindInt(
                    status.RootElement,
                    "tool_count") ??
                    FindInt(
                        status.RootElement,
                        "tools") ??
                    0;
            }
            catch
            {
            }
        }

        return new ManagerHealthSummary(
            Ready(agents, "system.tunnel"),
            Ready(agents, "files.service"),
            Ready(agents, "web.service"),
            ReadyOrDegraded(
                agents,
                "arcmap.service"),
            Ready(agents, "arcmap.service"),
            routedTools,
            DateTimeOffset.UtcNow);
    }

    private static bool Ready(
        IReadOnlyDictionary<string, RegisteredAgent> agents,
        string agentId) =>
        agents.TryGetValue(agentId, out var agent) &&
        agent.Health == AgentHealthState.Ready;

    private static bool ReadyOrDegraded(
        IReadOnlyDictionary<string, RegisteredAgent> agents,
        string agentId) =>
        agents.TryGetValue(agentId, out var agent) &&
        agent.Health is
            AgentHealthState.Ready or
            AgentHealthState.Degraded;

    private static int? FindInt(
        JsonElement element,
        string name)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            if (element.TryGetProperty(
                    name,
                    out var direct) &&
                direct.TryGetInt32(out var number))
            {
                return number;
            }

            foreach (var property in element.EnumerateObject())
            {
                var nested = FindInt(
                    property.Value,
                    name);

                if (nested is not null)
                {
                    return nested;
                }
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in element.EnumerateArray())
            {
                var nested = FindInt(item, name);
                if (nested is not null)
                {
                    return nested;
                }
            }
        }

        return null;
    }

    private static ManagerRefreshRequest ParseRefresh(
        JsonElement? element) =>
        ManagerJson.FromElement<ManagerRefreshRequest>(
            element) ??
        new ManagerRefreshRequest();

    private static T Require<T>(JsonElement? element)
        where T : class =>
        ManagerJson.FromElement<T>(element) ??
        throw new InvalidOperationException(
            $"Manager method requires {typeof(T).Name} parameters.");

    private static ManagerResponseEnvelope Error(
        ManagerRequestEnvelope request,
        string error) =>
        new(
            ManagerProtocol.Version,
            request.RequestId,
            false,
            null,
            error);

    private static ManagerProfilesSnapshot EmptyProfiles() =>
        new(
            Array.Empty<ManagerProfileRow>(),
            Array.Empty<ManagerWorkspaceRow>(),
            Array.Empty<ManagerApprovalRow>(),
            "",
            DateTimeOffset.UtcNow);

    private static int AgentOrder(string agentId) =>
        agentId switch
        {
            "system.tunnel" => 0,
            "files.service" => 1,
            "web.service" => 2,
            "arcmap.service" => 3,
            _ => 100
        };
}