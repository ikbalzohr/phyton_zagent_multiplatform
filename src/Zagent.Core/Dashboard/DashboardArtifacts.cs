using System.Security.Cryptography;
using System.Text.Json;
using Zagent.Core.Manager;

namespace Zagent.Core.Dashboard;

public sealed record DashboardArtifact(string Id, string? Source, string? Label, string MimeType,
    long Bytes, string Sha256, DateTimeOffset CapturedAtUtc, string WorkspaceId);
public sealed record DashboardArtifactContent(byte[] Bytes, string MimeType, string FileName);

/// <summary>Manifest-ID lookup only. Legacy manifests without workspace/hash are metadata-only, never downloadable.</summary>
public sealed class DashboardArtifacts(string visualRoot)
{
    private readonly string _root = Path.GetFullPath(visualRoot);
    private const int MaximumBytes = 16 * 1024 * 1024;
    public async Task<object> LatestAsync(string workspace, CancellationToken token)
    {
        var resolved = await ResolveAsync(workspace, token);
        return resolved is null ? new { available = false, reason = "No verified workspace artifact. Manifest requires workspace_id, sha256 and a recent capture." } :
            new { available = true, artifact = resolved.Value.Artifact, contentUrl = "/api/management/v1/artifacts/" + Uri.EscapeDataString(resolved.Value.Artifact.Id) + "/content" };
    }
    public async Task<DashboardArtifactContent?> ReadAsync(string id, string workspace, CancellationToken token)
    {
        var resolved = await ResolveAsync(workspace, token);
        if (resolved is not { } item || item.Artifact.Id != id) return null;
        await using var stream = new FileStream(item.Path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length != item.Artifact.Bytes || stream.Length > MaximumBytes) return null;
        var bytes = new byte[(int)stream.Length];
        await stream.ReadExactlyAsync(bytes, token);
        if (!Convert.ToHexString(SHA256.HashData(bytes)).Equals(item.Artifact.Sha256, StringComparison.OrdinalIgnoreCase)) return null;
        return new DashboardArtifactContent(bytes, item.Artifact.MimeType, "artifact-" + item.Artifact.Id + item.Extension);
    }
    private async Task<(DashboardArtifact Artifact, string Path, string Extension)?> ResolveAsync(string workspace, CancellationToken token)
    {
        var manifestPath = Path.Combine(_root, "latest.json");
        if (!SafePath(manifestPath) || !File.Exists(manifestPath) || new FileInfo(manifestPath).Length > 65536) return null;
        using var doc = JsonDocument.Parse(await File.ReadAllTextAsync(manifestPath, token));
        var m = doc.RootElement;
        var p = m.TryGetProperty("provenance", out var provenance) && provenance.ValueKind == JsonValueKind.Object ? provenance : default;
        var id = Text(m, "id"); var path = Text(m, "artifactPath") ?? Text(m, "artifact_path") ?? Text(m, "ArtifactPath");
        var owner = Text(p, "workspace_id") ?? Text(p, "workspaceId") ?? Text(p, "WorkspaceId");
        var hash = Text(m, "sha256") ?? Text(m, "Sha256"); var timestamp = Text(m, "capturedAt") ?? Text(m, "captured_at") ?? Text(m, "CapturedAt");
        if (id is null || id.Length > 128 || !id.All(c => char.IsAsciiLetterOrDigit(c) || c is '-' or '_') ||
            owner != workspace || path is null || hash is null || hash.Length != 64 || !hash.All(Uri.IsHexDigit) ||
            !DateTimeOffset.TryParse(timestamp, out var captured) || captured < DateTimeOffset.UtcNow.AddHours(-24) || captured > DateTimeOffset.UtcNow.AddMinutes(1)) return null;
        if (Path.IsPathRooted(path)) return null;
        path = Path.GetFullPath(Path.Combine(_root, path));
        if (!SafePath(path) || !File.Exists(path)) return null;
        var extension = Path.GetExtension(path).ToLowerInvariant();
        var mime = extension switch { ".png" => "image/png", ".jpg" or ".jpeg" => "image/jpeg", ".pdf" => "application/pdf", ".txt" => "text/plain", ".zip" => "application/zip", _ => null };
        var info = new FileInfo(path);
        if (mime is null || info.Length > MaximumBytes || info.Length < 1) return null;
        return (new DashboardArtifact(id, Text(m, "source"), Text(m, "label"), mime, info.Length,
            hash, captured, workspace), path, extension);
    }
    private bool SafePath(string path)
    {
        var full = Path.GetFullPath(path);
        if (!full.StartsWith(_root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar,
            OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal)) return false;
        // Reject symlink/reparse points on every existing ancestor, including data-root ancestors.
        for (var current = full; !string.IsNullOrEmpty(current); current = Path.GetDirectoryName(current))
            if ((File.Exists(current) || Directory.Exists(current)) && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0) return false;
        return true;
    }
    private static string? Text(JsonElement element, string name) => element.ValueKind == JsonValueKind.Object &&
        element.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() : null;
}
