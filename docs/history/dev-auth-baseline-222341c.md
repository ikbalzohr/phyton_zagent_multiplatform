# Zagent v3 DEV — Authorization & Credential Guide

Status: DEV implementation guide
Updated: 2026-10-05

## 1. Scope

Panduan ini berlaku untuk Zagent v3 DEV di:

`D:\3-Ikbalzohr\Agent\appBridge\production\Zagent\v3\dev`

Tujuan perubahan:

1. Zagent DEV yang dipicu dari Zagent Production tidak meminta Manager approval kedua.
2. Production dan DEV boleh memiliki chat/session ID berbeda.
3. DEV tetap subordinate terhadap grant Production; revoke Production memutus akses DEV.
4. Tunnel ID dan API key DEV tidak hilang saat source/build/install diperbarui.
5. API key tetap dienkripsi dengan Windows DPAPI CurrentUser.

## 2. DEV isolation

Canonical launcher:

`dev\Start-Zagent-Dev.ps1`

Legacy launcher:

`dev\Start-ZagentDev.ps1`

Legacy launcher sekarang hanya meneruskan eksekusi ke canonical launcher sehingga tidak ada konfigurasi port/pipe ganda.

DEV environment:

- Environment: `DEVELOPMENT`
- Manager pipe: `Zagent.Manager.Development`
- Bind host: `127.0.0.3`
- Tunnel MCP: `19010`
- Tunnel health: `19011`
- Files MCP: `19020`
- Web MCP: `19030`
- ArcMap MCP: `19040`

## 3. Production -> DEV authorization

Policy DEV:

- audience: `zagent-dev`
- mode: `production-grant`
- enforcement: `mandatory`
- parent_audience: `zagent-production`

Normal flow:

1. Production session sudah APPROVED dan BOUND.
2. Production membuat DEV grant.
3. Grant menyimpan parent Production session dan grant ID.
4. DEV tetap menggunakan child session ID miliknya sendiri.
5. DEV mengikat child session ke parent Production grant.
6. DEV authorization memvalidasi parent grant, bukan memaksa child session ID sama dengan Production session ID.
7. Tidak ada Manager approval kedua untuk DEV.
8. Jika grant Production direvoke/invalid, authorization DEV langsung fail-closed.

Security rules:

- DEV tidak boleh membuat independent approval state untuk bypass Production.
- Grant ID yang salah ditolak.
- Grant dari device lain ditolak jika issuer device tidak cocok.
- Same-session legacy grant tetap didukung untuk backward compatibility.
- Try Plugin tetap tidak boleh dipakai sebagai pengganti grant Production.

## 4. Credential persistence

Lokasi lama:

`dev\data\tunnel\config\transport.credentials.json`

Lokasi persisten baru untuk DEV:

`%LOCALAPPDATA%\Zagent\Credentials\development\transport.credentials.json`

Behavior:

1. Pada DEV startup, jika vault baru belum ada dan credential lama tersedia, credential lama dicopy satu kali ke vault baru.
2. Setelah migrasi, TunnelCredentialStore membaca vault baru.
3. Update source/build/install tidak boleh menghapus vault ini.
4. Production dan Development memiliki folder credential berbeda.
5. API key tetap DPAPI CurrentUser protected.
6. Jangan menaruh API key plaintext di source, script, dokumentasi, issue, atau chat log.

## 5. Build DEV

Dari folder `dev`:

`Build-ZagentDev.ps1 -SkipWeb`

Expected result:

- Zagent.Core: 0 warnings / 0 errors
- Zagent.Manager: 0 warnings / 0 errors
- Output: `ZAGENT_DEV_BUILD_PASS`

Gunakan build tanpa `-SkipWeb` jika perubahan juga menyentuh Web TypeScript.

## 6. Authorization regression test

Dari:

`v3\agents\tunnel\engine`

jalankan dengan Python DEV:

`dev\runtime\tunnel-python\python.exe -m unittest tests.test_plugin_access_guard -v`

Minimum acceptance:

- parent Production session dan child DEV session boleh berbeda
- valid parent grant -> DEV allowed
- wrong grant ID -> denied
- Production revoke -> DEV denied
- no second Manager approval
- seluruh regression test PASS

Current validated result pada 2026-10-05: 12/12 PASS. DEV Core/Manager build: 0 warnings, 0 errors. Persistent Development credential vault terverifikasi sudah terbentuk. DEV Manager dikembalikan ke kondisi off setelah validasi; live Dev Plugin endpoint belum diuji karena Start All/Tunnel client tidak dijalankan.

## 7. Start / status / stop

Start canonical:

`dev\Start-Zagent-Dev.ps1`

Start tanpa rebuild:

`dev\Start-Zagent-Dev.ps1 -NoBuild`

Status:

`dev\Status-Zagent-Dev.ps1`

Stop:

`dev\Stop-Zagent-Dev.ps1`

Sebelum testing, pastikan endpoint DEV memakai port 190xx, bukan port Production 188xx.

## 8. Update procedure

Untuk update DEV:

1. Pertahankan vault credential di `%LOCALAPPDATA%\Zagent\Credentials\development`.
2. Update source.
3. Build DEV.
4. Jalankan authorization regression test.
5. Start DEV.
6. Verifikasi Manager/Tunnel/Files/Web/ArcMap pada port DEV.
7. Verifikasi DEV Plugin dapat memakai Production grant tanpa approval kedua.
8. Jangan promote ke Production sebelum acceptance DEV selesai.

## 9. Rollback

Jika authorization baru bermasalah:

1. Stop DEV.
2. Restore backup source terakhir untuk `access.py` dan `server.py`.
3. Build ulang DEV.
4. Jalankan regression test.
5. Start DEV kembali.

Credential vault tidak perlu dihapus saat rollback kode. Jangan hapus credential kecuali memang melakukan explicit credential reset/uninstall yang dimaksudkan untuk menghapus data.

## 10. Acceptance checklist

- [ ] DEV build PASS
- [ ] 0 build errors
- [ ] Authorization tests PASS
- [ ] DEV config = production-grant
- [ ] parent_audience = zagent-production
- [ ] Child session dapat berbeda dari parent session
- [ ] DEV tidak meminta Manager approval kedua
- [ ] Wrong grant ditolak
- [ ] Parent revoke memutus DEV
- [ ] Credential legacy termigrasi ke persistent vault
- [ ] DEV Tunnel ID tetap ada setelah update
- [ ] DEV API key tetap dapat dipakai setelah update
- [ ] DEV ports = 19010/19011/19020/19030/19040
- [ ] Production ports tidak terganggu
