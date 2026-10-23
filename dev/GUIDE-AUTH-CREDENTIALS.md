# Otorisasi v1 dan provisioning dashboard

Dashboard lokal dan MCP publik adalah gate berbeda. Dashboard memakai exact `https://localhost:<port>/`, akun lokal/password hash, secure cookies serta CSRF/Origin protection; tidak public bind, reverse proxy management atau remote dashboard.

## Provision owner lokal

Gunakan PowerShell Windows interaktif **non-elevated** milik installation owner. Tidak menerima password/token/private key di parameter, environment file, chat atau source. Password dan konfirmasi hanya dibaca tanpa echo oleh Core. Secret internal dibuat CSPRNG, disimpan DPAPI CurrentUser pada `<DataRoot>\config\internal-secrets.dpapi.json`, bukan bearer OAuth; data/config/keys dan file secret owner-only protected ACL. DPAPI terikat akun Windows; menyalin blob ke user lain bukan migrasi.

`packaging/scripts/Provision-WindowsDashboard.ps1` mendukung:

- Installed v1 payload: `-InstallRoot <installed-v1-root> -DataRoot <dedicated-local-data-root> -WorkspaceId <owner-selected-id> -Account <local-admin-name>`.
- DEV: tambahkan `-Development -CoreExecutable <Windows-built-Zagent.Core.exe>`; default DataRoot `dev\data`. Tidak perlu full Setup/ArcMap AddIn untuk enroll dashboard.
- Pilih tepat satu `-CertificateThumbprint <existing-currentuser-my-thumbprint>` atau `-CreateCertificate`. Sertifikat harus SAN exact DNS localhost saja, valid/private key, EKU serverAuth. Creation memakai CurrentUser\My, non-exportable RSA key; tidak mengexport PFX.
- `-TrustCertificate` opt-in hanya bersama `-CreateCertificate`: trust public cert pada CurrentUser\Root, **bukan LocalMachine**. Tanpa ini trust perlu gate manual; jangan mengabaikan browser/TLS warning. Untuk existing CA certificate, kelola trust chain secara lokal terpisah.
- `-RegisterStartup` opt-in installed-only shortcut CurrentUser desktop memakai `--dashboard`. Tidak ada service/Session0 atau autostart DEV.

Fresh DataRoot atau existing root yang sudah owner-only diperlukan. Existing config/secret/shortcut tidak ditimpa. Reparse/junction/symlink ancestor ditolak. Jangan gunakan drive root, repo root atau root data instalasi lain. DataRoot lama dengan ACL permissive harus ditinjau offline oleh owner, bukan diadopsi rekursif secara diam-diam.

Provisioning bisa meninggalkan certificate/trust/directories/internal envelope bila prompt gagal/cancel. Tidak auto-delete atau reset state. Hentikan Core secara terkoordinasi, review/back up state dengan ACL, lalu owner melakukan recovery offline spesifik. Jangan menambahkan switch force/reset atau mengirim secret/log mentah. Mengganti akun/password/key memerlukan recovery eksplisit dan restart; panduan ini bukan implementasi reset.

## Gate readiness

Packaging↔Core envelope/loader contract: `/root/.hermes/profiles/ikbal/zagent-implementation/PROVISION-CONTRACT.md` pada workspace audit. Loader C harus membaca blob dari DataRoot sebelum child start, fail closed pada missing/corrupt/wrong owner, dan meneruskan secret hanya ke environment proses anak. **Script tersimpan bukan bukti loader tersedia atau Windows run-ready.** Handoff readiness ada di direktori implementasi yang sama.

MCP tetap **BLOCKED** sampai AS existing, issuer/introspection/client registration, resource/grant/profile lokal, transport existing dan public HTTPS route dibuktikan. Tidak membuat AS baru, fake token, static bearer bypass atau envfile plaintext. Config OAuth authoritative tetap router `<DataRoot>\tunnel\config\tunnel.json`; provisioning dashboard tidak menulis issuer/AS/grants atau secret introspection. Secret introspection external belum diselesaikan oleh blob internal ini.

Legacy guide: `docs/history/dev-auth-baseline-222341c.md`; PASS historis bukan acceptance v1.
