using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using Zagent.Setup;

var passed = 0;
var failed = 0;
var devRoot =
    Environment.GetEnvironmentVariable("ZAGENT_DEV_ROOT") ??
    Path.GetTempPath();
// Fixture output can be isolated without moving the TestChild build lookup.
var fixtureRoot = Environment.GetEnvironmentVariable("ZAGENT_TEST_FIXTURE_ROOT") ?? devRoot;
var root = Path.Combine(
    fixtureRoot,
    "_validation",
    "phase9-setup-" +
    Guid.NewGuid().ToString("N"));

Directory.CreateDirectory(root);

try
{
    await RunAsync(
        "fresh install supports a pre-created exact target folder with spaces",
        async () =>
        {
            var source = CreatePayload(
                Path.Combine(root, "source v1"),
                "v1");

            var target =
                Path.Combine(root, "Install Folder Selected By User");

            Directory.CreateDirectory(target);

            var initializer = new RecordingInitializer();
            var engine = CreateEngine(initializer);

            var result = await engine.ExecuteAsync(
                new SetupRequest(
                    SetupMode.Install,
                    target,
                    source));

            True(result.Success, result.Message);
            True(
                File.Exists(
                    Path.Combine(
                        target,
                        "agents",
                        "files",
                        "engine",
                        "sample.txt")),
                "Program payload was not installed.");

            Equal(
                Path.GetFullPath(target),
                initializer.LastTarget);

            Equal(
                Path.Combine(
                    Path.GetFullPath(target),
                    "data"),
                initializer.LastData);

            Equal(
                Path.Combine(
                    Path.GetFullPath(target),
                    "workspace"),
                initializer.LastProfile);

            True(
                File.Exists(
                    Path.Combine(
                        target,
                        "payload-manifest.json")),
                "Installed payload manifest missing.");
        });

    await RunAsync(
        "verify validates every installed program file",
        async () =>
        {
            var source = CreatePayload(
                Path.Combine(root, "source verify"),
                "verify");

            var target =
                Path.Combine(root, "verify target");

            var engine =
                CreateEngine(
                    new RecordingInitializer());

            await engine.ExecuteAsync(
                new SetupRequest(
                    SetupMode.Install,
                    target,
                    source));

            var verify =
                await engine.ExecuteAsync(
                    new SetupRequest(
                        SetupMode.Verify,
                        target,
                        source));

            True(verify.Success, verify.Message);
            Equal(3, verify.FilesVerified);
        });

    await RunAsync(
        "repair restores a corrupted file without touching workspace data",
        async () =>
        {
            var source = CreatePayload(
                Path.Combine(root, "source repair"),
                "repair");

            var target =
                Path.Combine(root, "repair target");

            var engine =
                CreateEngine(
                    new RecordingInitializer());

            await engine.ExecuteAsync(
                new SetupRequest(
                    SetupMode.Install,
                    target,
                    source));

            var userFile =
                Path.Combine(
                    target,
                    "workspace",
                    "user.txt");

            Directory.CreateDirectory(
                Path.GetDirectoryName(userFile)!);

            await File.WriteAllTextAsync(
                userFile,
                "KEEP-ME");

            var programFile =
                Path.Combine(
                    target,
                    "agents",
                    "files",
                    "engine",
                    "sample.txt");

            await File.WriteAllTextAsync(
                programFile,
                "CORRUPT");

            var repair =
                await engine.ExecuteAsync(
                    new SetupRequest(
                        SetupMode.Repair,
                        target,
                        source));

            True(repair.Success, repair.Message);
            Equal(1, repair.FilesChanged);
            Equal(
                "payload-repair",
                await File.ReadAllTextAsync(programFile));
            Equal(
                "KEEP-ME",
                await File.ReadAllTextAsync(userFile));
        });

    await RunAsync(
        "failed upgrade rolls changed program files back",
        async () =>
        {
            var sourceV1 = CreatePayload(
                Path.Combine(root, "source rollback v1"),
                "one");
            var sourceV2 = CreatePayload(
                Path.Combine(root, "source rollback v2"),
                "two");

            var target =
                Path.Combine(root, "rollback target");

            var good =
                CreateEngine(
                    new RecordingInitializer());

            await good.ExecuteAsync(
                new SetupRequest(
                    SetupMode.Install,
                    target,
                    sourceV1));

            var before =
                await File.ReadAllTextAsync(
                    Path.Combine(
                        target,
                        "agents",
                        "files",
                        "engine",
                        "sample.txt"));

            var bad =
                CreateEngine(
                    new ThrowingInitializer());

            var threw = false;

            try
            {
                await bad.ExecuteAsync(
                    new SetupRequest(
                        SetupMode.Install,
                        target,
                        sourceV2));
            }
            catch (InvalidOperationException)
            {
                threw = true;
            }

            True(
                threw,
                "Upgrade failure was not surfaced.");

            Equal(
                before,
                await File.ReadAllTextAsync(
                    Path.Combine(
                        target,
                        "agents",
                        "files",
                        "engine",
                        "sample.txt")));
        });

    await RunAsync(
        "legacy installation without product-line metadata is rejected without changing data",
        async () =>
        {
            var source = CreatePayload(
                Path.Combine(root, "source in-place partial"),
                "new");

            var target =
                Path.Combine(root, "existing partial target");

            Directory.CreateDirectory(
                Path.Combine(target, "agents"));
            Directory.CreateDirectory(
                Path.Combine(target, "data"));

            await File.WriteAllTextAsync(
                Path.Combine(target, "Zagent.Manager.exe"),
                "old-manager");

            await File.WriteAllTextAsync(
                Path.Combine(target, "data", "user.json"),
                "KEEP-DATA");

            var engine =
                CreateEngine(
                    new RecordingInitializer());

            var rejected = false;
            try
            {
                await engine.ExecuteAsync(new SetupRequest(SetupMode.Install, target, source));
            }
            catch (InvalidOperationException ex) when (ex.Message.Contains("offline", StringComparison.OrdinalIgnoreCase))
            {
                rejected = true;
            }
            True(rejected, "Legacy state was silently imported into the v1 product line.");
            Equal("old-manager", await File.ReadAllTextAsync(Path.Combine(target, "Zagent.Manager.exe")));
            Equal(
                "KEEP-DATA",
                await File.ReadAllTextAsync(
                    Path.Combine(
                        target,
                        "data",
                        "user.json")));
            True(
                !File.Exists(
                    Path.Combine(
                        target,
                        "payload-manifest.json")),
                "Rejected migration wrote an installed manifest.");
        });

    await RunAsync(
        "in-place upgrade removes stale tracked program files and preserves persistent data",
        async () =>
        {
            var sourceV1 = CreatePayload(
                Path.Combine(root, "source stale v1"),
                "stale-one",
                includeLegacyFile: true);
            var sourceV2 = CreatePayload(
                Path.Combine(root, "source stale v2"),
                "stale-two");

            var target =
                Path.Combine(root, "stale upgrade target");

            var engine =
                CreateEngine(
                    new RecordingInitializer());

            await engine.ExecuteAsync(
                new SetupRequest(
                    SetupMode.Install,
                    target,
                    sourceV1));

            var staleFile =
                Path.Combine(
                    target,
                    "agents",
                    "files",
                    "engine",
                    "legacy-only.txt");

            True(
                File.Exists(staleFile),
                "Legacy test file was not installed.");

            Directory.CreateDirectory(
                Path.Combine(target, "workspace"));
            Directory.CreateDirectory(
                Path.Combine(target, "data"));

            await File.WriteAllTextAsync(
                Path.Combine(target, "workspace", "user.txt"),
                "KEEP-WORK");
            await File.WriteAllTextAsync(
                Path.Combine(target, "data", "user.txt"),
                "KEEP-DATA");

            var update = await engine.ExecuteAsync(
                new SetupRequest(
                    SetupMode.Install,
                    target,
                    sourceV2));

            True(update.Success, update.Message);
            False(
                File.Exists(staleFile),
                "Stale tracked program file remained after update.");
            Equal(
                "KEEP-WORK",
                await File.ReadAllTextAsync(
                    Path.Combine(
                        target,
                        "workspace",
                        "user.txt")));
            Equal(
                "KEEP-DATA",
                await File.ReadAllTextAsync(
                    Path.Combine(
                        target,
                        "data",
                        "user.txt")));
        });

    await RunAsync(
        "in-place update stops running process from target before replace",
        async () =>
        {
            var sourceV1 = CreatePayload(
                Path.Combine(root, "source process v1"),
                "proc-one");
            var sourceV2 = CreatePayload(
                Path.Combine(root, "source process v2"),
                "proc-two");

            var target =
                Path.Combine(root, "process update target");

            var engine =
                CreateEngine(
                    new RecordingInitializer());

            await engine.ExecuteAsync(
                new SetupRequest(
                    SetupMode.Install,
                    target,
                    sourceV1));

            var testChildSource =
                Path.Combine(
                    devRoot,
                    "tests",
                    "Zagent.TestChild",
                    "bin",
                    "Debug",
                    "net10.0");

            var testChildTarget =
                Path.Combine(
                    target,
                    "agents",
                    "test-child-runtime");

            Directory.CreateDirectory(testChildTarget);

            foreach (var file in Directory.GetFiles(testChildSource))
            {
                File.Copy(
                    file,
                    Path.Combine(
                        testChildTarget,
                        Path.GetFileName(file)),
                    overwrite: true);
            }

            var childExe =
                Path.Combine(
                    testChildTarget,
                    "Zagent.TestChild.exe");
            var pidFile =
                Path.Combine(
                    target,
                    "data",
                    "setup-process-test.pid");

            Directory.CreateDirectory(
                Path.GetDirectoryName(pidFile)!);

            using var process = Process.Start(
                new ProcessStartInfo
                {
                    FileName = childExe,
                    WorkingDirectory = testChildTarget,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    ArgumentList =
                    {
                        "--mode",
                        "hang",
                        "--pid-file",
                        pidFile
                    }
                }) ??
                throw new InvalidOperationException(
                    "Failed to start target-root test process.");

            try
            {
                var deadline =
                    DateTime.UtcNow +
                    TimeSpan.FromSeconds(5);

                while (!File.Exists(pidFile) &&
                       DateTime.UtcNow < deadline)
                {
                    await Task.Delay(25);
                }

                True(
                    File.Exists(pidFile),
                    "Target-root test process did not start.");

                var update =
                    await engine.ExecuteAsync(
                        new SetupRequest(
                            SetupMode.Install,
                            target,
                            sourceV2));

                True(update.Success, update.Message);

                var exited =
                    process.HasExited ||
                    process.WaitForExit(5000);

                True(
                    exited,
                    "In-place update did not stop the running target-root process.");

                Equal(
                    "fake-manager-proc-two",
                    await File.ReadAllTextAsync(
                        Path.Combine(
                            target,
                            "Zagent.Manager.exe")));
            }
            finally
            {
                if (!process.HasExited)
                {
                    process.Kill(
                        entireProcessTree: true);
                    process.WaitForExit(5000);
                }
            }
        });

    await RunAsync(
        "uninstall keep-data removes tracked program files but preserves data and workspace",
        async () =>
        {
            var source = CreatePayload(
                Path.Combine(root, "source keep"),
                "keep");

            var target =
                Path.Combine(root, "uninstall keep target");

            var engine =
                CreateEngine(
                    new RecordingInitializer());

            await engine.ExecuteAsync(
                new SetupRequest(
                    SetupMode.Install,
                    target,
                    source));

            Directory.CreateDirectory(
                Path.Combine(target, "data"));
            Directory.CreateDirectory(
                Path.Combine(target, "workspace"));

            await File.WriteAllTextAsync(
                Path.Combine(
                    target,
                    "data",
                    "user-data.txt"),
                "DATA");

            await File.WriteAllTextAsync(
                Path.Combine(
                    target,
                    "workspace",
                    "work.txt"),
                "WORK");

            var uninstall =
                await engine.ExecuteAsync(
                    new SetupRequest(
                        SetupMode.Uninstall,
                        target,
                        KeepData: true));

            True(uninstall.Success, uninstall.Message);
            False(
                File.Exists(
                    Path.Combine(
                        target,
                        "Zagent.Core.exe")),
                "Tracked program file remained.");

            Equal(
                "DATA",
                await File.ReadAllTextAsync(
                    Path.Combine(
                        target,
                        "data",
                        "user-data.txt")));

            Equal(
                "WORK",
                await File.ReadAllTextAsync(
                    Path.Combine(
                        target,
                        "workspace",
                        "work.txt")));
        });

    await RunAsync(
        "uninstall delete-data removes default persistent roots",
        async () =>
        {
            var source = CreatePayload(
                Path.Combine(root, "source delete"),
                "delete");

            var target =
                Path.Combine(root, "uninstall delete target");

            var engine =
                CreateEngine(
                    new RecordingInitializer());

            await engine.ExecuteAsync(
                new SetupRequest(
                    SetupMode.Install,
                    target,
                    source));

            Directory.CreateDirectory(
                Path.Combine(target, "data"));
            Directory.CreateDirectory(
                Path.Combine(target, "workspace"));

            await File.WriteAllTextAsync(
                Path.Combine(
                    target,
                    "data",
                    "user-data.txt"),
                "DATA");

            var uninstall =
                await engine.ExecuteAsync(
                    new SetupRequest(
                        SetupMode.Uninstall,
                        target,
                        KeepData: false));

            True(uninstall.Success, uninstall.Message);
            False(
                Directory.Exists(
                    Path.Combine(target, "data")),
                "Data root remained after delete-data.");
            False(
                Directory.Exists(
                    Path.Combine(target, "workspace")),
                "Workspace remained after delete-data.");
        });

    await RunAsync(
        "payload traversal path is rejected before installation",
        async () =>
        {
            var source =
                Path.Combine(
                    root,
                    "source traversal");

            Directory.CreateDirectory(source);

            var manifest = new PayloadManifest(
                "1.0",
                "Zagent",
                "test",
                "win-x64",
                "EXACT_USER_SELECTED_FOLDER",
                "<InstallRoot>\\data",
                "<InstallRoot>\\workspace",
                1,
                1,
                DateTimeOffset.UtcNow.ToString("o"),
                Runtime(),
                [
                    new PayloadFileEntry(
                        "../escape.txt",
                        1,
                        new string('0', 64))
                ]);

            await File.WriteAllTextAsync(
                Path.Combine(
                    source,
                    "payload-manifest.json"),
                JsonSerializer.Serialize(
                    manifest,
                    Json()));

            var engine =
                CreateEngine(
                    new RecordingInitializer());

            var threw = false;

            try
            {
                await engine.ExecuteAsync(
                    new SetupRequest(
                        SetupMode.Install,
                        Path.Combine(root, "traversal target"),
                        source));
            }
            catch (InvalidDataException)
            {
                threw = true;
            }

            True(
                threw,
                "Traversal payload was accepted.");
        });
}
finally
{
    try
    {
        Directory.Delete(
            root,
            recursive: true);
    }
    catch
    {
    }
}

Console.WriteLine(
    failed == 0
        ? $"SETUP_TEST_PASS passed={passed} failed={failed}"
        : $"SETUP_TEST_FAIL passed={passed} failed={failed}");

return failed == 0 ? 0 : 1;

string CreatePayload(
    string source,
    string value,
    bool includeLegacyFile = false)
{
    Directory.CreateDirectory(source);

    var files = new Dictionary<string, string>
    {
        ["Zagent.Core.exe"] =
            "fake-core-" + value,
        ["Zagent.Manager.exe"] =
            "fake-manager-" + value,
        ["agents/files/engine/sample.txt"] =
            "payload-" + value
    };

    if (includeLegacyFile)
    {
        files["agents/files/engine/legacy-only.txt"] =
            "legacy-" + value;
    }

    var entries =
        new List<PayloadFileEntry>();

    foreach (var pair in files)
    {
        var path =
            Path.Combine(
                source,
                pair.Key.Replace(
                    '/',
                    Path.DirectorySeparatorChar));

        Directory.CreateDirectory(
            Path.GetDirectoryName(path)!);

        File.WriteAllText(
            path,
            pair.Value);

        var bytes =
            File.ReadAllBytes(path);

        entries.Add(
            new PayloadFileEntry(
                pair.Key,
                bytes.LongLength,
                Convert.ToHexString(
                        SHA256.HashData(bytes))
                    .ToLowerInvariant()));
    }

    var manifest =
        new PayloadManifest(
            "1.0",
            "Zagent",
            "test-" + value,
            "win-x64",
            "EXACT_USER_SELECTED_FOLDER",
            "<InstallRoot>\\data",
            "<InstallRoot>\\workspace",
            entries.Count,
            entries.Sum(x => x.Size),
            DateTimeOffset.UtcNow.ToString("o"),
            Runtime(),
            entries) { ProductLine = "zagent-mcp-v1", SuiteVersion = "1.0.0" };

    File.WriteAllText(
        Path.Combine(
            source,
            "payload-manifest.json"),
        JsonSerializer.Serialize(
            manifest,
            Json()));

    return source;
}

PayloadRuntimeInfo Runtime() =>
    new(
        "self-contained",
        "embedded",
        "embedded",
        "embedded",
        "portable",
        "1.63.0",
        ["chromium", "firefox", "webkit"]);

JsonSerializerOptions Json() =>
    new()
    {
        WriteIndented = true
    };

SetupEngine CreateEngine(
    IInstallInitializer initializer) =>
    new(
        initializer,
        new NoOpWindowsInstallationIntegration());

async Task RunAsync(
    string name,
    Func<Task> test)
{
    try
    {
        await test();
        passed++;
        Console.WriteLine(
            "PASS " + name);
    }
    catch (Exception ex)
    {
        failed++;
        Console.WriteLine(
            $"FAIL {name}: {ex}");
    }
}

static void True(
    bool condition,
    string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
}

static void False(
    bool condition,
    string message) =>
    True(!condition, message);

static void Equal<T>(
    T expected,
    T actual)
{
    if (!EqualityComparer<T>.Default.Equals(
            expected,
            actual))
    {
        throw new InvalidOperationException(
            $"Expected '{expected}', actual '{actual}'.");
    }
}

sealed class RecordingInitializer : IInstallInitializer
{
    public string LastTarget { get; private set; } = "";
    public string LastData { get; private set; } = "";
    public string LastProfile { get; private set; } = "";

    public Task InitializeAsync(
        string targetRoot,
        string dataRoot,
        string filesProfile,
        string productVersion,
        CancellationToken cancellationToken)
    {
        LastTarget = Path.GetFullPath(targetRoot);
        LastData = Path.GetFullPath(dataRoot);
        LastProfile = Path.GetFullPath(filesProfile);

        Directory.CreateDirectory(dataRoot);
        Directory.CreateDirectory(filesProfile);

        return Task.CompletedTask;
    }
}

sealed class NoOpWindowsInstallationIntegration : IWindowsInstallationIntegration
{
    public void Register(
        string targetRoot,
        string productVersion)
    {
    }

    public void Unregister(
        string targetRoot)
    {
    }
}

sealed class ThrowingInitializer : IInstallInitializer
{
    public Task InitializeAsync(
        string targetRoot,
        string dataRoot,
        string filesProfile,
        string productVersion,
        CancellationToken cancellationToken) =>
        throw new InvalidOperationException(
            "Synthetic initialize failure.");
}