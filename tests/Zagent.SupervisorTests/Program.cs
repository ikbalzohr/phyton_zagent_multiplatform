using System.Diagnostics;
using Zagent.Core.Supervision;
using Zagent.Shared.Contracts;

var passed = 0;
var failed = 0;
var testLeaseName =
    @"Local\Zagent.v2.Supervisor.Tests." +
    Environment.ProcessId;
var testRoot = Path.Combine(
    Path.GetTempPath(),
    "zagent-supervisor-tests",
    Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(testRoot);

try
{
    await RunAsync("start stop owns one real process", async () =>
    {
        await using var supervisor = new NativeAgentSupervisor(instanceLeaseName: testLeaseName);
        var pidFile = Path.Combine(testRoot, "start-stop.pid");
        supervisor.Register(CreateHangDefinition("test.start-stop", pidFile));

        var start = await supervisor.StartAsync("test.start-stop");
        True(start.Success, start.Message ?? "Start failed.");

        var pid = await WaitForPidAsync(pidFile);
        True(ProcessExists(pid), "Child process is not running.");

        True(
            supervisor.TryGetSnapshot("test.start-stop", out var running) &&
            running is not null,
            "Running snapshot missing.");
        Equal(AgentProcessState.Running, running!.State);
        Equal(pid, running.ProcessId);
        True(
            running.ProcessTreeOwned,
            "Windows Job Object ownership was not established.");

        var stop = await supervisor.StopAsync("test.start-stop");
        True(stop.Success, stop.Message ?? "Stop failed.");
        await WaitUntilAsync(() => !ProcessExists(pid), TimeSpan.FromSeconds(5));

        True(
            supervisor.TryGetSnapshot("test.start-stop", out var stopped) &&
            stopped is not null,
            "Stopped snapshot missing.");
        Equal(AgentProcessState.Stopped, stopped!.State);
        Equal(DesiredProcessState.Stopped, stopped.DesiredState);
        Equal<int?>(null, stopped.ProcessId);
    });

    await RunAsync("parallel start produces one pid", async () =>
    {
        await using var supervisor = new NativeAgentSupervisor(instanceLeaseName: testLeaseName);
        var pidFile = Path.Combine(testRoot, "parallel.pid");
        supervisor.Register(CreateHangDefinition("test.parallel", pidFile));

        var starts = await Task.WhenAll(
            Enumerable.Range(0, 8)
                .Select(_ => supervisor.StartAsync("test.parallel")));

        True(starts.All(result => result.Success), "A parallel start failed.");

        var pid = await WaitForPidAsync(pidFile);
        var snapshot = supervisor.Snapshot()
            .Single(item => item.AgentId == "test.parallel");

        Equal(pid, snapshot.ProcessId);
        Equal(1, supervisor.Snapshot().Count);

        await supervisor.StopAsync("test.parallel");
        await WaitUntilAsync(() => !ProcessExists(pid), TimeSpan.FromSeconds(5));
    });

    await RunAsync("unexpected exit becomes faulted", async () =>
    {
        await using var supervisor = new NativeAgentSupervisor(instanceLeaseName: testLeaseName);
        supervisor.Register(CreateExitDefinition("test.crash", exitCode: 7));

        var start = await supervisor.StartAsync("test.crash");
        True(start.Success, start.Message ?? "Start failed.");

        await WaitUntilAsync(
            () =>
            {
                return supervisor.TryGetSnapshot("test.crash", out var snapshot) &&
                    snapshot is not null &&
                    snapshot.State == AgentProcessState.Faulted;
            },
            TimeSpan.FromSeconds(5));

        supervisor.TryGetSnapshot("test.crash", out var faulted);
        Equal(AgentProcessState.Faulted, faulted!.State);
        Equal(DesiredProcessState.Running, faulted.DesiredState);
        Equal(7, faulted.LastExitCode);
    });


    await RunAsync("job object kills descendant after parent crash", async () =>
    {
        await using var supervisor = new NativeAgentSupervisor(instanceLeaseName: testLeaseName);
        var childPidFile = Path.Combine(
            testRoot,
            "descendant-after-crash.pid");

        supervisor.Register(
            CreateDefinition(
                "test.job-crash",
                new[]
                {
                    "--mode", "spawn-child-exit",
                    "--child-pid-file", childPidFile,
                    "--parent-delay-ms", "300",
                    "--exit-code", "9"
                }));

        var start = await supervisor.StartAsync("test.job-crash");
        True(start.Success, start.Message ?? "Start failed.");

        True(
            supervisor.TryGetSnapshot("test.job-crash", out var running) &&
            running is not null &&
            running.ProcessTreeOwned,
            "Job Object ownership was not established.");

        var childPid = await WaitForPidAsync(childPidFile);
        True(ProcessExists(childPid), "Descendant never started.");

        await WaitUntilAsync(
            () =>
            {
                return supervisor.TryGetSnapshot("test.job-crash", out var snapshot) &&
                    snapshot is not null &&
                    snapshot.State == AgentProcessState.Faulted;
            },
            TimeSpan.FromSeconds(5));

        await WaitUntilAsync(
            () => !ProcessExists(childPid),
            TimeSpan.FromSeconds(5));

        False(
            ProcessExists(childPid),
            "Descendant survived parent crash and became orphaned.");
    });



    await RunAsync("explicit restart replaces process pid", async () =>
    {
        await using var supervisor = new NativeAgentSupervisor(instanceLeaseName: testLeaseName);
        var pidFile = Path.Combine(testRoot, "restart.pid");
        supervisor.Register(CreateHangDefinition("test.restart", pidFile));

        True(
            (await supervisor.StartAsync("test.restart")).Success,
            "Initial start failed.");

        var firstPid = await WaitForPidAsync(pidFile);
        var restart = await supervisor.RestartAsync("test.restart");
        True(restart.Success, restart.Message ?? "Restart failed.");

        await WaitUntilAsync(
            () =>
            {
                return supervisor.TryGetSnapshot("test.restart", out var snapshot) &&
                    snapshot is not null &&
                    snapshot.ProcessId is int pid &&
                    pid != firstPid;
            },
            TimeSpan.FromSeconds(5));

        supervisor.TryGetSnapshot("test.restart", out var restarted);
        True(restarted?.ProcessId is not null, "Restarted PID missing.");
        False(
            ProcessExists(firstPid),
            "Original PID survived explicit restart.");

        await supervisor.StopAsync("test.restart");
    });

    await RunAsync("auto restart is bounded with exponential backoff", async () =>
    {
        await using var supervisor = new NativeAgentSupervisor(instanceLeaseName: testLeaseName);
        var definition = CreateExitDefinition(
            "test.auto-restart",
            exitCode: 23) with
        {
            AutoRestart = true,
            MaxRestartAttempts = 2,
            RestartBackoffMilliseconds = 50,
            RestartBackoffMaxMilliseconds = 100
        };

        supervisor.Register(definition);
        True(
            (await supervisor.StartAsync("test.auto-restart")).Success,
            "Initial auto-restart process failed to start.");

        await WaitUntilAsync(
            () =>
            {
                return supervisor.TryGetSnapshot(
                        "test.auto-restart",
                        out var snapshot) &&
                    snapshot is not null &&
                    snapshot.State == AgentProcessState.Faulted &&
                    snapshot.RestartAttempts == 2 &&
                    snapshot.NextRestartAtUtc is null;
            },
            TimeSpan.FromSeconds(5));

        supervisor.TryGetSnapshot(
            "test.auto-restart",
            out var finalSnapshot);

        Equal(2, finalSnapshot!.RestartAttempts);
        Equal(23, finalSnapshot.LastExitCode);
        True(
            finalSnapshot.LastError?.Contains(
                "Auto-restart limit reached",
                StringComparison.Ordinal) == true,
            "Crash-loop limit message missing.");
    });

    await RunAsync("only one supervisor can own lifecycle lease", async () =>
    {
        await using var first = new NativeAgentSupervisor(instanceLeaseName: testLeaseName);

        var rejected = false;
        try
        {
            await using var second = new NativeAgentSupervisor(instanceLeaseName: testLeaseName);
        }
        catch (InvalidOperationException)
        {
            rejected = true;
        }

        True(
            rejected,
            "Second supervisor acquired the lifecycle lease.");
    });




    await RunAsync("failed health restarts only desired-running agent", async () =>
    {
        await using var supervisor = new NativeAgentSupervisor(instanceLeaseName: testLeaseName);
        var pidFile = Path.Combine(testRoot, "health-restart.pid");
        supervisor.Register(
            CreateHangDefinition("test.health-restart", pidFile));

        True(
            (await supervisor.StartAsync("test.health-restart")).Success,
            "Health test initial start failed.");

        var firstPid = await WaitForPidAsync(pidFile);

        var health = await supervisor.ReportHealthAsync(
            "test.health-restart",
            AgentHealthState.Failed);
        True(health.Success, health.Message ?? "Health restart failed.");

        await WaitUntilAsync(
            () =>
            {
                return supervisor.TryGetSnapshot(
                        "test.health-restart",
                        out var snapshot) &&
                    snapshot is not null &&
                    snapshot.ProcessId is int pid &&
                    pid != firstPid &&
                    snapshot.LastReportedHealth == AgentHealthState.Failed;
            },
            TimeSpan.FromSeconds(5));

        False(
            ProcessExists(firstPid),
            "Health-triggered restart left the old PID running.");

        await supervisor.StopAsync("test.health-restart");

        var stoppedHealth = await supervisor.ReportHealthAsync(
            "test.health-restart",
            AgentHealthState.Offline);
        True(
            stoppedHealth.Success,
            stoppedHealth.Message ?? "Stopped health report failed.");

        supervisor.TryGetSnapshot(
            "test.health-restart",
            out var stopped);
        Equal(DesiredProcessState.Stopped, stopped!.DesiredState);
        Equal<int?>(null, stopped.ProcessId);
    });

    await RunAsync("startup health grace prevents premature restart", async () =>
    {
        await using var supervisor = new NativeAgentSupervisor(instanceLeaseName: testLeaseName);
        var pidFile = Path.Combine(testRoot, "health-grace.pid");
        var definition = CreateHangDefinition(
            "test.health-grace",
            pidFile) with
        {
            HealthRestartGraceMilliseconds = 5000
        };

        supervisor.Register(definition);

        True(
            (await supervisor.StartAsync("test.health-grace")).Success,
            "Grace test initial start failed.");

        var firstPid = await WaitForPidAsync(pidFile);

        var startupFailure = await supervisor.ReportHealthAsync(
            "test.health-grace",
            AgentHealthState.Offline);

        True(
            startupFailure.Success,
            startupFailure.Message ?? "Startup grace health report failed.");

        await Task.Delay(200);

        supervisor.TryGetSnapshot(
            "test.health-grace",
            out var duringGrace);

        Equal(firstPid, duringGrace!.ProcessId);
        True(
            ProcessExists(firstPid),
            "Startup health grace restarted the process prematurely.");

        var ready = await supervisor.ReportHealthAsync(
            "test.health-grace",
            AgentHealthState.Ready);

        True(
            ready.Success,
            ready.Message ?? "Ready health report failed.");

        var failedAfterReady = await supervisor.ReportHealthAsync(
            "test.health-grace",
            AgentHealthState.Failed);

        True(
            failedAfterReady.Success,
            failedAfterReady.Message ?? "Post-ready health restart failed.");

        await WaitUntilAsync(
            () =>
            {
                return supervisor.TryGetSnapshot(
                        "test.health-grace",
                        out var snapshot) &&
                    snapshot is not null &&
                    snapshot.ProcessId is int pid &&
                    pid != firstPid;
            },
            TimeSpan.FromSeconds(5));

        False(
            ProcessExists(firstPid),
            "Post-ready failure did not replace the unhealthy PID.");

        await supervisor.StopAsync("test.health-grace");
    });


    await RunAsync("ten lifecycle cycles leave no orphan pid", async () =>
    {
        await using var supervisor = new NativeAgentSupervisor(instanceLeaseName: testLeaseName);

        for (var index = 0; index < 10; index++)
        {
            var agentId = $"test.cycle-{index}";
            var pidFile = Path.Combine(
                testRoot,
                $"cycle-{index}.pid");

            supervisor.Register(
                CreateHangDefinition(agentId, pidFile));

            var start = await supervisor.StartAsync(agentId);
            True(start.Success, $"Cycle {index} start failed.");

            var pid = await WaitForPidAsync(pidFile);
            True(ProcessExists(pid), $"Cycle {index} PID was not alive.");

            var stop = await supervisor.StopAsync(agentId);
            True(stop.Success, $"Cycle {index} stop failed.");

            await WaitUntilAsync(
                () => !ProcessExists(pid),
                TimeSpan.FromSeconds(5));

            False(
                ProcessExists(pid),
                $"Cycle {index} left an orphan PID.");
        }
    });


    await RunAsync("stop all blocks future starts", async () =>
    {
        await using var supervisor = new NativeAgentSupervisor(instanceLeaseName: testLeaseName);
        var pidFileA = Path.Combine(testRoot, "all-a.pid");
        var pidFileB = Path.Combine(testRoot, "all-b.pid");
        supervisor.Register(CreateHangDefinition("test.all-a", pidFileA));
        supervisor.Register(CreateHangDefinition("test.all-b", pidFileB));

        True((await supervisor.StartAsync("test.all-a")).Success, "Start A failed.");
        True((await supervisor.StartAsync("test.all-b")).Success, "Start B failed.");

        var pidA = await WaitForPidAsync(pidFileA);
        var pidB = await WaitForPidAsync(pidFileB);

        var shutdown = await supervisor.StopAllAsync();
        True(shutdown.Success, "StopAll reported failures.");

        await WaitUntilAsync(
            () => !ProcessExists(pidA) && !ProcessExists(pidB),
            TimeSpan.FromSeconds(5));

        var blocked = await supervisor.StartAsync("test.all-a");
        False(blocked.Success, "Start succeeded after StopAll shutdown gate.");
    });
}
finally
{
    try
    {
        Directory.Delete(testRoot, recursive: true);
    }
    catch
    {
    }
}

Console.WriteLine(
    failed == 0
        ? $"SUPERVISOR_TEST_PASS passed={passed} failed={failed}"
        : $"SUPERVISOR_TEST_FAIL passed={passed} failed={failed}");

return failed == 0 ? 0 : 1;

AgentProcessDefinition CreateHangDefinition(
    string agentId,
    string pidFile) =>
    CreateDefinition(
        agentId,
        new[] { "--mode", "hang", "--pid-file", pidFile });

AgentProcessDefinition CreateExitDefinition(
    string agentId,
    int exitCode) =>
    CreateDefinition(
        agentId,
        new[]
        {
            "--mode", "exit",
            "--delay-ms", "150",
            "--exit-code", exitCode.ToString()
        });

AgentProcessDefinition CreateDefinition(
    string agentId,
    IReadOnlyList<string> childArguments)
{
    var dotnetRoot = Environment.GetEnvironmentVariable("DOTNET_ROOT");
    if (string.IsNullOrWhiteSpace(dotnetRoot))
    {
        throw new InvalidOperationException("DOTNET_ROOT is not set.");
    }

    var dotnet = Path.Combine(dotnetRoot, "dotnet.exe");
    var configuration = new DirectoryInfo(
        AppContext.BaseDirectory).Parent?.Name
        ?? throw new InvalidOperationException(
            "Unable to determine test build configuration.");

    var testsRoot = new DirectoryInfo(AppContext.BaseDirectory)
        .Parent?.Parent?.Parent?.Parent?.FullName
        ?? throw new InvalidOperationException(
            "Unable to determine tests root.");

    var childDll = Path.Combine(
        testsRoot,
        "Zagent.TestChild",
        "bin",
        configuration,
        "net10.0",
        "Zagent.TestChild.dll");

    if (!File.Exists(childDll))
    {
        throw new FileNotFoundException(
            "Test child was not built.",
            childDll);
    }

    var arguments = new List<string> { childDll };
    arguments.AddRange(childArguments);

    return new AgentProcessDefinition(
        AgentId: agentId,
        ExecutablePath: dotnet,
        Arguments: arguments,
        WorkingDirectory: Path.GetDirectoryName(childDll),
        GracefulShutdownSeconds: 0);
}

async Task<int> WaitForPidAsync(string pidFile)
{
    var deadline = DateTime.UtcNow + TimeSpan.FromSeconds(5);

    while (DateTime.UtcNow < deadline)
    {
        if (File.Exists(pidFile))
        {
            try
            {
                var text = await File.ReadAllTextAsync(pidFile);
                if (int.TryParse(text, out var pid))
                {
                    return pid;
                }
            }
            catch (IOException)
            {
            }
        }

        await Task.Delay(25);
    }

    throw new TimeoutException(
        $"PID file '{pidFile}' was not readable within 5 seconds.");
}

static bool ProcessExists(int pid)
{
    try
    {
        using var process = Process.GetProcessById(pid);
        return !process.HasExited;
    }
    catch (ArgumentException)
    {
        return false;
    }
}

static async Task WaitUntilAsync(
    Func<bool> predicate,
    TimeSpan timeout)
{
    var deadline = DateTime.UtcNow + timeout;
    while (DateTime.UtcNow < deadline)
    {
        if (predicate())
        {
            return;
        }

        await Task.Delay(25);
    }

    throw new TimeoutException(
        $"Condition was not satisfied within {timeout}.");
}

async Task RunAsync(string name, Func<Task> test)
{
    try
    {
        await test();
        passed++;
        Console.WriteLine($"PASS {name}");
    }
    catch (Exception ex)
    {
        failed++;
        Console.WriteLine($"FAIL {name}: {ex}");
    }
}

static void True(bool condition, string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
}

static void False(bool condition, string message) =>
    True(!condition, message);

static void Equal<T>(T expected, T actual)
{
    if (!EqualityComparer<T>.Default.Equals(expected, actual))
    {
        throw new InvalidOperationException(
            $"Expected '{expected}', actual '{actual}'.");
    }
}