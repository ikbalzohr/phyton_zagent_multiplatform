using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Zagent.Core.Dashboard;

public static class DashboardRevision
{
    public static string Profiles(JsonElement snapshot)
    {
        var material = snapshot.GetProperty("profiles").GetRawText() + "\n" +
            snapshot.GetProperty("pendingApprovals").GetRawText() + "\n" + snapshot.GetProperty("defaultProfile").GetRawText();
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(material)));
    }
}
