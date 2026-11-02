# Aturan kerja tetap — Zagent Multi Platform

**Ditetapkan pengguna:** 2 November 2026. **Cakupan:** semua pekerjaan dan diskusi pengembangan pada repository `phyton_zagent_multiplatform`.

## Prosedur sebelum memberikan jawaban teknis

1. **Baca dokumentasi proyek terlebih dahulu** dari repository aktual, minimal `docs/ARCHITECTURE_TARGET.md`, `docs/MCP_FIRST_ARCHITECTURE.md`, serta dokumen spesifik yang berkaitan dengan tugas (OAuth: `docs/MCP-OAUTH-MULTICLIENT.md`, progres ChatGPT: `docs/CHATGPT_OAUTH_CONNECTION.md`).
2. Periksa source dan status aktual sebelum menyatakan sesuatu "sudah diimplementasikan", "sudah aktif", atau "PASS". Pisahkan **target**, **source code**, **build lokal**, **instalasi uji**, dan **deployment publik**.
3. Jika dokumen tidak dapat diakses, **katakan akses dokumen gagal**; jangan mengandalkan ringkasan historis sebagai pengganti inspeksi.
4. Jangan menyamakan Zagent Production dengan Zagent Multi Platform. Mereka terpisah dalam kode, runtime, kredensial, API key, tunnel, issuer, grant, dan deployment. Jangan melakukan perubahan ke Production untuk pekerjaan Multi Platform.
5. Arsitektur yang ditetapkan pengguna adalah:
   **ChatGPT / Claude / Hermes / klien MCP → HTTPS MCP + OAuth → Zagent Core (.NET 10) → Tunnel, Files, Web, ArcMap.**
   `docs/ARCHITECTURE_TARGET.md` adalah sumber desain otoritatif. Bedakan diagram logis dari jalur HTTP implementasi yang sedang ada.

## Prosedur setelah pekerjaan

1. **Selalu perbarui docs** untuk perkembangan Multi Platform: keputusan desain, perubahan source, hasil test aktual (termasuk SKIP), status instalasi dan deployment, risiko, blocker, dan langkah berikutnya.
2. Untuk pekerjaan OAuth ChatGPT, perbarui `docs/CHATGPT_OAUTH_CONNECTION.md`, dengan tanggal, bukti, dan status; untuk perubahan arsitektur perbarui juga `docs/ARCHITECTURE_TARGET.md`.
3. Jangan menyimpan access token, API key, password, client secret, SID nyata, konfigurasi internal sensitif, atau token dari klien ke dokumen.
4. Jangan menyatakan koneksi ChatGPT/Claude/Hermes aktif hanya karena source lulus unit test. Live consent/PKCE/token refresh/initialize/tools harus diuji terpisah.
5. Jangan commit, push, restart, deploy, maupun mengubah domain/ingress tanpa konteks permintaan dan persetujuan yang memadai. Pertahankan perubahan source lain yang sedang berjalan, dan kecualikan `artifacts/` serta file runtime/kredensial.
