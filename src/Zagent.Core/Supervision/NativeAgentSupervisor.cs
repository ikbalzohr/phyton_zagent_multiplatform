using System.Collections.Concurrent;
using System.Diagnostics;
using Zagent.Core.Abstractions;
using Zagent.Shared.Contracts;

namespace Zagent.Core.Supervision;

public sealed class NativeAgentSupervisor : IAgentSupervisor
{
    private readonly ConcurrentDictionary<string, AgentSlot> _slots =
        new(StringComparer.Ordinal);
    private readonly SupervisorInstanceLease? _instanceLease;
    private int _shutdownRequested;
    private int _disposed;

    public NativeAgentSupervisor(
        bool acquireInstanceLease = true,
        string? instanceLeaseName = null)
    {
        if (!acquireInstanceLease)
        {
            return;
        }

        var leaseName = string.IsNullOrWhiteSpace(instanceLeaseName)
            ? SupervisorInstanceLease.DefaultName
            : instanceLeaseName;

        if (!SupervisorInstanceLease.TryAcquire(
                leaseName,
                out _instanceLease))
        {
            throw new InvalidOperationException(
                "Another Zagent supervisor already owns the lifecycle lease.");
        }
    }

    public void Register(AgentProcessDefinition definition)
    {
        ThrowIfDisposed();

        ArgumentNullException.ThrowIfNull(definition);
        ValidateDefinition(definition);

        if (!_slots.TryAdd(
                definition.AgentId,
                new AgentSlot(definition)))
        {
            throw new InvalidOperationException(
                $"Agent '{definition.AgentId}' is already registered with the supervisor.");
        }
    }

    public async Task<LifecycleOperationResult> StartAsync(
        string agentId,
        CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();

        var slot = GetSlot(agentId);

        await slot.Gate.WaitAsync(cancellationToken);
        try
        {
            if (Volatile.Read(ref _shutdownRequested) != 0)
            {
                return new LifecycleOperationResult(
                    false,
                    agentId,
                    "start",
                    "Supervisor shutdown is in progress; new starts are blocked.");
            }

            slot.DesiredState = DesiredProcessState.Running;
            slot.RestartAttempts = 0;
            slot.NextRestartAtUtc = null;

            return StartProcessLocked(
                slot,
                resetRestartCounter: true);
        }
        finally
        {
            slot.Gate.Release();
        }
    }

    public async Task<LifecycleOperationResult> StopAsync(
        string agentId,
        CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();

        var slot = GetSlot(agentId);
        return await StopSlotAsync(
            slot,
            cancellationToken);
    }

    public async Task<LifecycleOperationResult> RestartAsync(
        string agentId,
        CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();

        var stop = await StopAsync(
            agentId,
            cancellationToken);

        if (!stop.Success)
        {
            return new LifecycleOperationResult(
                false,
                agentId,
                "restart",
                $"Stop failed: {stop.Message}");
        }

        var start = await StartAsync(
            agentId,
            cancellationToken);

        return new LifecycleOperationResult(
            start.Success,
            agentId,
            "restart",
            start.Message);
    }

    public bool TryGetSnapshot(
        string agentId,
        out AgentProcessSnapshot? snapshot)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(agentId);

        if (!_slots.TryGetValue(agentId, out var slot))
        {
            snapshot = null;
            return false;
        }

        snapshot = CreateSnapshot(slot);
        return true;
    }

    public IReadOnlyList<AgentProcessSnapshot> Snapshot() =>
        _slots.Values
            .OrderBy(
                slot => slot.Definition.AgentId,
                StringComparer.Ordinal)
            .Select(CreateSnapshot)
            .ToArray();

    public async Task<LifecycleOperationResult> ReportHealthAsync(
        string agentId,
        AgentHealthState health,
        CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();

        var slot = GetSlot(agentId);
        var shouldRestart = false;

        await slot.Gate.WaitAsync(cancellationToken);
        try
        {
            slot.LastReportedHealth = health;

            if (health is AgentHealthState.Ready or
                AgentHealthState.Degraded)
            {
                slot.HasReachedHealthyState = true;

                return new LifecycleOperationResult(
                    true,
                    agentId,
                    "health",
                    $"Health recorded as {health}.");
            }

            if (health == AgentHealthState.Unknown)
            {
                return new LifecycleOperationResult(
                    true,
                    agentId,
                    "health",
                    "Health recorded as Unknown.");
            }

            if (slot.DesiredState != DesiredProcessState.Running)
            {
                return new LifecycleOperationResult(
                    true,
                    agentId,
                    "health",
                    "Health is unhealthy, but desired state is Stopped.");
            }

            if (slot.State is AgentProcessState.BackingOff or
                AgentProcessState.Starting or
                AgentProcessState.Stopping)
            {
                return new LifecycleOperationResult(
                    true,
                    agentId,
                    "health",
                    $"Health is {health}; lifecycle recovery is already in progress.");
            }

            if (!slot.HasReachedHealthyState &&
                slot.StartedAtUtc is DateTimeOffset startedAt &&
                slot.Definition.HealthRestartGraceMilliseconds > 0)
            {
                var grace = TimeSpan.FromMilliseconds(
                    slot.Definition.HealthRestartGraceMilliseconds);

                if (DateTimeOffset.UtcNow - startedAt < grace)
                {
                    return new LifecycleOperationResult(
                        true,
                        agentId,
                        "health",
                        $"Health is {health}; startup health grace is active.");
                }
            }

            shouldRestart =
                slot.Process is { HasExited: false } &&
                slot.State == AgentProcessState.Running;
        }
        finally
        {
            slot.Gate.Release();
        }

        if (!shouldRestart)
        {
            return new LifecycleOperationResult(
                true,
                agentId,
                "health",
                $"Health recorded as {health}; no running process required restart.");
        }

        var restart = await RestartAsync(
            agentId,
            cancellationToken);

        return new LifecycleOperationResult(
            restart.Success,
            agentId,
            "health",
            restart.Success
                ? $"Health {health} triggered a supervised restart."
                : $"Health {health} restart failed: {restart.Message}");
    }

    public async Task<SupervisorShutdownResult> StopAllAsync(
        CancellationToken cancellationToken = default)
    {
        ThrowIfDisposed();

        Interlocked.Exchange(ref _shutdownRequested, 1);

        var failures = new ConcurrentBag<string>();

        await Task.WhenAll(
            _slots.Values.Select(
                async slot =>
                {
                    var result = await StopSlotAsync(
                        slot,
                        cancellationToken);

                    if (!result.Success)
                    {
                        failures.Add(slot.Definition.AgentId);
                    }
                }));

        return new SupervisorShutdownResult(
            failures.IsEmpty,
            failures.OrderBy(
                id => id,
                StringComparer.Ordinal).ToArray());
    }

    public async ValueTask DisposeAsync()
    {
        if (Interlocked.Exchange(ref _disposed, 1) != 0)
        {
            return;
        }

        Interlocked.Exchange(ref _shutdownRequested, 1);

        try
        {
            foreach (var slot in _slots.Values)
            {
                await StopSlotForDisposeAsync(slot);
                slot.Gate.Dispose();
            }
        }
        finally
        {
            _instanceLease?.Dispose();
        }
    }

    private LifecycleOperationResult StartProcessLocked(
        AgentSlot slot,
        bool resetRestartCounter)
    {
        var agentId = slot.Definition.AgentId;

        if (slot.Process is { HasExited: false })
        {
            slot.State = AgentProcessState.Running;
            return new LifecycleOperationResult(
                true,
                agentId,
                "start",
                $"Already running with PID {slot.Process.Id}.");
        }

        DisposeProcess(slot);

        if (resetRestartCounter)
        {
            slot.RestartAttempts = 0;
        }

        slot.NextRestartAtUtc = null;
        slot.State = AgentProcessState.Starting;
        slot.LastError = null;
        slot.LastExitCode = null;
        slot.HasReachedHealthyState = false;

        try
        {
            var process = CreateProcess(slot.Definition);
            if (!process.Start())
            {
                process.Dispose();
                slot.State = AgentProcessState.Faulted;
                slot.LastError = "Process.Start returned false.";

                return new LifecycleOperationResult(
                    false,
                    agentId,
                    "start",
                    slot.LastError);
            }

            slot.Process = process;
            slot.StartedAtUtc = DateTimeOffset.UtcNow;

            if (WindowsJobObject.TryCreateAndAssign(
                    process,
                    out var jobObject,
                    out var ownershipError))
            {
                slot.JobObject = jobObject;
                slot.ProcessTreeOwned = true;
            }
            else
            {
                slot.ProcessTreeOwned = false;
                slot.LastError =
                    "Process tree ownership degraded: " +
                    ownershipError;
            }

            slot.State = AgentProcessState.Running;
            slot.Generation++;

            ObserveExit(
                slot,
                process,
                slot.Generation);

            return new LifecycleOperationResult(
                true,
                agentId,
                "start",
                $"Started PID {process.Id}.");
        }
        catch (Exception ex)
        {
            slot.State = AgentProcessState.Faulted;
            slot.LastError = ex.Message;
            DisposeProcess(slot);

            return new LifecycleOperationResult(
                false,
                agentId,
                "start",
                ex.Message);
        }
    }

    private async Task<LifecycleOperationResult> StopSlotAsync(
        AgentSlot slot,
        CancellationToken cancellationToken)
    {
        await slot.Gate.WaitAsync(cancellationToken);
        try
        {
            return await StopSlotLockedAsync(
                slot,
                cancellationToken);
        }
        finally
        {
            slot.Gate.Release();
        }
    }

    private async Task StopSlotForDisposeAsync(AgentSlot slot)
    {
        await slot.Gate.WaitAsync();
        try
        {
            await StopSlotLockedAsync(
                slot,
                CancellationToken.None);
        }
        finally
        {
            slot.Gate.Release();
        }
    }

    private static async Task<LifecycleOperationResult> StopSlotLockedAsync(
        AgentSlot slot,
        CancellationToken cancellationToken)
    {
        var agentId = slot.Definition.AgentId;
        slot.DesiredState = DesiredProcessState.Stopped;
        slot.NextRestartAtUtc = null;

        var process = slot.Process;
        if (process is null)
        {
            slot.State = AgentProcessState.Stopped;
            return new LifecycleOperationResult(
                true,
                agentId,
                "stop",
                "Already stopped.");
        }

        if (process.HasExited)
        {
            CaptureExit(slot, process);
            DisposeProcess(slot);
            slot.State = AgentProcessState.Stopped;

            return new LifecycleOperationResult(
                true,
                agentId,
                "stop",
                "Process had already exited.");
        }

        slot.State = AgentProcessState.Stopping;

        try
        {
            var gracefulRequested = false;
            try
            {
                gracefulRequested = process.CloseMainWindow();
            }
            catch (InvalidOperationException)
            {
                gracefulRequested = false;
            }

            if (gracefulRequested &&
                slot.Definition.GracefulShutdownSeconds > 0)
            {
                var gracefulDelay = TimeSpan.FromSeconds(
                    slot.Definition.GracefulShutdownSeconds);

                using var gracefulCts =
                    CancellationTokenSource.CreateLinkedTokenSource(
                        cancellationToken);
                gracefulCts.CancelAfter(gracefulDelay);

                try
                {
                    await process.WaitForExitAsync(
                        gracefulCts.Token);
                }
                catch (OperationCanceledException)
                    when (!cancellationToken.IsCancellationRequested)
                {
                }
            }

            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                await process.WaitForExitAsync(cancellationToken);
            }

            CaptureExit(slot, process);
            DisposeProcess(slot);
            slot.State = AgentProcessState.Stopped;

            return new LifecycleOperationResult(
                true,
                agentId,
                "stop",
                "Stopped.");
        }
        catch (Exception ex)
            when (ex is not OperationCanceledException)
        {
            slot.State = AgentProcessState.Faulted;
            slot.LastError = ex.Message;

            return new LifecycleOperationResult(
                false,
                agentId,
                "stop",
                ex.Message);
        }
    }

    private void ObserveExit(
        AgentSlot slot,
        Process process,
        long generation)
    {
        _ = Task.Run(
            async () =>
            {
                try
                {
                    await process.WaitForExitAsync();
                }
                catch
                {
                    return;
                }

                var scheduleRestart = false;
                var restartDelay = TimeSpan.Zero;
                var restartGeneration = generation;

                await slot.Gate.WaitAsync();
                try
                {
                    if (slot.Generation != generation ||
                        !ReferenceEquals(
                            slot.Process,
                            process))
                    {
                        return;
                    }

                    CaptureExit(slot, process);
                    DisposeProcess(slot);

                    if (slot.DesiredState == DesiredProcessState.Stopped ||
                        Volatile.Read(ref _shutdownRequested) != 0 ||
                        Volatile.Read(ref _disposed) != 0)
                    {
                        slot.State = AgentProcessState.Stopped;
                        slot.NextRestartAtUtc = null;
                        return;
                    }

                    if (!slot.Definition.AutoRestart)
                    {
                        slot.State = AgentProcessState.Faulted;
                        slot.LastError ??=
                            "Process exited while desired state was Running.";
                        return;
                    }

                    if (slot.RestartAttempts >=
                        slot.Definition.MaxRestartAttempts)
                    {
                        slot.State = AgentProcessState.Faulted;
                        slot.LastError =
                            $"Auto-restart limit reached after " +
                            $"{slot.RestartAttempts} attempt(s).";
                        slot.NextRestartAtUtc = null;
                        return;
                    }

                    slot.RestartAttempts++;
                    restartDelay = CalculateBackoff(
                        slot.Definition,
                        slot.RestartAttempts);
                    slot.NextRestartAtUtc =
                        DateTimeOffset.UtcNow + restartDelay;
                    slot.State = AgentProcessState.BackingOff;

                    scheduleRestart = true;
                    restartGeneration = slot.Generation;
                }
                finally
                {
                    slot.Gate.Release();
                }

                if (scheduleRestart)
                {
                    _ = RestartAfterBackoffAsync(
                        slot,
                        restartGeneration,
                        restartDelay);
                }
            });
    }

    private async Task RestartAfterBackoffAsync(
        AgentSlot slot,
        long expectedGeneration,
        TimeSpan delay)
    {
        try
        {
            await Task.Delay(delay);
        }
        catch
        {
            return;
        }

        await slot.Gate.WaitAsync();
        try
        {
            if (Volatile.Read(ref _shutdownRequested) != 0 ||
                Volatile.Read(ref _disposed) != 0 ||
                slot.DesiredState != DesiredProcessState.Running ||
                slot.Generation != expectedGeneration)
            {
                return;
            }

            _ = StartProcessLocked(
                slot,
                resetRestartCounter: false);
        }
        finally
        {
            slot.Gate.Release();
        }
    }

    private static TimeSpan CalculateBackoff(
        AgentProcessDefinition definition,
        int attempt)
    {
        long delay = definition.RestartBackoffMilliseconds;

        for (var index = 1; index < attempt; index++)
        {
            delay = Math.Min(
                delay * 2,
                definition.RestartBackoffMaxMilliseconds);
        }

        delay = Math.Min(
            delay,
            definition.RestartBackoffMaxMilliseconds);

        return TimeSpan.FromMilliseconds(delay);
    }

    private static Process CreateProcess(
        AgentProcessDefinition definition)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = definition.ExecutablePath,
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = string.IsNullOrWhiteSpace(
                definition.WorkingDirectory)
                ? Path.GetDirectoryName(
                    Path.GetFullPath(
                        definition.ExecutablePath))
                    ?? Environment.CurrentDirectory
                : Path.GetFullPath(
                    definition.WorkingDirectory)
        };

        foreach (var argument in definition.Arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        if (definition.EnvironmentVariables is not null)
        {
            foreach (var pair in definition.EnvironmentVariables)
            {
                startInfo.Environment[pair.Key] = pair.Value;
            }
        }

        return new Process
        {
            StartInfo = startInfo,
            EnableRaisingEvents = false
        };
    }

    private static AgentProcessSnapshot CreateSnapshot(
        AgentSlot slot)
    {
        var process = slot.Process;

        int? pid = null;
        if (process is { HasExited: false })
        {
            pid = process.Id;
        }

        return new AgentProcessSnapshot(
            AgentId: slot.Definition.AgentId,
            DesiredState: slot.DesiredState,
            State: slot.State,
            ProcessId: pid,
            StartedAtUtc: slot.StartedAtUtc,
            LastExitCode: slot.LastExitCode,
            LastError: slot.LastError,
            ProcessTreeOwned: slot.ProcessTreeOwned,
            RestartAttempts: slot.RestartAttempts,
            NextRestartAtUtc: slot.NextRestartAtUtc,
            LastReportedHealth: slot.LastReportedHealth);
    }

    private static void CaptureExit(
        AgentSlot slot,
        Process process)
    {
        try
        {
            if (process.HasExited)
            {
                slot.LastExitCode = process.ExitCode;
            }
        }
        catch (InvalidOperationException)
        {
        }
    }

    private static void DisposeProcess(AgentSlot slot)
    {
        var process = slot.Process;
        slot.Process = null;

        DisposeJobObject(slot);

        if (process is not null)
        {
            process.Dispose();
        }
    }

    private static void DisposeJobObject(AgentSlot slot)
    {
        var jobObject = slot.JobObject;
        slot.JobObject = null;
        slot.ProcessTreeOwned = false;
        jobObject?.Dispose();
    }

    private AgentSlot GetSlot(string agentId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(agentId);

        return _slots.TryGetValue(agentId, out var slot)
            ? slot
            : throw new KeyNotFoundException(
                $"Agent '{agentId}' is not registered with the supervisor.");
    }

    private static void ValidateDefinition(
        AgentProcessDefinition definition)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(
            definition.AgentId);
        ArgumentException.ThrowIfNullOrWhiteSpace(
            definition.ExecutablePath);

        if (definition.GracefulShutdownSeconds is < 0 or > 300)
        {
            throw new ArgumentOutOfRangeException(
                nameof(definition),
                "Graceful shutdown must be between 0 and 300 seconds.");
        }

        if (definition.MaxRestartAttempts is < 0 or > 100)
        {
            throw new ArgumentOutOfRangeException(
                nameof(definition),
                "Max restart attempts must be between 0 and 100.");
        }

        if (definition.RestartBackoffMilliseconds < 0 ||
            definition.RestartBackoffMaxMilliseconds <
                definition.RestartBackoffMilliseconds)
        {
            throw new ArgumentOutOfRangeException(
                nameof(definition),
                "Restart backoff values are invalid.");
        }

        if (definition.HealthRestartGraceMilliseconds is < 0 or > 600000)
        {
            throw new ArgumentOutOfRangeException(
                nameof(definition),
                "Health restart grace must be between 0 and 600000 milliseconds.");
        }
    }

    private void ThrowIfDisposed() =>
        ObjectDisposedException.ThrowIf(
            Volatile.Read(ref _disposed) != 0,
            this);

    private sealed class AgentSlot
    {
        public AgentSlot(AgentProcessDefinition definition)
        {
            Definition = definition;
        }

        public AgentProcessDefinition Definition { get; }

        public SemaphoreSlim Gate { get; } = new(1, 1);

        public DesiredProcessState DesiredState { get; set; } =
            DesiredProcessState.Stopped;

        public AgentProcessState State { get; set; } =
            AgentProcessState.Stopped;

        public Process? Process { get; set; }

        public DateTimeOffset? StartedAtUtc { get; set; }

        public int? LastExitCode { get; set; }

        public string? LastError { get; set; }

        public bool ProcessTreeOwned { get; set; }

        public WindowsJobObject? JobObject { get; set; }

        public long Generation { get; set; }

        public int RestartAttempts { get; set; }

        public DateTimeOffset? NextRestartAtUtc { get; set; }

        public AgentHealthState LastReportedHealth { get; set; } =
            AgentHealthState.Unknown;

        public bool HasReachedHealthyState { get; set; }
    }
}