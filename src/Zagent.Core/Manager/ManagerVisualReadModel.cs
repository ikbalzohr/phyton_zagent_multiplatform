using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Zagent.Shared.Manager;

namespace Zagent.Core.Manager;

public sealed class ManagerVisualReadModel
{
    private readonly string _root;
    private readonly string _latestPath;

    public ManagerVisualReadModel(string visualRoot)
    {
        _root = Path.GetFullPath(
            visualRoot ??
            throw new ArgumentNullException(nameof(visualRoot)));
        _latestPath = Path.Combine(_root, "latest.json");
    }

    // Backward-compat entry point: reads the flat public path only.
    public Task<ManagerVisualSnapshot> GetLatestAsync(
        CancellationToken cancellationToken = default) =>
        GetLatestAsync(null, null, cancellationToken);

    // Reads the per-owner (canonical) path first, then falls back to the flat
    // public path (backward-compat bridge). Owner hash = sha256 hex of the JSON
    // serialization of [principalId, workspaceId] (no whitespace), matching the
    // B producers (web TS / arcmap python).
    public async Task<ManagerVisualSnapshot> GetLatestAsync(
        string? principalId,
        string? workspaceId,
        CancellationToken cancellationToken = default)
    {
        var candidates = new List<string>();
        var ownerHash = TryComputeOwnerHash(principalId, workspaceId);
        if (ownerHash is not null)
            candidates.Add(Path.Combine(_root, "owners", ownerHash, "latest.json"));
        candidates.Add(_latestPath); // flat public path (bridge)

        ManagerVisualSnapshot? firstFailure = null;
        foreach (var path in candidates)
        {
            if (!File.Exists(path)) continue;
            var snapshot = await ReadOneAsync(path, cancellationToken);
            if (snapshot.Available) return snapshot;
            firstFailure ??= snapshot;
        }
        return firstFailure ?? Empty();
    }

    private async Task<ManagerVisualSnapshot> ReadOneAsync(
        string path,
        CancellationToken cancellationToken)
    {
        try
        {
            await using var stream = File.Open(
                path,
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete);

            var manifest = await JsonSerializer.DeserializeAsync<VisualManifest>(
                stream,
                new JsonSerializerOptions
                {
                    PropertyNameCaseInsensitive = true
                },
                cancellationToken);

            if (manifest is null ||
                string.IsNullOrWhiteSpace(manifest.ArtifactPath))
            {
                return Empty("Visual manifest is empty.");
            }

            if (string.IsNullOrWhiteSpace(manifest.Sha256) || manifest.Provenance?.WorkspaceId is null)
                return Empty("Visual manifest is not workspace-scoped and hashed.");
            var artifactPath = Path.GetFullPath(manifest.ArtifactPath);
            if (!IsUnderRoot(artifactPath))
            {
                return Empty(
                    "Visual manifest points outside the shared visual root.");
            }

            if (!File.Exists(artifactPath))
            {
                return Empty(
                    "Latest visual artifact file no longer exists.");
            }

            return new ManagerVisualSnapshot(true, manifest.Id, manifest.Source, manifest.Kind, manifest.Label,
                ParseTimestamp(manifest.CapturedAt), manifest.MimeType, manifest.Bytes, manifest.Provenance?.DeviceId,
                manifest.Provenance?.DeviceName, manifest.Provenance?.WorkspaceId, manifest.Sha256, null);
        }
        catch (Exception ex)
        {
            return Empty(ex.Message);
        }
    }

    private bool IsUnderRoot(string candidate)
    {
        var root = _root.TrimEnd(
            Path.DirectorySeparatorChar,
            Path.AltDirectorySeparatorChar) +
            Path.DirectorySeparatorChar;

        return candidate.StartsWith(
            root,
            OperatingSystem.IsWindows()
                ? StringComparison.OrdinalIgnoreCase
                : StringComparison.Ordinal);
    }

    private static DateTimeOffset? ParseTimestamp(string? value) =>
        DateTimeOffset.TryParse(value, out var parsed)
            ? parsed
            : null;

    private static ManagerVisualSnapshot Empty(string? error = null) =>
        new(
            Available: false, Id: null, Source: null, Kind: null, Label: null,
            CapturedAtUtc: null, MimeType: null, Bytes: 0, DeviceId: null,
            DeviceName: null, WorkspaceId: null, Sha256: null, Error: error);

    private static string? TryComputeOwnerHash(string? principalId, string? workspaceId)
    {
        if (string.IsNullOrWhiteSpace(principalId) ||
            string.IsNullOrWhiteSpace(workspaceId))
            return null;
        // Canonical serialization matches B producers: JSON array, no whitespace.
        var json = JsonSerializer.Serialize(new[] { principalId, workspaceId });
        return Convert.ToHexString(
            SHA256.HashData(Encoding.UTF8.GetBytes(json))).ToLowerInvariant();
    }

    private sealed record VisualManifest(
        string? Id,
        string? Source,
        string? Kind,
        string? Label,
        string? CapturedAt,
        string? ArtifactPath,
        string? MimeType,
        long Bytes,
        string? Sha256,
        VisualProvenance? Provenance);

    private sealed record VisualProvenance(
        string? DeviceId,
        string? DeviceName,
        string? WorkspaceId);
}