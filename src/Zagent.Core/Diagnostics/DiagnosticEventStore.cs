using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Zagent.Core.Diagnostics;

public sealed record DiagnosticEvent(int Version, string TimestampUtc, string RequestId, string Component, string Stage, string Code, string Severity, string Message);
public sealed record DiagnosticSourceStatus(string Component, string Status, int Accepted, int Ignored, int Truncated);
public sealed record DiagnosticReport(DateTimeOffset CapturedAtUtc, string Status, IReadOnlyList<DiagnosticEvent> Events, IReadOnlyList<DiagnosticSourceStatus> Sources);

/// <summary>Best-effort, bounded, code-only diagnostics. Never accepts exception text or caller messages.</summary>
public sealed class DiagnosticEventStore
{
    public const int MaxFileBytes = 2 * 1024 * 1024;
    public const int RotationBytes = 1024 * 1024;
    public const int MaxRecordBytes = 4096;
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private static readonly Regex IdPattern = new("\\A[a-f0-9]{32}\\z", RegexOptions.CultureInvariant);
    private static readonly Regex TimestampPattern = new("\\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\\.[0-9]{1,7})?Z\\z", RegexOptions.CultureInvariant);
    private readonly string directory;
    private static readonly object gate = new();
    // Both stage and code are selected from a static vocabulary: attacker-controlled JSONL strings are not display text.
    private static readonly Dictionary<string, (string Stage, string Hint)> Hints = new(StringComparer.Ordinal) {
        ["DASHBOARD_REQUEST_FAILED"] = ("dashboard.request", "The dashboard request failed. Check dependency status; do not assume an operation succeeded."),
        ["CORE_STARTED"] = ("core.lifecycle", "Core management host started."),
        ["CORE_START_FAILED"] = ("core.lifecycle", "Core startup failed. Verify owner-local enrollment and runtime prerequisites."),
        ["CORE_STOPPING"] = ("core.lifecycle", "Core management host is stopping."),
        ["CORE_AGENT_START_FAILED"] = ("supervisor.start", "An agent process could not start. Verify the selected runtime and owner-local configuration."),
        ["CORE_AGENT_EXITED"] = ("supervisor.exit", "An agent process exited unexpectedly. Inspect current process state before retrying work."),
        ["AUTH_INVALID_TOKEN"] = ("auth", "Authentication failed. Verify the authorized owner-local configuration."),
        ["AUTH_NOT_AUTHORIZED"] = ("auth", "Authorization was denied. Do not bypass the configured grants."),
        ["AUTH_REQUIRED"] = ("auth", "Authentication is required."),
        ["AUTH_TOKEN_EXPIRED"] = ("auth", "The authorization token expired. Renew through the normal owner-approved flow."),
        ["AUTH_INTROSPECTION_FAILED"] = ("auth", "Token verification is unavailable. Verify the configured authentication service."),
        ["ROUTER_CONFIGURATION_ERROR"] = ("init", "Router configuration could not be initialized."),
        ["ROUTER_UPSTREAM_UNAVAILABLE"] = ("dispatch", "The upstream component is unavailable. Inspect component state."),
        ["ROUTER_PROTOCOL_ERROR"] = ("dispatch", "Request arguments or protocol were rejected. Check the published input schema."),
        ["FILES_OPERATION_FAILED"] = ("dispatch", "The Files operation failed. Check its existing receipt before retrying."),
        ["UNEXPECTED_ERROR"] = ("error", "An unexpected component error occurred. Inspect component state."),
        ["DIAGNOSTIC_IO_FAILED"] = ("diagnostics", "Diagnostic storage is unavailable."),
        ["DISPATCH_FAILED"] = ("dispatch", "Dispatch failed. Check the existing operation receipt before retrying uncertain work.")
    };
    private static readonly HashSet<string> Stages = new(StringComparer.Ordinal) {
        "dashboard.request", "core.lifecycle", "supervisor.start", "supervisor.exit", "auth", "init", "dispatch", "error", "diagnostics",
        "auth.current_grant", "auth.token", "auth.configuration", "auth.token_header", "auth.introspection_configuration",
        "auth.introspection_status", "auth.introspection_size", "auth.introspection", "auth.token_claims", "auth.rejection",
        "job.scheduler", "job.upstream_result", "job.execution", "upstream.dispatch",
        "router.configuration", "mcp.auth_context", "mcp.handler", "mcp.protocol", "mcp.request", "mcp.initialize", "mcp.tools_list", "mcp.tools_call",
        "files.authentication", "files.tool_dispatch", "files.operation"
    };
    public DiagnosticEventStore(string dataRoot) => directory = Path.Combine(Path.GetFullPath(dataRoot), "logs", "diagnostics");
    public static bool ValidRequestId(string? value) => value is not null && IdPattern.IsMatch(value);
    public static bool ValidFilters(string? component, string? severity, string? requestId) =>
        (component is null or "core" or "router" or "files") && (severity is null or "info" or "warning" or "error") && (requestId is null || ValidRequestId(requestId));
    public string Record(string stage, string code, string severity, string? requestId = null)
    {
        var id = ValidRequestId(requestId) ? requestId! : Guid.NewGuid().ToString("N");
        if (!Hints.TryGetValue(code, out var hint) || hint.Stage != stage || severity is not ("info" or "warning" or "error")) return id;
        try { lock (gate) {
            if (!SafePath(directory)) return id;
            Directory.CreateDirectory(directory);
            var path = Path.Combine(directory, "core.jsonl"); var rotated = path + ".1";
            if (!SafePath(path) || !SafePath(rotated)) return id;
            if (File.Exists(path) && new FileInfo(path).Length >= RotationBytes) File.Move(path, rotated, true);
            var entry = new DiagnosticEvent(1, DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffffffZ"), id, "core", stage, code, severity, hint.Hint);
            using var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.Read);
            var bytes = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(entry, Json) + "\n"); stream.Write(bytes);
        } } catch (Exception) { /* Diagnostics never changes API/auth/lifecycle outcomes, nor logs recursively. */ }
        return id;
    }
    public DiagnosticReport Read(int limit = 200, string? component = null, string? severity = null, string? requestId = null)
    {
        if (limit is < 1 or > 500 || !ValidFilters(component, severity, requestId)) throw new ArgumentException("Invalid diagnostic filter.");
        var events = new List<DiagnosticEvent>(); var statuses = new List<DiagnosticSourceStatus>();
        foreach (var source in new[] { "core", "router", "files" }) {
            int accepted = 0, ignored = 0, truncated = 0; bool found = false, unavailable = false;
            foreach (var suffix in new[] { ".jsonl.1", ".jsonl" }) {
                var path = Path.Combine(directory, source + suffix);
                try {
                    if (!SafePath(path)) { unavailable = true; continue; }
                    if (!File.Exists(path)) continue;
                    found = true;
                    using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
                    if (stream.Length > MaxFileBytes) { unavailable = true; truncated++; continue; }
                    // Fixed byte and record budgets; no ReadLine allocation on attacker-sized lines.
                    var buffer = new byte[MaxFileBytes + 1]; int length = 0, count;
                    while (length < buffer.Length && (count = stream.Read(buffer, length, buffer.Length - length)) > 0) length += count;
                    if (length > MaxFileBytes) { unavailable = true; truncated++; continue; }
                    int start = 0;
                    for (int i = 0; i < length; i++) if (buffer[i] == 10) {
                        int size = i - start;
                        if (size > MaxRecordBytes) { ignored++; truncated++; }
                        else if (TryParse(buffer.AsSpan(start, size), source, out var entry)) {
                            accepted++;
                            if ((component is null || entry!.Component == component) && (severity is null || entry!.Severity == severity) && (requestId is null || entry!.RequestId == requestId)) events.Add(entry!);
                        } else ignored++;
                        start = i + 1;
                    }
                    if (start < length) { ignored++; truncated++; }
                } catch (Exception) { unavailable = true; }
            }
            statuses.Add(new(source, unavailable ? "unavailable" : !found ? "missing" : ignored > 0 ? "partial" : accepted == 0 ? "empty" : "available", accepted, ignored, truncated));
        }
        var rows = events.OrderByDescending(e => e.TimestampUtc, StringComparer.Ordinal).Take(limit).ToArray();
        return new(DateTimeOffset.UtcNow, statuses.Any(s => s.Status is "unavailable" or "partial") ? "partial" : rows.Length == 0 ? "no_events" : "available", rows, statuses);
    }
    private static bool TryParse(ReadOnlySpan<byte> bytes, string source, out DiagnosticEvent? entry)
    {
        entry = null;
        try {
            using var doc = JsonDocument.Parse(bytes.ToArray(), new JsonDocumentOptions { MaxDepth = 4 });
            var obj = doc.RootElement;
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var property in obj.EnumerateObject()) if (!names.Add(property.Name)) return false;
            if (!names.SetEquals(new[] { "version", "timestampUtc", "requestId", "component", "stage", "code", "severity", "message" })) return false;
            if (obj.GetProperty("version").GetInt32() != 1) return false;
            string? Text(string key) => obj.GetProperty(key).GetString();
            var timestamp = Text("timestampUtc"); var id = Text("requestId"); var code = Text("code"); var stage = Text("stage"); var severity = Text("severity");
            if (timestamp is null || timestamp.Length > 40 || !TimestampPattern.IsMatch(timestamp) || !DateTimeOffset.TryParse(timestamp, System.Globalization.CultureInfo.InvariantCulture, System.Globalization.DateTimeStyles.None, out var date) || date.Offset != TimeSpan.Zero || !ValidRequestId(id) || Text("component") != source || severity is not ("info" or "warning" or "error") || code is null || !Hints.TryGetValue(code, out var hint) || stage is null || !Stages.Contains(stage) || Text("message") is null) return false;
            entry = new(1, date.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffffffZ"), id!, source, stage, code, severity, hint.Hint);
            return true;
        } catch (Exception) { return false; }
    }
    private static bool SafePath(string path)
    {
        for (var current = new FileInfo(path) as FileSystemInfo; current is not null;) {
            current.Refresh();
            if (current.LinkTarget is not null || (current.Exists && (current.Attributes & FileAttributes.ReparsePoint) != 0)) return false;
            current = current is DirectoryInfo dir ? dir.Parent : ((FileInfo)current).Directory;
        }
        return true;
    }
}
