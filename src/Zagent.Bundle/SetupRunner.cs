using System.IO;
using System.Diagnostics;
using System.Text.Json;

namespace Zagent.Bundle;

public sealed record SetupRunResult(
    bool Success,
    string Message,
    int ExitCode);

public static class SetupRunner
{
    public static async Task<SetupRunResult> RunAsync(
        string payloadRoot,
        string mode,
        string targetRoot,
        IProgress<(int Percent, string Message)>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var setup = Path.Combine(
            payloadRoot,
            "Zagent.Setup.exe");

        if (!File.Exists(setup))
        {
            throw new FileNotFoundException(
                "Bundled Zagent.Setup.exe was not found.",
                setup);
        }

        var info = new ProcessStartInfo
        {
            FileName = setup,
            WorkingDirectory = payloadRoot,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };

        info.ArgumentList.Add(mode);
        info.ArgumentList.Add("--target");
        info.ArgumentList.Add(Path.GetFullPath(targetRoot));

        if (mode is "install" or "repair" or "verify")
        {
            info.ArgumentList.Add("--source");
            info.ArgumentList.Add(payloadRoot);
        }

        info.ArgumentList.Add("--product-version");
        info.ArgumentList.Add("1.0.0");
        if (mode == "uninstall")
        {
            info.ArgumentList.Add("--keep-data");
            info.ArgumentList.Add("true");
        }

        using var process = Process.Start(info) ??
            throw new InvalidOperationException(
                "Could not start bundled Zagent Setup engine.");

        var stderrTask = process.StandardError.ReadToEndAsync(
            cancellationToken);

        string lastMessage = "";

        while (true)
        {
            cancellationToken.ThrowIfCancellationRequested();

            var line = await process.StandardOutput.ReadLineAsync(
                cancellationToken);

            if (line is null)
            {
                break;
            }

            try
            {
                using var document = JsonDocument.Parse(line);
                var root = document.RootElement;
                var type = root.TryGetProperty("type", out var t)
                    ? t.GetString()
                    : null;

                if (type == "progress")
                {
                    var percent = root.TryGetProperty("percent", out var p)
                        ? p.GetInt32()
                        : 0;
                    var message = root.TryGetProperty("message", out var m)
                        ? m.GetString() ?? ""
                        : "";

                    var mapped = 25 + (int)Math.Round(percent * 0.73);
                    progress?.Report((Math.Clamp(mapped, 25, 98), message));
                    lastMessage = message;
                }
                else if (type == "result")
                {
                    if (root.TryGetProperty("Message", out var messageUpper))
                    {
                        lastMessage = messageUpper.GetString() ?? lastMessage;
                    }
                    else if (root.TryGetProperty("message", out var messageLower))
                    {
                        lastMessage = messageLower.GetString() ?? lastMessage;
                    }
                }
            }
            catch (JsonException)
            {
                lastMessage = line;
            }
        }

        await process.WaitForExitAsync(cancellationToken);
        var stderr = await stderrTask;

        if (process.ExitCode != 0)
        {
            return new SetupRunResult(
                false,
                string.IsNullOrWhiteSpace(stderr)
                    ? lastMessage
                    : stderr.Trim(),
                process.ExitCode);
        }

        progress?.Report((100, "Selesai."));
        return new SetupRunResult(
            true,
            string.IsNullOrWhiteSpace(lastMessage)
                ? "Operasi selesai."
                : lastMessage,
            0);
    }
}