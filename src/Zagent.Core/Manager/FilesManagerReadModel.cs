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
        CancellationToken cancellationToken = default)
    {
        var profilesJson = await CallToolForJsonAsync(
            "files_profile_list",
            cancellationToken);

        var activeJson = await CallToolForJsonAsync(
            "files_profile_default_get",
            cancellationToken);

        var pendingJson = await CallToolForJsonAsync(
            "files_profile_pending_list",
            cancellationToken);

        var sessionsJson = await CallToolForJsonAsync(
            "files_workspace_list",
            cancellationToken);

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
            DateTimeOffset.UtcNow);
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

    public async Task<ManagerOperationResult> AddProfileAsync(
        ManagerProfileAddRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);

        var name = (request.Name ?? "").Trim();
        var root = (request.Root ?? "").Trim();
        var mode = (request.Mode ?? "read-only").Trim().ToLowerInvariant();

        if (string.IsNullOrWhiteSpace(name) ||
            string.IsNullOrWhiteSpace(root))
        {
            return new ManagerOperationResult(
                false,
                "profiles.add",
                name,
                "Profile name and root path are required.");
        }

        if (mode is not "read-only" and not "read-write")
        {
            return new ManagerOperationResult(
                false,
                "profiles.add",
                name,
                "Profile mode must be read-only or read-write.");
        }

        var fullRoot = Path.GetFullPath(root);
        if (!Directory.Exists(fullRoot))
        {
            return new ManagerOperationResult(
                false,
                "profiles.add",
                name,
                $"Folder does not exist: {fullRoot}");
        }

        var code =
            "import json,os; " +
            "from app.profiles.manager import request_add; " +
            "r=request_add(os.environ['ZAGENT_MANAGER_PROFILE_NAME'],os.environ['ZAGENT_MANAGER_PROFILE_ROOT'],os.environ['ZAGENT_MANAGER_PROFILE_MODE'],'Added from Zagent Manager','zagent_manager'); " +
            "print(json.dumps(r,ensure_ascii=False))";

        return await RunLocalProfileMutationAsync(
            "profiles.add",
            name,
            code,
            new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["ZAGENT_MANAGER_PROFILE_NAME"] = name,
                ["ZAGENT_MANAGER_PROFILE_ROOT"] = fullRoot,
                ["ZAGENT_MANAGER_PROFILE_MODE"] = mode
            },
            cancellationToken);
    }

    public async Task<ManagerOperationResult> RemoveProfileAsync(
        ManagerProfileRemoveRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);

        var name = (request.Name ?? "").Trim();
        if (string.IsNullOrWhiteSpace(name))
        {
            return new ManagerOperationResult(
                false,
                "profiles.remove",
                "",
                "Select a Files profile to remove.");
        }

        var code =
            "import json,os; " +
            "from app.profiles.manager import request_delete; " +
            "r=request_delete(os.environ['ZAGENT_MANAGER_PROFILE_NAME'],'zagent_manager'); " +
            "print(json.dumps(r,ensure_ascii=False))";

        return await RunLocalProfileMutationAsync(
            "profiles.remove",
            name,
            code,
            new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["ZAGENT_MANAGER_PROFILE_NAME"] = name
            },
            cancellationToken);
    }

    public async Task<ManagerOperationResult> UpdateProfileAsync(
        ManagerProfileUpdateRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);

        var name = (request.Name ?? "").Trim();
        if (string.IsNullOrWhiteSpace(name))
        {
            return new ManagerOperationResult(
                false,
                "profiles.update",
                "",
                "Select a Files profile to update.");
        }

        string? fullRoot = null;
        if (request.Root is not null)
        {
            if (string.IsNullOrWhiteSpace(request.Root))
            {
                return new ManagerOperationResult(
                    false,
                    "profiles.update",
                    name,
                    "Profile root cannot be empty.");
            }

            fullRoot = Path.GetFullPath(request.Root.Trim());
            if (!Directory.Exists(fullRoot))
            {
                return new ManagerOperationResult(
                    false,
                    "profiles.update",
                    name,
                    $"Folder does not exist: {fullRoot}");
            }
        }

        var mode = request.Mode?.Trim().ToLowerInvariant();
        if (mode is not null &&
            mode is not "read-only" and not "read-write")
        {
            return new ManagerOperationResult(
                false,
                "profiles.update",
                name,
                "Profile mode must be read-only or read-write.");
        }

        if (fullRoot is null &&
            mode is null &&
            request.Enabled is null &&
            request.Description is null)
        {
            return new ManagerOperationResult(
                false,
                "profiles.update",
                name,
                "No profile changes were requested.");
        }

        var code =
            "import json,os; " +
            "from app.profiles.manager import request_update; " +
            "root=os.environ.get('ZAGENT_MANAGER_PROFILE_ROOT') or None; " +
            "mode=os.environ.get('ZAGENT_MANAGER_PROFILE_MODE') or None; " +
            "desc=os.environ.get('ZAGENT_MANAGER_PROFILE_DESCRIPTION') if os.environ.get('ZAGENT_MANAGER_PROFILE_HAS_DESCRIPTION')=='1' else None; " +
            "raw=os.environ.get('ZAGENT_MANAGER_PROFILE_ENABLED',''); enabled=None if raw=='' else raw=='1'; " +
            "r=request_update(os.environ['ZAGENT_MANAGER_PROFILE_NAME'],root=root,mode=mode,description=desc,enabled=enabled,requested_by='zagent_manager'); " +
            "print(json.dumps(r,ensure_ascii=False))";

        return await RunLocalProfileMutationAsync(
            "profiles.update",
            name,
            code,
            new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["ZAGENT_MANAGER_PROFILE_NAME"] = name,
                ["ZAGENT_MANAGER_PROFILE_ROOT"] = fullRoot ?? "",
                ["ZAGENT_MANAGER_PROFILE_MODE"] = mode ?? "",
                ["ZAGENT_MANAGER_PROFILE_DESCRIPTION"] = request.Description ?? "",
                ["ZAGENT_MANAGER_PROFILE_HAS_DESCRIPTION"] = request.Description is null ? "0" : "1",
                ["ZAGENT_MANAGER_PROFILE_ENABLED"] = request.Enabled is null
                    ? ""
                    : request.Enabled.Value ? "1" : "0"
            },
            cancellationToken);
    }

    public async Task<ManagerOperationResult> SwitchProfileAsync(
        ManagerProfileSwitchRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);

        var name = (request.Name ?? "").Trim();
        if (string.IsNullOrWhiteSpace(name))
        {
            return new ManagerOperationResult(
                false,
                "profiles.switch",
                "",
                "Select a Files profile to use as the default for new sessions.");
        }

        var code =
            "import json,os; " +
            "from app.profiles.manager import switch_default_profile; " +
            "r=switch_default_profile(os.environ['ZAGENT_MANAGER_PROFILE_NAME']); " +
            "print(json.dumps(r,ensure_ascii=False))";

        return await RunLocalProfileMutationAsync(
            "profiles.switch",
            name,
            code,
            new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["ZAGENT_MANAGER_PROFILE_NAME"] = name
            },
            cancellationToken);
    }

    private async Task<ManagerOperationResult> RunLocalProfileMutationAsync(
        string operation,
        string target,
        string code,
        IReadOnlyDictionary<string, string> variables,
        CancellationToken cancellationToken)
    {
        if (_approvalOptions is null)
        {
            return new ManagerOperationResult(
                false,
                operation,
                target,
                "Local Files profile-management runtime is not configured.");
        }

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

        foreach (var pair in variables)
        {
            startInfo.Environment[pair.Key] = pair.Value;
        }

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
                operation,
                target,
                string.IsNullOrWhiteSpace(stderr)
                    ? $"Profile helper exited {process.ExitCode}."
                    : stderr.Trim());
        }

        return new ManagerOperationResult(
            true,
            operation,
            target,
            stdout.Trim());
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