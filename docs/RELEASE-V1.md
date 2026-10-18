# Release/migrasi v1 — Windows lokal

## Status dan bukti

SOURCE INTEGRATION, **NOT ACCEPTED**. Seluruh versi produk target 1.0.0 termasuk Files; schema/protokol/SDK/runtime/vendor tidak di-reset. Source patch dan parse JSON/XML bukan build/test PASS. Script Windows yang ditambah belum dieksekusi. Full gates: build semua project, semua mandatory harness tanpa unexpected skip, client interoperability/auth/revoke/isolation, GIS workflow/artefak nyata, dashboard security/lifecycle, clean install/repair/update/uninstall/restore pada candidate digest yang sama.

`Invoke-WindowsValidation.ps1` menghasilkan inventory project, log per command, exit code/durasi aktual dan results JSON di evidence root baru di luar source. Default harness hanya subset; live acceptance tetap NOT_RUN dan promotion BLOCKED. Jangan menambahkan output contoh seolah hasil nyata. Test-first source migration guard ada di SetupTests dan release source checks, tetapi RED/GREEN belum dijalankan karena Windows-only instruction.

## Input yang masih wajib disediakan

- SDK sesuai global.json, Windows desktop owner interaktif, Node/npm/locked dependencies terpisah per agent.
- Arsip Python/Node baseline berhash; resolved transitive hash locks Windows + wheelhouse untuk masing-masing Files/Tunnel/ArcMap. Jangan fabricate locks atau gabung environment modern dengan ArcGIS Python2.7.
- External tunnel-client/ingress/resource-server provider yang terpelihara, provenance/license/digest dan deployment configuration sah; tidak membaca secret lewat chat.
- ArcMap vendor27 + AddIn implementation lengkap (`Install/zagent_arcmap_addin.py` dan dependencies); source descriptor saja ditolak Build-ArcMapAddIn, bukan ZIP sukses palsu.
- Candidate Web dist/Chrome Bridge artifacts, runtime-tools.snapshot.json Files/Web/ArcMap, catalog/schema/name reconciliation. Historical 160 total bukan acceptance selamanya; safety/goal tools tetap required.
- FFmpeg helper, Chrome eksternal, ArcMap Desktop/Python2.7/ArcPy/ArcObjects/lisensi, fixture MXD/data/template/fonts dan reference outputs yang sah.
- Signing/distribution trust implementation. Existing footer/hash verification bukan publisher authentication; verifikasi trust **sebelum** extracted Setup execution masih blocker. Jangan promote unsigned build menjadi signed/public release.

Simpan input manifest aktual berisi path lokal yang disetujui, sumber, versi dependency, SHA256 nyata, lisensi dan bukti pengadaan. Metadata shipping tidak membawa path personal/toolchain snapshot developer atau hasil acceptance baseline.

## Urutan candidate Windows

1. Freeze source + component map; catat commit/diff aktual, Windows/toolchain inventory nyata, external-input manifest, dependency locks dan sandbox roots. Tidak ada secret di evidence.
2. `npm ci --ignore-scripts`, typecheck/build/regression sesuai Web package pada Windows. Jalankan portable/pure agent tests hanya dengan per-agent interpreter/fixture dan inventory A/B; jangan menyapu `_probe_*`/live tests sembarangan.
3. `Invoke-WindowsValidation.ps1 -EvidenceRoot <fresh outside source> -RunHarnesses`; lalu tambah harness live yang prasyaratnya benar-benar lengkap. Semua console Exe perlu `dotnet run --no-build`, tidak cukup `dotnet test`.
4. Build portable runtimes dengan `-CacheRoot`, `-BootstrapPython`, `-LockRoot`, `-Wheelhouse`; build AddIn lengkap. Publish Core/Setup/Bundle lewat script parameterized `-Dotnet`. Output publish/core ditransfer lengkap (Razor + wwwroot), bukan Core exe saja.
5. `Build-ProductionPayload.ps1 -OutputRoot <fresh staging> [-RuntimeRoot <root>] [-PublishRoot <root>]` tetap menjalankan known-bug + Chrome consent gates; excludes tests/probes/docs dari engine yang dicopy. Keberadaan source lama untuk referensi bukan shipping authority. Deny literals personal di scanner sengaja dipertahankan sebagai detektor, bukan runtime dependency.
6. `Build-SingleExeBundle.ps1` memverifikasi hashes/count/paths dan menolak extra undeclared files; verify archive, missing/tampered/duplicate/traversal, partial extraction. Build status bukan acceptance promotion.
7. Jalankan clean-user install, repair, v1 upgrade, cancel/fault/disk-denied, uninstall keep-data/delete-data fixture dan rollback/read-back. Verify registry shortcut target **Core --dashboard**, manifest/digests/assets, AddIn, ACL/DPAPI ownership dan tidak ada WPF Manager produk aktif.
8. Provision certificate trust + akun lokal, dashboard authenticated HTTPS loopback/Origin/CSRF/Host negatives, tab close/no shutdown, single lifecycle, explicit stop/restart. Jalankan client dan GIS acceptance terhadap digest yang sama sebelum promotion.

## Cutover dari lini lama

Reset versi produk 4.x/3.x/2.x → 1.0.0 bukan SemVer downgrade biasa. Installer v1 menolak in-place legacy/damaged product-line manifest: backup offline + fresh target diperlukan. Ini guard nyata untuk mencegah implicit import otoritas chat/operator lama, **bukan importer state otomatis yang sudah selesai**.

1. Stop admission, drain atau tandai unfinished/unknown outcome, simpan job/journal evidence. Jangan replay mutasi yang uncertain.
2. Backup config/state/journals dan data/checkpoints dengan ACL/owner asli; secrets DPAPI tetap pada owner. Uji restore di sandbox. GIS side effects bukan transaksi installer.
3. Coordinated stop Core owner; pastikan tidak ada bridge owner kedua. Jangan force-kill Chrome/ArcMap eksternal.
4. Install candidate ke target baru; sumber/data asli tidak dihapus. Re-enroll workspace/account/resources/credentials yang sah, jangan impor old per-chat approval/binding ke principal baru.
5. Reconcile jobs/artifacts dan admission, verify exact endpoints/read-back/version. Satu produk aktif saja; legacy installer hanya offline recovery artifact.

Rollback: stop v1 sepenuhnya, restore known-good immutable artifact **beserta matching state snapshot**, maintenance downtime, read-back digest/schema/owner dan fixture data. Jangan jalankan dua versi paralel atau memaksa executable lama ke DB baru. Restore software tidak menghapus efek GIS/file/browser yang sudah terjadi. Retention/delete-data hanya dengan izin eksplisit di fixture.

## Dashboard provisioning dan startup

Native installer membuat data/config/dashboard-keys private CurrentUser sebelum Core initialization. Fresh install tanpa `data/config/dashboard.json` tetap NOT_CONFIGURED dan tidak membuka UI tanpa auth. Gunakan `Provision-WindowsDashboard.ps1` dari console Windows owner, certificate thumbprint publik + WorkspaceId + Account; password diprompt Core tanpa echo. Sertifikat harus valid CurrentUser dengan private key, SAN/trust cocok origin loopback. Script tidak auto-create/trust self-signed cert.

`-RegisterStartup` adalah opt-in shortcut desktop startup CurrentUser menjalankan **Core --serve-dashboard** dengan config eksplisit. Tidak install service Session0. Startup shortcut baru tidak menimpa existing; owner perlu menghapus entry opt-in saat uninstall (pending installer integration). Dashboard browser launcher menggunakan **Core --dashboard** alias dari stream C, default config diturunkan dari persisted DataRoot. Jika alias belum diintegrasikan, itu blocker lintas stream, bukan alasan publish WPF lagi.

## Exception ledger

- `docs/history/**` dan dated baseline design docs: historical reference, bukan active policy/evidence v1; tidak dipaketkan.
- `packaging/scripts/Build-ProductionPayload.ps1` forbidden path literals: regression detectors, tidak operational defaults.
- `src/Zagent.Setup/SetupEngine.cs`/SetupTests legacy Manager detection/fixtures: offline migration recognition/negative tests, bukan launch target.
- SDK/vendor names, copyright/license/notices dan protocol sessions tetap apa adanya; bukan personal/provider authority.

## Release blockers yang tidak disembunyikan

Windows build/harness/runtime belum dijalankan; external payload/dependency locks/snapshots belum tersedia dalam source-only checkout; ingress/client/live desktop acceptance belum dilakukan; signature trust chain belum implemented/verified. C harus mengonfirmasi launcher alias/config path, host per-user startup, maintenance pipe dan dashboard Chrome consent page/actions; A/B pemilik versi manifest/runtime. ACL descendant yang memiliki explicit old rules/reparse ancestors perlu audit negatif Windows. Installer backup rollback bukan transaksi penuh ACL/HKCU/AddIn; fault rollback membutuhkan bukti Windows.
