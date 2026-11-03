# Audit dan koreksi port Zagent Multi Platform — 3 November 2026 (WITA)

**Scope:** repository `D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform`, instalasi uji `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform`, dan **inspeksi read-only** Zagent Production pada `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Master`.

**Ketentuan:** Produk terpisah; tidak menyalin/menyentuh credential, identitas, atau konfigurasi Production. Port **yang tersimpan**, port **yang benar-benar listening**, default **source**, dan kesiapan **instalasi** adalah tingkat bukti yang berbeda. Memodifikasi source tidak mengaktifkan binary terpasang.

## Inventaris terverifikasi sebelum perubahan

| Fungsi | Production (config) | Multi Platform (installed config sebelum patch) | Listener Production teramati | Penilaian |
| --- | --- | --- | --- | --- |
| Core (konfigurasi) | 18800 | **18800** | Tidak teramati pada 18800 | **Duplikat konfigurasi**; bukan bukti benturan socket aktif |
| Tunnel Router | 18810 | 18812 | 127.0.0.3:18810 | Port berbeda |
| Tunnel health/transport | 18811 | 18813 | 127.0.0.3:18811 | Port berbeda |
| Files MCP | 18820 | 18821 | 127.0.0.3:18820 | Port berbeda |
| Web MCP/Bridge | 18830 | 18831 | 127.0.0.3:18830 | Port berbeda |
| ArcMap MCP | 18840 | 18841 | 127.0.0.3:18840 | Port berbeda |
| Development Gateway | **18900–18999** | **18900–18999** | Tidak ada listener yang teramati di range | **Tumpang tindih rentang konfigurasi** |
| Dashboard lokal HTTPS | Tidak ada file `data/config/dashboard.json` di instalasi Production yang diperiksa | 19444 | Tidak ada listener 19444 | Tidak ada benturan yang teramati |
| QGIS MCP opsional | Tidak ada listener QGIS teramati | Belum diaktifkan; source default lama 18850 | Tidak ada listener di 9876 saat snapshot | Perlu default baru terpisah |

Listener Production yang aktif saat audit: Tunnel 18810, Tunnel transport 18811, Files 18820, Web 18830, ArcMap 18840. Semua ada pada `127.0.0.3`. Tidak ada proses dengan executable path di bawah instalasi Multi Platform; port calon 18802, 19100–19150, 19200, 19300 dan 19444 tidak sedang listening. Pemindaian ini adalah **snapshot**, bukan lease atau jaminan port tersedia selamanya. Proses Cloudflare mempunyai listener internal dinamis yang bukan port layanan MCP dan tidak dimigrasikan.

Catatan: QGIS Desktop bridge memakai port loopback 9876 pada integrasi opsional, **berbeda** dari port MCP Agent. Source `QGIS_MCP_PORT` tidak dimodifikasi karena mengubahnya mengharuskan koordinasi dengan QGIS plugin.

## Perubahan source: default fresh install yang tidak bentrok

| Fungsi | Default source baru |
| --- | --- |
| Core | 19100 |
| Tunnel Router / transport health | 19110 / 19111 |
| Files / Web / ArcMap | 19120 / 19130 / 19140 |
| QGIS MCP opsional | 19150 (dicadangkan dari allocator built-in) |
| Fixed service allocation range | 19100–19199 |
| Development Gateway | 19200–19299 |
| Development runtime | 19300–19399 |
| Dashboard HTTPS yang sudah diprovision | tetap 19444; port berasal dari konfigurasi dashboard |

**Source yang disesuaikan:** `src/Zagent.Core/Network/ZagentNetworkPolicy.cs`, `ZagentPortAllocator.cs`, `Manager/ManagerCoreHost.cs`, `Manager/DevelopmentAgentStore.cs`, `Agents/Qgis/QgisIntegration.cs`, `Agents/ArcMap/ArcMapIntegrationModels.cs`; fallback Router/ArcMap Python, template/config Router, metadata komponen ArcMap/Tunnel/Web, dan bootstrap legacy allowlist. Test arsitektur, QGIS dan ManagerFeature diperbarui sesuai default baru. Test fixture yang eksplisit menguji port legacy 188xx dipertahankan apabila tidak menentukan default produk.

`IsSupportedPortBlock` mempertahankan pembacaan konfigurasi historis (188xx + gateway 189xx), default baru (191xx + gateway 192xx), serta **transisi non-disruptif** (188xx + gateway 192xx) untuk menjaga port layanan instalasi uji sebelum migrasi penuh. Tidak ada role Master/User yang diperkenalkan.

## Patch aman pada instalasi uji

Setelah verifikasi **0 proses Multi Platform** dan port 18802 tidak listening, hanya satu field diubah pada `data/config/zagent.machine.json` dengan pemeriksaan SHA-256 awal:

- `core_port: 18800 → 18802` — **APPLIED dan READ-BACK PASS**. Verifikasi akhir menunjukkan tidak ada fixed port yang identik antara kedua instalasi; hash SHA-256 setelah perubahan tercatat pada log pemeriksaan (tidak membutuhkan penyalinan file konfigurasi ke chat).
- `tunnel_port=18812`, `tunnel_health_port=18813`, `files_port=18821`, `web_port=18831`, `arc_map_port=18841` — **UNCHANGED**.
- `development_port_start=18900` / `end=18999` — **NOT CHANGED in installed configuration**. Binary Core yang terpasang masih memvalidasi kombinasi `188xx+189xx` atau `191xx+192xx`, bukan `188xx+192xx`; mengubah hanya gateway tanpa menerapkan binary Core baru dapat membuat aplikasi gagal startup. Source baru telah ditingkatkan untuk migrasi tersebut, tetapi **belum dipublish ke instalasi**.

Koreksi Core port pada konfigurasi lama sengaja memakai 18802 agar tetap sesuai validator binary terpasang. **Risiko tersisa:** port ini masih berada dalam rentang besar 188xx yang juga dipakai allocator Production; port 18802 tidak teramati dipakai sekarang, tetapi tidak ada jaminan reservasi lintas instalasi ketika MP offline. Solusi isolasi total memerlukan migrasi terkoordinasi semua endpoint MP ke 191xx beserta perubahan published Cloudflare route dari 18812, migrasi Chrome Bridge, dan verifikasi OAuth; **tidak dilakukan diam-diam** karena dapat memutus koneksi pengguna.

Tidak ada perubahan ke Production, Cloudflare route/domain, Keycloak, grant OAuth, Files profile, atau transport credentials. Tidak ada restart/deployment source/commit/push; hanya konfigurasi `core_port` installed MP yang ditulis. Setelah patch: **0 proses MP**, listener Production tetap di 18810/18811/18820/18830/18840, fixed-port intersection kosong. File machine config masih mewarisi ACL dari direktori `data/config` yang memiliki `AreAccessRulesProtected=true`; pemeriksaan tersebut bukan audit penuh DACL/DPAPI.

## Hasil pengujian source (3 November 2026)

- Core Debug build: **PASS**, 0 warnings, 0 errors.
- ArchitectureTests: **29 PASS / 0 FAIL** termasuk blok port baru, legacy readback, fallback, isolasi QGIS, dan penolakan campuran blok tidak sah. Satu pengujian awal melihat fixture lama yang menyimpan 18831; setelah fixture test disposable direset, PASS.
- ManagerTests: **19 PASS / 0 FAIL**; perubahan independensi startup dari pekerjaan sebelumnya tetap lolos.
- ManagerFeatureTests: **13 PASS / 0 FAIL** setelah fixture development disesuaikan ke 192xx.
- SupervisorTests: **11 PASS / 0 FAIL**.
- SetupTests: **10 PASS / 0 FAIL** setelah `ZAGENT_DEV_ROOT` dan TestChild Debug disiapkan; run awal tanpa fixture gagal 9/1 dan tidak disembunyikan.
- QGIS tests: **PASS**; default 19150 dan custom-port contract.
- DashboardTests: **PASS (exit 0)**.
- Router Python unittest: **163 tests OK (3 skipped)**.
- Python syntax changed files: **PASS**; JSON changed templates/manifests: **parse PASS**.
- ManagerFeatureTests memerlukan pemutakhiran fixture lama 18955/18960/18977 ke 19255/19260/19277; run pertama gagal 10/13, kemudian **13/13 PASS** sesudah koreksi fixture. `git diff --check` **PASS**.
- Live Core Multi Platform / installed Tunnel Router / Cloudflare/OAuth after patch: **NOT RUN**. Tidak ada klaim port isolasi runtime penuh atau release readiness. `Zagent.TunnelTests` lama pernah gagal karena fixture/prasyarat tidak lengkap pada pekerjaan sebelumnya dan bukan bagian test gate sukses ini.

## Gate berikutnya sebelum mengaktifkan perubahan penuh

1. Review dan build/publish candidate Core/Router/runtime serta manifest yang benar dengan toolchain Windows yang disetujui; jangan menyalin file Debug sembarang ke instalasi terpasang.
2. Verifikasi binary terpasang mendukung `188xx+192xx` dengan konfigurasi fixture di luar runtime aktif.
3. Pada maintenance window owner-approved, migrasikan hanya gateway instalasi lama dari `18900–18999` ke `19200–19299` **setelah** binary kompatibel aktif; audit tambahan Development Agent registrations dan port dev runtime 193xx. Uji start/stop independen dan dashboard secara nyata.
4. Jika ingin isolasi rentang port sepenuhnya, rencanakan migrasi **semua** layanan ke blok 191xx bersama Cloudflare origin 18812, Chrome Bridge 18831, private core_services, settings dan health checks; lakukan fail-safe rollback dan read-back MCP/OAuth yang sebenarnya. Jangan mengubah routing publik tanpa koordinasi.
5. Catat bukti live (proses, listeners, `initialize/tools/list/files_stat`, Cloudflare, OAuth) dan status belum diuji dengan jujur.

## Status setelah permintaan instalasi (3 November 2026, malam WITA)

**UPDATE INSTALASI: PASS / STARTUP LIVE: BLOCKED BY ALLOWLIST.** Berdasarkan `docs/INSTALLATION_20261103.md`, kandidat delta dibangun dari 7.014 file program baseline yang terverifikasi dengan Core Release self-contained dan delta source; SetupEngine `verify` → 7.014/7.014 PASS; SetupEngine `install` → Success, 8 changed, 7.014 verified dan rollback program tersedia. Instalasi uji sekarang menyimpan `19100/19110/19111/19120/19130/19140` serta development gateway `19200–19299`, sehingga item migrasi port yang sebelumnya PENDING **selesai di disk**.

URL Router/Files/Web/ArcMap tersimpan diperbarui secara offline; OAuth resource server, tool policy dan workflow policy cocok dengan backup. Production masih memiliki kelima listener aktif dan tidak disentuh. Namun `Zagent.Core.exe` belum dapat dijalankan otomatis melalui tool Zagent karena **executable allowlist menolak**; Router `19110` belum listening, live MCP/OAuth dan Cloudflare belum diuji. **Jangan menyimpulkan runtime/multi-client PASS.** Untuk detail backup, bukti dan langkah operator, baca `INSTALLATION_20261103.md`. Source release gate penuh tetap memiliki blocker dan **bukan** promoted official release.

**Boundary:** Satu-satunya produk tempat perubahan dilakukan adalah Zagent Multi Platform; baseline Zagent Production hanya dibaca.
