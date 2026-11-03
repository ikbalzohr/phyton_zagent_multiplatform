# Instalasi uji Zagent Multi Platform dan migrasi port — 3 November 2026 (WITA)

**Status:** **INSTALLED / OFFLINE CONFIG VERIFIED / LIVE START BLOCKED BY EXECUTABLE ALLOWLIST**. Ini pembaruan **instalasi uji**, **bukan** promosi release produksi. Tidak boleh mengklaim Cloudflare/OAuth live PASS sesudah migrasi.

## Lokasi dan batas

- Source: `D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform`.
- Instalasi tujuan yang diperbarui: `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform`.
- Kandidat terpisah: `D:\3-Ikbalzohr\Agent\ZagentMP-Candidate-20261103\payload`; Release Core di folder sibling `publish/core`.
- Production `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Master` hanya diperiksa read-only. Tidak ada perubahan binary, registry, proses, port, konfigurasi, tunnel ID, OAuth atau credential Production.
- Tidak ada aksi Cloudflare/Keycloak. Domain publik saat ini harus disesuaikan dengan origin baru **setelah Router berhasil start**.
- Existing `data`, `workspace`, OAuth grant, DPAPI, browser state, jurnal task dan device identity tidak dibawa ke kandidat dan tetap di instalasi yang sama.

## Packaging: delta dari baseline berintegritas, bukan release builder resmi

Repo sumber tidak menyediakan `packaging/runtime` lengkap, source ArcMap snapshot/vendor27/addin, atau seluruh publish output yang diperlukan `Build-ProductionPayload.ps1`. Release gate source juga tidak PASS: `Test-ReleaseSource.ps1` berhenti pada versi manifest Tunnel yang tidak kanonis, `Test-KnownBugRegressions.ps1` menemukan snapshot ArcMap hilang, dan `Test-WebPersistentConsentBundle.ps1` menemukan guard Chrome pada DashboardHost belum terpenuhi. **Jangan sebut ini hasil official Build-ProductionPayload/installer release-approved**.

Sebagai alternatif untuk **instalasi uji yang sudah ada**, dilakukan:
1. Verifikasi **7.014/7.014 file** pada installed `payload-manifest.json`, **0 missing/0 hash mismatches**.
2. Publish Core melalui `packaging/scripts/Publish-Core.ps1` — **Release win-x64 self-contained PASS**. SHA256 Core Release: `C0A0DDF228B6F3C0284C789F63DC6CF29353304518B8E82A06505112218D7D3C`.
3. Staging hanya file yang **terdaftar di manifest** (7.014 entri, sekitar 577,8 MiB), tanpa `data/` atau `workspace/`. Overlay output Core Release (exe, web.config, static webassets/wwwroot) dan delta source Router registry/server, ArcMap MCP server, Files allowlist bootstrap serta metadata komponen Tunnel/Web/ArcMap; total **16 entri kandidat di-overlay**. Entri yang hash-nya identik dengan instalasi tidak menyebabkan copy ulang saat Setup berjalan.
4. Memperbarui hash/size manifest staging sesuai file kandidat. SHA256 candidate `payload-manifest.json`: `35EC42BAE25501F2FD12742DBEC46B1863F5F246208FC09ECB644580513EBCF0`.
5. `Zagent.Setup` `verify` pada kandidat → **7.014 verified / PASS**.
6. Tujuh file konfigurasi privat dipertahankan dalam backup berdampingan dengan akhiran `.preinstall-20261103.bak`, masing-masing diperiksa hash.
7. Jalankan **SetupEngine `install --target <installed> --source <candidate>`** → **Success=true; FilesVerified=7014; FilesChanged=8**. Backup program bawaan Setup dibuat di `data/backups/setup/20261103_135641_029` dalam root instalasi uji. Program tracked yang diperiksa, termasuk Core exe, Router server/registry, Files dan ArcMap, cocok hash-nya dengan kandidat.
8. Migrasi `data/config/zagent.machine.json` dengan file sementara dan **atomic File.Replace**, menggunakan file konfigurasi lama sebagai backup kedua `.migration-replace-20261103.bak`. Percobaan pertama memakai `File.Move(src,dst,overwrite)` yang tidak didukung PowerShell .NET Framework lokal; **tidak mengubah target**. `File.Replace` berikutnya berhasil dan dibaca ulang.
9. Patch minimal field port pada persisted `data/tunnel/config/tunnel.json`, `core_services.json`, `data/files/config/settings.json`, `data/web/config/settings.json`, dan `bridge.json`. **Bukan rewrite konfigurasi OAuth.** Verifikasi struktural membuktikan resource server OAuth, `tool_policy`, dan `workflow_policy` **identik** dengan backup pre-install.

## Konfigurasi port lokal setelah instalasi (verified on disk)

| Fungsi | Port/endpoint |
| --- | --- |
| Core machine-config | 19100 (tidak selalu listener tersendiri pada `--serve-dashboard`) |
| Tunnel MCP Router | `http://127.0.0.3:19110/mcp` |
| Tunnel Health/transport | 19111 |
| Files | `http://127.0.0.3:19120/mcp` |
| Web | `http://127.0.0.3:19130/mcp` dan `http://127.0.0.3:19130/bridge/` |
| ArcMap | `http://127.0.0.3:19140/mcp` |
| QGIS (jika diaktifkan) | 19150 |
| Development Gateway | 19200–19299 |
| Development Runtime | 19300–19399 |
| Local Dashboard HTTPS | `https://localhost:19444/` (unchanged) |

Publik MCP hostname `zagent.ikbalzohr.web.id` sebelumnya diarahkan melalui Cloudflare ke `http://127.0.0.3:18812`. **Sesudah layanan siap, ubah origin Cloudflare ke `http://127.0.0.3:19110`**; hostname dan path `/mcp` serta metadata OAuth tidak perlu diganti hanya karena perubahan port lokal. **Belum ada tindakan Cloudflare** dan Router belum aktif pada origin baru ketika laporan dibuat.

## Status live start dan keamanan

Panggilan melalui Zagent Production `files_process_start` untuk menjalankan installed `Zagent.Core.exe --serve-dashboard --root ...` **ditolak** oleh allowlist resmi dengan `Executable is not allowed`. **Tidak dilakukan bypass via PowerShell, dotnet-run, atau proses tak berotorisasi.** Karena itu status: `LOCAL_CORE_START=BLOCKED_BY_ALLOWLIST`; `LIVE_ROUTER_DISCOVERY=NOT_RUN`; `CLOUDFLARE_ROUTE_NEW_ORIGIN=NOT_RUN`; `OAUTH_END_TO_END_AFTER_MIGRATION=NOT_RUN`.

Pemeriksaan read-only akhir: **0 proses Multi Platform aktif**, **7 proses Zagent Production** terdeteksi, dan kelima listener utama Production tetap aktif pada `127.0.0.3:18810/18811/18820/18830/18840`. New origin `127.0.0.3:19110` **belum listening**. Tidak ada server yang dihentikan.

## Uji dan catatan risiko

- Sebelum kandidat: Core Debug build 0 warning/error, Architecture 29/29, Manager 19/19, ManagerFeature 13/13, Supervisor 11/11, Setup 10/10, QGIS PASS, Dashboard PASS, Router Python 163 OK/3 skipped. Seluruh angka ini adalah **source-test**, bukan bukti installed runtime.
- Kandidat: Release Core publish PASS, candidate manifest 7014/7014 hash PASS, SetupEngine update PASS, installed selected-file hash PASS, persisted port config read-back PASS, OAuth/tool/workflow config preservation PASS.
- Pemeriksaan policy rilis penuh masih **BLOCKED**, sehingga jangan menyatakan release-ready. Candidate staging/backup harus dipertahankan sampai runtime acceptance dan rollback window selesai. Cakupan ArcMap/QGIS GUI, Chrome extension endpoint cache, OAuth introspection live, restart persistence, Cloudflare ingress masih **NOT_RUN**.
- Risiko kompatibilitas Chrome Bridge: endpoint runtime/config telah berubah dari 18831 ke 19130; ekstensi Chrome yang menyimpan URL lama dapat memerlukan sinkronisasi/pairing saat Core/Chrome dibuka. Tidak menghapus storage browser atau melakukan ulang consent diam-diam.

## Langkah berikutnya — owner UI

1. Di Windows milik pemilik, jalankan `Zagent.Launcher.exe` pada **instalasi Multi Platform** (bukan Zagent Master), atau berikan izin executable Core melalui Zagent Manager/allowlist resmi. Tidak boleh melakukan bypass policy executable.
2. Verifikasi Dashboard `https://localhost:19444/`, proses Core dan agent yang siap, listener Router `127.0.0.3:19110`, Files 19120, Web 19130, ArcMap 19140, serta logs/status Router dan `tools/list`. Periksa juga Production masih aktif.
3. **Baru setelah Router benar-benar ready**, sesuaikan satu Cloudflare published application origin dari `http://127.0.0.3:18812` menjadi `http://127.0.0.3:19110` (tanpa mengubah tunnel/API key Production). Cek GET metadata OAuth (200), POST MCP anonymous (401), kemudian OAuth/login/token authorized read-only `files_stat path="."`.
4. Jika startup gagal, pertahankan log dan gunakan backup pada lokasi di atas untuk rollback **hanya instalasi Multi Platform**; jangan menghapus data/journal/DPAPI atau mengganggu Production.
5. Catat hasil runtime aktual dan perbarui dokumen ini serta `CHATGPT_OAUTH_CONNECTION.md`.

## Pembaruan instalasi final dan tampilan profil — 3 November 2026

**Hasil setelah tindak lanjut:** Full installed target **7.014/7.014 program files PASS** melalui `Zagent.Setup verify`, Core Release baru dipasang dan Dashboard diberikan fallback **read-only** untuk katalog profil lokal. `appBridge` sudah ada di `profiles.json` (root = `...\\workspace`) sehingga tidak dibuat ulang. Penyebab Dashboard kosong: grant lokal hanya `files:read`, belum memiliki `profile_management` maupun `files:write`; jalur admin fail-closed secara benar. Endpoint lokal read-only terpisah `/api/management/v1/workspaces/local-profiles` disediakan khusus Administrator, tanpa admin rights atau pengubahan grant. Ini **tidak** menggantikan katalog otoritatif.

Perbedaan manifest dari Chrome Bridge setelah inisialisasi terdeteksi (1 dari 7014), diaudit sebagai `bridge-config.json` yang digenerasi Core untuk port 19130; kandidat **installation-specific** diselaraskan lalu terverifikasi 7014/7014. Detail build, tests, validasi, backup dan batas live: `docs/FULL_INSTALL_AND_DEFAULT_PROFILE_20261103.md`.

### Tindak lanjut Launcher icon — 3 November 2026

Pemilik meminta hanya Launcher menggunakan `image/zohrsystem.png`, meliputi native EXE/icon context dan shortcut. Dibuat `image/zohrsystem.ico` 7 resolusi, publish Launcher win-x64, 50/50 Launcher tests PASS, SourceSetup 10/10 PASS, serta paket program target diinstal ulang dengan SetupEngine ketika Core tidak berjalan. `FilesChanged=1`, `FilesVerified=7014`; verifikasi postinstall 7014/7014 PASS. Kedua shortcut target/icon reference PASS. Core/Router tidak dijalankan ulang; Keycloak/Cloudflare/Production tidak diubah. Detail dan backup: `LAUNCHER_ICON_20261103.md`.

**Git/source:** perubahan source sebelumnya sedang disiapkan untuk commit/push sesuai perintah terbaru pemilik; catat hasil Git terpisah setelah operasi selesai.
