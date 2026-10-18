# Standar Template A4

Gunakan nama elemen unik:
- ZAGENT_TITLE (TextElement)
- ZAGENT_SUBTITLE (TextElement)
- ZAGENT_LEGEND (LegendElement)
- ZAGENT_LEGEND_TITLE (TextElement terpisah)
- ZAGENT_SOURCE, ZAGENT_PROJECTION (TextElement)
- ZAGENT_NORTH_ARROW, ZAGENT_SCALE_BAR (MapSurroundElement)
- ZAGENT_LOGO_LEFT / ZAGENT_LOGO_RIGHT opsional (PictureElement)

Legenda native sengaja tetap dipakai karena mendukung `listLegendItemLayers`, `removeItem`, `updateItem`, `adjustColumnCount`, dan `isOverflowing`. Detail patch/font/spacing item yang tidak writable lewat ArcPy harus disimpan pada Legend Item Style atau template MXD. Judul legenda visual memakai TextElement terpisah agar ukuran font dapat dikontrol.

Template sumber tidak pernah ditimpa. Setiap job membuat working MXD dan persistent baseline checkpoint di disk.
