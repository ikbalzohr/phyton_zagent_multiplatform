# Otorisasi v1 dan provisioning dashboard

Satu identitas dari credential tervalidasi menghasilkan principal/workspace; metadata client/chat/provider tidak memberi izin. Workspace default diprovision pada instalasi. Management dashboard terpisah dari publik MCP: HTTPS loopback, akun lokal, cookie secure dan CSRF/Origin protection. Tidak ada production-grant/child chat binding/Try Plugin sebagai mode produk.

Password dashboard hanya dimasukkan pada console interaktif owner melalui `Core --provision-dashboard`. Tidak lewat CLI argument, environment, source, log atau chat. Certificate/private key berada pada CurrentUser Windows owner; data/config dan dashboard key directory harus private owner **sebelum** enrollment. Jangan copy vault DPAPI ke akun lain dan mengaku berhasil migrate.

Untuk instalasi candidate, `packaging/scripts/Provision-WindowsDashboard.ps1 -InstallRoot <root> -CertificateThumbprint <public-thumbprint> -WorkspaceId <workspace> -Account <local-account>` mengatur ACL dan memanggil enrollment Core. Sertifikat loopback valid + trust harus disiapkan lewat mekanisme lokal yang disetujui; script tidak membuat/menerima private key atau password. `-RegisterStartup` opt-in startup desktop CurrentUser, bukan Windows service. Untuk DEV source gunakan CLI Core yang sama dengan config di `dev/data/config/dashboard.json` dan owner ACL yang sama, bukan provisioning script instalasi yang mensyaratkan installed payload.

Credential ingress/transport memakai mekanisme A/Core yang dikonfigurasi, tidak plaintext di build scripts/manifest. JWT/JWKS atau introspection provider eksternal perlu provisioning nyata. NOT_CONFIGURED tetap fail-closed, jangan fake success/automatic unauthenticated fallback. Resource grants/Chrome consent/approval mutasi berisiko tetap dipertahankan.

Recovery: stop admission, drain jobs/mark unknown, coordinated stop, backup state/config dengan ACL, lalu offline replacement/re-enrollment sesuai runbook. Izin provider/chat lama tidak otomatis menjadi principal v1. Legacy guide dipindah ke `docs/history/dev-auth-baseline-222341c.md`; klaim PASS lama bukan bukti v1.
