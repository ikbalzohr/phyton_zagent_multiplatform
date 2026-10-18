using Zagent.Shared.Manager;

namespace Zagent.Manager.Services;

public static class ChatPresentation
{
    public static string BuildDisplayTitle(
        ManagerChatRow chat,
        IReadOnlyList<ManagerChatLogRow> entries)
    {
        if (!string.IsNullOrWhiteSpace(chat.Title))
        {
            return $"Chat - {chat.Title}";
        }

        var inferred = InferWorkTitle(entries);

        return string.IsNullOrWhiteSpace(inferred)
            ? "Chat"
            : $"Chat - {inferred}";
    }

    public static string Humanize(
        ManagerChatLogRow row)
    {
        if (!string.IsNullOrWhiteSpace(row.Message) &&
            string.IsNullOrWhiteSpace(row.Tool))
        {
            return row.Message;
        }

        return row.Tool switch
        {
            "files_powershell_run" =>
                "Menjalankan perintah PowerShell",
            "files_exec_command" =>
                "Menjalankan perintah sistem",
            "files_read" =>
                "Membaca file",
            "files_write" =>
                "Menulis file",
            "files_search" =>
                "Mencari isi file",
            "web_find" =>
                "Mencari elemen di halaman",
            "web_get_text" =>
                "Membaca isi halaman",
            "web_new_tab" =>
                "Membuka tab baru",
            "web_click" =>
                "Mengklik elemen halaman",
            "web_type" =>
                "Mengetik di halaman",
            "arcmap_ping" =>
                "Memeriksa koneksi ArcMap",
            "" => row.Message,
            _ when row.Tool.StartsWith(
                "arcmap_",
                StringComparison.Ordinal) =>
                "Operasi ArcMap · " +
                row.Tool[7..].Replace('_', ' '),
            _ when row.Tool.StartsWith(
                "web_",
                StringComparison.Ordinal) =>
                "Automasi web · " +
                row.Tool[4..].Replace('_', ' '),
            _ when row.Tool.StartsWith(
                "files_",
                StringComparison.Ordinal) =>
                "Operasi file · " +
                row.Tool[6..].Replace('_', ' '),
            _ => string.IsNullOrWhiteSpace(row.Message)
                ? row.Tool
                : row.Message
        };
    }

    public static string BuildEntryDisplayTitle(
        ManagerChatLogRow row)
    {
        if (!string.IsNullOrWhiteSpace(row.Title))
        {
            return $"Chat - {row.Title}";
        }

        return "Chat";
    }

    private static string NormalizeChatAlias(string alias)
    {
        if (string.IsNullOrWhiteSpace(alias))
        {
            return "Chat";
        }

        var trimmed = alias.Trim();

        if (trimmed.StartsWith(
                "Chat ",
                StringComparison.OrdinalIgnoreCase) &&
            trimmed[5..].All(char.IsDigit))
        {
            return "Chat";
        }

        return trimmed;
    }

    private static string InferWorkTitle(
        IReadOnlyList<ManagerChatLogRow> entries)
    {
        var recent = entries
            .Take(30)
            .Select(
                row =>
                    $"{row.Agent} {row.Tool} {row.Message}")
            .ToArray();

        var text = string.Join(
            " ",
            recent);

        if (text.Contains(
                "zagent",
                StringComparison.OrdinalIgnoreCase))
        {
            return "Produksi Zagent";
        }

        if (text.Contains(
                "Zagent.Manager",
                StringComparison.OrdinalIgnoreCase) ||
            text.Contains(
                "manager",
                StringComparison.OrdinalIgnoreCase))
        {
            return "Pengembangan Zagent Manager";
        }

        if (text.Contains(
                "arcmap",
                StringComparison.OrdinalIgnoreCase))
        {
            return "Pengembangan ArcMap";
        }

        if (text.Contains(
                "web_",
                StringComparison.OrdinalIgnoreCase) ||
            text.Contains(
                "chrome",
                StringComparison.OrdinalIgnoreCase))
        {
            return "Automasi Web";
        }

        if (text.Contains(
                "files_",
                StringComparison.OrdinalIgnoreCase))
        {
            return "Manajemen File";
        }

        if (text.Contains(
                "tunnel",
                StringComparison.OrdinalIgnoreCase))
        {
            return "Integrasi Zagent";
        }

        return "";
    }
}
