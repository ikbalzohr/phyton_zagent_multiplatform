# DEV v1 — Windows lokal terisolasi

Client MCP apa pun → ingress berotorisasi → Tunnel → Files/Web/ArcMap. Tidak ada parent Production grant/per-chat approval atau provider routing. UI hanya dashboard web Core. Historical DEV notes: `docs/history/dev-workflow-baseline-222341c.md` (bukan bukti untuk v1).

1. Provision dependency/runtime terkunci secara eksplisit; jangan install runtime di server Linux.
2. `dev/Build-ZagentDev.ps1 -Dotnet <dotnet.exe>` build solution dan Web; `-SkipWeb` hanya subset .NET.
3. `dev/Prepare-Zagent-DevRuntime.ps1` menyalin runtime ke target baru, tidak menggunakan junction/hardlink dan tidak menulis agent source/config. Overlay lama tidak dihapus/reuse otomatis.
4. Provision dashboard DEV dengan Core CLI dari console owner; sertifikat CurrentUser, directory ACL dan akun wajib. Jangan pakai kredensial/IPC produksi. Baca `GUIDE-AUTH-CREDENTIALS.md`.
5. `dev/Start-Zagent-Dev.ps1 -NoBuild -DashboardConfig <path>` launch Core dashboard, bukan Manager WPF. Default data `dev/data`, profile `dev/workspace`, lease `Local\Zagent.v1.Supervisor.Development`, maintenance pipe `Zagent.Manager.Development`, agent bind `127.0.0.3`, port `19010/19011/19020/19030/19040`.
6. `dev/Status-Zagent-Dev.ps1` melaporkan provisioning saja; status runtime authoritative dilihat di dashboard terautentikasi.
7. `dev/Stop-Zagent-Dev.ps1` meminta coordinated shutdown lewat maintenance pipe. Tidak ada fallback kill PID/scan Python/Node/Chrome/ArcMap.

Nama script tanpa tanda hubung tambahan hanya forwarder, bukan workflow produk lain. Tidak mencari folder produksi developer, tidak memakai source sebagai Files profile, tidak auto-connect upstream IPC atau menulis bridge locator di source.

Pending crossstream: Core launcher alias `--dashboard`/maintenance pipe harus sesuai kontrak C; source ini belum dieksekusi. Tab browser ditutup tidak menghentikan Core; stop eksplisit lewat UI/maintenance. Jangan jalankan DEV dan Production terhadap MXD/bridge yang sama. Live tests dan build hanya Windows lokal dengan fixture disposable; jangan menyebut PASS sampai evidence nyata tersedia.
