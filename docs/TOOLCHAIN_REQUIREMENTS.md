# Toolchain v1 — requirements, bukan inventory mesin

Semua build/test/runtime/install hanya Windows lokal yang disetujui. Server Linux dipakai untuk source/static JSON/XML review saja pada pekerjaan ini. Jangan menganggap versi yang disebut sebagai hasil inventory host.

- .NET SDK: tepat sesuai `global.json`, roll-forward policy tidak diubah. Script menerima `-Dotnet` atau discovery `dotnet` dan fail bila versi tidak cocok; tidak hardcode drive/akun developer atau install SDK.
- Node/npm: sesuai `agents/web/engine/package.json` + tracked lock; portable baseline Node archive dipertahankan, bukan klaim security support.
- Python modern: portable Python3.11 per Files/Tunnel/ArcMap, dependency environment terpisah. Jangan menyentuh interpreter ArcGIS Python2.7.
- `Build-PortableRuntimes.ps1 -CacheRoot <archive-cache> -BootstrapPython <python.exe> -LockRoot <resolved-lock-directory> -Wheelhouse <verified-wheelhouse>` memerlukan `files.requirements.lock`, `tunnel.requirements.lock`, `arcmap.requirements.lock` resolved untuk Windows Python3.11 lengkap dengan hashes. Tidak disediakan lock fabricasi; penyelesaian/transitive lock masih prerequisite Windows. Pip offline `--require-hashes --only-binary=:all:`. Arsip Python/Node tetap diverifikasi SHA256 existing.
- Web build dev dependencies: `npm ci --ignore-scripts` di engine Windows, typecheck/build/regression tests; browser download tidak otomatis diizinkan.
- External payload: transport executable + provenance/digest/license; vendor27 ArcMap yang sah; AddIn `Install/zagent_arcmap_addin.py` beserta dependency; generated tool snapshots + schema diff; FFmpeg helper; Chrome eksternal; ArcMap/Desktop/ArcObjects/ArcPy/lisensi; fixtures data/MXD/templates/fonts.
- Distribusi: signing identity/tool dan trust-chain verification sebelum extracted Setup dieksekusi. Hash saja bukan signature. Native Setup/Bundle tidak membutuhkan WPF Manager produk atau WiX; installer acceptance tetap wajib.

Source-only checkout belum cukup membuat paket lengkap. Missing input = BLOCKED, bukan placeholder success. Historical toolchain audit disimpan di `docs/history/toolchain-baseline-222341c.md`; tidak menentukan kondisi Windows user sekarang.
