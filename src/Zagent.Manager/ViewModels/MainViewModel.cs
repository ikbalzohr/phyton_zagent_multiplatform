using System.Collections.ObjectModel;
using System.IO;
using System.Windows;
using Microsoft.Win32;
using Zagent.Manager.Mvvm;
using Zagent.Manager.Services;
using Zagent.Shared.Manager;
using Zagent.Shared.Installation;

namespace Zagent.Manager.ViewModels;

public sealed class MainViewModel : ObservableObject
{
    private const int MaxVisibleChatColumns = 3;

    private readonly ManagerPipeClient _client;
    private readonly NotificationService _notifications;
    private readonly List<ManagerCapabilityRow> _allCapabilities = [];
    private readonly List<ManagerChatLogRow> _dashboardAllChatEntries = [];
    private readonly HashSet<string> _knownApprovalIds =
        new(StringComparer.Ordinal);
    private bool _connected;
    private bool _busy;
    private bool _showRecentCompleted;
    private bool _autoScrollChat = true;
    private bool _showChatHistory;
    private string _dashboardLogFilter = "Log Chat";
    private double _dashboardChatClearBefore;
    private double _pageChatClearBefore;
    private double _latestPageChatTimestamp;
    private DateTimeOffset _dashboardAgentLogClearBefore = DateTimeOffset.MinValue;
    private string _capabilitySearch = "";
    private string _statusText = "Menghubungkan ke Zagent Core...";
    private string _coreVersion = "";
    private int _capabilityCount;
    private int _runningProcesses;
    private int _activeTasks;
    private int _pendingApprovals;
    private bool _webBridgeConnected;
    private bool _webBridgeAuthorized;
    private bool _chromePersistentConsent;
    private bool _chromeReconnectAvailable;
    private int _chromeApprovedTabCount;
    private string _selectedChromeProfile = "";
    private string _chromeBoundProfile = "None";
    private string _chromeExtensionStatus = "Checking...";
    private string _chromeNativeBridgeStatus = "Checking...";
    private string _chromeNativeAttachedStatus = "Checking...";
    private string _arcMapDesktopStatus = "Checking...";
    private string _arcMapAddInStatus = "Checking...";
    private string _arcMapToolsStatus = "Checking...";
    private string _integrationActionStatus = "Ready.";
    private string _arcMapMcpStatus = "Unknown";
    private string _arcMapBridgeStatus = "Unknown";
    private string _arcMapCurrentMxdStatus = "Unknown";
    private ManagerAgentRow? _selectedAgent;
    private ManagerTaskRow? _selectedTask;
    private ManagerProfileRow? _selectedProfile;
    private ManagerFilesSessionRow? _selectedFilesSession;
    private ManagerIdentityDeviceRow? _selectedIdentityDevice;
    private ManagerIdentitySessionBindingRow? _selectedIdentitySessionBinding;
    private ManagerRouterServiceRow? _selectedRouterService;
    private ManagerApprovalRow? _selectedApproval;
    private int _routerToolCount;
    private string _routerStatus = "Checking...";
    private string _tunnelId = "";
    private string _tunnelApiKeyStatus = "Not configured";
    private string _tunnelSettingsHint = "Tunnel transport credentials are protected with Windows DPAPI.";
    private string _developmentName = "";
    private string _developmentNamespace = "";
    private string _developmentUrl = "http://127.0.0.3:18900/mcp";
    private string _deviceId = "";
    private string _deviceName = "";
    private string _deviceAlias = "";
    private string _deviceTrustState = "unknown";
    private string _deviceBindingState = "unknown";
    private string _deviceBindingFingerprint = "";
    private string _deviceShortFingerprint = "";
    private string _deviceInstallationId = "";
    private string _deviceProtection = "";
    private string _deviceTargetValidationMode = "";
    private string _deviceSessionBindingSummary = "0 active session bindings";
    private string _identityRegistrySummary = "Identity registry unavailable";
    private string _identitySessionIdInput = "";
    private string _identityOperatorAliasInput = "";
    private string _visualLatestPath = "";
    private string _visualStatus = "Waiting for visual artifact...";
    private string _visualMetadata = "";
    private ManagerArcMapWorkflowRow? _selectedArcMapWorkflow;
    private string _arcMapWorkflowEvidence = "Select a workflow run to inspect its durable evidence.";

    public MainViewModel(
        ManagerPipeClient client,
        NotificationService? notifications = null)
    {
        _client = client ??
            throw new ArgumentNullException(nameof(client));
        _notifications =
            notifications ?? new NotificationService();
        _developmentUrl = ZagentInstallationProfile.InferRole(AppContext.BaseDirectory)
            == ZagentInstallationProfile.User
                ? "http://127.0.0.3:19200/mcp"
                : "http://127.0.0.3:18900/mcp";

        RefreshCommand = new AsyncRelayCommand(
            () => RefreshAllAsync(
                automatic: false));

        StartAllCommand = new AsyncRelayCommand(
            () => LifecycleAllAsync("start"));

        StopAllCommand = new AsyncRelayCommand(
            () => LifecycleAllAsync("stop"));

        RestartAllCommand = new AsyncRelayCommand(
            () => LifecycleAllAsync("restart"));

        StartAgentCommand = new AsyncRelayCommand(
            parameter => LifecycleAgentAsync(
                parameter?.ToString(),
                "start"));

        StopAgentCommand = new AsyncRelayCommand(
            parameter => LifecycleAgentAsync(
                parameter?.ToString(),
                "stop"));

        RestartAgentCommand = new AsyncRelayCommand(
            parameter => LifecycleAgentAsync(
                parameter?.ToString(),
                "restart"));

        RefreshAgentCommand = new AsyncRelayCommand(
            parameter => LifecycleAgentAsync(
                parameter?.ToString(),
                "refresh"));

        CancelTaskCommand = new AsyncRelayCommand(
            async parameter =>
            {
                var row =
                    parameter as ManagerTaskRow ??
                    SelectedTask;

                if (row is null ||
                    !row.CanStop)
                {
                    return;
                }

                await ExecuteOperationAsync(
                    async () =>
                        await _client.SendAsync<
                            ManagerOperationResult>(
                            "task.cancel",
                            new ManagerTaskCancelRequest(
                                row.TaskId)),
                    refreshAfter: true);
            });

        ApproveCommand = new AsyncRelayCommand(
            () => ResolveApprovalAsync("approve"));

        DenyCommand = new AsyncRelayCommand(
            () => ResolveApprovalAsync("deny"));

        AddProfileCommand = new AsyncRelayCommand(
            AddProfileAsync);
        RemoveProfileCommand = new AsyncRelayCommand(
            RemoveProfileAsync);
        SwitchProfileCommand = new AsyncRelayCommand(
            SwitchProfileAsync);
        SwitchSessionProfileCommand = new AsyncRelayCommand(
            SwitchSelectedSessionProfileAsync);
        EditProfileCommand = new AsyncRelayCommand(
            EditProfileAsync);
        ToggleProfileEnabledCommand = new AsyncRelayCommand(
            ToggleProfileEnabledAsync);

        EnableRoutingCommand = new AsyncRelayCommand(
            () => RunRouterActionAsync("enable"));
        DisableRoutingCommand = new AsyncRelayCommand(
            () => RunRouterActionAsync("disable"));
        ReconnectRouterCommand = new AsyncRelayCommand(
            () => RunRouterActionAsync("reconnect"));
        TestRouterCommand = new AsyncRelayCommand(
            () => RunRouterActionAsync("test"));
        RouterToolsCommand = new AsyncRelayCommand(
            () => RunRouterActionAsync("tools"));
        ReloadRouterCommand = new AsyncRelayCommand(
            () => RunRouterActionAsync("reload"));
        SaveDeviceAliasCommand = new AsyncRelayCommand(
            SaveDeviceAliasAsync);
        ReverifyDeviceIdentityCommand = new AsyncRelayCommand(
            ReverifyDeviceIdentityAsync);
        BindIdentitySessionCommand = new AsyncRelayCommand(
            BindIdentitySessionAsync);
        SwitchIdentitySessionCommand = new AsyncRelayCommand(
            SwitchSelectedIdentitySessionAsync);
        RevokeIdentitySessionCommand = new AsyncRelayCommand(
            RevokeSelectedIdentitySessionAsync);

        AddDevelopmentCommand = new AsyncRelayCommand(
            AddDevelopmentAgentAsync);

        RemoveDevelopmentCommand = new AsyncRelayCommand(
            parameter => RemoveDevelopmentAgentAsync(
                parameter as ManagerDevelopmentAgentRow));

        ClearDashboardChatCommand = new AsyncRelayCommand(
            ClearDashboardChatAsync);

        ShowChatHistoryCommand = new AsyncRelayCommand(
            ShowChatHistoryAsync);
        ClearChatViewCommand = new AsyncRelayCommand(
            ClearChatViewAsync);
        RefreshChatCommand = new AsyncRelayCommand(
            RefreshChatPageAsync);

        RefreshIntegrationsCommand = new AsyncRelayCommand(
            RefreshIntegrationsAsync);
        ChromeOpenSetupCommand = new AsyncRelayCommand(
            () => RunIntegrationActionAsync("chrome.open_setup"));
        ChromeRepairBridgeCommand = new AsyncRelayCommand(
            () => RunIntegrationActionAsync("chrome.repair_bridge"));
        ChromeRequestAccessCommand = new AsyncRelayCommand(
            () => RunIntegrationActionAsync(
                "chrome.request_access", SelectedChromeProfile));
        ChromeDisconnectCommand = new AsyncRelayCommand(
            () => RunIntegrationActionAsync("chrome.disconnect"));
        ArcMapOpenSetupCommand = new AsyncRelayCommand(
            () => RunIntegrationActionAsync("arcmap.open_setup"));
        ArcMapRepairBridgeCommand = new AsyncRelayCommand(
            () => RunIntegrationActionAsync("arcmap.repair_bridge"));
        ArcMapCheckCommand = new AsyncRelayCommand(
            () => RunIntegrationActionAsync("arcmap.check"));
        LoadArcMapWorkflowEvidenceCommand = new AsyncRelayCommand(
            LoadSelectedArcMapWorkflowEvidenceAsync);
    }

    public ObservableCollection<ManagerAgentRow> Agents { get; } = [];

    public ObservableCollection<ManagerCapabilityRow> Capabilities { get; } = [];

    public ObservableCollection<ManagerTaskRow> Tasks { get; } = [];

    public ObservableCollection<ManagerProfileRow> Profiles { get; } = [];

    public ObservableCollection<ManagerFilesSessionRow> FilesSessions { get; } = [];

    public ObservableCollection<ManagerRouterServiceRow> RouterServices { get; } = [];

    public ObservableCollection<ManagerApprovalRow> Approvals { get; } = [];

    public ObservableCollection<string> ChromeProfileOptions { get; } = [];

    public ObservableCollection<ManagerTechnicalLogRow> TechnicalLogs { get; } = [];

    public ObservableCollection<ChatColumnViewModel> ChatColumns { get; } = [];

    public ObservableCollection<ManagerChatLogRow> DashboardChatEntries { get; } = [];

    public IReadOnlyList<string> DashboardLogFilters { get; } =
        ["Log Chat", "Tunnel", "Files", "Web", "ArcMap"];

    public ObservableCollection<ManagerDevelopmentAgentRow> DevelopmentAgents { get; } = [];
    public ObservableCollection<ManagerIdentityDeviceRow> IdentityDevices { get; } = [];
    public ObservableCollection<ManagerIdentitySessionBindingRow> IdentitySessionBindings { get; } = [];
    public ObservableCollection<ManagerArcMapWorkflowRow> ArcMapWorkflows { get; } = [];

    public AsyncRelayCommand RefreshCommand { get; }

    public AsyncRelayCommand StartAllCommand { get; }

    public AsyncRelayCommand StopAllCommand { get; }

    public AsyncRelayCommand RestartAllCommand { get; }

    public AsyncRelayCommand StartAgentCommand { get; }

    public AsyncRelayCommand StopAgentCommand { get; }

    public AsyncRelayCommand RestartAgentCommand { get; }

    public AsyncRelayCommand RefreshAgentCommand { get; }

    public AsyncRelayCommand CancelTaskCommand { get; }

    public AsyncRelayCommand ApproveCommand { get; }

    public AsyncRelayCommand DenyCommand { get; }

    public AsyncRelayCommand AddProfileCommand { get; }

    public AsyncRelayCommand RemoveProfileCommand { get; }

    public AsyncRelayCommand SwitchProfileCommand { get; }

    public AsyncRelayCommand SwitchSessionProfileCommand { get; }

    public AsyncRelayCommand EditProfileCommand { get; }

    public AsyncRelayCommand ToggleProfileEnabledCommand { get; }

    public AsyncRelayCommand EnableRoutingCommand { get; }

    public AsyncRelayCommand DisableRoutingCommand { get; }

    public AsyncRelayCommand ReconnectRouterCommand { get; }

    public AsyncRelayCommand TestRouterCommand { get; }

    public AsyncRelayCommand RouterToolsCommand { get; }

    public AsyncRelayCommand ReloadRouterCommand { get; }

    public AsyncRelayCommand SaveDeviceAliasCommand { get; }

    public AsyncRelayCommand ReverifyDeviceIdentityCommand { get; }

    public AsyncRelayCommand BindIdentitySessionCommand { get; }

    public AsyncRelayCommand SwitchIdentitySessionCommand { get; }

    public AsyncRelayCommand RevokeIdentitySessionCommand { get; }

    public AsyncRelayCommand AddDevelopmentCommand { get; }

    public AsyncRelayCommand RemoveDevelopmentCommand { get; }

    public AsyncRelayCommand ClearDashboardChatCommand { get; }

    public AsyncRelayCommand ShowChatHistoryCommand { get; }

    public AsyncRelayCommand ClearChatViewCommand { get; }

    public AsyncRelayCommand RefreshChatCommand { get; }

    public AsyncRelayCommand RefreshIntegrationsCommand { get; }

    public AsyncRelayCommand ChromeOpenSetupCommand { get; }

    public AsyncRelayCommand ChromeRepairBridgeCommand { get; }

    public AsyncRelayCommand ChromeRequestAccessCommand { get; }

    public AsyncRelayCommand ChromeDisconnectCommand { get; }

    public AsyncRelayCommand ArcMapOpenSetupCommand { get; }

    public AsyncRelayCommand ArcMapRepairBridgeCommand { get; }

    public AsyncRelayCommand ArcMapCheckCommand { get; }

    public AsyncRelayCommand LoadArcMapWorkflowEvidenceCommand { get; }

    public ManagerArcMapWorkflowRow? SelectedArcMapWorkflow
    {
        get => _selectedArcMapWorkflow;
        set => SetProperty(
            ref _selectedArcMapWorkflow,
            value);
    }

    public string ArcMapWorkflowEvidence
    {
        get => _arcMapWorkflowEvidence;
        private set => SetProperty(
            ref _arcMapWorkflowEvidence,
            value);
    }

    public string VisualLatestPath
    {
        get => _visualLatestPath;
        private set => SetProperty(
            ref _visualLatestPath,
            value);
    }

    public string VisualStatus
    {
        get => _visualStatus;
        private set => SetProperty(
            ref _visualStatus,
            value);
    }

    public string VisualMetadata
    {
        get => _visualMetadata;
        private set => SetProperty(
            ref _visualMetadata,
            value);
    }

    public bool Connected
    {
        get => _connected;
        private set => SetProperty(
            ref _connected,
            value);
    }

    public bool Busy
    {
        get => _busy;
        private set => SetProperty(
            ref _busy,
            value);
    }

    public bool ShowRecentCompleted
    {
        get => _showRecentCompleted;
        set
        {
            if (SetProperty(
                    ref _showRecentCompleted,
                    value))
            {
                _ = RefreshMonitoringAsync();
            }
        }
    }

    public bool AutoScrollChat
    {
        get => _autoScrollChat;
        set
        {
            if (SetProperty(
                    ref _autoScrollChat,
                    value) &&
                value)
            {
                _ = RefreshChatAsync();
            }
        }
    }

    public string ChatHistoryButtonText =>
        _showChatHistory ? "Show Active" : "Show History";

    public string DashboardLogFilter
    {
        get => _dashboardLogFilter;
        set
        {
            if (SetProperty(
                    ref _dashboardLogFilter,
                    value))
            {
                ApplyDashboardChatFilter();
            }
        }
    }

    public string CapabilitySearch
    {
        get => _capabilitySearch;
        set
        {
            if (SetProperty(
                    ref _capabilitySearch,
                    value))
            {
                ApplyCapabilityFilter();
            }
        }
    }

    public string StatusText
    {
        get => _statusText;
        private set => SetProperty(
            ref _statusText,
            value);
    }

    public string CoreVersion
    {
        get => _coreVersion;
        private set => SetProperty(
            ref _coreVersion,
            value);
    }

    public int CapabilityCount
    {
        get => _capabilityCount;
        private set => SetProperty(
            ref _capabilityCount,
            value);
    }

    public int RunningProcesses
    {
        get => _runningProcesses;
        private set => SetProperty(
            ref _runningProcesses,
            value);
    }

    public int ActiveTasks
    {
        get => _activeTasks;
        private set => SetProperty(
            ref _activeTasks,
            value);
    }

    public int PendingApprovals
    {
        get => _pendingApprovals;
        private set => SetProperty(
            ref _pendingApprovals,
            value);
    }

    public bool WebBridgeConnected
    {
        get => _webBridgeConnected;
        private set
        {
            if (SetProperty(
                    ref _webBridgeConnected,
                    value))
            {
                Raise(nameof(WebBridgeConnectionStatus));
                Raise(nameof(ChromeNativeBridgeStatus));
            }
        }
    }

    public bool WebBridgeAuthorized
    {
        get => _webBridgeAuthorized;
        private set
        {
            if (SetProperty(
                    ref _webBridgeAuthorized,
                    value))
            {
                Raise(nameof(WebBridgeAuthorizationStatus));
            }
        }
    }

    public string WebBridgeConnectionStatus =>
        WebBridgeConnected ? "Connected" : "Disconnected";

    public string WebBridgeAuthorizationStatus =>
        WebBridgeAuthorized ? "Authorized" : "Not authorized";

    public string SelectedChromeProfile
    {
        get => _selectedChromeProfile;
        set => SetProperty(ref _selectedChromeProfile, value);
    }

    public string ChromeBoundProfile => _chromeBoundProfile;

    public string ChromeConsentStatus =>
        _chromePersistentConsent ? "Persistent - until Disconnect" : "Not approved";

    public string ChromeReconnectStatus =>
        _chromeReconnectAvailable ? "Enabled for this profile" : "Not available";

    public string ChromeApprovedTabsStatus =>
        _chromeApprovedTabCount.ToString();

    public string ChromeExtensionStatus
    {
        get => _chromeExtensionStatus;
        private set => SetProperty(
            ref _chromeExtensionStatus,
            value);
    }

    public string ChromeNativeBridgeStatus
    {
        get => _chromeNativeBridgeStatus;
        private set => SetProperty(
            ref _chromeNativeBridgeStatus,
            value);
    }

    public string ChromeNativeAttachedStatus
    {
        get => _chromeNativeAttachedStatus;
        private set => SetProperty(
            ref _chromeNativeAttachedStatus,
            value);
    }

    public string IntegrationActionStatus
    {
        get => _integrationActionStatus;
        private set => SetProperty(
            ref _integrationActionStatus,
            value);
    }

    public string ArcMapMcpStatus
    {
        get => _arcMapMcpStatus;
        private set => SetProperty(ref _arcMapMcpStatus, value);
    }

    public string ArcMapBridgeStatus
    {
        get => _arcMapBridgeStatus;
        private set => SetProperty(ref _arcMapBridgeStatus, value);
    }

    public string ArcMapCurrentMxdStatus
    {
        get => _arcMapCurrentMxdStatus;
        private set => SetProperty(ref _arcMapCurrentMxdStatus, value);
    }

    public string ArcMapDesktopStatus
    {
        get => _arcMapDesktopStatus;
        private set => SetProperty(
            ref _arcMapDesktopStatus,
            value);
    }

    public string ArcMapAddInStatus
    {
        get => _arcMapAddInStatus;
        private set => SetProperty(
            ref _arcMapAddInStatus,
            value);
    }

    public string ArcMapToolsStatus
    {
        get => _arcMapToolsStatus;
        private set => SetProperty(
            ref _arcMapToolsStatus,
            value);
    }

    public ManagerAgentRow? SelectedAgent
    {
        get => _selectedAgent;
        set => SetProperty(
            ref _selectedAgent,
            value);
    }

    public ManagerTaskRow? SelectedTask
    {
        get => _selectedTask;
        set => SetProperty(
            ref _selectedTask,
            value);
    }

    public ManagerProfileRow? SelectedProfile
    {
        get => _selectedProfile;
        set => SetProperty(
            ref _selectedProfile,
            value);
    }

    public ManagerFilesSessionRow? SelectedFilesSession
    {
        get => _selectedFilesSession;
        set => SetProperty(
            ref _selectedFilesSession,
            value);
    }

    public ManagerIdentityDeviceRow? SelectedIdentityDevice
    {
        get => _selectedIdentityDevice;
        set => SetProperty(
            ref _selectedIdentityDevice,
            value);
    }

    public ManagerIdentitySessionBindingRow? SelectedIdentitySessionBinding
    {
        get => _selectedIdentitySessionBinding;
        set => SetProperty(
            ref _selectedIdentitySessionBinding,
            value);
    }

    public ManagerRouterServiceRow? SelectedRouterService
    {
        get => _selectedRouterService;
        set => SetProperty(
            ref _selectedRouterService,
            value);
    }

    public int RouterToolCount
    {
        get => _routerToolCount;
        private set => SetProperty(
            ref _routerToolCount,
            value);
    }

    public string RouterStatus
    {
        get => _routerStatus;
        private set => SetProperty(
            ref _routerStatus,
            value);
    }

    public ManagerApprovalRow? SelectedApproval
    {
        get => _selectedApproval;
        set => SetProperty(
            ref _selectedApproval,
            value);
    }

    public string TunnelId
    {
        get => _tunnelId;
        set => SetProperty(
            ref _tunnelId,
            value);
    }

    public string TunnelApiKeyStatus
    {
        get => _tunnelApiKeyStatus;
        private set => SetProperty(
            ref _tunnelApiKeyStatus,
            value);
    }

    public string TunnelSettingsHint
    {
        get => _tunnelSettingsHint;
        private set => SetProperty(
            ref _tunnelSettingsHint,
            value);
    }

    public string DevelopmentName
    {
        get => _developmentName;
        set => SetProperty(
            ref _developmentName,
            value);
    }

    public string DevelopmentNamespace
    {
        get => _developmentNamespace;
        set => SetProperty(
            ref _developmentNamespace,
            value);
    }

    public string DevelopmentUrl
    {
        get => _developmentUrl;
        set => SetProperty(
            ref _developmentUrl,
            value);
    }

    public string DeviceId
    {
        get => _deviceId;
        private set => SetProperty(
            ref _deviceId,
            value);
    }

    public string DeviceName
    {
        get => _deviceName;
        private set => SetProperty(
            ref _deviceName,
            value);
    }

    public string DeviceAlias
    {
        get => _deviceAlias;
        set => SetProperty(
            ref _deviceAlias,
            value);
    }

    public string DeviceTrustState
    {
        get => _deviceTrustState;
        private set => SetProperty(
            ref _deviceTrustState,
            value);
    }

    public string DeviceShortFingerprint
    {
        get => _deviceShortFingerprint;
        private set => SetProperty(
            ref _deviceShortFingerprint,
            value);
    }

    public string DeviceInstallationId
    {
        get => _deviceInstallationId;
        private set => SetProperty(
            ref _deviceInstallationId,
            value);
    }

    public string DeviceSessionBindingSummary
    {
        get => _deviceSessionBindingSummary;
        private set => SetProperty(
            ref _deviceSessionBindingSummary,
            value);
    }

    public string IdentityRegistrySummary
    {
        get => _identityRegistrySummary;
        private set => SetProperty(
            ref _identityRegistrySummary,
            value);
    }

    public string IdentitySessionIdInput
    {
        get => _identitySessionIdInput;
        set => SetProperty(
            ref _identitySessionIdInput,
            value);
    }

    public string IdentityOperatorAliasInput
    {
        get => _identityOperatorAliasInput;
        set => SetProperty(
            ref _identityOperatorAliasInput,
            value);
    }

    public string DeviceBindingState
    {
        get => _deviceBindingState;
        private set => SetProperty(
            ref _deviceBindingState,
            value);
    }

    public string DeviceBindingFingerprint
    {
        get => _deviceBindingFingerprint;
        private set => SetProperty(
            ref _deviceBindingFingerprint,
            value);
    }

    public string DeviceProtection
    {
        get => _deviceProtection;
        private set => SetProperty(
            ref _deviceProtection,
            value);
    }

    public string DeviceTargetValidationMode
    {
        get => _deviceTargetValidationMode;
        private set => SetProperty(
            ref _deviceTargetValidationMode,
            value);
    }

    public async Task RefreshAllAsync(
        bool automatic)
    {
        if (Busy && automatic)
        {
            return;
        }

        Busy = true;

        try
        {
            var dashboard =
                await _client.SendAsync<
                    ManagerDashboardSnapshot>(
                    "manager.dashboard");

            Connected = true;
            ApplyDashboard(dashboard);

            if (_allCapabilities.Count == 0 ||
                !automatic)
            {
                var capabilities =
                    await _client.SendAsync<
                        IReadOnlyList<
                            ManagerCapabilityRow>>(
                        "registry.capabilities");

                _allCapabilities.Clear();
                _allCapabilities.AddRange(
                    capabilities);
                ApplyCapabilityFilter();
            }

            await Task.WhenAll(
                RefreshMonitoringAsync(),
                RefreshProfilesAsync(),
                RefreshRouterAsync(),
                RefreshTunnelSettingsAsync(),
                RefreshMachineIdentityAsync(),
                RefreshDevelopmentAgentsAsync(),
                RefreshIntegrationsAsync(),
                RefreshVisualAsync(),
                AutoScrollChat || !automatic
                    ? RefreshChatAsync()
                    : Task.CompletedTask,
                RefreshLogsAsync());

            StatusText =
                $"Terhubung - diperbarui {DateTime.Now:HH:mm:ss}";
        }
        catch (Exception ex)
        {
            Connected = false;
            StatusText =
                "Core tidak terhubung - " +
                ex.Message;
        }
        finally
        {
            Busy = false;
        }
    }

    public async Task ShutdownCoreAsync()
    {
        await _client.RequestShutdownAsync();
    }

    private void ApplyDashboard(
        ManagerDashboardSnapshot snapshot)
    {
        CoreVersion = snapshot.CoreVersion;
        CapabilityCount =
            snapshot.CapabilityCount;
        RunningProcesses =
            snapshot.RunningProcesses;
        ActiveTasks =
            snapshot.ActiveTasks;

        Replace(
            Agents,
            snapshot.Agents);

        var arcMap = Agents.FirstOrDefault(
            item => item.AgentId == "arcmap.service");

        ArcMapMcpStatus = arcMap is null
            ? "Not detected"
            : arcMap.ProcessState == "Running"
                ? "Running"
                : arcMap.ProcessState;

        var arcMapDetail = arcMap?.Detail ?? "";
        var bridgeOffline = arcMapDetail.Contains(
            "bridge offline",
            StringComparison.OrdinalIgnoreCase) ||
            arcMapDetail.Contains(
                "CURRENT-MXD bridge offline",
                StringComparison.OrdinalIgnoreCase);

        ArcMapBridgeStatus = arcMap is null
            ? "Not detected"
            : bridgeOffline
                ? "Disconnected"
                : arcMap.Health.ToString();

        ArcMapCurrentMxdStatus = bridgeOffline
            ? "Not attached"
            : arcMap is null
                ? "Unknown"
                : "Check live bridge";

        SelectedAgent ??= Agents.FirstOrDefault();
    }

    private async Task RefreshMonitoringAsync()
    {
        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerMonitoringSnapshot>(
                    "monitoring.snapshot",
                    new ManagerRefreshRequest(
                        IncludeCompletedTasks:
                            ShowRecentCompleted,
                        TaskLimit: 100,
                        ChatLogLimit: 500));

            Replace(
                Tasks,
                snapshot.Tasks);

            ActiveTasks =
                snapshot.Tasks.Count(
                    item =>
                        item.State is not "succeeded" and
                        not "failed" and
                        not "cancelled");

            if (SelectedTask is not null)
            {
                SelectedTask =
                    Tasks.FirstOrDefault(
                        item =>
                            item.TaskId ==
                            SelectedTask.TaskId);
            }

            await RefreshArcMapWorkflowsAsync(
                snapshot.Chats);
        }
        catch
        {
        }
    }

    private async Task RefreshArcMapWorkflowsAsync(
        IReadOnlyList<ManagerChatRow> chats)
    {
        var selectedRunId =
            SelectedArcMapWorkflow?.RunId;
        var rows =
            new List<ManagerArcMapWorkflowRow>();

        foreach (var chat in chats
                     .Where(
                         item =>
                             !string.IsNullOrWhiteSpace(
                                 item.SessionId))
                     .Take(20))
        {
            try
            {
                var snapshot =
                    await _client.SendAsync<
                        ManagerArcMapWorkflowSnapshot>(
                        "arcmap.workflow.snapshot",
                        new ManagerArcMapWorkflowRequest(
                            chat.SessionId,
                            50));

                rows.AddRange(
                    snapshot.Runs);
            }
            catch
            {
            }
        }

        Replace(
            ArcMapWorkflows,
            rows
                .OrderByDescending(
                    item =>
                        item.UpdatedAt ??
                        item.CreatedAt ??
                        0)
                .Take(200)
                .ToArray());

        SelectedArcMapWorkflow =
            string.IsNullOrWhiteSpace(
                selectedRunId)
                ? ArcMapWorkflows.FirstOrDefault()
                : ArcMapWorkflows.FirstOrDefault(
                    item =>
                        item.RunId ==
                        selectedRunId) ??
                  ArcMapWorkflows.FirstOrDefault();
    }

    private async Task LoadSelectedArcMapWorkflowEvidenceAsync()
    {
        var selected =
            SelectedArcMapWorkflow;

        if (selected is null)
        {
            ArcMapWorkflowEvidence =
                "Select a workflow run to inspect its durable evidence.";
            return;
        }

        try
        {
            var evidence =
                await _client.SendAsync<
                    ManagerArcMapWorkflowEvidence>(
                    "arcmap.workflow.evidence",
                    new ManagerArcMapWorkflowEvidenceRequest(
                        selected.SessionId,
                        selected.RunId));

            ArcMapWorkflowEvidence =
                evidence.Report.ToString();
        }
        catch (Exception ex)
        {
            ArcMapWorkflowEvidence =
                "Evidence unavailable: " +
                ex.Message;
        }
    }

    private async Task RefreshProfilesAsync()
    {
        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerProfilesSnapshot>(
                    "profiles.snapshot");

            Replace(
                Profiles,
                snapshot.Profiles);

            Replace(
                FilesSessions,
                snapshot.Sessions);

            Replace(
                Approvals,
                snapshot.PendingApprovals);

            PendingApprovals =
                snapshot.PendingApprovals.Count;
            WebBridgeConnected =
                snapshot.WebBridgeConnected;
            WebBridgeAuthorized =
                snapshot.WebBridgeAuthorized;

            foreach (var request in snapshot.PendingApprovals)
            {
                if (!string.IsNullOrWhiteSpace(
                        request.RequestId) &&
                    _knownApprovalIds.Add(
                        request.RequestId))
                {
                    _notifications.Notify(
                        request.RequestId);
                }
            }

            if (SelectedProfile is not null)
            {
                SelectedProfile =
                    Profiles.FirstOrDefault(
                        item =>
                            item.Name ==
                            SelectedProfile.Name);
            }

            if (SelectedFilesSession is not null)
            {
                SelectedFilesSession =
                    FilesSessions.FirstOrDefault(
                        item =>
                            item.SessionId ==
                            SelectedFilesSession.SessionId);
            }

            if (SelectedApproval is not null)
            {
                SelectedApproval =
                    Approvals.FirstOrDefault(
                        item =>
                            item.RequestId ==
                            SelectedApproval.RequestId);
            }
        }
        catch
        {
        }
    }

    private async Task RefreshRouterAsync()
    {
        try
        {
            var snapshot =
                await _client.SendAsync<ManagerRouterSnapshot>(
                    "router.snapshot");

            var selectedId = SelectedRouterService?.Id;

            Replace(
                RouterServices,
                snapshot.Services);

            RouterToolCount = snapshot.ToolCount;
            RouterStatus = snapshot.RouterStatus;

            SelectedRouterService =
                string.IsNullOrWhiteSpace(selectedId)
                    ? RouterServices.FirstOrDefault()
                    : RouterServices.FirstOrDefault(
                        item => item.Id == selectedId) ??
                        RouterServices.FirstOrDefault();
        }
        catch
        {
            RouterStatus = "Offline";
            RouterToolCount = 0;
        }
    }

    private async Task RefreshMachineIdentityAsync()
    {
        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerMachineIdentitySnapshot>(
                    "identity.snapshot");

            DeviceId = snapshot.DeviceId;
            DeviceName = snapshot.DeviceName;
            DeviceAlias = string.IsNullOrWhiteSpace(
                    snapshot.DeviceAlias)
                ? snapshot.DeviceName
                : snapshot.DeviceAlias;
            DeviceTrustState = snapshot.TrustState;
            DeviceBindingState = snapshot.BindingState;
            DeviceBindingFingerprint =
                string.IsNullOrWhiteSpace(
                    snapshot.BindingFingerprint)
                    ? ""
                    : snapshot.BindingFingerprint.Length > 20
                        ? snapshot.BindingFingerprint[..20] + "..."
                        : snapshot.BindingFingerprint;
            DeviceShortFingerprint =
                snapshot.ShortFingerprint;
            DeviceInstallationId =
                snapshot.InstallationId;
            DeviceProtection = snapshot.Protection;
            DeviceTargetValidationMode =
                snapshot.TargetValidationMode;
            ApplyIdentityRoutingSnapshot(snapshot);
        }
        catch (Exception ex)
        {
            DeviceBindingState =
                "unavailable - " +
                ex.Message;
        }
    }

    private void ApplyIdentityRoutingSnapshot(
        ManagerMachineIdentitySnapshot snapshot)
    {
        DeviceSessionBindingSummary =
            $"{snapshot.SessionBindingCount} active session binding(s) · no silent fallback={snapshot.NoSilentFallback.ToString().ToLowerInvariant()}";
        IdentityRegistrySummary =
            $"{(snapshot.Devices?.Count ?? 0)} trusted/known device(s) · registry={snapshot.RegistryScope} · shared={snapshot.SharedAuthorityConfigured.ToString().ToLowerInvariant()}";
        Replace(
            IdentityDevices,
            snapshot.Devices ??
            Array.Empty<ManagerIdentityDeviceRow>());
        Replace(
            IdentitySessionBindings,
            snapshot.SessionBindings ??
            Array.Empty<ManagerIdentitySessionBindingRow>());
    }

    private async Task SaveDeviceAliasAsync()
    {
        var alias = DeviceAlias.Trim();
        if (string.IsNullOrWhiteSpace(alias))
        {
            return;
        }

        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerMachineIdentitySnapshot>(
                    "identity.rename",
                    new ManagerMachineIdentityRenameRequest(
                        alias));

            DeviceAlias = snapshot.DeviceAlias;
            DeviceTrustState = snapshot.TrustState;
            ApplyIdentityRoutingSnapshot(snapshot);
        }
        catch (Exception ex)
        {
            DeviceTrustState =
                "alias update failed - " +
                ex.Message;
        }
    }

    private async Task ReverifyDeviceIdentityAsync()
    {
        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerMachineIdentitySnapshot>(
                    "identity.reverify");

            DeviceTrustState = snapshot.TrustState;
            ApplyIdentityRoutingSnapshot(snapshot);
        }
        catch (Exception ex)
        {
            DeviceTrustState =
                "reverify failed - " +
                ex.Message;
        }
    }

    private async Task BindIdentitySessionAsync()
    {
        var sessionId = IdentitySessionIdInput.Trim();
        var operatorAlias = IdentityOperatorAliasInput.Trim();
        var device = SelectedIdentityDevice;

        if (string.IsNullOrWhiteSpace(sessionId) ||
            string.IsNullOrWhiteSpace(operatorAlias) ||
            device is null)
        {
            DeviceTrustState =
                "Session ID, operator alias, and target device are required.";
            return;
        }

        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerMachineIdentitySnapshot>(
                    "identity.session.bind",
                    new ManagerIdentitySessionBindRequest(
                        sessionId,
                        operatorAlias,
                        device.DeviceId));

            DeviceTrustState = snapshot.TrustState;
            ApplyIdentityRoutingSnapshot(snapshot);
        }
        catch (Exception ex)
        {
            DeviceTrustState =
                "session bind failed - " +
                ex.Message;
        }
    }

    private async Task SwitchSelectedIdentitySessionAsync()
    {
        var selectedBinding =
            SelectedIdentitySessionBinding;
        var selectedDevice =
            SelectedIdentityDevice;

        if (selectedBinding is null ||
            selectedDevice is null)
        {
            DeviceTrustState =
                "Select a session binding and target device to switch.";
            return;
        }

        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerMachineIdentitySnapshot>(
                    "identity.session.switch",
                    new ManagerIdentitySessionSwitchRequest(
                        selectedBinding.SessionId,
                        selectedDevice.DeviceId,
                        Confirmation: true));

            DeviceTrustState = snapshot.TrustState;
            ApplyIdentityRoutingSnapshot(snapshot);
        }
        catch (Exception ex)
        {
            DeviceTrustState =
                "session switch failed - " +
                ex.Message;
        }
    }

    private async Task RevokeSelectedIdentitySessionAsync()
    {
        var selected =
            SelectedIdentitySessionBinding;

        if (selected is null)
        {
            DeviceTrustState =
                "Select a session binding to revoke.";
            return;
        }

        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerMachineIdentitySnapshot>(
                    "identity.session.revoke",
                    new ManagerIdentitySessionRevokeRequest(
                        selected.SessionId));

            SelectedIdentitySessionBinding = null;
            DeviceTrustState = snapshot.TrustState;
            ApplyIdentityRoutingSnapshot(snapshot);
        }
        catch (Exception ex)
        {
            DeviceTrustState =
                "session revoke failed - " +
                ex.Message;
        }
    }

    private async Task RefreshTunnelSettingsAsync()
    {
        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerTunnelSettingsSnapshot>(
                    "settings.tunnel.snapshot");

            TunnelId = snapshot.TunnelId;
            TunnelApiKeyStatus =
                snapshot.ApiKeyConfigured
                    ? snapshot.ApiKeyMasked
                    : "Not configured";
            TunnelSettingsHint =
                snapshot.ApiKeyConfigured
                    ? "Saved securely with " +
                        snapshot.CredentialProtection +
                        ". Enter a new API key only when changing it. Core restart is required after saving."
                    : "Tunnel transport is not configured. Credentials will be protected with " +
                        snapshot.CredentialProtection + ".";
        }
        catch (Exception ex)
        {
            TunnelSettingsHint =
                "Settings unavailable - " +
                ex.Message;
        }
    }

    private async Task RefreshVisualAsync()
    {
        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerVisualSnapshot>(
                    "visual.latest");

            if (!snapshot.Available)
            {
                VisualLatestPath = "";
                VisualStatus =
                    snapshot.Error is null
                        ? "No visual artifact yet."
                        : "Visual unavailable · " + snapshot.Error;
                VisualMetadata = "";
                return;
            }

            var imagePreview =
                snapshot.MimeType?.StartsWith(
                    "image/",
                    StringComparison.OrdinalIgnoreCase) == true;

            VisualLatestPath =
                imagePreview
                    ? snapshot.ArtifactPath ?? ""
                    : "";

            var captured =
                snapshot.CapturedAtUtc?.ToLocalTime()
                    .ToString("yyyy-MM-dd HH:mm:ss") ??
                "unknown time";

            VisualStatus =
                $"{snapshot.Source ?? "visual"} · {snapshot.Kind ?? "artifact"} · {captured}";

            VisualMetadata =
                $"ID: {snapshot.Id ?? "-"}  |  Device: {snapshot.DeviceName ?? snapshot.DeviceId ?? "-"}  |  Session: {snapshot.SessionId ?? "-"}  |  {snapshot.MimeType ?? "unknown"}  |  {snapshot.Bytes:N0} bytes" +
                (imagePreview
                    ? ""
                    : "  |  Preview unavailable for non-image artifact.");
        }
        catch (Exception ex)
        {
            VisualLatestPath = "";
            VisualStatus =
                "Visual status unavailable · " +
                ex.Message;
            VisualMetadata = "";
        }
    }

    private async Task RefreshIntegrationsAsync()
    {
        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerIntegrationSnapshot>(
                    "integrations.snapshot");

            ApplyIntegrationSnapshot(snapshot);
        }
        catch (Exception ex)
        {
            IntegrationActionStatus =
                "Integration status unavailable · " +
                ex.Message;
        }
    }

    private async Task RunIntegrationActionAsync(
        string action,
        string? chromeProfile = null)
    {
        try
        {
            IntegrationActionStatus =
                "Running " + action + "...";

            var result =
                await _client.SendAsync<
                    ManagerIntegrationActionResult>(
                    "integrations.action",
                    new ManagerIntegrationActionRequest(
                        action,
                        chromeProfile),
                    timeout: action == "chrome.request_access"
                        ? TimeSpan.FromSeconds(215)
                        : TimeSpan.FromSeconds(30));

            ApplyIntegrationSnapshot(
                result.Snapshot);

            IntegrationActionStatus =
                result.Success
                    ? result.Message
                    : "Failed · " + result.Message;
        }
        catch (Exception ex)
        {
            IntegrationActionStatus =
                "Failed · " + ex.Message;
        }
    }

    private void ApplyIntegrationSnapshot(
        ManagerIntegrationSnapshot snapshot)
    {
        ChromeExtensionStatus =
            snapshot.ChromeExtensionStatus;
        ChromeNativeBridgeStatus =
            snapshot.ChromeNativeBridgeStatus;
        WebBridgeConnected =
            snapshot.ChromeConnected;
        WebBridgeAuthorized =
            snapshot.ChromeAuthorized;
        ChromeNativeAttachedStatus =
            snapshot.ChromeNativeAttached
                ? "Attached"
                : "Not attached";

        _chromeBoundProfile = string.IsNullOrWhiteSpace(snapshot.ChromeProfile)
            ? "None" : snapshot.ChromeProfile;
        _chromePersistentConsent = snapshot.ChromePersistentConsent;
        _chromeReconnectAvailable = snapshot.ChromeReconnectAvailable;
        _chromeApprovedTabCount = snapshot.ChromeApprovedTabCount;
        Raise(nameof(ChromeBoundProfile));
        Raise(nameof(ChromeConsentStatus));
        Raise(nameof(ChromeReconnectStatus));
        Raise(nameof(ChromeApprovedTabsStatus));

        var previousSelection = SelectedChromeProfile;
        ChromeProfileOptions.Clear();
        foreach (var profile in snapshot.ChromeProfileOptions)
        {
            if (!string.IsNullOrWhiteSpace(profile))
            {
                ChromeProfileOptions.Add(profile);
            }
        }
        var boundName = snapshot.ChromeProfile.Split('/')
            .LastOrDefault()?.Trim() ?? "";
        SelectedChromeProfile = ChromeProfileOptions.Contains(
            previousSelection)
                ? previousSelection
                : ChromeProfileOptions.Contains(boundName)
                    ? boundName
                    : ChromeProfileOptions.FirstOrDefault() ?? "";

        ArcMapDesktopStatus =
            snapshot.ArcMapDesktopStatus;
        ArcMapAddInStatus =
            snapshot.ArcMapAddInStatus;
        ArcMapToolsStatus =
            snapshot.ArcMapToolsStatus;
        ArcMapMcpStatus =
            snapshot.ArcMapMcpStatus;
        ArcMapBridgeStatus =
            snapshot.ArcMapBridgeStatus;
        ArcMapCurrentMxdStatus =
            snapshot.ArcMapCurrentMxdStatus;
    }

    private async Task RefreshDevelopmentAgentsAsync()
    {
        try
        {
            var rows =
                await _client.SendAsync<
                    IReadOnlyList<
                        ManagerDevelopmentAgentRow>>(
                    "development.snapshot");

            Replace(
                DevelopmentAgents,
                rows);
        }
        catch
        {
        }
    }

    public async Task SaveTunnelSettingsAsync(
        string tunnelId,
        string apiKey)
    {
        Busy = true;

        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerTunnelSettingsSnapshot>(
                    "settings.tunnel.save",
                    new ManagerTunnelSettingsUpdateRequest(
                        tunnelId,
                        string.IsNullOrWhiteSpace(apiKey)
                            ? null
                            : apiKey));

            TunnelId = snapshot.TunnelId;
            TunnelApiKeyStatus =
                snapshot.ApiKeyMasked;
            TunnelSettingsHint =
                "Saved securely. Restart Zagent Manager/Core to apply the Tunnel transport credentials.";
            StatusText =
                "Tunnel settings saved - restart Manager/Core to apply transport changes.";
        }
        catch (Exception ex)
        {
            StatusText =
                "Gagal - " +
                ex.Message;
            TunnelSettingsHint =
                StatusText;
        }
        finally
        {
            Busy = false;
        }
    }

    private async Task AddDevelopmentAgentAsync()
    {
        var name = DevelopmentName.Trim();
        var ns = DevelopmentNamespace.Trim();
        var url = DevelopmentUrl.Trim();

        if (string.IsNullOrWhiteSpace(name) ||
            string.IsNullOrWhiteSpace(ns) ||
            string.IsNullOrWhiteSpace(url))
        {
            StatusText =
                "Nama, namespace, dan MCP URL Development Agent wajib diisi.";
            return;
        }

        await ExecuteOperationAsync(
            async () =>
                await _client.SendAsync<
                    ManagerOperationResult>(
                    "development.add",
                    new ManagerDevelopmentAgentRequest(
                        name,
                        ns,
                        url)),
            refreshAfter: true);

        await RefreshDevelopmentAgentsAsync();
    }

    private async Task RemoveDevelopmentAgentAsync(
        ManagerDevelopmentAgentRow? row)
    {
        if (row is null)
        {
            return;
        }

        await ExecuteOperationAsync(
            async () =>
                await _client.SendAsync<
                    ManagerOperationResult>(
                    "development.remove",
                    new ManagerDevelopmentAgentRemoveRequest(
                        row.Id)),
            refreshAfter: true);

        await RefreshDevelopmentAgentsAsync();
    }

    private async Task ShowChatHistoryAsync()
    {
        _showChatHistory = !_showChatHistory;
        Raise(nameof(ChatHistoryButtonText));

        if (_showChatHistory)
        {
            _pageChatClearBefore = 0;
        }

        await RefreshChatAsync();
        StatusText = _showChatHistory
            ? $"Log Chat history ditampilkan - {DateTime.Now:HH:mm:ss}"
            : $"3 chat terbaru ditampilkan - {DateTime.Now:HH:mm:ss}";
    }

    private async Task ClearChatViewAsync()
    {
        if (_latestPageChatTimestamp <= 0)
        {
            await RefreshChatAsync();
        }

        _pageChatClearBefore =
            Math.Max(
                _pageChatClearBefore,
                _latestPageChatTimestamp);

        ChatColumns.Clear();

        StatusText =
            "Log Chat view dibersihkan. History tetap tersimpan.";
    }

    private async Task RefreshChatPageAsync()
    {
        await RefreshChatAsync();
        StatusText =
            $"Log Chat diperbarui - {DateTime.Now:HH:mm:ss}";
    }

    private async Task RefreshChatAsync()
    {
        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerChatSnapshot>(
                    "chat.snapshot",
                    new ManagerRefreshRequest(
                        IncludeCompletedTasks:
                            ShowRecentCompleted,
                        TaskLimit: 100,
                        ChatLogLimit: 600));

            _latestPageChatTimestamp =
                snapshot.Entries
                    .Select(
                        item =>
                            item.Timestamp ?? 0)
                    .DefaultIfEmpty(0)
                    .Max();

            var columns = new List<
                ChatColumnViewModel>();

            foreach (var chat in snapshot.Chats
                         .OrderByDescending(
                             item =>
                                 item.LastSeen ?? 0))
            {
                var rawEntries =
                    snapshot.Entries
                        .Where(
                            item =>
                                item.SessionId ==
                                chat.SessionId &&
                                (item.Timestamp ?? 0) >
                                _pageChatClearBefore)
                        .OrderByDescending(
                            item =>
                                item.Timestamp ?? 0)
                        .ToArray();

                if (rawEntries.Length == 0)
                {
                    continue;
                }

                var entries =
                    rawEntries
                        .Select(
                            item =>
                                item with
                                {
                                    Message =
                                        ChatPresentation.Humanize(
                                            item),
                                    DisplayTitle =
                                        ChatPresentation.BuildEntryDisplayTitle(
                                            item)
                                })
                        .ToArray();

                columns.Add(
                    new ChatColumnViewModel(
                        chat.SessionId,
                        ChatPresentation.BuildDisplayTitle(
                            chat,
                            rawEntries),
                        entries));

                if (!_showChatHistory &&
                    columns.Count >= MaxVisibleChatColumns)
                {
                    break;
                }
            }

            Replace(
                ChatColumns,
                columns);

            _dashboardAllChatEntries.Clear();
            _dashboardAllChatEntries.AddRange(
                snapshot.Entries
                    .OrderByDescending(
                        item =>
                            item.Timestamp ?? 0)
                    .Where(
                        item =>
                            (item.Timestamp ?? 0) >
                            _dashboardChatClearBefore)
                    .Select(
                        item =>
                            item with
                            {
                                Message =
                                    ChatPresentation.Humanize(
                                        item),
                                DisplayTitle =
                                    ChatPresentation.BuildEntryDisplayTitle(
                                        item)
                            })
                    .Take(120));

            ApplyDashboardChatFilter();
        }
        catch
        {
        }
    }

    private async Task RefreshLogsAsync()
    {
        try
        {
            var snapshot =
                await _client.SendAsync<
                    ManagerLogsSnapshot>(
                    "logs.snapshot");

            Replace(
                TechnicalLogs,
                snapshot.Technical);

            ApplyDashboardChatFilter();
        }
        catch
        {
        }
    }

    private async Task LifecycleAgentAsync(
        string? agentId,
        string operation)
    {
        if (string.IsNullOrWhiteSpace(agentId))
        {
            return;
        }

        await ExecuteOperationAsync(
            async () =>
                await _client.SendAsync<
                    ManagerOperationResult>(
                    "lifecycle.agent",
                    new ManagerLifecycleRequest(
                        agentId,
                        operation),
                    timeout:
                        TimeSpan.FromSeconds(45)),
            refreshAfter: true);
    }

    private async Task LifecycleAllAsync(
        string operation)
    {
        await ExecuteOperationAsync(
            async () =>
                await _client.SendAsync<
                    ManagerOperationResult>(
                    "lifecycle.all",
                    new ManagerLifecycleRequest(
                        "all",
                        operation),
                    timeout:
                        TimeSpan.FromSeconds(45)),
            refreshAfter: true);
    }

    private async Task AddProfileAsync()
    {
        var dialog = new OpenFolderDialog
        {
            Title = "Pilih folder yang akan ditambahkan ke Zagent Files",
            Multiselect = false
        };

        if (dialog.ShowDialog() != true)
        {
            return;
        }

        var root = Path.GetFullPath(dialog.FolderName);
        var trimmed = root.TrimEnd(
            Path.DirectorySeparatorChar,
            Path.AltDirectorySeparatorChar);
        var name = new DirectoryInfo(
            string.IsNullOrWhiteSpace(trimmed)
                ? root
                : trimmed).Name;

        if (string.IsNullOrWhiteSpace(name))
        {
            name = new DirectoryInfo(root).Root.Name
                .TrimEnd(
                    Path.DirectorySeparatorChar,
                    Path.AltDirectorySeparatorChar,
                    ':');
        }

        var modeChoice = MessageBox.Show(
            "Gunakan path ini dalam mode read-write?\n\nYes = read-write\nNo = read-only\nCancel = batalkan",
            "Add Zagent Files Path",
            MessageBoxButton.YesNoCancel,
            MessageBoxImage.Question);

        if (modeChoice == MessageBoxResult.Cancel)
        {
            return;
        }

        var mode =
            modeChoice == MessageBoxResult.Yes
                ? "read-write"
                : "read-only";

        await ExecuteOperationAsync(
            async () =>
                await _client.SendAsync<
                    ManagerOperationResult>(
                    "profiles.add",
                    new ManagerProfileAddRequest(
                        name,
                        root,
                        mode),
                    timeout:
                        TimeSpan.FromSeconds(30)),
            refreshAfter: true);

        await RefreshProfilesAsync();
    }

    private async Task RemoveProfileAsync()
    {
        var row = SelectedProfile;
        if (row is null)
        {
            StatusText =
                "Pilih Files profile/path yang akan dihapus.";
            return;
        }

        if (row.Active)
        {
            StatusText =
                $"Profile aktif '{row.Name}' tidak dapat dihapus. Aktifkan profile lain terlebih dahulu.";
            return;
        }

        var choice = MessageBox.Show(
            $"Hapus profile/path '{row.Name}' dari Zagent Files?\n\nFolder asli tidak akan dihapus.",
            "Remove Zagent Files Path",
            MessageBoxButton.YesNo,
            MessageBoxImage.Warning);

        if (choice != MessageBoxResult.Yes)
        {
            return;
        }

        await ExecuteOperationAsync(
            async () =>
                await _client.SendAsync<
                    ManagerOperationResult>(
                    "profiles.remove",
                    new ManagerProfileRemoveRequest(
                        row.Name),
                    timeout:
                        TimeSpan.FromSeconds(30)),
            refreshAfter: true);

        SelectedProfile = null;
        await RefreshProfilesAsync();
    }

    private async Task SwitchProfileAsync()
    {
        var row = SelectedProfile;
        if (row is null)
        {
            StatusText = "Pilih Files profile terlebih dahulu.";
            return;
        }

        if (row.Active)
        {
            StatusText = "Profile '" + row.Name + "' sudah menjadi default untuk session baru.";
            return;
        }

        if (!row.Enabled)
        {
            StatusText = "Profile '" + row.Name + "' sedang disabled. Enable terlebih dahulu.";
            return;
        }

        await ExecuteOperationAsync(
            async () => await _client.SendAsync<ManagerOperationResult>(
                "profiles.switch",
                new ManagerProfileSwitchRequest(row.Name),
                timeout: TimeSpan.FromSeconds(30)),
            refreshAfter: true);
    }

    private async Task SwitchSelectedSessionProfileAsync()
    {
        var profile = SelectedProfile;
        var session = SelectedFilesSession;

        if (session is null)
        {
            StatusText = "Pilih Files session terlebih dahulu.";
            return;
        }

        if (profile is null)
        {
            StatusText = "Pilih Files profile terlebih dahulu.";
            return;
        }

        if (!profile.Enabled)
        {
            StatusText = "Profile '" + profile.Name + "' sedang disabled. Enable terlebih dahulu.";
            return;
        }

        if (string.Equals(
                session.ActiveProfile,
                profile.Name,
                StringComparison.Ordinal))
        {
            StatusText =
                "Session '" + session.SessionId +
                "' sudah menggunakan profile '" + profile.Name + "'.";
            return;
        }

        await ExecuteOperationAsync(
            async () => await _client.SendAsync<ManagerOperationResult>(
                "profiles.session_switch",
                new ManagerSessionProfileSwitchRequest(
                    session.SessionId,
                    profile.Name),
                timeout: TimeSpan.FromSeconds(30)),
            refreshAfter: true);
    }

    private async Task EditProfileAsync()
    {
        var row = SelectedProfile;
        if (row is null)
        {
            StatusText = "Pilih Files profile yang akan diubah.";
            return;
        }

        string? newRoot = null;
        string? newMode = null;

        var rootChoice = MessageBox.Show(
            "Ubah root folder untuk profile '" + row.Name + "'?\n\nYes = pilih folder baru\nNo = pertahankan root saat ini\nCancel = batalkan",
            "Edit Zagent Files Profile",
            MessageBoxButton.YesNoCancel,
            MessageBoxImage.Question);

        if (rootChoice == MessageBoxResult.Cancel)
        {
            return;
        }

        if (rootChoice == MessageBoxResult.Yes)
        {
            var dialog = new OpenFolderDialog
            {
                Title = "Pilih root folder baru untuk " + row.Name,
                Multiselect = false,
                InitialDirectory = row.Root
            };

            if (dialog.ShowDialog() != true)
            {
                return;
            }

            var candidate = Path.GetFullPath(dialog.FolderName);
            if (!string.Equals(candidate, row.Root, StringComparison.OrdinalIgnoreCase))
            {
                newRoot = candidate;
            }
        }

        var modeChoice = MessageBox.Show(
            "Pilih mode akses profile '" + row.Name + "'.\n\nYes = read-write\nNo = read-only\nCancel = pertahankan mode saat ini",
            "Edit Zagent Files Profile",
            MessageBoxButton.YesNoCancel,
            MessageBoxImage.Question);

        if (modeChoice != MessageBoxResult.Cancel)
        {
            var candidateMode = modeChoice == MessageBoxResult.Yes
                ? "read-write"
                : "read-only";

            if (!string.Equals(candidateMode, row.Mode, StringComparison.OrdinalIgnoreCase))
            {
                newMode = candidateMode;
            }
        }

        if (newRoot is null && newMode is null)
        {
            StatusText = "Tidak ada perubahan profile yang diminta.";
            return;
        }

        await ExecuteOperationAsync(
            async () => await _client.SendAsync<ManagerOperationResult>(
                "profiles.update",
                new ManagerProfileUpdateRequest(
                    row.Name,
                    newRoot,
                    newMode),
                timeout: TimeSpan.FromSeconds(30)),
            refreshAfter: true);
    }

    private async Task ToggleProfileEnabledAsync()
    {
        var row = SelectedProfile;
        if (row is null)
        {
            StatusText = "Pilih Files profile terlebih dahulu.";
            return;
        }

        if (row.Active && row.Enabled)
        {
            StatusText = "Profile default tidak dapat di-disable. Set Default ke profile lain terlebih dahulu.";
            return;
        }

        var targetEnabled = !row.Enabled;
        var choice = MessageBox.Show(
            (targetEnabled ? "Enable" : "Disable") + " profile '" + row.Name + "'?\n\nPerubahan akan masuk Pending Local Approvals.",
            "Zagent Files Profile",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question);

        if (choice != MessageBoxResult.Yes)
        {
            return;
        }

        await ExecuteOperationAsync(
            async () => await _client.SendAsync<ManagerOperationResult>(
                "profiles.update",
                new ManagerProfileUpdateRequest(
                    row.Name,
                    Enabled: targetEnabled),
                timeout: TimeSpan.FromSeconds(30)),
            refreshAfter: true);
    }

    private async Task RunRouterActionAsync(string action)
    {
        var row = SelectedRouterService;
        if (!string.Equals(action, "reload", StringComparison.Ordinal) && row is null)
        {
            StatusText = "Pilih Tunnel/MCP service terlebih dahulu.";
            return;
        }

        Busy = true;
        try
        {
            var result = await _client.SendAsync<ManagerOperationResult>(
                "router.action",
                new ManagerRouterActionRequest(
                    action,
                    row?.Id),
                timeout: TimeSpan.FromSeconds(30));

            StatusText = result.Success
                ? result.Message
                : "Gagal - " + result.Message;

            if (action is "tools" or "test")
            {
                MessageBox.Show(
                    result.Message,
                    action == "tools"
                        ? (row?.Name ?? "MCP Service") + " Tools"
                        : (row?.Name ?? "MCP Service") + " Test",
                    MessageBoxButton.OK,
                    result.Success
                        ? MessageBoxImage.Information
                        : MessageBoxImage.Warning);
            }
        }
        catch (Exception ex)
        {
            StatusText = "Gagal - " + ex.Message;
        }
        finally
        {
            Busy = false;
        }

        await RefreshRouterAsync();
        await RefreshLogsAsync();
    }

    private async Task ResolveApprovalAsync(
        string action)
    {
        var row = SelectedApproval;
        if (row is null ||
            !row.CanResolveLocally)
        {
            StatusText =
                row is null
                    ? "Pilih approval terlebih dahulu."
                    : "Pair/Approve Web harus diselesaikan di Zagent Chrome Bridge.";
            return;
        }

        await ExecuteOperationAsync(
            async () =>
                await _client.SendAsync<
                    ManagerOperationResult>(
                    "approval.resolve",
                    new ManagerApprovalActionRequest(
                        row.RequestId,
                        action,
                        action == "deny"
                            ? "Denied from Zagent Manager"
                            : null,
                        row.Source)),
            refreshAfter: true);
    }

    private async Task ExecuteOperationAsync(
        Func<Task<ManagerOperationResult>> operation,
        bool refreshAfter)
    {
        Busy = true;

        try
        {
            var result = await operation();

            StatusText =
                result.Success
                    ? result.Message
                    : "Gagal - " +
                        result.Message;
        }
        catch (Exception ex)
        {
            StatusText =
                "Gagal - " +
                ex.Message;
        }
        finally
        {
            Busy = false;
        }

        if (refreshAfter)
        {
            await RefreshAllAsync(
                automatic: false);
        }
    }

    private Task ClearDashboardChatAsync()
    {
        if (string.Equals(
                DashboardLogFilter,
                "Log Chat",
                StringComparison.Ordinal))
        {
            _dashboardChatClearBefore =
                _dashboardAllChatEntries
                    .Select(
                        item =>
                            item.Timestamp ?? 0)
                    .DefaultIfEmpty(0)
                    .Max();

            _dashboardAllChatEntries.Clear();
        }
        else
        {
            _dashboardAgentLogClearBefore =
                DateTimeOffset.UtcNow;
        }

        DashboardChatEntries.Clear();

        return Task.CompletedTask;
    }

    private void ApplyDashboardChatFilter()
    {
        IEnumerable<ManagerChatLogRow> rows;

        if (string.Equals(
                DashboardLogFilter,
                "Log Chat",
                StringComparison.Ordinal))
        {
            rows = _dashboardAllChatEntries;
        }
        else
        {
            var filter = DashboardLogFilter;

            rows = TechnicalLogs
                .Where(
                    item =>
                        item.TimestampUtc >
                            _dashboardAgentLogClearBefore &&
                        (item.Source.Contains(
                             filter,
                             StringComparison.OrdinalIgnoreCase) ||
                         item.Event.Contains(
                             filter,
                             StringComparison.OrdinalIgnoreCase)))
                .Select(
                    item =>
                        new ManagerChatLogRow(
                            SessionId: "",
                            Alias: "",
                            Title: "",
                            Source: item.Level,
                            Agent: item.Source,
                            Tool: item.Event,
                            Message: item.Message,
                            Timestamp:
                                item.TimestampUtc
                                    .ToUnixTimeMilliseconds() /
                                1000d,
                            DisplayTitle:
                                $"{item.Source} - {item.Event}"));
        }

        Replace(
            DashboardChatEntries,
            rows
                .Take(80)
                .OrderBy(
                    item =>
                        item.Timestamp ?? 0));
    }

    private void ApplyCapabilityFilter()
    {
        var needle =
            CapabilitySearch.Trim();

        IEnumerable<ManagerCapabilityRow> rows =
            _allCapabilities;

        if (!string.IsNullOrWhiteSpace(needle))
        {
            rows = rows.Where(
                item =>
                    item.Capability.Contains(
                        needle,
                        StringComparison.OrdinalIgnoreCase) ||
                    item.AgentName.Contains(
                        needle,
                        StringComparison.OrdinalIgnoreCase) ||
                    item.AgentId.Contains(
                        needle,
                        StringComparison.OrdinalIgnoreCase) ||
                    item.Access.ToString().Contains(
                        needle,
                        StringComparison.OrdinalIgnoreCase) ||
                    item.Approval.ToString().Contains(
                        needle,
                        StringComparison.OrdinalIgnoreCase));
        }

        Replace(
            Capabilities,
            rows.Take(1000));
    }

    private static void Replace<T>(
        ObservableCollection<T> collection,
        IEnumerable<T> values)
    {
        collection.Clear();

        foreach (var value in values)
        {
            collection.Add(value);
        }
    }
}
