using System.Text.Json.Nodes;
using Zagent.Core.Configuration;

namespace Zagent.Core.Agents.ArcMap;

public sealed class ArcMapConfigurationWriter
{
    private readonly AtomicJsonFileStore _store;

    public ArcMapConfigurationWriter(
        AtomicJsonFileStore? store = null)
    {
        _store = store ?? new AtomicJsonFileStore();
    }

    public async Task WriteAsync(
        ArcMapIntegrationOptions options,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(options);

        Directory.CreateDirectory(options.DataRoot);
        Directory.CreateDirectory(options.ConfigRoot);
        Directory.CreateDirectory(options.IpcRoot);
        Directory.CreateDirectory(options.RuntimeRoot);
        Directory.CreateDirectory(options.LogRoot);

        foreach (var name in new[]
        {
            "inbox",
            "outbox",
            "archive",
            "logs"
        })
        {
            Directory.CreateDirectory(
                Path.Combine(options.IpcRoot, name));
        }

        var agentConfig = new JsonObject
        {
            ["safe_mode"] = false,
            ["allow_live_write"] = true,
            ["allow_save"] = true,
            ["allow_destructive_operations"] = true,
            ["allow_geoprocessing"] = true,
            ["allow_export"] = true,
            ["require_health_check"] = true,
            ["ipc_poll_ms"] = 500,
            ["command_timeout_seconds"] =
                options.CommandTimeoutSeconds,
            ["archive_ipc"] = true,
            ["max_title_length"] = 240,
            ["default_export_dpi"] = 400,
            ["default_export_formats"] =
                new JsonArray("PDF", "PNG"),
            ["default_output_folder"] = "Hasil Peta",
            ["default_naming"] =
                "PETA A4 <nama perusahaan> – <jenis peta>"
        };

        var paths = new JsonObject
        {
            ["work_root"] =
                Path.GetFullPath(options.EngineRoot),
            ["data_root"] =
                Path.GetFullPath(options.DataRoot),
            ["manual_baseline"] =
                string.IsNullOrWhiteSpace(
                    options.LegacyManualBaseline)
                    ? ""
                    : Path.GetFullPath(
                        options.LegacyManualBaseline),
            ["master_data_shp"] = "",
            ["sasplanet_export"] = "",
            ["default_export_folder"] = "Hasil Peta"
        };

        await _store.SaveAsync(
            Path.Combine(
                options.ConfigRoot,
                "agent_config.json"),
            agentConfig,
            cancellationToken);

        await _store.SaveAsync(
            Path.Combine(
                options.ConfigRoot,
                "paths.json"),
            paths,
            cancellationToken);

        CopyStaticConfigIfMissing(
            options.EngineRoot,
            options.ConfigRoot);
    }

    private static void CopyStaticConfigIfMissing(
        string engineRoot,
        string configRoot)
    {
        var source = Path.Combine(
            engineRoot,
            "config");

        if (!Directory.Exists(source))
        {
            return;
        }

        foreach (var file in Directory.EnumerateFiles(
            source,
            "*",
            SearchOption.AllDirectories))
        {
            var relative = Path.GetRelativePath(
                source,
                file);

            if (relative is "agent_config.json" or
                "paths.json")
            {
                continue;
            }

            var target = Path.Combine(
                configRoot,
                relative);

            if (File.Exists(target))
            {
                continue;
            }

            Directory.CreateDirectory(
                Path.GetDirectoryName(target)!);
            File.Copy(
                file,
                target,
                overwrite: false);
        }
    }
}
