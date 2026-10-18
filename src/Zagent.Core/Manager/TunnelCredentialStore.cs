using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using Zagent.Shared.Manager;

namespace Zagent.Core.Manager;

public sealed record TunnelCredentials(
    string TunnelId,
    string ApiKey);

public sealed class TunnelCredentialStore
{
    private readonly string _path;

    public TunnelCredentialStore(string path)
    {
        _path = Path.GetFullPath(
            path ?? throw new ArgumentNullException(nameof(path)));
    }

    public async Task<TunnelCredentials?> LoadAsync(
        CancellationToken cancellationToken = default)
    {
        if (!File.Exists(_path))
        {
            return null;
        }

        var json = await File.ReadAllTextAsync(
            _path,
            cancellationToken);

        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;

        var protectedPayload = root.TryGetProperty(
            "protected_payload",
            out var payload)
            ? payload.GetString()
            : null;

        if (string.IsNullOrWhiteSpace(protectedPayload))
        {
            return null;
        }

        var protectedBytes = Convert.FromBase64String(
            protectedPayload);

        var clear = Unprotect(protectedBytes);

        try
        {
            return JsonSerializer.Deserialize<TunnelCredentials>(
                clear);
        }
        finally
        {
            Array.Clear(clear);
        }
    }

    public async Task SaveAsync(
        TunnelCredentials credentials,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(credentials);
        ArgumentException.ThrowIfNullOrWhiteSpace(
            credentials.TunnelId);
        ArgumentException.ThrowIfNullOrWhiteSpace(
            credentials.ApiKey);

        Directory.CreateDirectory(
            Path.GetDirectoryName(_path)!);

        var clear = JsonSerializer.SerializeToUtf8Bytes(
            credentials);

        byte[] encrypted;
        try
        {
            encrypted = Protect(clear);
        }
        finally
        {
            Array.Clear(clear);
        }

        var envelope = new
        {
            schema_version = 1,
            protection = "Windows DPAPI CurrentUser",
            protected_payload = Convert.ToBase64String(encrypted)
        };

        var temporary = _path + ".tmp";
        await File.WriteAllTextAsync(
            temporary,
            JsonSerializer.Serialize(
                envelope,
                new JsonSerializerOptions
                {
                    WriteIndented = true
                }) + Environment.NewLine,
            Encoding.UTF8,
            cancellationToken);

        File.Move(
            temporary,
            _path,
            overwrite: true);
    }

    public async Task<ManagerTunnelSettingsSnapshot> SnapshotAsync(
        CancellationToken cancellationToken = default)
    {
        var credentials = await LoadAsync(
            cancellationToken);

        if (credentials is null)
        {
            return new ManagerTunnelSettingsSnapshot(
                "",
                false,
                "Not configured",
                false,
                "Windows DPAPI CurrentUser");
        }

        return new ManagerTunnelSettingsSnapshot(
            credentials.TunnelId,
            true,
            Mask(credentials.ApiKey),
            true,
            "Windows DPAPI CurrentUser");
    }

    private static string Mask(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return "Not configured";
        }

        var visible = Math.Min(4, value.Length);
        return new string('•', Math.Max(8, value.Length - visible)) +
            value[^visible..];
    }

    private static byte[] Protect(byte[] clear) =>
        Crypt(clear, protect: true);

    private static byte[] Unprotect(byte[] encrypted) =>
        Crypt(encrypted, protect: false);

    private static byte[] Crypt(
        byte[] input,
        bool protect)
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException(
                "Tunnel credential protection requires Windows.");
        }

        var inputPtr = IntPtr.Zero;
        var output = new DataBlob();

        try
        {
            inputPtr = Marshal.AllocHGlobal(
                input.Length);
            Marshal.Copy(
                input,
                0,
                inputPtr,
                input.Length);

            var inputBlob = new DataBlob
            {
                Size = input.Length,
                Data = inputPtr
            };

            var success = protect
                ? CryptProtectData(
                    ref inputBlob,
                    "Zagent Tunnel Credentials",
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

            var result = new byte[output.Size];
            Marshal.Copy(
                output.Data,
                result,
                0,
                output.Size);
            return result;
        }
        finally
        {
            if (inputPtr != IntPtr.Zero)
            {
                Marshal.FreeHGlobal(inputPtr);
            }

            if (output.Data != IntPtr.Zero)
            {
                LocalFree(output.Data);
            }
        }
    }

    private const int CryptProtectUiForbidden = 0x1;

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
