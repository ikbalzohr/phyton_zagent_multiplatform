using System.Diagnostics;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Zagent.Shared.Manager;

namespace Zagent.Core.Manager;

public sealed record FilesLocalApprovalOptions(
    string PythonExecutable,
    string EngineRoot,
    IReadOnlyDictionary<string, string> EnvironmentVariables);

public sealed class FilesManagerReadModel
{
    private readonly HttpClient _httpClient;
    private readonly Uri _mcpUri;
    private readonly FilesLocalApprovalOptions? _approvalOptions;

    public FilesManagerReadModel(
        Uri mcpUri,
        FilesLocalApprovalOptions? approvalOptions = null,
        HttpClient? httpClient = null)
    {
        ArgumentNullException.ThrowIfNull(mcpUri);

        if (!mcpUri.IsLoopback)
        {
            throw new ArgumentException(
                "Files Manager endpoint must be loopback.",
                nameof(mcpUri));
        }

        _mcpUri = mcpUri;
        _approvalOptions = approvalOptions;
        _httpClient = httpClient ?? Zagent.Core.Manager.InternalManagementChannel.CreateClient(TimeSpan.FromSeconds(5));
    }

    public async Task<ManagerProfilesSnapshot> GetProfilesAsync(
        CancellationToken cancellationToken = default,
        bool includeWorkspace = true)
    {
        // Profile administration is intentionally unavailable over Files MCP.
        // The authenticated local dashboard reads the owner's configuration directly.
        using var profilesJson = await ReadLocalProfilesAsync("ZAGENT_FILES_CONFIG_DIR", "profiles.json", cancellationToken);
        using var activeJson = JsonDocument.Parse(JsonSerializer.Serialize(new {
            name = profilesJson.RootElement.GetProperty("active_profile").GetString()
        }));
        using var pendingJson = await ReadLocalProfilesAsync("ZAGENT_FILES_DATA_ROOT", "pending_profile_requests.json", cancellationToken, optional: true);
        var workspace = includeWorkspace ? await ReadWorkspaceViewAsync(cancellationToken)
            : (Document: JsonDocument.Parse("[]"), Available: false);
        using var sessionsJson = workspace.Document;

        var profileRoot =
            UnwrapData(profilesJson.RootElement);
        var activeRoot =
            UnwrapData(activeJson.RootElement);
        var pendingRoot =
            UnwrapData(pendingJson.RootElement);
        var sessionsRoot =
            UnwrapData(sessionsJson.RootElement);

        var activeName =
            GetString(activeRoot, "name") ??
            GetString(activeRoot, "profile") ??
            "";

        var profiles = new List<ManagerProfileRow>();

        var profileArray =
            profileRoot.ValueKind == JsonValueKind.Array
                ? profileRoot
                : profileRoot.TryGetProperty(
                    "profiles",
                    out var nestedProfiles)
                    ? nestedProfiles
                    : default;

        if (profileArray.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in profileArray.EnumerateArray())
            {
                var name = GetString(item, "name") ?? "";
                profiles.Add(
                    new ManagerProfileRow(
                        name,
                        GetString(item, "root") ?? "",
                        GetString(item, "mode") ?? "",
                        GetBool(item, "enabled", true),
                        string.Equals(
                            name,
                            activeName,
                            StringComparison.Ordinal),
                        GetBool(
                            item,
                            "authorized_by_user",
                            false),
                        GetString(
                            item,
                            "authorization_source") ??
                            ""));
            }
        }

        var sessions = new List<ManagerWorkspaceRow>();
        if (sessionsRoot.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in sessionsRoot.EnumerateArray())
            {
                var mountedProfiles = "";
                if (item.TryGetProperty("profiles", out var mounted) &&
                    mounted.ValueKind == JsonValueKind.Array)
                {
                    mountedProfiles = string.Join(
                        ", ",
                        mounted.EnumerateArray()
                            .Select(value =>
                                value.ValueKind == JsonValueKind.String
                                    ? value.GetString()
                                    : value.ToString())
                            .Where(value =>
                                !string.IsNullOrWhiteSpace(value)));
                }

                sessions.Add(
                    new ManagerWorkspaceRow(
                        GetString(item, "session_id") ?? "",
                        GetString(item, "active_profile") ?? "",
                        mountedProfiles,
                        GetDouble(item, "updated")));
            }
        }

        var approvals = new List<ManagerApprovalRow>();
        var approvalArray =
            pendingRoot.ValueKind == JsonValueKind.Array
                ? pendingRoot
                : pendingRoot.TryGetProperty(
                    "requests",
                    out var nestedRequests)
                    ? nestedRequests
                    : default;

        if (approvalArray.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in approvalArray.EnumerateArray())
            {
                if (GetString(item, "status") != "pending") continue;
                var summary = item.TryGetProperty(
                        "payload",
                        out var payload)
                    ? payload.ToString()
                    : "";

                var privilege =
                    item.TryGetProperty(
                        "payload",
                        out payload) &&
                    payload.ValueKind == JsonValueKind.Object &&
                    payload.TryGetProperty(
                        "privilege_escalation",
                        out var escalation) &&
                    escalation.ValueKind == JsonValueKind.True;

                approvals.Add(
                    new ManagerApprovalRow(
                        GetString(
                            item,
                            "request_id") ?? "",
                        GetString(item, "kind") ?? "",
                        GetString(item, "status") ?? "",
                        GetString(
                            item,
                            "requested_by") ?? "",
                        GetDouble(item, "created_at"),
                        summary,
                        privilege));
            }
        }

        return new ManagerProfilesSnapshot(
            profiles,
            sessions,
            approvals,
            activeName,
            DateTimeOffset.UtcNow) {
                UnavailableDependencies = workspace.Available ? Array.Empty<string>()
                    : new[] { "Files workspace view unavailable; local profile/approval state only." }
            };
    }

    public async Task<ManagerOperationResult> ResolveApprovalAsync(
        ManagerApprovalActionRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);

        if (_approvalOptions is null)
        {
            return new ManagerOperationResult(
                false,
                "approval.resolve",
                request.RequestId,
                "Local Files approval runtime is not configured.");
        }

        if (request.Action is not "approve" and not "deny")
        {
            return new ManagerOperationResult(
                false,
                "approval.resolve",
                request.RequestId,
                "Approval action must be approve or deny.");
        }

        var code =
            "import json,os; " +
            "from app.profiles.manager import approve_request,deny_request; " +
            "rid=os.environ['ZAGENT_MANAGER_REQUEST_ID']; " +
            "action=os.environ['ZAGENT_MANAGER_APPROVAL_ACTION']; " +
            "reason=os.environ.get('ZAGENT_MANAGER_APPROVAL_REASON',''); " +
            "result=approve_request(rid,'zagent_manager') if action=='approve' " +
            "else deny_request(rid,'zagent_manager',reason); " +
            "print(json.dumps(result,ensure_ascii=False))";

        var startInfo = new ProcessStartInfo
        {
            FileName = Path.GetFullPath(
                _approvalOptions.PythonExecutable),
            WorkingDirectory = Path.GetFullPath(
                _approvalOptions.EngineRoot),
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };

        startInfo.ArgumentList.Add("-c");
        startInfo.ArgumentList.Add(code);

        foreach (var pair in _approvalOptions.EnvironmentVariables)
        {
            startInfo.Environment[pair.Key] = pair.Value;
        }

        startInfo.Environment[
            "ZAGENT_MANAGER_REQUEST_ID"] =
            request.RequestId;
        startInfo.Environment[
            "ZAGENT_MANAGER_APPROVAL_ACTION"] =
            request.Action;
        startInfo.Environment[
            "ZAGENT_MANAGER_APPROVAL_REASON"] =
            request.Reason ?? "";

        // Strip after every explicit environment merge as well as ambient inheritance.
        startInfo.Environment.Remove(OAuthIntrospectionCredentialStore.EnvironmentName);
        using var process = new Process
        {
            StartInfo = startInfo
        };

        process.Start();

        var stdoutTask =
            process.StandardOutput.ReadToEndAsync(
                cancellationToken);
        var stderrTask =
            process.StandardError.ReadToEndAsync(
                cancellationToken);

        await process.WaitForExitAsync(
            cancellationToken);

        var stdout = await stdoutTask;
        var stderr = await stderrTask;

        if (process.ExitCode != 0)
        {
            return new ManagerOperationResult(
                false,
                "approval.resolve",
                request.RequestId,
                string.IsNullOrWhiteSpace(stderr)
                    ? $"Approval helper exited {process.ExitCode}."
                    : stderr.Trim());
        }

        return new ManagerOperationResult(
            true,
            "approval.resolve",
            request.RequestId,
            stdout.Trim());
    }

    public Task<ManagerOperationResult> AddProfileAsync(
        ManagerProfileAddRequest request, CancellationToken cancellationToken = default) =>
        Task.FromResult(new ManagerOperationResult(false, "profiles.add", request.Name,
            "Authenticated direct profile administration is required; use the Administrator dashboard. No pending request was created."));

    public Task<ManagerOperationResult> RemoveProfileAsync(
        ManagerProfileRemoveRequest request, CancellationToken cancellationToken = default) =>
        Task.FromResult(new ManagerOperationResult(false, "profiles.remove", request.Name,
            "Authenticated direct profile administration is required; use the Administrator dashboard. No pending request was created."));

    public Task<ManagerOperationResult> UpdateProfileAsync(
        ManagerProfileUpdateRequest request, CancellationToken cancellationToken = default) =>
        Task.FromResult(new ManagerOperationResult(false, "profiles.update", request.Name,
            "Authenticated direct profile administration is required; use the Administrator dashboard. No pending request was created."));

    public Task<ManagerOperationResult> SwitchProfileAsync(
        ManagerProfileSwitchRequest request, CancellationToken cancellationToken = default) =>
        Task.FromResult(new ManagerOperationResult(false, "profiles.switch", request.Name,
            "Authenticated direct profile administration is required; use the Administrator dashboard. No pending request was created."));

    private async Task<JsonDocument> ReadLocalProfilesAsync(string rootKey, string fileName,
        CancellationToken cancellationToken, bool optional = false)
    {
        if (_approvalOptions is null || !_approvalOptions.EnvironmentVariables.TryGetValue(rootKey, out var root))
            throw new InvalidOperationException("Local Files management paths are not configured.");
        var path = Path.Combine(root, fileName);
        if (optional && !File.Exists(path)) return JsonDocument.Parse("{\"requests\":[]}");
        return JsonDocument.Parse(await File.ReadAllTextAsync(path, cancellationToken));
    }

    private async Task<(JsonDocument Document, bool Available)> ReadWorkspaceViewAsync(CancellationToken cancellationToken)
    {
        try { return (await CallToolForJsonAsync("files_workspace_list", cancellationToken), true); }
        catch (Exception ex) when (ex is HttpRequestException or InvalidOperationException or JsonException or TaskCanceledException)
        {
            cancellationToken.ThrowIfCancellationRequested();
            // Local approvals remain visible when the agent is stopped/revoked; no ready claim.
            return (JsonDocument.Parse("[]"), false);
        }
    }

    private Task<JsonDocument> CallToolForJsonAsync(
        string toolName,
        CancellationToken cancellationToken) =>
        CallToolForJsonAsync(
            toolName,
            arguments: null,
            cancellationToken);

    private async Task<JsonDocument> CallToolForJsonAsync(
        string toolName,
        object? arguments,
        CancellationToken cancellationToken)
    {
        var rpc = JsonSerializer.Serialize(
            new
            {
                jsonrpc = "2.0",
                id = Guid.NewGuid().ToString("N"),
                method = "tools/call",
                @params = new
                {
                    name = toolName,
                    arguments = arguments ?? new { }
                }
            });

        using var request = new HttpRequestMessage(
            HttpMethod.Post,
            _mcpUri);

        request.Content = new StringContent(
            rpc,
            Encoding.UTF8,
            "application/json");

        request.Headers.Accept.Add(
            new MediaTypeWithQualityHeaderValue(
                "application/json"));
        request.Headers.Accept.Add(
            new MediaTypeWithQualityHeaderValue(
                "text/event-stream"));
        request.Headers.TryAddWithoutValidation(
            "MCP-Protocol-Version",
            "2025-06-18");

        using var response = await _httpClient.SendAsync(
            request,
            cancellationToken);

        var body = await response.Content.ReadAsStringAsync(
            cancellationToken);

        response.EnsureSuccessStatusCode();

        using var rpcDocument = ParseRpcBody(body);
        var result = rpcDocument.RootElement.GetProperty(
            "result");

        if (result.TryGetProperty(
                "isError",
                out var isError) &&
            isError.ValueKind == JsonValueKind.True)
        {
            throw new InvalidOperationException(
                result.ToString());
        }

        if (result.TryGetProperty(
                "structuredContent",
                out var structured) &&
            structured.ValueKind is not
                JsonValueKind.Null and not
                JsonValueKind.Undefined)
        {
            if (structured.ValueKind ==
                    JsonValueKind.Object &&
                structured.TryGetProperty(
                    "result",
                    out var wrapped))
            {
                if (wrapped.ValueKind ==
                        JsonValueKind.String)
                {
                    var raw = wrapped.GetString();
                    if (!string.IsNullOrWhiteSpace(raw))
                    {
                        return JsonDocument.Parse(raw);
                    }
                }

                if (wrapped.ValueKind is
                    JsonValueKind.Object or
                    JsonValueKind.Array)
                {
                    return JsonDocument.Parse(
                        wrapped.ToString());
                }
            }

            if (structured.ValueKind is
                JsonValueKind.Object or
                JsonValueKind.Array)
            {
                return JsonDocument.Parse(
                    structured.ToString());
            }
        }

        if (result.TryGetProperty(
                "content",
                out var content) &&
            content.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in content.EnumerateArray())
            {
                if (item.TryGetProperty(
                        "text",
                        out var text) &&
                    text.ValueKind == JsonValueKind.String)
                {
                    var raw = text.GetString();
                    if (!string.IsNullOrWhiteSpace(raw))
                    {
                        return JsonDocument.Parse(raw);
                    }
                }
            }
        }

        throw new InvalidDataException(
            $"Files MCP tool '{toolName}' returned no JSON payload.");
    }

    private static JsonDocument ParseRpcBody(string body)
    {
        if (body.TrimStart().StartsWith(
                "event:",
                StringComparison.Ordinal))
        {
            var payloads = body
                .Split(
                    new[] { "\r\n", "\n" },
                    StringSplitOptions.None)
                .Where(
                    line => line.StartsWith(
                        "data:",
                        StringComparison.Ordinal))
                .Select(line => line[5..].Trim())
                .Where(
                    line =>
                        !string.IsNullOrWhiteSpace(line) &&
                        line != "[DONE]")
                .ToArray();

            if (payloads.Length == 0)
            {
                throw new InvalidDataException(
                    "Files MCP SSE response had no data payload.");
            }

            return JsonDocument.Parse(payloads[^1]);
        }

        return JsonDocument.Parse(body);
    }

    private static JsonElement UnwrapData(
        JsonElement root)
    {
        if (root.ValueKind == JsonValueKind.Object &&
            root.TryGetProperty(
                "data",
                out var data))
        {
            return data;
        }

        return root;
    }

    private static string? GetString(
        JsonElement element,
        string name)
    {
        if (!element.TryGetProperty(name, out var value))
        {
            return null;
        }

        return value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : value.ToString();
    }

    private static bool GetBool(
        JsonElement element,
        string name,
        bool fallback)
    {
        if (!element.TryGetProperty(name, out var value))
        {
            return fallback;
        }

        return value.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.False => false,
            _ => fallback
        };
    }

    private static double? GetDouble(
        JsonElement element,
        string name)
    {
        if (!element.TryGetProperty(name, out var value))
        {
            return null;
        }

        return value.TryGetDouble(out var number)
            ? number
            : null;
    }
}