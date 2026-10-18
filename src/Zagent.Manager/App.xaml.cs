using System.Windows;
using Zagent.Manager.Services;
using Zagent.Manager.ViewModels;
using Zagent.Shared.Installation;

namespace Zagent.Manager;

public partial class App : Application
{
    private CoreProcessBootstrapper? _bootstrapper;

    protected override async void OnStartup(
        StartupEventArgs e)
    {
        base.OnStartup(e);

        var pipeName =
            Environment.GetEnvironmentVariable(
                "ZAGENT_MANAGER_PIPE") ??
            (string.Equals(Environment.GetEnvironmentVariable("ZAGENT_ENVIRONMENT"),
                "DEVELOPMENT", StringComparison.OrdinalIgnoreCase)
                ? "Zagent.Manager.Development"
                : Zagent.Shared.Manager.ManagerProtocol.ForInstallationRole(
                    Environment.GetEnvironmentVariable("ZAGENT_INSTALLATION_ROLE") ??
                        ZagentInstallationProfile.InferRole(AppContext.BaseDirectory)));

        var client = new ManagerPipeClient(pipeName);
        _bootstrapper =
            new CoreProcessBootstrapper();

        var viewModel =
            new MainViewModel(client);

        var window =
            new MainWindow(
                viewModel,
                _bootstrapper);
        if (!string.Equals(Environment.GetEnvironmentVariable("ZAGENT_ENVIRONMENT"),
            "DEVELOPMENT", StringComparison.OrdinalIgnoreCase))
            window.Title = ZagentInstallationProfile.DisplayName(
                ZagentInstallationProfile.InferRole(AppContext.BaseDirectory)) + " Manager";

        MainWindow = window;
        window.Show();

        try
        {
            await _bootstrapper.EnsureCoreAsync(
                client);
        }
        catch
        {
        }

        await viewModel.RefreshAllAsync(
            automatic: false);
    }
}
