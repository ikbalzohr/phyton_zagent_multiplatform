using System.IO;
using System.IO.Compression;
using System.Text;

namespace Zagent.Bundle;

public static class BundlePayloadReader
{
    private const string Magic = "ZAGENTBUNDLE0001";
    private const int FooterSize = 32;

    public static async Task<string> ExtractAsync(
        IProgress<(int Percent, string Message)>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var executable = Environment.ProcessPath ??
            throw new InvalidOperationException("Could not resolve installer executable path.");

        var tempRoot = Path.Combine(
            Path.GetTempPath(),
            "Zagent",
            "Installer",
            Guid.NewGuid().ToString("N"));

        Directory.CreateDirectory(tempRoot);

        var zipPath = Path.Combine(tempRoot, "payload.zip");
        var payloadRoot = Path.Combine(tempRoot, "payload");

        await using var source = new FileStream(
            executable,
            FileMode.Open,
            FileAccess.Read,
            FileShare.Read,
            1024 * 1024,
            FileOptions.Asynchronous | FileOptions.SequentialScan);

        if (source.Length < FooterSize)
        {
            throw new InvalidDataException("Installer bundle footer is missing.");
        }

        source.Seek(-FooterSize, SeekOrigin.End);
        var footer = new byte[FooterSize];
        await source.ReadExactlyAsync(footer, cancellationToken);

        var magic = Encoding.ASCII.GetString(footer, 0, 16);
        if (!string.Equals(magic, Magic, StringComparison.Ordinal))
        {
            throw new InvalidDataException("Installer payload signature is invalid.");
        }

        var offset = BitConverter.ToInt64(footer, 16);
        var length = BitConverter.ToInt64(footer, 24);

        if (offset < 0 ||
            length <= 0 ||
            offset + length + FooterSize != source.Length)
        {
            throw new InvalidDataException("Installer payload bounds are invalid.");
        }

        progress?.Report((2, "Mengekstrak payload installer..."));

        source.Seek(offset, SeekOrigin.Begin);

        await using (var destination = new FileStream(
            zipPath,
            FileMode.CreateNew,
            FileAccess.Write,
            FileShare.None,
            1024 * 1024,
            FileOptions.Asynchronous | FileOptions.SequentialScan))
        {
            var buffer = new byte[1024 * 1024];
            long remaining = length;
            long copied = 0;

            while (remaining > 0)
            {
                cancellationToken.ThrowIfCancellationRequested();

                var wanted = (int)Math.Min(buffer.Length, remaining);
                var read = await source.ReadAsync(
                    buffer.AsMemory(0, wanted),
                    cancellationToken);

                if (read == 0)
                {
                    throw new EndOfStreamException("Unexpected end of installer payload.");
                }

                await destination.WriteAsync(
                    buffer.AsMemory(0, read),
                    cancellationToken);

                remaining -= read;
                copied += read;

                var percent = 2 + (int)Math.Min(
                    18,
                    Math.Floor(18d * copied / length));

                progress?.Report((percent, "Mengekstrak payload installer..."));
            }
        }

        progress?.Report((21, "Membuka payload..."));
        ZipFile.ExtractToDirectory(
            zipPath,
            payloadRoot,
            overwriteFiles: false);

        var manifest = Path.Combine(
            payloadRoot,
            "payload-manifest.json");

        var setup = Path.Combine(
            payloadRoot,
            "Zagent.Setup.exe");

        if (!File.Exists(manifest) || !File.Exists(setup))
        {
            throw new InvalidDataException(
                "Bundled payload is incomplete.");
        }

        progress?.Report((25, "Payload siap."));
        return payloadRoot;
    }

    public static void Cleanup(string? payloadRoot)
    {
        if (string.IsNullOrWhiteSpace(payloadRoot))
        {
            return;
        }

        try
        {
            var tempRoot = Directory.GetParent(payloadRoot)?.FullName;
            if (!string.IsNullOrWhiteSpace(tempRoot) &&
                Directory.Exists(tempRoot))
            {
                Directory.Delete(tempRoot, recursive: true);
            }
        }
        catch
        {
        }
    }
}