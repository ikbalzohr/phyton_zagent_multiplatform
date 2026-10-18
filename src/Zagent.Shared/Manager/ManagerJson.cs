using System.Text.Json;
using System.Text.Json.Serialization;

namespace Zagent.Shared.Manager;

public static class ManagerJson
{
    public static JsonSerializerOptions Options { get; } = Create();

    public static JsonElement ToElement<T>(T value)
    {
        using var document = JsonDocument.Parse(
            JsonSerializer.Serialize(value, Options));
        return document.RootElement.Clone();
    }

    public static T? FromElement<T>(JsonElement? element)
    {
        if (element is null)
        {
            return default;
        }

        return element.Value.Deserialize<T>(Options);
    }

    private static JsonSerializerOptions Create()
    {
        var options = new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            PropertyNameCaseInsensitive = true,
            WriteIndented = false
        };

        options.Converters.Add(new JsonStringEnumConverter());
        return options;
    }
}
