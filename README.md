# Zagent Suite 1.0.0 — source integration

**Arsitektur target yang ditetapkan pengguna:** klien ChatGPT / Claude / Hermes / klien MCP → **HTTPS MCP + OAuth** → **Zagent Core (.NET 10)** → **Tunnel, Files, Web, ArcMap**. Dalam implementasi saat ini, MCP Router Python yang berada di modul Tunnel menangani ingress dan dapat meneruskan panggilan langsung ke upstream, sementara Core memiliki lifecycle, supervisor dan registry. Core1 adalah satu pemilik lifecycle Windows per-user; UI1 adalah dashboard web same-origin yang dilayani Core. Tidak ada WPF Manager produk, mode provider, approval/binding per chat, atau otoritas berdasarkan nama client. Installer native Setup/Bundle tetap khusus install/repair/uninstall.

**Status: source integration, bukan rilis accepted.** Semua produk termasuk Files memakai versi `1.0.0`. Targeted build/unit/harness Windows lokal telah dijalankan untuk perubahan netralisasi instalasi; full client/live/installer acceptance masih memerlukan evidence terpisah. Angka versi target bukan bukti release-ready. Provenance baseline `222341c3840b4048b8f19c534e8619fbc6a711f0`; inventaris historis disimpan di `docs/history/`, tidak dikirim sebagai konfigurasi payload baru.

## Arsitektur produk independen

Zagent Multi Platform adalah produk **MCP-first** tersendiri, bukan varian, dependensi runtime, atau deployment Zagent Dev/Production. Klien MCP yang kompatibel terhubung melalui HTTPS MCP + OAuth; tidak ada fallback otorisasi dari plugin produk lain. **Diagram target pengguna:** [ARCHITECTURE_TARGET.md](docs/ARCHITECTURE_TARGET.md). **Aturan kerja wajib (baca docs dahulu dan catat progres):** [WORKING_AGREEMENT.md](docs/WORKING_AGREEMENT.md). **Status koneksi ChatGPT:** [CHATGPT_OAUTH_CONNECTION.md](docs/CHATGPT_OAUTH_CONNECTION.md). Kontrak arsitektur dan aturan pemulihan task: [MCP_FIRST_ARCHITECTURE.md](docs/MCP_FIRST_ARCHITECTURE.md). Jalur identitas ChatGPT (pre-registered PKCE), Claude/Hermes (CIMD terikat domain), serta release gate OAuth: [MCP-OAUTH-MULTICLIENT.md](docs/MCP-OAUTH-MULTICLIENT.md).

## Struktur

- `src/Zagent.Core`: lifecycle + ASP.NET Core/Razor dashboard, `src/Zagent.Shared`: kontrak.
- `src/Zagent.Setup`, `src/Zagent.Bundle`: installer native, bukan UI manajemen kedua.
- `src/Zagent.Launcher`: peluncur mandiri per-installasi. Tidak memindai `*Zagent*` atau mengambil runtime dari instalasi lain; lihat `docs/WINDOWS-OWNER-LAUNCHER.md`.
- `agents/{tunnel,files,web,arcmap}`: engine dan manifest agent; versi dependency/protokol/vendor tidak di-reset.
- `component-manifest.json`: versi suite/product-line, status bukti; `capability-inventory.json`: policy rekonsiliasi katalog, bukan tool-count/runtime PASS historis.
- `packaging/scripts`: workflow Windows dan gates; `dev`: launcher terisolasi.

## Instalasi netral (tanpa role)

Produk menggunakan satu nama instalasi **Zagent** tanpa pilihan slot Primary/Secondary atau Master/User. Nama folder baru `Zagent`; nilai `installation_role` / `InstallationRole` dari konfigurasi lama tidak lagi menjadi otoritas atau penentu routing. Port yang tersimpan dibaca tanpa migrasi otomatis, termasuk blok lama; instalasi baru menggunakan kebijakan port netral dan allocator mengecek ketersediaan. Named pipe, supervisor lease, cache uninstaller, registrasi uninstall, serta folder konfigurasi privat baru dipisahkan memakai fingerprint deterministik dari **path root instalasi**, bukan nama operator, audience MCP, atau label instalasi.

**Batas migrasi:** runtime lama tidak di-restart/diubah oleh pekerjaan source ini. Akses plugin/credential yang sebelumnya tersimpan di direktori berdasarkan slot lama **tidak** dipindahkan secara otomatis ke direktori path-scoped. Sebelum cutover diperlukan migrasi offline yang diverifikasi atau enrolment ulang oleh owner, disertai pemeriksaan ACL, kredensial, endpoint, dan cleanup shortcut/registration lama. Identitas perangkat dan installation UUID yang dipakai otorisasi MCP tetap dipertahankan; penghapusan role instalasi bukan penghapusan security binding.

## Windows lokal: prasyarat

.NET SDK sesuai `global.json` (pin tidak diubah), Node/npm sesuai package lock Web, Python modern terpisah per-agent. ArcMap Desktop/Python2.7/ArcPy dan Chrome eksternal tetap perlu mesin desktop/lisensi yang sah. Tidak ada service Session0 sebagai default. Source checkout tidak mengandung seluruh payload eksternal.

Baca [toolchain](docs/TOOLCHAIN_REQUIREMENTS.md), [runbook rilis/migrasi](docs/RELEASE-V1.md), [DEV](dev/README.md). Tidak melakukan install SDK atau koneksi ingress otomatis.

## Build dan harness (perintah untuk Windows, belum dijalankan)

Dari source root di Windows, pilih evidence directory **baru di luar source**:

```powershell
& .\packaging\scripts\Invoke-WindowsValidation.ps1 `
  -Dotnet 'dotnet' -EvidenceRoot $EvidenceRoot -RunHarnesses
```

Script menginventarisasi semua `.csproj`, build TestChild dahulu, build project satu per satu, dan menjalankan console harness termasuk 33 assertions Launcher memakai `dotnet run --no-build`, bukan menganggap `dotnet test` menjalankan proyek Exe. Default harness subset: Setup/Architecture/Supervisor/ArcMapWorkflowUnit. `-HarnessTests` memilih daftar eksplisit. Hasil subset tidak berarti full acceptance; unexpected SKIP/BLOCKED adalah error. Environment/interpreter/fixture live harus dipenuhi terpisah sebelum memilih harness integration. Jangan arahkan fixture ke data pengguna/source.

```powershell
& .\packaging\scripts\Publish-Core.ps1 -Dotnet 'dotnet'
& .\packaging\scripts\Publish-Launcher.ps1 -Dotnet 'dotnet'
& .\packaging\scripts\Publish-Setup.ps1 -Dotnet 'dotnet'
& .\packaging\scripts\Publish-Bundle.ps1 -Dotnet 'dotnet'
# Setelah seluruh runtime, snapshots, AddIn implementation dan input eksternal tervalidasi:
& .\packaging\scripts\Build-ProductionPayload.ps1 -OutputRoot $FreshStaging
& .\packaging\scripts\Build-SingleExeBundle.ps1 -PayloadRoot $FreshStaging -OutputFile $FreshBundle
```

Hanya `Publish-Core.ps1` yang mem-publish Core dan Web Dashboard; tidak ada lagi proyek atau alias publish WPF Manager. Payload menyalin **seluruh** publish Core termasuk assets dashboard. Staging/publish/bundle menolak output existing. Browser binaries Chromium/Firefox/WebKit dilarang; hanya FFmpeg helper, Chrome eksternal. Hash manifest bukan publisher signature; signing/trust bundle masih release blocker.

## Instalasi dan keamanan

Installer memakai engine backup/stage/hash/reconcile yang ada. In-place update hanya dari lini `zagent-mcp-v1`; legacy/damaged manifests ditolak dan wajib cutover offline ke target baru. Data/izin lama tidak otomatis diimpor. Tidak menjalankan dua produk untuk rollback.

Fresh install sengaja **NOT_CONFIGURED** sampai sertifikat TLS CurrentUser dan direktori private owner diprovision out-of-band. `Provision-WindowsDashboard.ps1` mengikat Dashboard ke identitas pengguna Windows interaktif tanpa membuat login/password browser, dan dapat mendaftarkan startup per-user secara opt-in. Management remote default OFF. Lihat runbook sebelum menjalankan. Closing browser tidak menghentikan Core.

Jangan commit payload binary, runtime/cache, secret/DPAPI vault, certificate/private key, identitas aktual, logs atau cookies. Tidak ada commit/push/deploy otomatis dalam workflow ini. Bukti Windows/client/ArcMap nyata wajib sebelum promotion digest candidate yang sama.
