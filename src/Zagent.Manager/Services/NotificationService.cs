using System.IO;
using System.Media;

namespace Zagent.Manager.Services;

public sealed class NotificationService
{
    private readonly HashSet<string> _seen =
        new(StringComparer.Ordinal);

    public void Notify(string? requestId = null)
    {
        if (!string.IsNullOrWhiteSpace(requestId) &&
            !_seen.Add(requestId))
        {
            return;
        }

        var wav = Path.Combine(
            AppContext.BaseDirectory,
            "Assets",
            "notification-kring.wav");

        try
        {
            if (File.Exists(wav))
            {
                using var player =
                    new SoundPlayer(wav);
                player.Play();
                return;
            }
        }
        catch
        {
        }

        SystemSounds.Exclamation.Play();
    }
}