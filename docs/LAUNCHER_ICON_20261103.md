# Zagent Multi Platform — identitas ikon Launcher (3 November 2026 WITA)

## Cakupan dan sumber

**Permintaan pemilik:** hanya logo `Zagent.Launcher.exe`, termasuk ikon aplikasi/window/taskbar milik Launcher dan shortcut Desktop/Start Menu. **Tidak** mengubah ikon `Zagent.Setup.exe`, Core, plugin produksi atau ikon Google Chrome.

- PNG sumber pengguna: `image/zohrsystem.png`, 1254×1254 piksel, SHA256 `205AC9B93D9E8F10B1E0C00FC8DF532EE25AB2785D38AA2329EE0E7B608A8B03`.
- Konversi menggunakan `packaging/scripts/New-LauncherIcon.ps1`: tujuh frame `16,24,32,48,64,128,256`. Untuk ukuran hingga 128 memakai Windows-compatible bottom-up BGRA DIB dan AND mask; untuk 256 memakai PNG. Ukuran lebih kecil menggunakan high-quality bicubic resampling.
- ICO terverifikasi: `image/zohrsystem.ico`, SHA256 `BB0B5EAB4CF2514B9C501BA2B623C164F27F336A3BB2BD9C96046EDEB2924BDF`.
- `src/Zagent.Launcher/Zagent.Launcher.csproj` menetapkan `ApplicationIcon` ke `../../image/zohrsystem.ico`. Tidak ada perubahan `Zagent.Setup.csproj`.
- Windows EXE apphost terbukti memuat resource ikon. Ekstraksi asosiasi ikon native Windows pada apphost Release dibandingkan dengan ICO 32px **1.024/1.024 piksel identik**. Test otomatis membandingkan byte image resource 32px terhadap isi PE.
- `src/Zagent.Setup/WindowsInstallationIntegration.cs` **sudah** menetapkan shortcut `IconLocation = <installed Zagent.Launcher.exe>,0`, tidak perlu diubah. Setelah instalasi, dua shortcut user CurrentUser diverifikasi tetap memiliki target dan icon reference yang tepat. Tampilan akhir Explorer/taskbar dapat terpengaruh cache Windows dan belum diuji melalui tangkapan layar desktop.

## Bukti build dan regresi

- `dotnet build src/Zagent.Launcher/Zagent.Launcher.csproj -c Release --no-restore`: **0 warning, 0 error**.
- `dotnet run --project tests/Zagent.LauncherTests/Zagent.LauncherTests.csproj -c Release -- <dotnet.exe>`: **50/50 PASS**, termasuk pemeriksaan grup ICO serta resource native EXE.
- `packaging/scripts/Publish-Launcher.ps1` ke output staging terpisah: **PASS**, self-contained single-file `win-x64`; EXE SHA256 `6AB373B19E7DE7083EB5EC60F0FA4DCD5EADF10C385F4D194FF437E9E945E0AD`; ikon 32px tertanam di PE.
- `Zagent.SetupTests` **10/10 PASS** setelah membangun prasyarat `tests/Zagent.TestChild` Debug dan menetapkan `ZAGENT_DEV_ROOT` ke repo checkout. Percobaan awal: 9 pass/1 failed hanya karena fixture path tidak tersedia, bukan kegagalan kode program.
- Regression source tambahan: Architecture **29/29 PASS**, Manager **19/19 PASS**, ManagerFeature **13/13 PASS**, Supervisor **11/11 PASS**, QGIS **PASS**, Dashboard policy **exit 0**.
- Router source: `py -3.11 -m unittest discover -s tests -p test_*.py -q` dari `agents/tunnel/engine` **163 OK, 3 skipped**. Percobaan awal memakai bundled Tunnel Python yang tidak menyertakan `pytest`: 4 diagnostic failures dan 1 import error (pytest-only module), sedangkan eksekusi terisolasi diagnostic 10/10 PASS dan suite penuh dengan Python pengembangan lengkap **OK**. Tidak mengubah Router sebagai workaround untuk kekurangan dependensi tes runtime terpaket.
- `git diff --check` PASS. Rilis distribusi umum masih memerlukan validasi dan input penuh sesuai `RELEASE-V1.md`; jangan menganggap candidate instalasi-specific sebagai paket distribusi resmi.

## Pemasangan pada instalasi Multi Platform yang telah ada

Root: `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform`.

1. Kandidat terpisah `D:\3-Ikbalzohr\Agent\ZagentMP-Candidate-20261103\payload-launcher-icon` dibuat dari baseline verified 7.014 file dengan hanya satu perbedaan tracked entry `Zagent.Launcher.exe`. Kandidat lolos `Zagent.Setup verify` 7.014/7.014.
2. Sebelum update, original installed root juga lolos `Zagent.Setup verify` 7.014/7.014 dan SHA256 Launcher lama `1E05DA6FF2B406E168CBA6EDA338F11A8F0673ECFB0885F7D034E21A980BB66A`.
3. Upaya skrip update terbatas pertama memberi error internal tool tanpa task receipt. **Tidak diulang secara buta.** Pembacaan setelahnya membuktikan Launcher dan manifest masih memakai hash lama; tidak ada direktori backup update itu. Ketika diperiksa ulang, proses serta listener Multi Platform tidak aktif (penyebab berhentinya Core tidak dikonfirmasi; skrip tidak menjalankan stop).
4. Karena instalasi sedang idle, preflight sekali lagi memastikan tidak ada proses/listener Multi Platform lalu **SetupEngine resmi** digunakan: `install --target <installed> --source <payload-launcher-icon>` -> **Success=true, FilesChanged=1, FilesVerified=7014**, backup `data/backups/setup/20261103_154522_119`.
5. `Zagent.Setup verify` sesudahnya: **Success=true, FilesChanged=0, FilesVerified=7014**. Hash installed Launcher persis SHA256 published di atas. Shortcut Start Menu dan Desktop yang diregistrasi ulang keduanya mempunyai `IconLocation=<installed Launcher.exe>,0`.
6. `appBridge` masih read-only. Tidak ada perubahan Keycloak/Cloudflare/Production, tidak ada pemberian grant baru. Core Multi Platform **belum dijalankan kembali pada pekerjaan ikon**; uji remote MCP setelah perubahan ikon tidak dilaksanakan.

**Status:** `SOURCE_PASS / PUBLISHED_LAUNCHER_PASS / INSTALLED_ICON_PASS / FULL_PROGRAM_VERIFY_7014_PASS / LIVE_LAUNCHER_UI_NOT_CHECKED`.

## Catatan penggunaan

Launcher saat ini adalah aplikasi `WinExe` tanpa main window WPF/WinForms tersendiri: ia memulai atau menyambung Core, kemudian Dashboard dibuka melalui Chrome. Icon resource EXE dipakai shell Windows untuk executable, icon app pada taskbar/dialog milik proses Launcher dan shortcut yang menunjuk ke EXE; **ikon tab/taskbar Chrome sendiri tetap dikelola oleh Chrome**. Jika shortcut masih terlihat lama, pengguna dapat refresh Explorer/ikon shell (bukan tanda gagal build).

**Source Git:** dokumentasikan hash commit dan status push setelah operasi Git selesai. Jangan commit `artifacts/`, private runtime state, secrets atau signing key.
