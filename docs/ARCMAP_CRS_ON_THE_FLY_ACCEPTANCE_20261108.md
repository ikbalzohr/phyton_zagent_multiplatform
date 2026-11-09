# ArcMap CRS On-the-Fly Correction and Print Acceptance — 8 November 2026

## Root cause (supersedes earlier CRS metadata mismatch diagnosis)
Original main activity shapefile has EPSG:3857 Web Mercator, correct for its native geometry, while ArcMap's main data frame uses EPSG:32651 UTM Zone 51N. Visible supporting SHP / ECW test datasets use geographic WGS84 (EPSG:4326); ArcMap supports on-the-fly display reprojection.
The bug was treating `arcpy.Describe(layer).extent`, which ArcMap reports in data-frame coordinates for a mapped layer, as though the extent were still in `arcpy.Describe(layer).spatialReference` native coordinates. This caused a false `DATASET_CRS_METADATA_INCONSISTENT` error. Use `arcpy.Describe(layer.dataSource)` for native bounds and native spatial reference, then explicitly project corners into frame CRS. Verify main layer geometry separately.

Observed native EPSG:3857 activity extent: x=13514793.55296878..13520452.17844732, y=117664.7026033..124671.5988431. Map-frame UTM 51N extent: x=322574.1305..328235.2333, y=116866.4576..123828.0023. Projected bottom-left point matches UTM x=322574.1305, y=116869.3164. No native source CRS changes needed.

## Fixes
- `agents/arcmap/engine/stage2/cartographic_apply.py`: source-dataset/native Describe for spatial bbox, not transformed layer extent; retained strict `Polygon`, main CRS and display guards.
- Selective scale-label rewrite: only the original main-frame scale label changes from source 1:70.000 to computed 1:50.000. Inset scale labels remain 1:3.500.000 and 1:23.000.000.
- `maintenance/arcmap_print_ready_pdf_qa.py`: check all three extracted PDF scale denominators against actual scales of all three data frames. Incorrect previous export was rejected with `MAIN_OR_INSET_SCALE_LABELS_DO_NOT_MATCH_FRAMES`; corrected export accepted.
- `tests/arcmap/test_cartographic_rules.py`: regression tests for native-vs-display bounds and preservation of inset scale labels.
- Original template MXD, SHP, ECW, .prj, and `Contoh Layout` were not changed. All work uses a disposable working MXD.

## Regression and live acceptance
- 136/136 ArcMap unittest suite PASS (outer exit code 0); nested Stage3 injected failure is an expected fixture test.
- Python 2.7 ArcPy compilation PASS; Git diff --check PASS.
- Original data source test: PDF + PNG exported at adaptive 1:50,000; structural QA PASS; 400 dpi and A4 landscape.
- Independent PDF checker rejected old wrong-inset-scale PDF, approved new data-correct one. Visual PDF preview reviewed: red transparent site outlines, roads, rivers, raster coverage, title, metadata, legend and two inset panels appear correctly positioned.
- **Public authenticated connector `arcmap_print_ready_template` succeeded** with installed runtime and exact real project input, job `print_ready_m1_fa21156bd955`.
- Public PDF: `D:\3-Ikbalzohr\Project\arcmap_agent_testing_project\Hasil Peta\print_ready_live_crs_20261108\print_ready_m1_fa21156bd955\PETA A4 BUOL AGRI LESTARI - ADMINISTRASI.pdf`.
- Public PNG: same job directory, `PETA A4 BUOL AGRI LESTARI - ADMINISTRASI.png`.
- Public output PDF sha256 ea0819ef286e24eb51222a9a53e380ebf769a4bc0522c2d7a5a989f3d4b25f94; PNG sha256 17e4255e947047f3790c580024b04b81a237bb2f5c1deef727247fd41ef31ab2.
- Independent reviewer tool status: `ok=true`, `automated_qa_pass=true`, `visual_reviewed=true`, `print_ready_accepted=true`, errors=[], `pdf_scale_labels`=[50000,23000000,3500000], expected frame scales=[50000,3500000,23000000].
- Final warnings: underlying dataset attribution is not independently fact-checked; physical printer paper/ink/color proof remains unverified.

## Installation and rollback
- Installed with SHA256 matching source: `engine/stage2/cartographic_apply.py` and `artifacts/qa_tools/arcmap_print_ready_pdf_qa.py`.
- Code backup: `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform\agents\arcmap\artifacts\deployment_backups\crs_native_extent_v2_20261108_171721`.
- Public call initially blocked because runtime config had no `allow_headless_print_ready` field, even though engine default had it. The **only new runtime config field** inserted was `allow_headless_print_ready=true`, preserving all preexisting keys and values. Backup: `data/arcmap/config/agent_config.json.headless_optin_backup_20261108_172149`.
- Restart only ArcMap agent using authenticated Core Dashboard lifecycle action `restart`; operation 21e5a7d4426449fca95a5ba26c85b379 succeeded. Final verification showed ArcMap port 19140 listening and Core/Files/Tunnel/QGIS alive.
- No commit/push was requested or performed. Other preexisting repo files were preserved.

## Experimental fixture warning
`Hasil Peta/crs_probe_v2_20261108` and `Hasil Peta/_cartography_rules_isolated_qa` were isolated exploratory fixtures in which copied .prj files were changed during diagnosis. They are **not** project source inputs and **must not be used for production maps**. The real project `SHP` and `Basemap` folders remain intact.

## Limitations beyond CRS
General cartographic work still includes richer ArcMap renderer/label/legend/grid adaptation; this milestone validates the on-the-fly CRS and print-ready specimen only, not universal automation for every GIS project.
