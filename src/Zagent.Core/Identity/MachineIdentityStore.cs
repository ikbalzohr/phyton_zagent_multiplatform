using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Zagent.Core.Identity;

public static class IdentityErrorCodes
{
    public const string SessionIdentityRequired =
        "SESSION_IDENTITY_REQUIRED";
    public const string DeviceNotTrusted =
        "DEVICE_NOT_TRUSTED";
    public const string TargetDeviceOffline =
        "TARGET_DEVICE_OFFLINE";
    public const string IdentityMismatch =
        "IDENTITY_MISMATCH";
    public const string IdentityProofFailed =
        "IDENTITY_PROOF_FAILED";
    public const string SessionBindingConflict =
        "SESSION_BINDING_CONFLICT";
    public const string DeviceSwitchConfirmationRequired =
        "DEVICE_SWITCH_CONFIRMATION_REQUIRED";
}

public sealed record MachineIdentitySnapshot(
    string DeviceId,
    string DeviceName,
    string BindingFingerprint,
    DateTimeOffset CreatedAtUtc,
    string BindingState,
    string Protection,
    string DeviceAlias = "",
    string InstallationId = "",
    string ShortFingerprint = "",
    string SchemaVersion = "2.0");

public class IdentityContractException : Exception
{
    public IdentityContractException(
        string code,
        string message)
        : base(code + ": " + message)
    {
        Code = code;
    }

    public string Code { get; }
}

public sealed class IdentityMismatchException :
    IdentityContractException
{
    public IdentityMismatchException(string message)
        : base(
            IdentityErrorCodes.IdentityMismatch,
            message)
    {
    }
}

public sealed class IdentityProofException :
    IdentityContractException
{
    public IdentityProofException(string message)
        : base(
            IdentityErrorCodes.IdentityProofFailed,
            message)
    {
    }
}

public sealed class MachineIdentityStore
{
    public const string FileName = "device_identity.json";
    public const string CurrentSchemaVersion = "2.0";
    private const string LegacySchemaVersion = "1.0";
    private const string ProtectionName =
        "Windows DPAPI CurrentUser";
    private const int CryptProtectUiForbidden = 0x1;

    private readonly string _path;
    private readonly TimeProvider _timeProvider;
    private readonly SemaphoreSlim _gate = new(1, 1);

    public MachineIdentityStore(
        string path,
        TimeProvider? timeProvider = null)
    {
        _path = Path.GetFullPath(
            path ??
            throw new ArgumentNullException(nameof(path)));
        _timeProvider =
            timeProvider ?? TimeProvider.System;
    }

    public string PathOnDisk => _path;

    public async Task<MachineIdentitySnapshot> EnsureAsync(
        CancellationToken cancellationToken = default)
    {
        await _gate.WaitAsync(cancellationToken);

        try
        {
            if (File.Exists(_path))
            {
                var loaded =
                    await LoadAndValidateEnvelopeAsync(
                        cancellationToken);

                if (string.Equals(
                        loaded.SchemaVersion,
                        LegacySchemaVersion,
                        StringComparison.Ordinal))
                {
                    loaded =
                        await UpgradeLegacyEnvelopeAsync(
                            loaded,
                            cancellationToken);
                }

                return ToSnapshot(loaded);
            }

            Directory.CreateDirectory(
                Path.GetDirectoryName(_path)!);

            var deviceId = Guid.NewGuid()
                .ToString("D")
                .ToLowerInvariant();
            var installationId = Guid.NewGuid()
                .ToString("D")
                .ToLowerInvariant();
            var deviceName = GetMachineName();
            var createdAt =
                _timeProvider.GetUtcNow();
            var secret =
                RandomNumberGenerator.GetBytes(32);

            try
            {
                var protectedSecret =
                    Protect(secret);
                var fingerprint =
                    ComputeFingerprint(
                        deviceId,
                        secret);

                var envelope = new IdentityEnvelope
                {
                    SchemaVersion =
                        CurrentSchemaVersion,
                    DeviceId = deviceId,
                    DeviceName = deviceName,
                    DeviceAlias = deviceName,
                    InstallationId =
                        installationId,
                    CreatedAtUtc = createdAt,
                    UpdatedAtUtc = createdAt,
                    BindingFingerprint =
                        fingerprint,
                    Protection =
                        ProtectionName,
                    ProtectedSecret =
                        Convert.ToBase64String(
                            protectedSecret)
                };

                await SaveEnvelopeAsync(
                    envelope,
                    overwrite: false,
                    cancellationToken);

                return ToSnapshot(envelope);
            }
            finally
            {
                CryptographicOperations.ZeroMemory(
                    secret);
            }
        }
        finally
        {
            _gate.Release();
        }
    }

    public Task<MachineIdentitySnapshot> SnapshotAsync(
        CancellationToken cancellationToken = default) =>
        EnsureAsync(cancellationToken);

    public async Task<MachineIdentitySnapshot> RenameAliasAsync(
        string deviceAlias,
        CancellationToken cancellationToken = default)
    {
        var normalized = NormalizeAlias(deviceAlias);

        await _gate.WaitAsync(cancellationToken);

        try
        {
            var envelope =
                await LoadAndValidateEnvelopeAsync(
                    cancellationToken);

            if (string.Equals(
                    envelope.SchemaVersion,
                    LegacySchemaVersion,
                    StringComparison.Ordinal))
            {
                envelope =
                    await UpgradeLegacyEnvelopeAsync(
                        envelope,
                        cancellationToken);
            }

            envelope.DeviceAlias = normalized;
            envelope.UpdatedAtUtc =
                _timeProvider.GetUtcNow();

            await SaveEnvelopeAsync(
                envelope,
                overwrite: true,
                cancellationToken);

            return ToSnapshot(envelope);
        }
        finally
        {
            _gate.Release();
        }
    }

    public async Task<string> CreateTunnelBindingAsync(
        string tunnelId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(
            tunnelId);

        var material =
            await ReadVerifiedSecretAsync(
                cancellationToken);

        try
        {
            using var hmac =
                new HMACSHA256(material.Secret);

            var payload =
                "zagent-tunnel-binding:" +
                material.Envelope.DeviceId
                    .ToLowerInvariant() +
                ":" +
                tunnelId.Trim();

            return Convert.ToHexString(
                    hmac.ComputeHash(
                        Encoding.UTF8.GetBytes(
                            payload)))
                .ToLowerInvariant();
        }
        finally
        {
            CryptographicOperations.ZeroMemory(
                material.Secret);
        }
    }

    public async Task<string> CreateChallengeProofAsync(
        string tunnelId,
        string nonce,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(
            tunnelId);
        ArgumentException.ThrowIfNullOrWhiteSpace(
            nonce);

        var identity =
            await EnsureAsync(cancellationToken);
        var tunnelBinding =
            await CreateTunnelBindingAsync(
                tunnelId,
                cancellationToken);

        byte[] key;
        try
        {
            key = Convert.FromHexString(
                tunnelBinding);
        }
        catch (FormatException ex)
        {
            throw new IdentityProofException(
                "Derived tunnel binding is malformed: " +
                ex.Message);
        }

        try
        {
            using var hmac =
                new HMACSHA256(key);

            var payload =
                "zagent-identity-challenge:" +
                identity.DeviceId
                    .ToLowerInvariant() +
                ":" +
                nonce.Trim();

            return Convert.ToHexString(
                    hmac.ComputeHash(
                        Encoding.UTF8.GetBytes(
                            payload)))
                .ToLowerInvariant();
        }
        finally
        {
            CryptographicOperations.ZeroMemory(key);
        }
    }

    public async Task<bool> VerifyChallengeProofAsync(
        string tunnelId,
        string nonce,
        string proof,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(proof))
        {
            return false;
        }

        var expected =
            await CreateChallengeProofAsync(
                tunnelId,
                nonce,
                cancellationToken);

        var expectedBytes =
            Encoding.ASCII.GetBytes(expected);
        var proofBytes =
            Encoding.ASCII.GetBytes(
                proof.Trim().ToLowerInvariant());

        if (expectedBytes.Length !=
            proofBytes.Length)
        {
            return false;
        }

        return CryptographicOperations
            .FixedTimeEquals(
                expectedBytes,
                proofBytes);
    }

    public async Task ValidateTargetAsync(
        string? targetDeviceId,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(
                targetDeviceId))
        {
            return;
        }

        await ValidateTargetRequiredAsync(
            targetDeviceId,
            cancellationToken);
    }

    public async Task ValidateTargetRequiredAsync(
        string? targetDeviceId,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(
                targetDeviceId))
        {
            throw new IdentityContractException(
                IdentityErrorCodes
                    .SessionIdentityRequired,
                "target_device_id is required for enforced execution.");
        }

        var identity =
            await EnsureAsync(cancellationToken);

        if (!string.Equals(
                identity.DeviceId,
                targetDeviceId.Trim(),
                StringComparison.OrdinalIgnoreCase))
        {
            throw new IdentityMismatchException(
                $"target_device_id '{targetDeviceId}' does not match this Zagent device '{identity.DeviceId}'.");
        }
    }

    public static string ShortenFingerprint(
        string? fingerprint)
    {
        var value =
            (fingerprint ?? "").Trim();

        if (value.Length <= 12)
        {
            return value.ToUpperInvariant();
        }

        return value[..12]
            .ToUpperInvariant();
    }

    private async Task<SecretMaterial>
        ReadVerifiedSecretAsync(
            CancellationToken cancellationToken)
    {
        await EnsureAsync(cancellationToken);

        var envelope =
            await LoadAndValidateEnvelopeAsync(
                cancellationToken);

        if (string.Equals(
                envelope.SchemaVersion,
                LegacySchemaVersion,
                StringComparison.Ordinal))
        {
            await _gate.WaitAsync(
                cancellationToken);

            try
            {
                envelope =
                    await UpgradeLegacyEnvelopeAsync(
                        envelope,
                        cancellationToken);
            }
            finally
            {
                _gate.Release();
            }
        }

        var clearSecret =
            UnprotectEnvelopeSecret(envelope);

        ValidateFingerprint(
            envelope,
            clearSecret);

        return new SecretMaterial(
            envelope,
            clearSecret);
    }

    private async Task<IdentityEnvelope>
        LoadAndValidateEnvelopeAsync(
            CancellationToken cancellationToken)
    {
        IdentityEnvelope envelope;

        try
        {
            var json =
                await File.ReadAllTextAsync(
                    _path,
                    cancellationToken);

            envelope =
                JsonSerializer
                    .Deserialize<IdentityEnvelope>(
                        json,
                        JsonOptions) ??
                throw new InvalidDataException(
                    "Machine identity file is empty.");
        }
        catch (JsonException ex)
        {
            throw new IdentityMismatchException(
                "Machine identity file is invalid JSON: " +
                ex.Message);
        }

        if (!string.Equals(
                envelope.SchemaVersion,
                CurrentSchemaVersion,
                StringComparison.Ordinal) &&
            !string.Equals(
                envelope.SchemaVersion,
                LegacySchemaVersion,
                StringComparison.Ordinal))
        {
            throw new IdentityMismatchException(
                $"Unsupported identity schema '{envelope.SchemaVersion}'.");
        }

        if (!Guid.TryParse(
                envelope.DeviceId,
                out _))
        {
            throw new IdentityMismatchException(
                "device_id is not a valid UUID.");
        }

        if (string.IsNullOrWhiteSpace(
                envelope.ProtectedSecret))
        {
            throw new IdentityMismatchException(
                "Protected machine secret is missing.");
        }

        var clearSecret =
            UnprotectEnvelopeSecret(envelope);

        try
        {
            if (clearSecret.Length != 32)
            {
                throw new IdentityMismatchException(
                    "Machine secret length is invalid.");
            }

            ValidateFingerprint(
                envelope,
                clearSecret);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(
                clearSecret);
        }

        return envelope;
    }

    private async Task<IdentityEnvelope>
        UpgradeLegacyEnvelopeAsync(
            IdentityEnvelope legacy,
            CancellationToken cancellationToken)
    {
        if (!string.Equals(
                legacy.SchemaVersion,
                LegacySchemaVersion,
                StringComparison.Ordinal))
        {
            return legacy;
        }

        legacy.SchemaVersion =
            CurrentSchemaVersion;
        legacy.DeviceAlias =
            string.IsNullOrWhiteSpace(
                    legacy.DeviceName)
                ? GetMachineName()
                : legacy.DeviceName.Trim();
        legacy.InstallationId =
            string.IsNullOrWhiteSpace(
                    legacy.InstallationId)
                ? Guid.NewGuid()
                    .ToString("D")
                    .ToLowerInvariant()
                : legacy.InstallationId;
        legacy.UpdatedAtUtc =
            _timeProvider.GetUtcNow();

        await SaveEnvelopeAsync(
            legacy,
            overwrite: true,
            cancellationToken);

        return legacy;
    }

    private async Task SaveEnvelopeAsync(
        IdentityEnvelope envelope,
        bool overwrite,
        CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(
            Path.GetDirectoryName(_path)!);

        var temporary =
            _path + ".tmp." +
            Guid.NewGuid().ToString("N");

        var json =
            JsonSerializer.Serialize(
                envelope,
                JsonOptions);

        await File.WriteAllTextAsync(
            temporary,
            json + Environment.NewLine,
            new UTF8Encoding(false),
            cancellationToken);

        try
        {
            if (!overwrite)
            {
                try
                {
                    File.Move(
                        temporary,
                        _path,
                        overwrite: false);
                    return;
                }
                catch (IOException)
                    when (File.Exists(_path))
                {
                    return;
                }
            }

            var backup = _path + ".bak";

            if (File.Exists(_path))
            {
                File.Copy(
                    _path,
                    backup,
                    overwrite: true);
            }

            File.Move(
                temporary,
                _path,
                overwrite: true);
        }
        finally
        {
            try
            {
                if (File.Exists(temporary))
                {
                    File.Delete(temporary);
                }
            }
            catch
            {
            }
        }
    }

    private static MachineIdentitySnapshot ToSnapshot(
        IdentityEnvelope envelope) =>
        new(
            envelope.DeviceId,
            string.IsNullOrWhiteSpace(
                    envelope.DeviceName)
                ? "Zagent Device"
                : envelope.DeviceName.Trim(),
            envelope.BindingFingerprint,
            envelope.CreatedAtUtc,
            "verified",
            string.IsNullOrWhiteSpace(
                    envelope.Protection)
                ? ProtectionName
                : envelope.Protection,
            string.IsNullOrWhiteSpace(
                    envelope.DeviceAlias)
                ? envelope.DeviceName
                : envelope.DeviceAlias.Trim(),
            envelope.InstallationId,
            ShortenFingerprint(
                envelope.BindingFingerprint),
            envelope.SchemaVersion);

    private static string NormalizeAlias(
        string value)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(
            value);

        var normalized = value.Trim();

        if (normalized.Length > 80)
        {
            throw new ArgumentOutOfRangeException(
                nameof(value),
                "Device alias must be 80 characters or fewer.");
        }

        if (normalized.Any(
                ch => char.IsControl(ch)))
        {
            throw new ArgumentException(
                "Device alias cannot contain control characters.",
                nameof(value));
        }

        return normalized;
    }

    private static string GetMachineName() =>
        string.IsNullOrWhiteSpace(
                Environment.MachineName)
            ? "Zagent Device"
            : Environment.MachineName.Trim();

    private static byte[] UnprotectEnvelopeSecret(
        IdentityEnvelope envelope)
    {
        byte[] protectedSecret;

        try
        {
            protectedSecret =
                Convert.FromBase64String(
                    envelope.ProtectedSecret);
        }
        catch (FormatException)
        {
            throw new IdentityMismatchException(
                "Protected machine secret is malformed.");
        }

        try
        {
            return Unprotect(protectedSecret);
        }
        catch (IdentityContractException)
        {
            throw;
        }
        catch (Exception ex)
        {
            throw new IdentityMismatchException(
                "Machine secret cannot be decrypted on this Windows user/device. " +
                ex.Message);
        }
    }

    private static void ValidateFingerprint(
        IdentityEnvelope envelope,
        byte[] clearSecret)
    {
        var expected =
            ComputeFingerprint(
                envelope.DeviceId,
                clearSecret);

        var expectedBytes =
            Encoding.ASCII.GetBytes(expected);
        var actualBytes =
            Encoding.ASCII.GetBytes(
                envelope.BindingFingerprint ??
                "");

        if (expectedBytes.Length !=
                actualBytes.Length ||
            !CryptographicOperations
                .FixedTimeEquals(
                    expectedBytes,
                    actualBytes))
        {
            throw new IdentityMismatchException(
                "Machine identity binding fingerprint does not match.");
        }
    }

    private static string ComputeFingerprint(
        string deviceId,
        byte[] secret)
    {
        using var hmac =
            new HMACSHA256(secret);

        var bytes =
            hmac.ComputeHash(
                Encoding.UTF8.GetBytes(
                    "zagent-device-binding:" +
                    deviceId.ToLowerInvariant()));

        return Convert.ToHexString(bytes)
            .ToLowerInvariant();
    }

    private static byte[] Protect(
        byte[] clear) =>
        Crypt(clear, protect: true);

    private static byte[] Unprotect(
        byte[] encrypted) =>
        Crypt(encrypted, protect: false);

    private static byte[] Crypt(
        byte[] input,
        bool protect)
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException(
                "Machine identity binding requires Windows DPAPI.");
        }

        var inputPointer = IntPtr.Zero;
        var output = new DataBlob();

        try
        {
            inputPointer =
                Marshal.AllocHGlobal(
                    input.Length);

            Marshal.Copy(
                input,
                0,
                inputPointer,
                input.Length);

            var inputBlob = new DataBlob
            {
                Size = input.Length,
                Data = inputPointer
            };

            var success = protect
                ? CryptProtectData(
                    ref inputBlob,
                    "Zagent Machine Identity",
                    IntPtr.Zero,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    CryptProtectUiForbidden,
                    ref output)
                : CryptUnprotectData(
                    ref inputBlob,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    CryptProtectUiForbidden,
                    ref output);

            if (!success)
            {
                throw new InvalidOperationException(
                    $"Windows DPAPI failed with Win32 error {Marshal.GetLastWin32Error()}.");
            }

            var result =
                new byte[output.Size];

            Marshal.Copy(
                output.Data,
                result,
                0,
                output.Size);

            return result;
        }
        finally
        {
            if (inputPointer !=
                IntPtr.Zero)
            {
                Marshal.FreeHGlobal(
                    inputPointer);
            }

            if (output.Data !=
                IntPtr.Zero)
            {
                LocalFree(output.Data);
            }
        }
    }

    private static readonly JsonSerializerOptions
        JsonOptions =
        new()
        {
            WriteIndented = true
        };

    private sealed record SecretMaterial(
        IdentityEnvelope Envelope,
        byte[] Secret);

    private sealed class IdentityEnvelope
    {
        [JsonPropertyName("schema_version")]
        public string SchemaVersion
        {
            get;
            set;
        } = "";

        [JsonPropertyName("device_id")]
        public string DeviceId
        {
            get;
            init;
        } = "";

        [JsonPropertyName("device_name")]
        public string DeviceName
        {
            get;
            init;
        } = "";

        [JsonPropertyName("device_alias")]
        public string DeviceAlias
        {
            get;
            set;
        } = "";

        [JsonPropertyName("installation_id")]
        public string InstallationId
        {
            get;
            set;
        } = "";

        [JsonPropertyName("created_at_utc")]
        public DateTimeOffset CreatedAtUtc
        {
            get;
            init;
        }

        [JsonPropertyName("updated_at_utc")]
        public DateTimeOffset? UpdatedAtUtc
        {
            get;
            set;
        }

        [JsonPropertyName("binding_fingerprint")]
        public string BindingFingerprint
        {
            get;
            init;
        } = "";

        [JsonPropertyName("protection")]
        public string Protection
        {
            get;
            init;
        } = "";

        [JsonPropertyName("protected_secret")]
        public string ProtectedSecret
        {
            get;
            init;
        } = "";
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct DataBlob
    {
        public int Size;
        public IntPtr Data;
    }

    [DllImport(
        "Crypt32.dll",
        SetLastError = true,
        CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptProtectData(
        ref DataBlob pDataIn,
        string? szDataDescr,
        IntPtr pOptionalEntropy,
        IntPtr pvReserved,
        IntPtr pPromptStruct,
        int dwFlags,
        ref DataBlob pDataOut);

    [DllImport(
        "Crypt32.dll",
        SetLastError = true,
        CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool CryptUnprotectData(
        ref DataBlob pDataIn,
        IntPtr ppszDataDescr,
        IntPtr pOptionalEntropy,
        IntPtr pvReserved,
        IntPtr pPromptStruct,
        int dwFlags,
        ref DataBlob pDataOut);

    [DllImport(
        "Kernel32.dll",
        SetLastError = true)]
    private static extern IntPtr LocalFree(
        IntPtr hMem);
}
