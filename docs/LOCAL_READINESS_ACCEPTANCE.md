# Penerimaan lokal Windows: Core1 / UI1 / MCP

**Status awal: NOT_READY.** Source guards bukan compiler; hasil compile terdahulu bukan bukti provisioning atau koneksi. Semua perintah di bawah hanya untuk owner Windows, dijalankan bertahap setelah izin lokal. Tidak ada build/test/agent/network produk yang dijalankan di VPS oleh penulis runbook.

## 0 — Batas dan prasyarat

- Repo lokal yang dilaporkan: `D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform`. SDK portable yang dilaporkan: `D:\3-Ikbalzohr\Agent\appBridge\toolchain\dotnet10\dotnet.exe`. Verifikasi, jangan fallback ke PATH: `global.json` mengunci SDK **10.0.401**, rollForward disabled.
- Pilih direktori disposable **di luar source dan instalasi aktif**. Jangan memakai data produksi, root drive, junction/symlink atau DataRoot user lain. Harness hanya menghapus subfolder fixture GUID yang dibuatnya sendiri. Setup fixture memakai executable palsu yang diberi label fixture, bukan produk/bearer/AS palsu.
- Password dashboard hanya prompt no-echo owner; bearer AS lewat secure process environment, bukan chat/CLI/log/file plaintext. Jangan dump config, headers, cookies, DPAPI plaintext atau `.env`.
- TLS CurrentUser My dengan private key, SAN localhost, serverAuth EKU; trust hanya keputusan owner. Protected owner-only ACL DataRoot/config/dashboard-keys/secret dan DPAPI CurrentUser wajib. Missing certificate/ACL/secret/account = BLOCKED, bukan insecure fallback.
- External OAuth AS/resource URI/introspection/principal grant/profile mapping yang nyata wajib untuk MCP. File example/domain `.example`, transport API key dan internal token **bukan** bearer OAuth. Tanpa AS nyata, hentikan fase MCP dengan `BLOCKED_NOT_CONFIGURED`; UI lokal boleh dinilai terpisah.
- Tidak membuka public listener, tunnel/relay/service baru, tidak mengedit konfigurasi Hermes.

## 1 — Build satu gate per langkah (manual Windows)

```powershell
$Repo = 'D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform'
$Dotnet = 'D:\3-Ikbalzohr\Agent\appBridge\toolchain\dotnet10\dotnet.exe'
if (-not (Test-Path -LiteralPath $Dotnet -PathType Leaf)) { throw 'Portable SDK missing' }
Set-Location -LiteralPath $Repo
$SdkVersion = & $Dotnet --version
if ($LASTEXITCODE -ne 0 -or $SdkVersion.Trim() -cne '10.0.401') { throw 'Exact SDK 10.0.401 required' }
$Fixture = Read-Host 'Existing approved disposable folder outside repo/install'
if (-not (Test-Path -LiteralPath $Fixture -PathType Container)) { throw 'Fixture parent missing' }
$env:ZAGENT_ACCEPTANCE_ROOT = $Fixture
$env:ZAGENT_ACCEPTANCE_SOURCE_ROOT = $Repo
$env:ZAGENT_DEV_ROOT = $Repo # TestChild binary lookup; bukan output fixture.
$env:ZAGENT_TEST_FIXTURE_ROOT = $Fixture
& $Dotnet build .\src\Zagent.Core\Zagent.Core.csproj -c Debug 2>&1 | Tee-Object (Join-Path $Fixture 'core-build.log')
if ($LASTEXITCODE -ne 0) { throw 'Core compile failed: stop' }
```

Sesudah Core compile PASS, jalankan **satu command build, periksa exit, baru run**:

```powershell
& $Dotnet build .\tests\Zagent.CoreAcceptanceTests\Zagent.CoreAcceptanceTests.csproj -c Debug
if ($LASTEXITCODE -ne 0) { throw 'Acceptance compile failed' }
& $Dotnet run --project .\tests\Zagent.CoreAcceptanceTests\Zagent.CoreAcceptanceTests.csproj -c Debug --no-build
if ($LASTEXITCODE -ne 0) { throw 'Acceptance failed' }
& $Dotnet build .\tests\Zagent.DashboardTests\Zagent.DashboardTests.csproj -c Debug
if ($LASTEXITCODE -ne 0) { throw 'Dashboard tests compile failed' }
& $Dotnet run --project .\tests\Zagent.DashboardTests\Zagent.DashboardTests.csproj -c Debug --no-build
if ($LASTEXITCODE -ne 0) { throw 'Dashboard policy tests failed' }
```

`CoreAcceptanceTests` menangkap output **handler produksi** di memory tanpa network; menguji deadline, scope read, placement/workspace, approved active profile bukan selector caller, disabled/missing approval, arbitrary tool dan nonloopback rejection. Juga DPAPI envelope/ACL/secret failure, certificate absence dan dashboard policy. Reflection hanya seam test untuk internal Configure/handler dan pembuat ciphertext fixture. Ini bukan public authentication atau Windows E2E. Wrong-owner DPAPI/ACL dan reparse-point negatives masih perlu owner Windows terpisah; jangan mengubah owner data aktif untuk tes.

Setup tetap sepuluh skenario existing; hanya lokasi fixture baru melalui env, binary TestChild tetap dicari di repo. Compile dan run sesudah dua gate di atas:

```powershell
& $Dotnet build .\tests\Zagent.TestChild\Zagent.TestChild.csproj -c Debug
if ($LASTEXITCODE -ne 0) { throw 'TestChild compile failed' }
& $Dotnet build .\tests\Zagent.SetupTests\Zagent.SetupTests.csproj -c Debug
if ($LASTEXITCODE -ne 0) { throw 'Setup tests compile failed' }
& $Dotnet run --project .\tests\Zagent.SetupTests\Zagent.SetupTests.csproj -c Debug --no-build
if ($LASTEXITCODE -ne 0) { throw 'Setup fixture tests failed' }
```

Jangan memakai `--no-build` setelah source test berubah tanpa rebuild. Full solution/Web/Files/ArcMap/installer release gate terpisah, tidak tersirat dari hasil di atas.

## 2 — Provision dan dashboard lokal (state-changing, approval terpisah)

Baca `packaging/scripts/Provision-WindowsDashboard.ps1`, helper `WindowsDashboard-Provisioning.ps1` dan kontrak owner sebelum eksekusi. Gunakan DataRoot baru yang owner pilih, bukan fixture test yang otomatis dihapus. Script tidak boleh menimpa enrollment/partial state; partial failure memerlukan offline owner recovery, bukan delete-and-retry otomatis.

Command source saat ini untuk DEV, setelah owner menyetujui pemilihan certificate/kepercayaan dan DataRoot:

```powershell
$DataRoot = Read-Host 'New approved dedicated private DataRoot'
$Workspace = Read-Host 'Configured installation workspace identifier'
$Account = Read-Host 'Local dashboard account name'
$CoreExe = Join-Path $Repo 'src\Zagent.Core\bin\Debug\net10.0\Zagent.Core.exe'
if (-not (Test-Path -LiteralPath $CoreExe -PathType Leaf)) { throw 'Locate actual built Core apphost; do not invent a path' }
# -CreateCertificate mutates CurrentUser My; no automatic trust or startup registration.
& .\packaging\scripts\Provision-WindowsDashboard.ps1 -Development -InstallRoot $Repo -DataRoot $DataRoot -CoreExecutable $CoreExe -WorkspaceId $Workspace -Account $Account -CreateCertificate
# STOP on any error. Validate trust locally before launch; never bypass TLS validation.
& $CoreExe --dashboard --root $Repo --data-root $DataRoot --dashboard-config (Join-Path $DataRoot 'config\dashboard.json')
```

Paths/apphost contract must be checked against actual Windows build output. Provisioning does not mean running. Current lifecycle may still resolve all agent runtimes before dashboard and writes local identity/config during initialization: inspect owner `CORE-READINESS.md`, capture real failures, do not claim Files-only startup until demonstrated. Missing Web/ArcMap runtime or transport is not permission to install/start everything silently.

Dashboard checks in browser DevTools/local trusted HTTPS:

1. Origin exact `https://localhost:19443/`, no certificate bypass. Network bind remains loopback, no forwarded/proxy identity trust.
2. Unauthenticated `/api/*` is 401, not a successful HTML login redirect. Login error must not disclose password/account hash. Correct owner login succeeds.
3. Missing/foreign/null Origin mutation rejected; correct-origin without anti-CSRF token rejected. Valid CSRF plus valid session plus authorized role required. Do not test destructive commands: use nonmutating check action authorized by UI.
4. Verify security headers/no-store, SameSite Strict Secure HttpOnly auth cookie. Check session stamp/account revocation offline only on disposable enrollment; restart/relogin expected.
5. Closing tab must not stop Core. Explicit shutdown once must stop same lifecycle owner; no duplicate supervisor. These are Windows runtime assertions, NOT_RUN until observed.

## 3 — MCP local authentication + initialize/catalog

UI **19443 is not MCP**. Local Router MCP `http://127.0.0.3:18810/mcp`; direct Files 18820/internal management must not become public. GET `/healthz` (even HTTP200), catalog alone and running process do not establish usable Files read/write.

Only after real external AS, actual DataRoot Router config, server-owned principal/workspace/profile mapping and local Files approval are configured, approved Files/Router processes are launched through the existing Core lifecycle, and bearer is securely provided as process env `ZAGENT_ACCEPTANCE_BEARER`:

```powershell
# Inspect actual router source PROTOCOL; currently 2025-11-25, marked candidate by server.
Select-String -LiteralPath .\agents\tunnel\engine\router\server.py -Pattern '^PROTOCOL ='
py -3.11 .\scripts\accept_local_mcp.py --config (Join-Path $DataRoot 'tunnel\config\tunnel.json') --protocol 2025-11-25
if ($LASTEXITCODE -ne 0) { throw 'MCP initialize/catalog BLOCKED or failed' }
# Clear bearer env in the owner process after use; never print it.
Remove-Item Env:ZAGENT_ACCEPTANCE_BEARER -ErrorAction SilentlyContinue
```

Probe validates config presence (not deployment), refuses `.example`/missing AS/resource configuration before network, no redirects/proxy, loopback-only fixed router port, MCP protocol matching and full cursor traversal. It prints only `INITIALIZE_CATALOG_ONLY`, protocol/count, read/write NOT_RUN, release_ready=false. Actual negotiated version comes from initialize response; do not replace protocol versions with product1.0.0. Probe is source authored, not executed on VPS.

Negative auth gate: missing/malformed/wrong-audience/expired/revoked bearer and revoked/wrong workspace/profile mapping must fail without effect. Use real AS-issued restricted test credentials securely. Router policy test source `agents/tunnel/engine/tests/test_files_resource_policy.py` remains parent-owned; run only on isolated approved Windows data/journals and installed real dependencies. Do not import/run it in VPS or point imports at active DataRoot.

## 4 — Read sentinel, then separately authorized write canary

- Owner approves exact narrow fixture root/profile/principal/workspace. Create one known small nonsecret sentinel locally, record expected bytes/hash locally. Initial grant is read-only and exact read tools. Obtain tool schemas from actual catalog; no invented argument names.
- Authenticated `files_stat`/`files_read` (according to real schemas) must return actual sentinel bytes. If task accepted, poll `zagent_task_status` then `zagent_task_result` until terminal success; HTTP200/accepted alone is not PASS. Verify bytes/hash and source unchanged. Unexpected root/profile/placement/deadline fails closed.
- Write is **NOT_RUN until separate explicit root+scope approval**. Unique absent filename within approved fixture only; exact one-file write tool/scope, approved read-write local profile. Read-back actual bytes/hash; cleanup only that canary when separately authorized, then verify absence. Never overwrite repo or recursively delete a root.
- Do not test `files_exec_command`, PowerShell/git/build/test/process/update over public MCP: command/update remain management-only. Product test execution is manual Windows phase1, not a public arbitrary shell capability.

## Reporting labels

Record each gate as `SOURCE_ONLY_PASS`, `WINDOWS_BUILD_PASS`, `WINDOWS_TEST_PASS`, `RUNTIME_PASS`, `BLOCKED_NOT_CONFIGURED`, `FAIL`, or `NOT_RUN`, with project/configuration/output evidence and no secrets. All mandatory gates including actual sentinel read, separately authorized canary, security negatives, intended agent regressions and release packaging evidence must pass before product-ready. Missing AS/HTTPS existing deployment keeps remote MCP blocked even if local dashboard passes. No remote endpoint/tunnel is provisioned by this runbook.
