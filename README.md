# Zagent Suite 1.0.0 — source integration

Satu produk MCP netral: HTTPS MCP → Tunnel/router/workflow → **Files1, Web1, ArcMap1**. Core1 adalah satu pemilik lifecycle Windows per-user; UI1 adalah dashboard web same-origin yang dilayani Core. Tidak ada WPF Manager produk, mode provider, approval/binding per chat, atau otoritas berdasarkan nama client. Installer native Setup/Bundle tetap khusus install/repair/uninstall.

**Status: source integration, bukan rilis accepted.** Semua produk termasuk Files memakai versi `1.0.0`. Build/test/install/live acceptance belum dijalankan pada pekerjaan ini; semuanya hanya pada Windows lokal yang diizinkan. Angka versi target bukan bukti release-ready. Provenance baseline `222341c3840b4048b8f19c534e8619fbc6a711f0`; inventaris historis disimpan di `docs/history/`, tidak dikirim sebagai konfigurasi payload baru.

## Struktur

- `src/Zagent.Core`: lifecycle + ASP.NET Core/Razor dashboard, `src/Zagent.Shared`: kontrak.
- `src/Zagent.Setup`, `src/Zagent.Bundle`: installer native, bukan UI manajemen kedua.
- `src/Zagent.Manager`: source referensi lama milik stream C; tidak dipublish/dipaketkan sebagai produk.
- `agents/{tunnel,files,web,arcmap}`: engine dan manifest agent; versi dependency/protokol/vendor tidak di-reset.
- `component-manifest.json`: versi suite/product-line, status bukti; `capability-inventory.json`: policy rekonsiliasi katalog, bukan tool-count/runtime PASS historis.
- `packaging/scripts`: workflow Windows dan gates; `dev`: launcher terisolasi.

## Windows lokal: prasyarat

.NET SDK sesuai `global.json` (pin tidak diubah), Node/npm sesuai package lock Web, Python modern terpisah per-agent. ArcMap Desktop/Python2.7/ArcPy dan Chrome eksternal tetap perlu mesin desktop/lisensi yang sah. Tidak ada service Session0 sebagai default. Source checkout tidak mengandung seluruh payload eksternal.

Baca [toolchain](docs/TOOLCHAIN_REQUIREMENTS.md), [runbook rilis/migrasi](docs/RELEASE-V1.md), [DEV](dev/README.md). Tidak melakukan install SDK atau koneksi ingress otomatis.

## Build dan harness (perintah untuk Windows, belum dijalankan)

Dari source root di Windows, pilih evidence directory **baru di luar source**:

```powershell
& .\packaging\scripts\Invoke-WindowsValidation.ps1 `
  -Dotnet 'dotnet' -EvidenceRoot $EvidenceRoot -RunHarnesses
```

Script menginventarisasi semua `.csproj`, build TestChild dahulu, build project satu per satu, dan menjalankan console harness memakai `dotnet run --no-build`, bukan menganggap `dotnet test` menjalankan proyek Exe. Default harness subset: Setup/Architecture/Supervisor/ArcMapWorkflowUnit. `-HarnessTests` memilih daftar eksplisit. Hasil subset tidak berarti full acceptance; unexpected SKIP/BLOCKED adalah error. Environment/interpreter/fixture live harus dipenuhi terpisah sebelum memilih harness integration. Jangan arahkan fixture ke data pengguna/source.

```powershell
& .\packaging\scripts\Publish-Core.ps1 -Dotnet 'dotnet'
& .\packaging\scripts\Publish-Setup.ps1 -Dotnet 'dotnet'
& .\packaging\scripts\Publish-Bundle.ps1 -Dotnet 'dotnet'
# Setelah seluruh runtime, snapshots, AddIn implementation dan input eksternal tervalidasi:
& .\packaging\scripts\Build-ProductionPayload.ps1 -OutputRoot $FreshStaging
& .\packaging\scripts\Build-SingleExeBundle.ps1 -PayloadRoot $FreshStaging -OutputFile $FreshBundle
```

`Publish-Manager.ps1` hanya alias publish Core untuk nama script historis, tidak membangun WPF Manager. Payload menyalin **seluruh** publish Core termasuk assets dashboard. Staging/publish/bundle menolak output existing. Browser binaries Chromium/Firefox/WebKit dilarang; hanya FFmpeg helper, Chrome eksternal. Hash manifest bukan publisher signature; signing/trust bundle masih release blocker.

## Instalasi dan keamanan

Installer memakai engine backup/stage/hash/reconcile yang ada. In-place update hanya dari lini `zagent-mcp-v1`; legacy/damaged manifests ditolak dan wajib cutover offline ke target baru. Data/izin lama tidak otomatis diimpor. Tidak menjalankan dua produk untuk rollback.

Fresh install sengaja **NOT_CONFIGURED** sampai sertifikat TLS CurrentUser, direktori private owner dan akun dashboard diprovision out-of-band. `Provision-WindowsDashboard.ps1` memanggil prompt password lokal Core (tidak menerima password lewat argumen) dan dapat mendaftarkan startup per-user secara opt-in. Management remote default OFF. Lihat runbook sebelum menjalankan. Closing browser tidak menghentikan Core.

Jangan commit payload binary, runtime/cache, secret/DPAPI vault, certificate/private key, identitas aktual, logs atau cookies. Tidak ada commit/push/deploy otomatis dalam workflow ini. Bukti Windows/client/ArcMap nyata wajib sebelum promotion digest candidate yang sama.
