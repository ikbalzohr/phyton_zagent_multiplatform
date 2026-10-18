using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;
using Zagent.Shared.Installation;

namespace Zagent.Bundle;

// Native install/repair UI only. The sole product management UI is Core's web dashboard.
public partial class MainWindow : Window
{
    private bool _busy;
    private bool _allowClose;
    private CancellationTokenSource? _cts;

    public MainWindow()
    {
        InitializeComponent();
        InstallPathBox.Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs");
        InstallPathBox.TextChanged += (_, _) => RefreshMode();
        PluginRoleBox.SelectionChanged += (_, _) => RefreshMode();
        RefreshMode();
    }

    private string SelectedRole() => PluginRoleBox.SelectedItem is ComboBoxItem { Tag: string role }
        ? ZagentInstallationProfile.Normalize(role) : "Master";

    private string TargetRoot()
    {
        if (string.IsNullOrWhiteSpace(InstallPathBox.Text)) return "";
        var selected = Path.GetFullPath(InstallPathBox.Text.Trim());
        if (File.Exists(Path.Combine(selected, "payload-manifest.json")) ||
            File.Exists(Path.Combine(selected, "Zagent.Core.exe"))) return selected;
        return InstallTargetResolver.ResolveFromBaseFolder(selected, SelectedRole());
    }

    private void RefreshMode()
    {
        if (_busy || ModeText is null) return;
        try
        {
            var target = TargetRoot();
            var existing = File.Exists(Path.Combine(target, "payload-manifest.json"));
            ModeText.Text = existing ? "Mode: verified v1 in-place update" : "Mode: fresh install";
            StatusText.Text = "Target: " + target;
        }
        catch (Exception ex) when (ex is ArgumentException or IOException or NotSupportedException)
        { StatusText.Text = ex.Message; }
    }

    private void BrowseButton_Click(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        var dialog = new OpenFolderDialog { Title = "Pilih base folder instalasi Zagent", Multiselect = false };
        if (Directory.Exists(InstallPathBox.Text)) dialog.InitialDirectory = InstallPathBox.Text;
        if (dialog.ShowDialog(this) == true) InstallPathBox.Text = dialog.FolderName;
    }

    private async void InstallButton_Click(object sender, RoutedEventArgs e)
    {
        if (_busy) return;
        string? payloadRoot = null;
        var previousRole = Environment.GetEnvironmentVariable("ZAGENT_INSTALLATION_ROLE");
        try
        {
            var target = TargetRoot();
            if (string.IsNullOrWhiteSpace(target)) throw new ArgumentException("Pilih base folder instalasi.");
            _busy = true;
            _cts = new CancellationTokenSource();
            ToggleUi(true);
            Environment.SetEnvironmentVariable("ZAGENT_INSTALLATION_ROLE", SelectedRole());
            var progress = new Progress<(int Percent, string Message)>(value => {
                Progress.Value = value.Percent; StatusText.Text = value.Message;
            });
            payloadRoot = await BundlePayloadReader.ExtractAsync(progress, _cts.Token);
            var result = await SetupRunner.RunAsync(payloadRoot, "install", target, progress, _cts.Token);
            if (!result.Success) throw new InvalidOperationException(result.Message);
            Progress.Value = 100;
            // Fresh installs deliberately remain NOT_CONFIGURED until out-of-band
            // certificate/account provisioning. Never downgrade to unauthenticated UI.
            var config = Path.Combine(target, "data", "config", "dashboard.json");
            if (!File.Exists(config))
            {
                StatusText.Text = "Program terpasang. Dashboard NOT_CONFIGURED: lakukan provisioning sertifikat dan akun lokal sesuai panduan v1, lalu buka shortcut Manager.";
                return;
            }
            var core = Path.Combine(target, "Zagent.Core.exe");
            var launch = new ProcessStartInfo { FileName = core, WorkingDirectory = target, UseShellExecute = true };
            launch.ArgumentList.Add("--dashboard");
            launch.ArgumentList.Add("--root");
            launch.ArgumentList.Add(target);
            launch.ArgumentList.Add("--dashboard-config");
            launch.ArgumentList.Add(config);
            using var process = Process.Start(launch) ?? throw new InvalidOperationException("Core dashboard launcher gagal dimulai.");
            _allowClose = true;
        }
        catch (OperationCanceledException) { StatusText.Text = "Operasi dibatalkan."; }
        catch (Exception ex)
        {
            StatusText.Text = "Gagal: " + ex.Message;
            MessageBox.Show(this, ex.Message, "Zagent Setup", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        finally
        {
            BundlePayloadReader.Cleanup(payloadRoot);
            Environment.SetEnvironmentVariable("ZAGENT_INSTALLATION_ROLE", previousRole);
            _cts?.Dispose(); _cts = null; _busy = false; ToggleUi(false);
        }
        if (_allowClose) Close();
    }

    private void ToggleUi(bool running)
    {
        InstallPathBox.IsEnabled = BrowseButton.IsEnabled = PluginRoleBox.IsEnabled = InstallButton.IsEnabled = !running;
        InstallButton.Visibility = running ? Visibility.Collapsed : Visibility.Visible;
        CancelButton.IsEnabled = true;
    }
    private void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        if (_busy) { _cts?.Cancel(); StatusText.Text = "Membatalkan..."; return; }
        _allowClose = true; Close();
    }
    protected override void OnClosing(System.ComponentModel.CancelEventArgs e)
    {
        if (_busy && !_allowClose) { _cts?.Cancel(); e.Cancel = true; return; }
        base.OnClosing(e);
    }
}
