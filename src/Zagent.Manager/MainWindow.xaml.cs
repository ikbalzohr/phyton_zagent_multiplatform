using System.ComponentModel;
using System.Windows;
using System.Windows.Threading;
using Zagent.Manager.Services;
using Zagent.Manager.ViewModels;

namespace Zagent.Manager;

public partial class MainWindow : Window
{
    private readonly MainViewModel _viewModel;
    private readonly CoreProcessBootstrapper _bootstrapper;
    private readonly DispatcherTimer _timer;
    private bool _allowClose;
    private bool _refreshing;

    public MainWindow(
        MainViewModel viewModel,
        CoreProcessBootstrapper bootstrapper)
    {
        InitializeComponent();

        _viewModel = viewModel ??
            throw new ArgumentNullException(nameof(viewModel));
        _bootstrapper = bootstrapper ??
            throw new ArgumentNullException(nameof(bootstrapper));

        DataContext = _viewModel;

        _viewModel.DashboardChatEntries.CollectionChanged +=
            (_, _) =>
            {
                if (!_viewModel.AutoScrollChat ||
                    DashboardChatList.Items.Count == 0)
                {
                    return;
                }

                Dispatcher.BeginInvoke(
                    () =>
                        DashboardChatList.ScrollIntoView(
                            DashboardChatList.Items[
                                DashboardChatList.Items.Count - 1]),
                    DispatcherPriority.Background);
            };

        var environment =
            Environment.GetEnvironmentVariable(
                "ZAGENT_ENVIRONMENT");

        if (!string.IsNullOrWhiteSpace(environment) &&
            !string.Equals(
                environment,
                "PRODUCTION",
                StringComparison.OrdinalIgnoreCase))
        {
            Title =
                $"Zagent Manager — {environment.ToUpperInvariant()}";
        }

        _timer = new DispatcherTimer(
            TimeSpan.FromSeconds(2),
            DispatcherPriority.Background,
            OnRefreshTick,
            Dispatcher)
        {
            IsEnabled = true
        };
    }

    protected override async void OnClosing(
        CancelEventArgs e)
    {
        if (_allowClose)
        {
            base.OnClosing(e);
            return;
        }

        if (!ShouldSkipCloseConfirmation())
        {
            var answer = MessageBox.Show(
                this,
                "Menutup Zagent Manager akan menghentikan seluruh agent yang dikelola Core, termasuk Tunnel, Files, Web, dan ArcMap.\n\nLanjutkan menutup Zagent?",
                "Tutup Zagent Manager",
                MessageBoxButton.YesNo,
                MessageBoxImage.Warning,
                MessageBoxResult.No);

            if (answer != MessageBoxResult.Yes)
            {
                e.Cancel = true;
                return;
            }
        }

        e.Cancel = true;
        _timer.Stop();

        try
        {
            await _viewModel.ShutdownCoreAsync();
        }
        finally
        {
            _bootstrapper.Dispose();
            _allowClose = true;
            Close();
        }
    }

    private static bool ShouldSkipCloseConfirmation() =>
        string.Equals(
            Environment.GetEnvironmentVariable(
                "ZAGENT_MANAGER_SKIP_CLOSE_CONFIRMATION"),
            "1",
            StringComparison.Ordinal);

    private async void SaveTunnelSettings_Click(
        object sender,
        RoutedEventArgs e)
    {
        await _viewModel.SaveTunnelSettingsAsync(
            TunnelIdBox.Text,
            TunnelApiKeyBox.Password);

        TunnelApiKeyBox.Clear();
    }

    private async void OnRefreshTick(
        object? sender,
        EventArgs e)
    {
        if (_refreshing)
        {
            return;
        }

        _refreshing = true;

        try
        {
            await _viewModel.RefreshAllAsync(
                automatic: true);
        }
        finally
        {
            _refreshing = false;
        }
    }
}