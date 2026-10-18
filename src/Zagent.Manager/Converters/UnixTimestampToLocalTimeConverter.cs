using System.Globalization;
using System.Windows.Data;

namespace Zagent.Manager.Converters;

public sealed class UnixTimestampToLocalTimeConverter : IValueConverter
{
    public object Convert(
        object? value,
        Type targetType,
        object? parameter,
        CultureInfo culture)
    {
        if (value is null)
        {
            return "";
        }

        double seconds;

        try
        {
            seconds = System.Convert.ToDouble(
                value,
                CultureInfo.InvariantCulture);
        }
        catch
        {
            return "";
        }

        if (seconds <= 0)
        {
            return "";
        }

        try
        {
            var milliseconds =
                checked((long)Math.Round(seconds * 1000d));

            return DateTimeOffset
                .FromUnixTimeMilliseconds(milliseconds)
                .ToLocalTime()
                .ToString("HH:mm:ss", culture);
        }
        catch
        {
            return "";
        }
    }

    public object ConvertBack(
        object value,
        Type targetType,
        object parameter,
        CultureInfo culture) =>
        throw new NotSupportedException();
}
