param(
  [string]$Root = ""
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Root)) {
  $scriptsDir = Split-Path -Parent $PSScriptRoot
  $Root = Split-Path -Parent $scriptsDir
}
$Root = [IO.Path]::GetFullPath([string]$Root)

# ZA-BUG-006: ArcMap 10.6.1 active application acquisition must use
# esriFramework.AppRef before the legacy esriArcMap.Application ROT fallback.
$stage3Bridge = [IO.Path]::Combine($Root, "agents", "arcmap", "engine", "stage3", "bridge.py")
if (-not [IO.File]::Exists($stage3Bridge)) {
  throw "ZA-BUG-006 gate: Stage 3 bridge missing: $stage3Bridge"
}

$source = [IO.File]::ReadAllText($stage3Bridge)
$win32AppRef = $source.IndexOf('Dispatch("esriFramework.AppRef")', [StringComparison]::Ordinal)
$comtypesAppRef = $source.IndexOf('CreateObject("esriFramework.AppRef", dynamic=True)', [StringComparison]::Ordinal)
$legacyRot = $source.IndexOf('GetActiveObject("esriArcMap.Application")', [StringComparison]::Ordinal)

if ($win32AppRef -lt 0 -or $comtypesAppRef -lt 0) {
  throw "ZA-BUG-006 regression: esriFramework.AppRef primary acquisition path is missing."
}
if ($legacyRot -ge 0 -and $legacyRot -lt $win32AppRef) {
  throw "ZA-BUG-006 regression: legacy esriArcMap.Application ROT lookup became primary again."
}
if ($source.IndexOf('win32com:esriFramework.AppRef', [StringComparison]::Ordinal) -lt 0) {
  throw "ZA-BUG-006 regression: expected AppRef backend marker is missing."
}

# ZA-BUG-007: owner heartbeat publication must be atomic and owner reads must
# tolerate brief Windows sharing locks before declaring the bridge offline.
$liveBridge = [IO.Path]::Combine($Root, "agents", "arcmap", "engine", "arcmap_bridge", "live_bridge.py")
$ipcClient = [IO.Path]::Combine($Root, "agents", "arcmap", "engine", "mcp_server", "ipc_client.py")
if (-not [IO.File]::Exists($liveBridge)) {
  throw "ZA-BUG-007 gate: live_bridge.py missing: $liveBridge"
}
if (-not [IO.File]::Exists($ipcClient)) {
  throw "ZA-BUG-007 gate: ipc_client.py missing: $ipcClient"
}
$liveSource = [IO.File]::ReadAllText($liveBridge)
$ipcSource = [IO.File]::ReadAllText($ipcClient)
if ($liveSource.IndexOf('MoveFileExW', [StringComparison]::Ordinal) -lt 0) {
  throw "ZA-BUG-007 regression: atomic MoveFileExW publication path is missing."
}
if ($liveSource.IndexOf('_replace_file_atomic(temp, _OWNER_FILE)', [StringComparison]::Ordinal) -lt 0) {
  throw "ZA-BUG-007 regression: owner publication no longer uses atomic replacement."
}
if ($liveSource.IndexOf('os.remove(_OWNER_FILE)', [StringComparison]::Ordinal) -ge 0) {
  throw "ZA-BUG-007 regression: delete-before-rename owner publication returned."
}
if ($ipcSource.IndexOf('def _read_owner_json(', [StringComparison]::Ordinal) -lt 0 -or
    $ipcSource.IndexOf('for index in range(attempts):', [StringComparison]::Ordinal) -lt 0 -or
    $ipcSource.IndexOf('time.sleep(delay)', [StringComparison]::Ordinal) -lt 0 -or
    $ipcSource.IndexOf('owner = _read_owner_json(owner_path)', [StringComparison]::Ordinal) -lt 0) {
  throw "ZA-BUG-007 regression: transient owner-read retry path is missing."
}

# ZA-BUG-008: Step 6 timing must preserve addin_claim_epoch and retain all
# diagnostic hop markers used for Live Bridge latency analysis.
$runner = [IO.Path]::Combine($Root, "agents", "arcmap", "engine", "arcmap_bridge", "core", "runner.py")
$requestContext = [IO.Path]::Combine($Root, "agents", "arcmap", "engine", "mcp_server", "request_context.py")
if (-not [IO.File]::Exists($runner)) {
  throw "ZA-BUG-008 gate: runner.py missing: $runner"
}
if (-not [IO.File]::Exists($requestContext)) {
  throw "ZA-BUG-008 gate: request_context.py missing: $requestContext"
}
$runnerSource = [IO.File]::ReadAllText($runner)
$requestContextSource = [IO.File]::ReadAllText($requestContext)
if ($runnerSource.IndexOf('claim_epoch = time.time()', [StringComparison]::Ordinal) -lt 0 -or
    $runnerSource.IndexOf('timing = command.setdefault("timing", {})', [StringComparison]::Ordinal) -lt 0 -or
    $runnerSource.IndexOf('timing["addin_claim_epoch"] = claim_epoch', [StringComparison]::Ordinal) -lt 0) {
  throw "ZA-BUG-008 regression: addin_claim_epoch preservation path is missing."
}
foreach ($marker in @(
  'addin_command_read_epoch',
  'current_mxd_validate_start_epoch',
  'current_mxd_validate_end_epoch',
  'dispatch_start_epoch',
  'dispatch_end_epoch',
  'result_write_epoch'
)) {
  if ($runnerSource.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) {
    throw "ZA-BUG-008 regression: runner timing marker missing: $marker"
  }
}
foreach ($marker in @('mcp_receive_epoch','mcp_tool_name')) {
  if ($requestContextSource.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) {
    throw "ZA-BUG-008 regression: MCP timing marker missing: $marker"
  }
}
foreach ($marker in @(
  'mcp_send_enter_epoch',
  'owner_checked_epoch',
  'owner_heartbeat_epoch',
  'owner_heartbeat_age_ms',
  'ipc_enqueue_epoch',
  'mcp_result_read_epoch',
  'mcp_total_ms'
)) {
  if ($ipcSource.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) {
    throw "ZA-BUG-008 regression: IPC timing marker missing: $marker"
  }
}
foreach ($marker in @(
  'timer_started_epoch',
  'timer_callback_epoch',
  'timer_interval_ms',
  'heartbeat_sequence'
)) {
  if ($liveSource.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) {
    throw "ZA-BUG-008 regression: Live Bridge timer marker missing: $marker"
  }
}

# ZA-BUG-009: ArcMap 10.6.1 PageLayout access must use typed ArcObjects
# interfaces from the installed type libraries. IApplication.Document exposes
# the base IDocument interface; PageLayout belongs to IMxDocument.
foreach ($marker in @(
  'def _typed_arcobjects_modules():',
  'GetInstallInfo()',
  '"esriFramework.olb"',
  '"esriArcMapUI.olb"',
  '"esriCarto.olb"',
  'interface=framework.IApplication',
  'QueryInterface(arcmapui.IMxDocument)',
  'QueryInterface(carto.IPageLayout)',
  'QueryInterface(carto.IPage)',
  '"comtypes:esriFramework.AppRef+IApplication+IMxDocument+IPageLayout"',
  '"PutCustomSize"'
)) {
  if ($source.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) {
    throw "ZA-BUG-009 regression: typed ArcObjects PageLayout marker missing: $marker"
  }
}
if ($source.IndexOf('def _query_interface_dispatch(', [StringComparison]::Ordinal) -ge 0) {
  throw "ZA-BUG-009 regression: unsupported raw-IID QueryInterface helper returned."
}
$generatedComtypes = [IO.Path]::Combine(
  $Root, "agents", "arcmap", "engine", "vendor27", "comtypes", "gen"
)
if ([IO.Directory]::Exists($generatedComtypes)) {
  throw "ZA-BUG-009 regression: generated comtypes cache must not be bundled: $generatedComtypes"
}

# ZA-BUG-010: ArcMap engine fingerprinting must exclude metadata files that
# themselves store fingerprint/build information. Including them makes the
# aggregate self-referential and non-deterministic after metadata updates.
$fingerprintScript = [IO.Path]::Combine(
  $Root, "packaging", "scripts", "Get-ArcMapEngineFingerprint.ps1"
)
if (-not [IO.File]::Exists($fingerprintScript)) {
  throw "ZA-BUG-010 gate: canonical ArcMap fingerprint helper is missing."
}
$fingerprintSource = [IO.File]::ReadAllText($fingerprintScript)
foreach ($marker in @(
  '"BUILD_INFO.json"',
  '"BUILD_MANIFEST.json"',
  '"ZAGENT_BUILD_INFO.json"',
  'self_referential_metadata_excluded = $true'
)) {
  if ($fingerprintSource.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) {
    throw "ZA-BUG-010 regression: fingerprint exclusion marker missing: $marker"
  }
}
$fingerprintJson = & $fingerprintScript -Root $Root
$fingerprint = $fingerprintJson | ConvertFrom-Json
if (-not $fingerprint.self_referential_metadata_excluded -or
    [string]::IsNullOrWhiteSpace([string]$fingerprint.aggregate_sha256) -or
    [int]$fingerprint.files -le 0) {
  throw "ZA-BUG-010 regression: canonical ArcMap fingerprint helper returned invalid output."
}

# ZA-BUG-011: long-running 400-DPI exports must not inherit the historical
# 2-second ArcMap command timeout. Core/runtime defaults are 15 seconds and
# rendering operations receive explicit 60/120 second budgets.
$coreOptions = [IO.Path]::Combine(
  $Root, "src", "Zagent.Core", "Agents", "ArcMap", "ArcMapIntegrationModels.cs"
)
$managerCoreHost = [IO.Path]::Combine(
  $Root, "src", "Zagent.Core", "Manager", "ManagerCoreHost.cs"
)
$staticAgentConfig = [IO.Path]::Combine(
  $Root, "agents", "arcmap", "engine", "config", "agent_config.json"
)
$exportTools = [IO.Path]::Combine(
  $Root, "agents", "arcmap", "engine", "mcp_server", "tools", "export.py"
)
$exportQaTools = [IO.Path]::Combine(
  $Root, "agents", "arcmap", "engine", "mcp_server", "tools", "export_qa.py"
)
foreach ($required in @($coreOptions,$managerCoreHost,$staticAgentConfig,$exportTools,$exportQaTools)) {
  if (-not [IO.File]::Exists($required)) {
    throw "ZA-BUG-011 gate: required timeout source missing: $required"
  }
}
$coreOptionsSource = [IO.File]::ReadAllText($coreOptions)
$managerCoreHostSource = [IO.File]::ReadAllText($managerCoreHost)
$staticAgent = [IO.File]::ReadAllText($staticAgentConfig) | ConvertFrom-Json
$exportSource = [IO.File]::ReadAllText($exportTools)
$exportQaSource = [IO.File]::ReadAllText($exportQaTools)
if ($coreOptionsSource.IndexOf('int CommandTimeoutSeconds = 15', [StringComparison]::Ordinal) -lt 0) {
  throw "ZA-BUG-011 regression: ArcMap Core default command timeout is not 15 seconds."
}
if ($managerCoreHostSource.IndexOf('CommandTimeoutSeconds: 15', [StringComparison]::Ordinal) -lt 0 -or
    $managerCoreHostSource.IndexOf('CommandTimeoutSeconds: 2', [StringComparison]::Ordinal) -ge 0) {
  throw "ZA-BUG-011 regression: ManagerCoreHost must instantiate ArcMap with a 15-second timeout."
}
if ([int]$staticAgent.command_timeout_seconds -ne 15) {
  throw "ZA-BUG-011 regression: static ArcMap command timeout is not 15 seconds."
}
if (($exportSource.Split('timeout=60').Count - 1) -lt 4) {
  throw "ZA-BUG-011 regression: export.py is missing 60-second render timeout coverage."
}
if (($exportQaSource.Split('timeout=60').Count - 1) -lt 2 -or
    $exportQaSource.IndexOf('timeout=120', [StringComparison]::Ordinal) -lt 0) {
  throw "ZA-BUG-011 regression: export_qa.py is missing 60/120-second render timeout coverage."
}

# Step 12 capability gate: real CURRENT ArcMap application-window capture.
$windowBackend = [IO.Path]::Combine(
  $Root, "agents", "arcmap", "engine", "mcp_server", "window_capture.py"
)
$windowTool = [IO.Path]::Combine(
  $Root, "agents", "arcmap", "engine", "mcp_server", "tools", "window_capture.py"
)
$arcmapServer = [IO.Path]::Combine(
  $Root, "agents", "arcmap", "engine", "mcp_server", "server.py"
)
$toolSnapshot = [IO.Path]::Combine(
  $Root, "agents", "arcmap", "runtime-tools.snapshot.json"
)
foreach ($required in @($windowBackend,$windowTool,$arcmapServer,$toolSnapshot)) {
  if (-not [IO.File]::Exists($required)) {
    throw "STEP12 regression: required window-capture source missing: $required"
  }
}
$windowBackendSource = [IO.File]::ReadAllText($windowBackend)
$windowToolSource = [IO.File]::ReadAllText($windowTool)
$arcmapServerSource = [IO.File]::ReadAllText($arcmapServer)
$toolSnapshotJson = [IO.File]::ReadAllText($toolSnapshot) | ConvertFrom-Json
foreach ($marker in @(
  'PrintWindow',
  'BitBltFallback',
  'ARCMAP_PROCESS_MISMATCH',
  'ARCMAP_WINDOW_MINIMIZED',
  'ARCMAP_WINDOW_CAPTURE_BLANK'
)) {
  if ($windowBackendSource.IndexOf($marker, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
    throw "STEP12 regression: window backend marker missing: $marker"
  }
}
if ($windowToolSource.IndexOf('confirm_current_arcmap_window', [StringComparison]::Ordinal) -lt 0 -or
    $windowToolSource.IndexOf('arcmap_application_window', [StringComparison]::Ordinal) -lt 0) {
  throw "STEP12 regression: MCP wrapper confirmation/provenance contract is missing."
}
if ($arcmapServerSource.IndexOf('window_capture', [StringComparison]::Ordinal) -lt 0) {
  throw "STEP12 regression: ArcMap server does not register window_capture."
}
$requiredArcMapGoalTools = @(
  'arcmap_goal_build_map',
  'arcmap_goal_cancel',
  'arcmap_goal_execute',
  'arcmap_goal_plan',
  'arcmap_goal_report',
  'arcmap_goal_resume',
  'arcmap_goal_status',
  'arcmap_goal_validate'
)
if ([int]$toolSnapshotJson.count -ne @($toolSnapshotJson.tools).Count -or
    [int]$toolSnapshotJson.count -le 0 -or
    -not ($toolSnapshotJson.tools -contains 'arcmap_window_capture')) {
  throw "STEP12 regression: candidate snapshot count/names mismatch or arcmap_window_capture missing."
}
foreach ($goalTool in $requiredArcMapGoalTools) {
  if (-not ($toolSnapshotJson.tools -contains $goalTool)) {
    throw "STEP12 regression: ArcMap Orchestrator goal tool missing from runtime snapshot: $goalTool"
  }
}

# Step 15 hardening gate: global ArcMap serialization, stale-owner fail-closed,
# mutex conflict protection, stale IPC quarantine, and no automatic replay
# when command outcome is unknown.
$servicesFile = [IO.Path]::Combine(
  $Root, "agents", "arcmap", "engine", "mcp_server", "services.py"
)
$ipcClientFile = [IO.Path]::Combine(
  $Root, "agents", "arcmap", "engine", "mcp_server", "ipc_client.py"
)
$liveBridgeFile = [IO.Path]::Combine(
  $Root, "agents", "arcmap", "engine", "arcmap_bridge", "live_bridge.py"
)
$ipcCoreFile = [IO.Path]::Combine(
  $Root, "agents", "arcmap", "engine", "arcmap_bridge", "core", "ipc.py"
)
foreach ($required in @($servicesFile,$ipcClientFile,$liveBridgeFile,$ipcCoreFile)) {
  if (-not [IO.File]::Exists($required)) {
    throw "STEP15 regression: required recovery source missing: $required"
  }
}
$servicesSource = [IO.File]::ReadAllText($servicesFile)
$ipcClientSource = [IO.File]::ReadAllText($ipcClientFile)
$liveBridgeSource = [IO.File]::ReadAllText($liveBridgeFile)
$ipcCoreSource = [IO.File]::ReadAllText($ipcCoreFile)
if ($servicesSource.IndexOf('_ARCMAP_LOCK = threading.RLock()', [StringComparison]::Ordinal) -lt 0 -or
    $servicesSource.IndexOf('with _ARCMAP_LOCK:', [StringComparison]::Ordinal) -lt 0) {
  throw "STEP15 regression: global ArcMap serialization lock is missing."
}
foreach ($marker in @('BRIDGE_OFFLINE','execution outcome unknown','No automatic replay')) {
  if ($ipcClientSource.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) {
    throw "STEP15 regression: IPC fail-closed marker missing: $marker"
  }
}
foreach ($marker in @('CreateMutexW','_ERROR_ALREADY_EXISTS','Dual bridge ownership is not allowed')) {
  if ($liveBridgeSource.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) {
    throw "STEP15 regression: dual-bridge mutex marker missing: $marker"
  }
}
if ($ipcCoreSource.IndexOf('quarantine_stale', [StringComparison]::Ordinal) -lt 0) {
  throw "STEP15 regression: stale IPC quarantine path is missing."
}

# ZA-BUG-012: Files profile authorization state must survive install/repair/
# upgrade initialization. Existing approved profiles and the active profile
# are merged; unapproved entries must never be promoted implicitly.
$filesConfigWriter = [IO.Path]::Combine(
  $Root, "src", "Zagent.Core", "Agents", "Files", "FilesConfigurationWriter.cs"
)
$filesTests = [IO.Path]::Combine(
  $Root, "tests", "Zagent.FilesTests", "Program.cs"
)
foreach ($required in @($filesConfigWriter,$filesTests)) {
  if (-not [IO.File]::Exists($required)) {
    throw "ZA-BUG-012 gate: required Files profile-preservation source missing: $required"
  }
}
$filesConfigWriterSource = [IO.File]::ReadAllText($filesConfigWriter)
$filesTestsSource = [IO.File]::ReadAllText($filesTests)
foreach ($marker in @(
  'BuildProfilesAsync(',
  'profile.AuthorizedByUser',
  'existing.ActiveProfile',
  'merged.Add(profile)',
  'AuthorizationSource'
)) {
  if ($filesConfigWriterSource.IndexOf($marker, [StringComparison]::Ordinal) -lt 0) {
    throw "ZA-BUG-012 regression: Files profile-preservation marker missing: $marker"
  }
}
if ($filesTestsSource.IndexOf(
    'configuration writer preserves approved profiles across upgrade',
    [StringComparison]::Ordinal) -lt 0) {
  throw "ZA-BUG-012 regression: profile-preservation regression test is missing."
}

# ZA-BUG-013: Core ArcMap capability manifest must include the runtime-only
# application-window capture tool so manager capability metadata stays in sync.
$arcMapManifestFactory = [IO.Path]::Combine(
  $Root, "src", "Zagent.Core", "Agents", "ArcMap", "ArcMapAgentManifestFactory.cs"
)
if (-not [IO.File]::Exists($arcMapManifestFactory)) {
  throw "ZA-BUG-013 gate: ArcMapAgentManifestFactory.cs is missing."
}
$arcMapManifestFactorySource = [IO.File]::ReadAllText($arcMapManifestFactory)
if ($arcMapManifestFactorySource.IndexOf('"arcmap_window_capture"', [StringComparison]::Ordinal) -lt 0 -or
    $arcMapManifestFactorySource.IndexOf('"window_capture"', [StringComparison]::Ordinal) -lt 0) {
  throw "ZA-BUG-013 regression: arcmap_window_capture is missing from Core capability metadata/background classification."
}

Write-Output "KNOWN_BUG_REGRESSION_GATES_PASS: ZA-BUG-006, ZA-BUG-007, ZA-BUG-008, ZA-BUG-009, ZA-BUG-010, ZA-BUG-011, ZA-BUG-012, ZA-BUG-013; STEP12_WINDOW_CAPTURE_PASS; STEP15_RECOVERY_HARDENING_PASS"
