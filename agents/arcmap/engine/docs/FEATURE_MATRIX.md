# Stage 2 Feature Matrix

| Area | Cakupan |
|---|---|
| Discovery | Folder, SHP, File GDB feature/table/raster, raster file, CAD, CSV/TXT, LYR |
| Matching | exact, alias, regex, fuzzy, constraint geometry/kind |
| Data source | replaceDataSource + add fallback |
| Layer | add, order, visibility, transparency, scale range |
| Symbology | `.lyr`, unique values, graduated class breaks |
| Label | expression, SQL class filter, show/hide |
| Legend | item filter, style item, TOC-driven order, columns, overflow fitting |
| Layout | named Text/Picture/MapSurround/Graphic placeholders, position/size/font size |
| Extent | target layer, padding, nice/fixed scale, rotation |
| Checkpoint | full MXD persistent copy + SHA1 metadata |
| QA | broken source, A4, required elements, legend overflow, visible empty layers |
| Export | PDF, PNG, JPEG, TIFF, EPS, SVG, AI, EMF |
| Batch | multi-job JSON |
| Geoprocessing | generic guarded ArcPy runner, including installed toolbox functions |

Catatan: ArcMap 10.x tidak mengekspos setiap properti UI melalui `arcpy.mapping`. Properti internal legenda yang tidak writable harus di-author di template/Style Manager dan diterapkan lewat Legend Item Style.
