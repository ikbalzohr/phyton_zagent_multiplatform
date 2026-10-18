using System.IO.Compression;
using System.Text.Json;
using System.Xml.Linq;

namespace Zagent.Setup;

public static class ArcMapAddInIntegration
{
    private const string Id = "{B88AE9DB-CC43-4EA0-8B91-A72FC933D690}";
    private static string Locator => Path.Combine(Environment.GetFolderPath(
        Environment.SpecialFolder.LocalApplicationData), "Zagent", "ArcMap", "production.json");
    private static string AddInPath => Path.Combine(Environment.GetFolderPath(
        Environment.SpecialFolder.MyDocuments), "ArcGIS", "AddIns", "Desktop10.6", Id, "Zagent.ArcMap.esriaddin");

    public static void Install(string root, string dataRoot)
    {
        var package = Path.Combine(root, "agents", "arcmap", "artifacts", "Zagent.ArcMap.esriaddin");
        // Older repair payloads can legitimately predate the Add-In.
        if (!File.Exists(package)) return;
        using (var zip = ZipFile.OpenRead(package))
        {
            var entry = zip.GetEntry("config.xml") ?? throw new InvalidDataException("ArcMap Add-In manifest missing.");
            using var stream = entry.Open();
            var document = XDocument.Load(stream);
            XNamespace ns = "http://schemas.esri.com/Desktop/AddIns";
            if ((string?)document.Root?.Element(ns + "AddInID") != Id)
                throw new InvalidDataException("Unexpected ArcMap Add-In identity.");
        }
        var engine = Path.Combine(root, "agents", "arcmap", "engine");
        var arcData = Path.Combine(dataRoot, "arcmap");
        var settings = new {
            environment = "PRODUCTION",
            install_root = Path.GetFullPath(root),
            engine_root = Path.GetFullPath(engine),
            data_root = Path.GetFullPath(arcData),
            config_dir = Path.Combine(arcData, "config"),
            ipc_root = Path.Combine(arcData, "ipc")
        };
        var json = JsonSerializer.Serialize(settings, new JsonSerializerOptions { WriteIndented = true });
        Directory.CreateDirectory(Path.GetDirectoryName(Locator)!);
        Directory.CreateDirectory(Path.GetDirectoryName(AddInPath)!);
        File.WriteAllText(Locator + ".tmp", json);
        File.Copy(package, AddInPath + ".tmp", true);
        File.Move(AddInPath + ".tmp", AddInPath, true);
        File.Move(Locator + ".tmp", Locator, true);
        File.WriteAllText(Path.Combine(engine, "arcmap_bridge", "bridge_runtime.json"), json);
    }

    public static void Uninstall(string root)
    {
        if (!File.Exists(Locator)) return;
        using var json = JsonDocument.Parse(File.ReadAllText(Locator));
        if (!json.RootElement.TryGetProperty("install_root", out var saved) ||
            !string.Equals(Path.GetFullPath(root), saved.GetString(), StringComparison.OrdinalIgnoreCase)) return;
        if (File.Exists(AddInPath)) File.Delete(AddInPath);
        File.Delete(Locator);
    }
}
