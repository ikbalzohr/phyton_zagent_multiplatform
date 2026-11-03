# Full installed payload dan default Files profile — 3 November 2026 (WITA)

**Status akhir:** INSTALLED ON DISK / **7.014/7.014 PROGRAM FILES VERIFIED** / PROFILE CONFIG VERIFIED / LIVE START NOT RUN (EXECUTABLE ALLOWLIST BLOCKED). Ini instalasi lengkap **pada target Windows yang sudah dipilih**, bukan klaim bahwa semua release gate distribusi umum atau live MCP sudah PASS.

## Keputusan pengguna dan ruang lingkup

- Lokasi final tetap `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform\`.
- Tidak membuat ulang profile default, tidak menyalin profile Production, tidak menimpa persistent `data/`, `workspace/`, OAuth/DPAPI, atau mengubah grant.
- Hanya source/instalasi Zagent Multi Platform yang berubah. Zagent Master Production tetap berjalan.
- Pengguna meminta instalasi penuh (bukan hanya membangun source atau fixture) dan mengingatkan bahwa mekanisme profil default sudah ada di kode.

## Temuan penyebab profil tidak tampil pada Dashboard

1. `ManagerCoreHost.cs` mengkonfigurasi `DefaultProfileName: "appBridge"`, `DefaultProfileRoot` dari `machine.files_default_profile`, `DefaultProfileMode: "read-only"`.
2. `FilesConfigurationWriter.BuildProfilesAsync` membuat profil default hanya jika `data/files/config/profiles.json` belum ada, dan mempertahankan profil yang ada bila sudah ada. Ini desain yang tepat, **tidak diubah**.
3. Konfigurasi installed `profiles.json`: `schema_version=2.0`, `active_profile=appBridge`, hanya satu profile, root `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform\workspace`, enabled, authorized_by_user, mode read-only; folder ada.
4. Route Dashboard `/api/management/v1/workspaces` menggunakan `ProfileAdministrationClient.CatalogAsync`; ini secara sengaja **fail-closed** bila authority profil belum diprovision.
5. `resource_server.grants` memiliki satu owner grant aktif dan `files:read`, tetapi **tidak memiliki `files:write` maupun `profile_management` capability**, dan tidak memiliki `tool_policy` untuk `files_profile_catalog_snapshot` atau enam operasi admin. Ini menjelaskan tidak munculnya katalog melalui route administrasi (tidak sekadar profilenya kosong).
6. Script resmi `Enable-OwnerProfileAdministration.ps1` memerlukan scope `files:read` **dan** `files:write` yang sudah ada. Script menolak membuat/memperbesar scope otomatis. Helper tersebut tidak ditemukan dalam `setup/` instalasi. **Tidak ada eskalasi scope atau penambahan tool grant** pada pekerjaan ini.

## Perubahan minimal yang diterapkan

- `src/Zagent.Core/Dashboard/DashboardProfileAdministration.cs`: menambah **GET `/api/management/v1/workspaces/local-profiles`**, hanya untuk Windows **Administrator** yang terautentikasi. Route mengambil snapshot lokal yang dibaca oleh `FilesManagerReadModel.GetProfilesAsync`, memproyeksikan nama/root/mode/enabled/default/authorized sebagai informasi `local-config-read-only`; `administrativeAccess=false`. Route hanya mengembalikan informasi, tidak menerima mutasi, grant, principal atau pemilihan profile dari browser.
- Route **otoritatif** `/workspaces` serta POST/PUT/DELETE/set-default **tidak diubah**, tetap mengharuskan private Files authority dan mengembalikan error saat belum terkonfigurasi.
- `src/Zagent.Core/wwwroot/dashboard.js`: jika katalog otoritatif merespons 503, meminta `workspaces/local-profiles`, menampilkan tabel `name/root/mode/enabled/active/authorized_by_user` berlabel **LOCAL CONFIG / READ ONLY**, dan menyembunyikan form create serta seluruh tombol edit/delete/default. Status yang tampil **bukan** bukti grant backend. Status 401/403 tidak di-fallback.
- `tests/Zagent.DashboardTests/Program.cs`: uji proyeksi mempertahankan path appBridge, default dan `administrativeAccess=false`.

## Instalasi lengkap target Windows dan bukti

- Baseline installed manifest memiliki **7.014 tracked program files** dan validasi sebelum perubahan menunjukkan 7.014/7.014 cocok hash.
- Repo source tidak memiliki input lengkap untuk official `Build-ProductionPayload.ps1` (portable Python/Node archive, snapshot ArcMap/vendor/addin, publish semua executable) dan tiga release gate melaporkan masalah: versi manifest komponen belum kanonis, snapshot ArcMap source tidak ada, dan Chrome bundle guard DashboardHost. **Tidak membypass, mengklaim PASS, atau mengubah kriteria release gate.**
- Untuk memperbarui **satu instalasi yang telah memiliki runtime lengkap**, kandidat installation-specific dibuat dari seluruh 7.014 file yang sebelumnya diverifikasi dan overlay Core Release self-contained serta delta source yang sudah diuji. Kandidat disimpan di `D:\3-Ikbalzohr\Agent\ZagentMP-Candidate-20261103\payload`.
- Core Release terbaru yang memuat route dan UI fallback dipublish dengan `packaging/scripts/Publish-Core.ps1`; digest SHA256 final `07004DE869833E87DC5125A57DA9D4ED10DA43A2C217FE96951959CECB91BD98`.
- `Zagent.Setup verify` terhadap kandidat: **7.014/7.014 PASS**.
- `Zagent.Setup install` ke folder final: **Success=true, 7.014 verified, 6 changed**; backup otomatis dibuat di `data/backups/setup/20261103_144011_913`.
- `Zagent.Setup verify` awal setelah instalasi mengidentifikasi **hanya** `agents/web/engine/extension/bridge-config.json` berbeda (7.013 match, 1 hash mismatch); `ChromeBridgeConfigurationSynchronizer` saat installer menginisialisasi mengubah endpoint lokal lama 18831 ke 19130. Ini file runtime-generated, bukan program korup.
- Kandidat installation-specific **diselaraskan hanya** pada file bridge tersebut menggunakan konfigurasi yang divalidasi: `schemaVersion=2`, `environment=PRODUCTION`, `defaultBase=http://127.0.0.3:19130/bridge/`, `generatedBy=Zagent.Core runtime configuration`, `generatedFrom=zagent.machine.json`, `legacyBases=[]`. Ini bukan paket generik siap distribusi.
- `Zagent.Setup verify` kandidat baru: 7.014/7.014 PASS, lalu `install` ulang: Success=true, 7.014 verified, 0 changed, backup root `data/backups/setup/20261103_144408_841`.
- **Verifikasi installer FINAL langsung ke folder installed:** `Zagent.Setup verify --target <installed> --source <candidate>`: **Success=true, FilesVerified=7014, FilesChanged=0**.
- File `profiles.json` pascainstalasi cocok hash sebelum instalasi (`0D0EF1D651AA7614CE70B7389E2077C6786CC7B025FC9180D29A751DE0F206DE`), machine config juga cocok hash (`AFB50E9BDD7014AEA01F976DEF9486C549C2A2FB579B1CFC7405BEE1D281B3CE`). Core exe dan UI asset cocok kandidat.
- Source test: Core Release build 0 warnings/errors, `DashboardTests` PASS dengan test fallback, `ArchitectureTests` 29/29, `ManagerTests` 19/19, `ManagerFeatureTests` 13/13, `DashboardOwnerTests` exit 0, `ProfileAdministrationTests` PASS (butuh fixture argument `tests/contracts/profile-admin-wire-v1.json`; invocation awal tanpa argumen exit 1 karena penggunaan salah), `node --check` PASS. Tidak mengklaim live acceptance.

## Konfigurasi akhir

- Dashboard HTTPS: `https://localhost:19444/`.
- Core machine port: 19100, Router MCP: `http://127.0.0.3:19110/mcp`; Files: `http://127.0.0.3:19120/mcp`; Web/Chrome Bridge: 19130; ArcMap: 19140; QGIS opsional: 19150; Development Gateway 19200–19299.
- Profile default: `appBridge`, root instalasi `workspace`, mode read-only, authorized=true, enabled=true.
- Profile administration/grant **belum** diprovision; owner local inventory hanya untuk tampilan dan tidak memberi hak menulis.

## Batas yang tetap ada

- Saat audit final: **0 proses Multi Platform aktif**, Router 19110 **belum listening**. Upaya tool `files_process_start` dari Zagent Production untuk Core MP sebelumnya ditolak executable allowlist; **tidak melakukan bypass**.
- Production: **7 proses** dan **5 listener** utama (`18810/18811/18820/18830/18840`) tetap aktif. Tidak ada perubahan ke Production.
- Profil lokal baru **belum diuji di Dashboard live**; UI hasil test/projection source bukan bukti tersedia di browser pada saat offline.
- Cloudflare masih harus menunjuk ke origin baru `http://127.0.0.3:19110` setelah listener aktif; belum mengubah tunnel/domain/Keycloak.
- Source release gate penuh masih BLOCKED. File package kandidat bersifat **installation-specific**; jangan mempromosikannya menjadi installer distribusi baru tanpa membangun dari seluruh input resmi dan lulus gate.

## Tindakan operator untuk menyelesaikan runtime acceptance

1. Jalankan `Zagent.Launcher.exe` milik instalasi Multi Platform melalui Windows interaktif pemilik, atau atur persetujuan executable melalui Zagent allowlist resmi. Jangan jalankan Zagent Master Launcher dan jangan bypass allowlist.
2. Buka `https://localhost:19444/#workspaces`. Jika private administration belum diprovision, daftar `appBridge` dan path `...\workspace` harus muncul sebagai **local-config-read-only** tanpa tombol mutasi. Jangan anggap munculnya tabel sebagai aktivasi izin tulis.
3. Periksa proses Core/Files/Router, listener, error Dashboard, dan status agent independen. Jika perlu admin profile write, lakukan provisioning owner secara terpisah dengan izin explicit yang benar, bukan melalui fallback.
4. Baru setelah Router 19110 ready, pindahkan Cloudflare origin MP ke `http://127.0.0.3:19110`; uji metadata OAuth, anonymous 401, dan authenticated read-only `files_stat`.
5. Simpan backup dan dokumentasikan hasil end-to-end sebelum menyatakan layanan siap.

**Commit/push:** NOT PERFORMED; working tree preexisting changes preserved dan `artifacts/` tidak distage.
