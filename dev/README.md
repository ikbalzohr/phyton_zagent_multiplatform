# DEV v1 — Windows lokal terisolasi

Client MCP apa pun → ingress berotorisasi → Tunnel → Files/Web/ArcMap. Tidak ada parent Production grant/per-chat approval atau provider routing. UI hanya dashboard web Core. Historical DEV notes: `docs/history/dev-workflow-baseline-222341c.md` (bukan bukti untuk v1).

1. Provision dependency/runtime terkunci secara eksplisit; jangan install runtime di server Linux.
2. `dev/Build-ZagentDev.ps1 -Dotnet <dotnet.exe>` build solution dan Web; `-SkipWeb` hanya subset .NET.
3. `dev/Prepare-Zagent-DevRuntime.ps1` menyalin runtime ke target baru, tidak menggunakan junction/hardlink dan tidak menulis agent source/config. Overlay lama tidak dihapus/reuse otomatis.
4. Provision dashboard DEV via `packaging/scripts/Provision-WindowsDashboard.ps1 -Development -CoreExecutable <Windows-built-Core.exe> -InstallRoot <repo> -WorkspaceId <owner-id> -Account <local-name> -CreateCertificate` (opsional `-TrustCertificate` CurrentUser). Certificate, private ACL, DPAPI internal secrets dan akun wajib; jangan pakai kredensial produksi. Baca `GUIDE-AUTH-CREDENTIALS.md`. Tidak build/install selama provision/launch.
5. `dev/Start-Zagent-Dev.ps1 -NoBuild -Dotnet 'D:\3-Ikbalzohr\Agent\appBridge\toolchain\dotnet10\dotnet.exe'` launch Core dashboard, bukan Manager WPF. SDK tepat 10.0.401; optional `-Python311 <absolute-python3.11.exe>` dan `-WebNode <node.exe>` hanya override process, tanpa install/dependency mutation. Dashboard-only tidak mensyaratkan tunnel-client/Python/Node/ArcMap. Default data `dev/data`, profile `dev/workspace`, lease `Local\Zagent.v1.Supervisor.Development`, maintenance pipe `Zagent.Manager.Development`, agent bind `127.0.0.3`, port `19010/19011/19020/19030/19040`. `-DataRoot` dapat memilih dedicated root; config harus `config\dashboard.json` di bawahnya. Build selalu eksplisit pada langkah 2, bukan default launch.
6. `dev/Status-Zagent-Dev.ps1` melaporkan provisioning saja; status runtime authoritative dilihat di dashboard terautentikasi.
7. `dev/Stop-Zagent-Dev.ps1` meminta coordinated shutdown lewat maintenance pipe. Tidak ada fallback kill PID/scan Python/Node/Chrome/ArcMap.

Nama script tanpa tanda hubung tambahan hanya forwarder, bukan workflow produk lain. Tidak mencari folder produksi developer, tidak memakai source sebagai Files profile, tidak auto-connect upstream IPC atau menulis bridge locator di source.

Pending crossstream: Core launcher alias `--dashboard`/maintenance pipe harus sesuai kontrak C; source ini belum dieksekusi. Tab browser ditutup tidak menghentikan Core; stop eksplisit lewat UI/maintenance. Jangan jalankan DEV dan Production terhadap MXD/bridge yang sama. Live tests dan build hanya Windows lokal dengan fixture disposable; jangan menyebut PASS sampai evidence nyata tersedia.
