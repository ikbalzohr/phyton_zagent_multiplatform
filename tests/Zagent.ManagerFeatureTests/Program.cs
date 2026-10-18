using System.Text.Json;
using Zagent.Core.Agents.Tunnel;
using Zagent.Core.Identity;
using Zagent.Core.Manager;
using Zagent.Core.Registry;
using Zagent.Core.Supervision;
using Zagent.Shared.Contracts;
using Zagent.Shared.Installation;
using Zagent.Shared.Manager;

var passed = 0;
var failed = 0;
var root = Path.Combine(
    Path.GetTempPath(),
    "ZagentManagerFeatures",
    Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);

try
{
    await RunAsync(
        "Tunnel credentials are DPAPI protected and masked",
        async () =>
        {
            var path = Path.Combine(
                root,
                "credentials",
                "transport.credentials.json");
            var store = new TunnelCredentialStore(path);

            await store.SaveAsync(
                new TunnelCredentials(
                    "tunnel-test-id",
                    "api-secret-123456"));

            var loaded = await store.LoadAsync();
            Equal("tunnel-test-id", loaded?.TunnelId);
            Equal("api-secret-123456", loaded?.ApiKey);

            var disk = await File.ReadAllTextAsync(path);
            False(
                disk.Contains(
                    "api-secret-123456",
                    StringComparison.Ordinal),
                "API key leaked plaintext to disk.");
            False(
                disk.Contains(
                    "tunnel-test-id",
                    StringComparison.Ordinal),
                "Tunnel credential payload leaked plaintext to disk.");

            var snapshot = await store.SnapshotAsync();
            True(snapshot.ApiKeyConfigured, "API key should be configured.");
            True(
                snapshot.ApiKeyMasked.EndsWith(
                    "3456",
                    StringComparison.Ordinal),
                "Masked key should expose only suffix.");
        });

    await RunAsync(
        "Development Agent store enforces gateway range",
        async () =>
        {
            var path = Path.Combine(
                root,
                "development",
                "additional_services.json");
            var store = new DevelopmentAgentStore(path);

            var row = await store.AddAsync(
                new ManagerDevelopmentAgentRequest(
                    "Dev Search",
                    "devsearch",
                    "http://127.0.0.3:18955/mcp"));

            Equal("dev_devsearch", row.Id);
            Equal(1, (await store.SnapshotAsync()).Count);

            var rejected = false;
            try
            {
                await store.AddAsync(
                    new ManagerDevelopmentAgentRequest(
                        "Bad Port",
                        "badport",
                        "http://127.0.0.3:18888/mcp"));
            }
            catch (ArgumentException)
            {
                rejected = true;
            }

            True(rejected, "Non-development port was not rejected.");
        });

    await RunAsync(
        "Tunnel prepare preserves additional development services",
        async () =>
        {
            var config = Path.Combine(
                root,
                "preserve",
                "config");
            var runtime = Path.Combine(
                root,
                "preserve",
                "runtime");
            var store = new DevelopmentAgentStore(
                Path.Combine(
                    config,
                    "additional_services.json"));

            await store.AddAsync(
                new ManagerDevelopmentAgentRequest(
                    "Dev MCP",
                    "devmcp",
                    "http://127.0.0.3:18960/mcp"));

            var writer = new TunnelConfigurationWriter();
            await writer.WriteAsync(
                new TunnelIntegrationOptions(
                    PythonExecutable: "python.exe",
                    EngineRoot: root,
                    ConfigRoot: config,
                    RuntimeRoot: runtime,
                    ChatLogPath: Path.Combine(runtime, "chat.jsonl"),
                    BindHost: "127.0.0.3",
                    RouterPort: 18810),
                [
                    new TunnelServiceDefinition(
                        "zagent_files",
                        "Zagent Files",
                        "files",
                        "http://127.0.0.3:18820/mcp")
                ]);

            var rows = await store.SnapshotAsync();
            Equal(1, rows.Count);
            Equal("dev_devmcp", rows[0].Id);
        });

    await RunAsync(
        "Manager protocol add/remove Development Agent restarts Tunnel",
        async () =>
        {
            var registry = new CapabilityRegistry();
            await using var supervisor =
                new NativeAgentSupervisor(
                    acquireInstanceLease: false);

            var calls = new List<string>();
            var controllers =
                new ManagerAgentControllerRegistry();

            controllers.Register(
                new ManagerAgentController(
                    "system.tunnel",
                    "system.tunnel.router",
                    _ => Task.FromResult(
                        new LifecycleOperationResult(
                            true,
                            "system.tunnel",
                            "start",
                            "started")),
                    _ => Task.FromResult(
                        new LifecycleOperationResult(
                            true,
                            "system.tunnel",
                            "stop",
                            "stopped")),
                    _ =>
                    {
                        calls.Add("restart");
                        return Task.FromResult(
                            new LifecycleOperationResult(
                                true,
                                "system.tunnel",
                                "restart",
                                "restarted"));
                    },
                    _ => Task.FromResult(
                        new ManagerOperationResult(
                            true,
                            "refresh",
                            "system.tunnel",
                            "ready"))));

            var credentialStore =
                new TunnelCredentialStore(
                    Path.Combine(
                        root,
                        "protocol",
                        "credentials.json"));
            var devStore =
                new DevelopmentAgentStore(
                    Path.Combine(
                        root,
                        "protocol",
                        "additional_services.json"));

            var service =
                new ManagerControlService(
                    registry,
                    supervisor,
                    controllers,
                    tunnelCredentials: credentialStore,
                    developmentAgents: devStore);

            var save = await CallAsync<ManagerTunnelSettingsSnapshot>(
                service,
                "settings.tunnel.save",
                new ManagerTunnelSettingsUpdateRequest(
                    "tid-001",
                    "key-001-secret"));

            Equal("tid-001", save.TunnelId);
            True(save.ApiKeyConfigured, "Tunnel API key not configured.");

            var added = await CallAsync<ManagerOperationResult>(
                service,
                "development.add",
                new ManagerDevelopmentAgentRequest(
                    "Dev Agent",
                    "devagent",
                    "http://127.0.0.3:18977/mcp"));

            True(added.Success, added.Message);
            Equal(1, calls.Count);

            var list = await CallAsync<
                IReadOnlyList<ManagerDevelopmentAgentRow>>(
                service,
                "development.snapshot");

            Equal(1, list.Count);

            var removed = await CallAsync<ManagerOperationResult>(
                service,
                "development.remove",
                new ManagerDevelopmentAgentRemoveRequest(
                    list[0].Id));

            True(removed.Success, removed.Message);
            Equal(2, calls.Count);
            Equal(
                0,
                (await CallAsync<
                    IReadOnlyList<ManagerDevelopmentAgentRow>>(
                    service,
                    "development.snapshot")).Count);
        });
    await RunAsync(
        "Machine Identity persists UUID and keeps secret protected",
        async () =>
        {
            var path = Path.Combine(
                root,
                "identity",
                MachineIdentityStore.FileName);
            var store = new MachineIdentityStore(path);

            var first = await store.EnsureAsync();
            var second = await new MachineIdentityStore(path)
                .EnsureAsync();

            True(
                Guid.TryParse(first.DeviceId, out _),
                "device_id is not a UUID.");
            Equal(first.DeviceId, second.DeviceId);
            Equal(first.BindingFingerprint, second.BindingFingerprint);
            Equal("verified", second.BindingState);

            var bindingA =
                await store.CreateTunnelBindingAsync(
                    "tunnel-a");
            var bindingA2 =
                await new MachineIdentityStore(path)
                    .CreateTunnelBindingAsync(
                        "tunnel-a");
            var bindingB =
                await store.CreateTunnelBindingAsync(
                    "tunnel-b");

            Equal(bindingA, bindingA2);
            True(
                !string.Equals(
                    bindingA,
                    bindingB,
                    StringComparison.Ordinal),
                "Tunnel binding must change when tunnel_id changes.");

            var disk = await File.ReadAllTextAsync(path);
            False(
                disk.Contains(
                    first.BindingFingerprint + first.DeviceId,
                    StringComparison.Ordinal),
                "Unexpected concatenated identity material found.");
            True(
                disk.Contains(
                    "\"protected_secret\"",
                    StringComparison.Ordinal),
                "Protected machine secret missing.");
            False(
                disk.Contains(
                    "\"secret\":",
                    StringComparison.Ordinal),
                "Plaintext secret field found.");
        });

    await RunAsync(
        "Machine Identity v2 alias, migration, proof and required-target contracts",
        async () =>
        {
            var path = Path.Combine(
                root,
                "identity-v2",
                MachineIdentityStore.FileName);
            var store = new MachineIdentityStore(path);
            var initial = await store.EnsureAsync();

            Equal(
                MachineIdentityStore.CurrentSchemaVersion,
                initial.SchemaVersion);
            True(
                Guid.TryParse(initial.InstallationId, out _),
                "installation_id is not a UUID.");

            var bindingBefore =
                await store.CreateTunnelBindingAsync(
                    "tunnel-proof");

            var renamed =
                await store.RenameAliasAsync(
                    "Laptop Test Identity");
            Equal(
                initial.DeviceId,
                renamed.DeviceId);
            Equal(
                "Laptop Test Identity",
                renamed.DeviceAlias);
            Equal(
                bindingBefore,
                await store.CreateTunnelBindingAsync(
                    "tunnel-proof"));

            const string nonce =
                "0123456789abcdef0123456789abcdef";
            var proof =
                await store.CreateChallengeProofAsync(
                    "tunnel-proof",
                    nonce);
            True(
                await store.VerifyChallengeProofAsync(
                    "tunnel-proof",
                    nonce,
                    proof),
                "Valid HMAC challenge proof was rejected.");
            False(
                await store.VerifyChallengeProofAsync(
                    "tunnel-proof",
                    nonce,
                    new string('0', proof.Length)),
                "Invalid HMAC challenge proof was accepted.");

            var missingTargetRejected = false;
            try
            {
                await store.ValidateTargetRequiredAsync(
                    null);
            }
            catch (IdentityContractException ex)
            {
                missingTargetRejected =
                    ex.Code ==
                    IdentityErrorCodes
                        .SessionIdentityRequired;
            }
            True(
                missingTargetRejected,
                "Required target contract did not fail closed.");

            using var current = JsonDocument.Parse(
                await File.ReadAllTextAsync(path));
            var legacy = new Dictionary<string, object?>
            {
                ["schema_version"] = "1.0",
                ["device_id"] =
                    current.RootElement
                        .GetProperty("device_id")
                        .GetString(),
                ["device_name"] =
                    current.RootElement
                        .GetProperty("device_name")
                        .GetString(),
                ["created_at_utc"] =
                    current.RootElement
                        .GetProperty("created_at_utc")
                        .GetDateTimeOffset(),
                ["binding_fingerprint"] =
                    current.RootElement
                        .GetProperty("binding_fingerprint")
                        .GetString(),
                ["protection"] =
                    current.RootElement
                        .GetProperty("protection")
                        .GetString(),
                ["protected_secret"] =
                    current.RootElement
                        .GetProperty("protected_secret")
                        .GetString()
            };
            await File.WriteAllTextAsync(
                path,
                JsonSerializer.Serialize(
                    legacy,
                    new JsonSerializerOptions
                    {
                        WriteIndented = true
                    }));

            var migrated =
                await new MachineIdentityStore(path)
                    .EnsureAsync();
            Equal(initial.DeviceId, migrated.DeviceId);
            Equal(
                MachineIdentityStore.CurrentSchemaVersion,
                migrated.SchemaVersion);
            True(
                Guid.TryParse(
                    migrated.InstallationId,
                    out _),
                "Legacy identity migration did not add installation_id.");
        });

    await RunAsync(
        "Machine Identity rejects wrong target and accepts matching target",
        async () =>
        {
            var path = Path.Combine(
                root,
                "identity-target",
                MachineIdentityStore.FileName);
            var store = new MachineIdentityStore(path);
            var identity = await store.EnsureAsync();

            await store.ValidateTargetAsync(identity.DeviceId);
            await store.ValidateTargetAsync(null);

            var rejected = false;
            try
            {
                await store.ValidateTargetAsync(
                    Guid.NewGuid().ToString("D"));
            }
            catch (IdentityMismatchException ex)
            {
                rejected = ex.Message.StartsWith(
                    "IDENTITY_MISMATCH:",
                    StringComparison.Ordinal);
            }

            True(
                rejected,
                "Wrong target_device_id was not rejected.");
        });

    await RunAsync(
        "Machine Identity detects tampered binding fingerprint",
        async () =>
        {
            var path = Path.Combine(
                root,
                "identity-tamper",
                MachineIdentityStore.FileName);
            var store = new MachineIdentityStore(path);
            await store.EnsureAsync();

            using var document = JsonDocument.Parse(
                await File.ReadAllTextAsync(path));

            var rootElement = document.RootElement;
            var tampered = new Dictionary<string, object?>
            {
                ["schema_version"] = rootElement.GetProperty("schema_version").GetString(),
                ["device_id"] = rootElement.GetProperty("device_id").GetString(),
                ["device_name"] = rootElement.GetProperty("device_name").GetString(),
                ["created_at_utc"] = rootElement.GetProperty("created_at_utc").GetDateTimeOffset(),
                ["binding_fingerprint"] = new string('0', 64),
                ["protection"] = rootElement.GetProperty("protection").GetString(),
                ["protected_secret"] = rootElement.GetProperty("protected_secret").GetString()
            };

            await File.WriteAllTextAsync(
                path,
                JsonSerializer.Serialize(
                    tampered,
                    new JsonSerializerOptions
                    {
                        WriteIndented = true
                    }));

            var rejected = false;
            try
            {
                await new MachineIdentityStore(path)
                    .EnsureAsync();
            }
            catch (IdentityMismatchException ex)
            {
                rejected = ex.Message.StartsWith(
                    "IDENTITY_MISMATCH:",
                    StringComparison.Ordinal);
            }

            True(
                rejected,
                "Tampered identity was not rejected.");
        });

    await RunAsync(
        "Manager identity.snapshot exposes verified local device",
        async () =>
        {
            var registry = new CapabilityRegistry();
            await using var supervisor =
                new NativeAgentSupervisor(
                    acquireInstanceLease: false);
            var controllers =
                new ManagerAgentControllerRegistry();

            var identityStore =
                new MachineIdentityStore(
                    Path.Combine(
                        root,
                        "manager-identity",
                        MachineIdentityStore.FileName));

            var service =
                new ManagerControlService(
                    registry,
                    supervisor,
                    controllers,
                    machineIdentity: identityStore);

            var snapshot =
                await CallAsync<
                    ManagerMachineIdentitySnapshot>(
                    service,
                    "identity.snapshot");

            True(
                Guid.TryParse(
                    snapshot.DeviceId,
                    out _),
                "Manager device ID is invalid.");
            Equal(
                "verified",
                snapshot.BindingState);
            Equal(
                "mandatory",
                snapshot.TargetValidationMode);
            Equal(
                "verified-local",
                snapshot.TrustState);
            True(
                !string.IsNullOrWhiteSpace(
                    snapshot.DeviceAlias),
                "Manager device alias is missing.");
            True(
                !string.IsNullOrWhiteSpace(
                    snapshot.InstallationId),
                "Manager installation ID is missing.");
        });

    await RunAsync(
        "Installer base folder resolves to one role-specific subfolder",
        () =>
        {
            var basePath = Path.Combine(
                root,
                "chosen-base");

            var target =
                InstallTargetResolver.ResolveFromBaseFolder(
                    basePath);

            Equal(
                Path.Combine(
                    Path.GetFullPath(basePath),
                    "Zagent Master"),
                target);

            Equal(
                target,
                InstallTargetResolver.ResolveFromBaseFolder(
                    target));

            return Task.CompletedTask;
        });

}
finally
{
    try
    {
        Directory.Delete(root, recursive: true);
    }
    catch
    {
    }
}

Console.WriteLine(
    $"MANAGER_FEATURE_TEST_{(failed == 0 ? "PASS" : "FAIL")} passed={passed} failed={failed}");

return failed == 0 ? 0 : 1;

async Task RunAsync(
    string name,
    Func<Task> action)
{
    try
    {
        await action();
        passed++;
        Console.WriteLine("PASS " + name);
    }
    catch (Exception ex)
    {
        failed++;
        Console.WriteLine(
            "FAIL " + name + " :: " + ex.Message);
    }
}

async Task<T> CallAsync<T>(
    ManagerControlService service,
    string method,
    object? parameters = null)
{
    var response = await service.HandleAsync(
        new ManagerRequestEnvelope(
            ManagerProtocol.Version,
            Guid.NewGuid().ToString("N"),
            method,
            parameters is null
                ? null
                : ManagerJson.ToElement(parameters)));

    if (!response.Success)
    {
        throw new InvalidOperationException(
            response.Error ?? "Manager request failed.");
    }

    return response.Result!.Value.Deserialize<T>(
               ManagerJson.Options) ??
           throw new InvalidDataException(
               "Manager result was null.");
}

void Equal<T>(T expected, T actual)
{
    if (!EqualityComparer<T>.Default.Equals(
            expected,
            actual))
    {
        throw new InvalidOperationException(
            $"Expected '{expected}', got '{actual}'.");
    }
}

void True(bool condition, string message)
{
    if (!condition)
    {
        throw new InvalidOperationException(message);
    }
}

void False(bool condition, string message) =>
    True(!condition, message);