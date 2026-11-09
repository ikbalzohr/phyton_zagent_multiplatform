# ZAGENT.md — Standar Global Kartografi Zagent ArcMap

Versi: 1.0 | Disetujui: 8 November 2026 | Lingkup: engine ArcMap Multi Platform

## Prioritas dan perlindungan
1. Kebijakan keamanan, izin akses, integritas data, dan larangan menyunting MXD asli maupun `Contoh Layout` tidak dapat ditimpa.
2. Instruksi eksplisit pemilik berlaku untuk **satu pekerjaan**, tidak otomatis mengubah file aturan.
3. `ZAGENT.md` di root proyek menimpa aturan desain global.
4. File global ini menjadi standar desain; MXD digunakan untuk susunan zona serta jenis/CRS/format grid yang belum ditentukan.
5. Tiap pekerjaan mengambil snapshot aturan saat dimulai; perubahan hanya berlaku pada pekerjaan berikutnya (hot reload).

## Kontrak peta siap cetak
- Gunakan salinan MXD. Ekspor A4 landscape, PDF + PNG, 400 DPI, working MXD, resolved_rules.json, cartographic_decisions.json, dan QA.
- Peta dibagi menjadi zona tetap: peta utama, judul, legenda, metadata, dua inset, scale bar, dan arah utara. Posisi zona dipertahankan, isi/ruang di dalamnya dapat disesuaikan.
- Font teks terbaca harus Arial; judul minimum 14 pt dan teks penting minimum 7 pt. Font simbol non-teks dikecualikan.
- Area utama dikenali dari nama, atribut, geometri, dan konteks perintah. Bila identitas ambigu, jangan memilih secara diam-diam.
- Skala ditentukan otomatis agar seluruh area utama beserta ruang tepi adaptif masuk bingkai. Bulatkan ke penyebut standar terkecil yang tetap memuat seluruh area.
- Simbologi area kegiatan: batas merah tegas dan isi transparan. Jalan abu-abu/putih, sungai biru, batas administrasi hitam/abu-abu, basemap sebagai latar.
- Pengurutan *draw order* mengikuti preset jenis peta (administrasi, lingkungan, pertambangan), bukan disamakan dengan urutan legenda.
- Label: atur posisi, halo, dan ukuran; jika tetap bertabrakan, coba callout/leader line untuk label penting. Label pendukung berprioritas rendah boleh disembunyikan dengan laporan.
- Pertahankan jenis grid, CRS, dan format koordinat dari template; interval boleh disesuaikan agar tetap terbaca.
- Pertahankan dua zona inset; cakupan dan skala harus sesuai lokasi proyek, bukan sekadar menyalin koordinat proyek sebelumnya.

## Legenda
- Urutan manual: Area kegiatan → Jalan → Sungai → Batas administrasi → Unsur tambahan.
- Masukkan hanya unsur relevan yang tersedia, nama yang terbaca dirapikan dari kode SHP, tetapi identitas layer asli dicatat untuk audit.
- Simbol dalam legenda harus sama dengan simbol sebenarnya di peta.
- Gunakan dua kolom jika diperlukan; sesuaikan jarak dan ukuran tanpa memindahkan posisi zona utama.

## QA dan kegagalan
- Status: `PASS`, `PASS WITH WARNINGS`, `FAIL`. Ekspor yang berhasil belum otomatis berstatus siap cetak.
- Peta **final** memerlukan QA struktural **dan** tinjauan visual PDF independen. Draft boleh `PASS WITH WARNINGS` jika pemeriksaan penting lulus tetapi visual belum selesai.
- Kegagalan kritis: sumber utama tidak ada/ambigu, area terpotong, CRS/grid salah, elemen wajib terpotong, output tidak sesuai, atau MXD asli berubah.
- Jika layer pendukung hilang, hasil bisa dilanjutkan sebagai peringatan asal tidak mengubah makna peta.
- Coba perbaikan yang aman pada salinan MXD. Jika tak berhasil, simpan draft `FAIL`, jangan beri status siap cetak.
- Simpan asal keputusan, skala, susunan layer, simbol, inset, label, pengecualian, dan hash aturan untuk audit.

## Aturan bebas dan bagian terstruktur
- Pengecualian desain proyek boleh ditulis dengan bahasa Indonesia biasa. Agent harus membaca dan menafsirkannya lebih dahulu.
- **Penting:** ArcPy tidak mengeksekusi instruksi bebas tanpa penyelesaian eksplisit menjadi parameter yang valid. Kalimat yang belum dapat diinterpretasikan tidak boleh diterapkan diam-diam; laporkan sebagai perlu keputusan pengguna.
- Blok `zagent-cartography` di bawah adalah subset parameter yang dapat dieksekusi secara deterministik. Ubah nilai di dalamnya untuk override yang didukung. Aturan yang tidak tersedia di blok tetap berlaku sebagai pedoman agent/QA dan tidak boleh diklaim sudah otomatis.

```zagent-cartography
{
  "format": {
    "paper": "A4",
    "orientation": "landscape",
    "dpi": 400,
    "outputs": [
      "PDF",
      "PNG"
    ]
  },
  "layout": {
    "preserve_zones": true,
    "margin_mm": 5
  },
  "typography": {
    "family": "Arial",
    "title_min_pt": 14,
    "important_min_pt": 7
  },
  "scale": {
    "mode": "auto",
    "padding_fraction": 0.12,
    "denominators": [
      1000,
      2500,
      5000,
      10000,
      15000,
      25000,
      50000,
      70000,
      75000,
      100000,
      150000,
      250000,
      500000,
      1000000,
      2500000,
      5000000
    ]
  },
  "area": {
    "layer": "",
    "dataset": "",
    "outline": "red",
    "fill": "transparent"
  },
  "layers": {
    "preset": "administration"
  },
  "legend": {
    "order": [
      "area",
      "road",
      "river",
      "administration",
      "other"
    ],
    "columns_max": 2
  },
  "grid": {
    "inherit_template": true,
    "adaptive_interval": true
  },
  "insets": {
    "count": 2,
    "adaptive_extent": true
  },
  "qa": {
    "visual_required_for_final": true,
    "important_font_min_pt": 7
  }
}
```

## Aturan proyek dan hot reload
- Setiap proyek menggunakan `ZAGENT.md` di root. Jika belum tersedia dan izin tulis sah, buat file awal yang mewarisi global; jika read-only, gunakan global tanpa membuat file.
- Baca ulang kedua aturan sebelum **setiap** pekerjaan baru. Jangan ubah aturan pekerjaan yang sedang dieksekusi.
- Aturan proyek boleh mengubah desain; aturan keamanan serta pelindungan data tetap lebih tinggi.