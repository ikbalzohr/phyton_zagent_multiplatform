# Aktivasi owner-local profil Files

Status source: helper + fixture ditulis; **Windows parser/fixture NOT_RUN**, **runtime activation NOT_APPLIED**. Tidak ada perintah di dokumen ini yang boleh dijalankan lewat public MCP/`files_exec_command`.

## Kontrak

- Entry: `packaging/scripts/Activate-OwnerFilesProfile.ps1`.
- `agentRoot` harus SUDAH ada, enabled, authorized_by_user, read-write, root literal `D:\3-Ikbalzohr\Agent`. Helper tidak membuat profil/approval.
- Hapus HANYA row konfigurasi `appBridge`, entry command policy-nya, dan allowlist membership. Folder `D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform\workspace` berikut SEMUA kontennya tetap ada. Tidak ada perubahan session/project DB, markers, atau generic cleanup.
- Key Files yang sebenarnya adalah `active_profile`; menjadi `agentRoot` untuk sesi baru. `grant.files_resource.profile_id` juga menjadi `agentRoot`.
- Allowlist default tepat `["agentRoot"]`. Parameter opsional `-AllowedProfileIds @('agentRoot','namaApprovedLain')` berarti keputusan owner eksplisit; bukan auto-grant seluruh profil lokal. Profil read-only opsional tetap read-only; tidak diberikan kebijakan command baru.
- Policy command persis `{ "version": 2, "profiles": { "id": <objek v1 asli> } }`. Reuse policy agentRoot existing atau clone appBridge existing dengan perubahan HANYA profile_id/root, tanpa executable/limit/tool expansion. Policy approved lain dipertahankan. Native `.exe` existing saja; batch wrappers, alias reparse, path relatif/UNC/device/ADS/env-expansion ditolak, bukan diam-diam dihapus/diganti.
- Review lokal mencetak root, executable, tools dan limit; dua frasa konfirmasi wajib, termasuk `ALLOW OWNER ACCOUNT EXECUTION AT agentRoot`. Command menggunakan hak owner Windows, **bukan OS sandbox**.
- Grant harus aktif/tidak revoked, expiry integer finite tetap `1793539666`, bindings instalasi/principal/workspace/issuer tepat. Scopes/tools/revocation/expiry/OAuth tidak diperluas/diperbarui; tidak ada login baru.
- Unrelated JSON tokens dipertahankan langsung, termasuk unknown numeric lexemes; bukan round-trip serialisasi seluruh tunnel config.

## Prasyarat stopped Core

Helper menerima `-DataRoot` yang diketahui; tidak mengharuskan restart Core untuk discovery. DataRoot target diketahui `C:\Users\fazrin\AppData\Local\Zagent-Local`. Jalankan sebagai owner enrollment yang sama di console Windows interaktif. Core harus sudah benar-benar keluar (**Stop Core**, bukan Stop all agents).

Validasi anchor: protected owner-only DataRoot; owner/SID/ACL serta non-reparse chain setiap file config; metadata regular bounded file `config/dashboard.json`, `config/device_identity.json`, `config/internal-secrets.dpapi.json` tanpa membaca/decrypt isi anchors. `config/zagent.machine.json` nonsecret harus menunjuk InstallRoot dan DataRoot yang diminta. Identity/OAuth/cert tidak ditulis. Anchor metadata dan snapshot machine diulang setelah pause approval.

## Urutan target (belum dieksekusi)

Hanya setelah parent mengintegrasikan dan menerbitkan **revision exact** beserta gate Windows lane A/B. Jangan jalankan placeholder revision. Path repo/InstallRoot berikut sesuai root appBridge lama yang dikonfirmasi, tetapi machine anchor harus cocok; bila tidak, STOP, jangan mengganti anchor.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $Repo = 'D:\3-Ikbalzohr\Agent\phyton_zagent_multiplatform'
    $ExpectedRevision = '<ISI_SHA_INTEGRASI_YANG_DIBERIKAN_PARENT>'
    if ($ExpectedRevision -notmatch '\A[0-9a-f]{40}\z') { throw 'Exact reviewed revision wajib diisi; placeholder bukan acceptance.' }
    Set-Location -LiteralPath $Repo
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'Pull gagal; jangan lanjut.' }
    $ActualRevision = git rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $ActualRevision.Trim() -cne $ExpectedRevision) { throw 'Revision mismatch; jangan lanjut.' }
    & .\packaging\scripts\Test-OwnerProfileActivation.ps1
    # Fixture script throws on failure and parses entry/library/self first.
    # Tidak ada product build/import/test dalam fixture helper ini.
    & .\packaging\scripts\Activate-OwnerFilesProfile.ps1 `
        -InstallRoot $Repo `
        -DataRoot 'C:\Users\fazrin\AppData\Local\Zagent-Local'
}
```

Tidak ada auto-start. Jangan menjalankan ulang enrollment, renewal, atau OAuth login sebagai kompensasi kegagalan. Source helper ini tidak membutuhkan build sendiri; product integration/rebuild/restart lane lain merupakan gate terpisah sebelum Core boleh dinyalakan lagi.

Expected target evidence (bukan hasil yang sudah diperoleh):

1. `OWNER_PROFILE_WINDOWS_FIXTURES_PASS`, path disposable evidence retained. Harness menggunakan direktori unik di TEMP Windows, SID/ACL asli, junction/reparse refusal, file replacements asli, tanpa product imports/production DataRoot. Evidence sengaja tidak dihapus.
2. Helper mencetak `STAGING`/`PREPARED` untuk tiga file lengkap dengan `.bak`/candidate paths, lalu `VERIFIED profiles`, `VERIFIED commands`, `VERIFIED grant`, akhirnya `OWNER_PROFILE_ACTIVATED` dan `ACTIVATION_APPLIED`.
3. Bila byte-identical sudah current: `OWNER_PROFILE_ALREADY_CURRENT`, tidak ada penulisan/backups/approval baru.
4. Sesudah restart existing enrollment yang dikendalikan terpisah: buktikan default lokal/remote agentRoot, selector approved lain, penolakan appBridge, dan canary terminal-result. Helper bukan bukti operasi remote berjalan.

## Pengaman dan recovery

Semua original/candidate strict bounded JSON divalidasi sebelum staging. Semua candidate dan backup original independen dibuat dengan CreateNew, owner ACL, bounded read-back SEBELUM target replacement pertama. Setiap replacement mengecek Core, expiry, snapshot semua target, semua backups dan candidates/recovery copies. Profiles dahulu, commands kedua, grant terakhir. `File.Replace` per-file bukan transaksi multi-file.

Bila gagal: `ACTIVATION_INCOMPLETE` mencetak daftar replacement yang sudah terverifikasi; **biarkan Core mati**, simpan seluruh transcript dan path `STAGING`/`PREPARED`/`VERIFIED`, `.bak`, `.tmp`, `.tmp.replaced`. Tidak ada auto rollback. Identifikasi tiga original backups satu invocation dan bandingkan exact bytes/ACL dengan receipts serta keadaan target sekarang sebelum keputusan restore/resume owner-local. Jangan mencampur backup invocation lama, jangan blind rerun, jangan menghapus direktori data, jangan membuat certificate/account baru. Restore manual merupakan keputusan recovery terpisah dengan Core tetap off, concurrent-change checks dan read-back; dokumen ini tidak menjalankan restore.

Jika executable lama menyertakan `.cmd`/reparse/nonexistent, helper menolak seluruh aktivasi sebelum write; tidak mengganti allowlist otomatis. Jika grant expired/revoked, profil/root/owner mismatch atau anchor tidak valid: hentikan dan laporkan error lokal; tidak ada renewal/approval adoption otomatis.

## Pemeriksaan source-only

```text
python packaging/scripts/check_owner_profile_activation_source.py
```

Guard membaca source saja dan merekonsiliasi set supported command tools, exact v1 keys dari AST literal (tanpa product imports), serta key Files default dari manager source. Itu bukan parser PowerShell, bukan .NET/Python product test, dan bukan bukti ACL/DPAPI/Windows runtime.
