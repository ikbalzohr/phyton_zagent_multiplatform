# Print-ready mapping: source audit and real-MXD checkpoint

Status: AUDIT / INPUT INSPECTED. Not implemented or print-ready accepted.
Checkout Windows agent-dev, branch zagent-v1, baseline 5dd573bc00d447b01148d5864a935f89a5c035a4. Parent native Git status/log verified: tracked clean; pre-existing untracked docs/WORK/maintenance preserved. No deployment, restart, original MXD save, commit or push.

## Feature Parity Matrix
Paths A relative agents/arcmap/engine; Q relative agents/qgis/engine/qgis_mcp_plugin/handlers. Rows are bounded source findings, not live equivalence claims. Child audit independently sampled by parent in worker27, Stage2 QA/export and Q layout handler.

| Kemampuan pembuatan peta | Implementasi QGIS | Implementasi ArcMap tersedia | Kesenjangan fitur | Prioritas | File/modul pengembangan | Kriteria PASS dapat diuji |
|---|---|---|---|---|---|---|
| Input/template | Q layout.py create_layout default page; layer ingestion | A stage2/engine.py build_a4; worker27._prepare copies seed, discovers/matches data | Exact deterministic data bindings and provenance | P0 | orchestrator/adapters/file_worker/worker27.py; new print job contract | Original hash unchanged; output copy reopens; required datasets resolved |
| A4 landscape | Q default layout page; no dedicated explicit page settings found | Stage2 a4_check accepts both orientations | Require landscape and independent PDF dimensions | P0 | orchestrator/validators/layout.py; worker evidence adapter | PDF approximately 297x210 mm within explicit tolerance |
| Main extent/scale/CRS | Q add_layout_map takes canvas extent; limited per-frame configuration | Stage2 configure_extent and disk frames | Explicit frame identity and measured scale evidence | P0 | stage2/engine.py; print preflight | Unique main frame, CRS verified, actual scale 70000 and extent/frame dimensions agree |
| Layer order/symbols | Q style.py single/categorized/graduated; layers.py QML round-trip | Stage2 configure_layer/apply_order and .lyr styling; cartography.py | Avoid ambiguous first-match and replacement failure fallback | P0 | stage2/engine.py | Exact layer mapping/order; no duplicates/broken sources; visual style agrees |
| Labels | Q layers.py simple field labels; richer QML | Stage2 labels; Attached labels/cartography | Collision/placement QA and parser errors not robust | P1 | labels.py; cartography.py; QA | Dense final-scale fixture readable; parser failures explicit |
| Title/source/north arrow/scalebar | Q layout labels/picture/scalebar; bounded association | Existing template + apply_layout; Attached layout automation | Template role naming, linkage and bounds verification | P0 | stage2/engine.py; layout evidence | Required text and surrounds present, legible, correct scale linkage |
| Legend | Q add_layout_legend | Stage2 rebuild_legend/legend_manifest | Fail closed ignored edits; sync with visible map | P0 | stage2/engine.py | Legend symbols/categories match exported map; no overflow |
| Insets | Q multiple map items; no dedicated overview linkage found | Existing MXD frames preserved; Stage2 main-frame recipe | Separate inset configuration and verification | P0 template / P1 authoring | worker27.py; layout QA | Two inset frames retain intended extents/scales and markers |
| Grid/graticule | No dedicated layout grid contract found | Template grids can be retained; broader authoring not fully audited | Verify real export, not names alone | P0 template / P1 authoring | layout QA/export verification | Correct edge coordinates, intervals and CRS visibly verified |
| PDF/PNG/TIFF | Q export_layout checks exporter status with DPI | Stage2 export_map; worker render_staging; Attached verified temporary exports | Unified explicit mode, atomic output and independent validation | P0 | mcp_server/tools; services.py; file worker/stager | No CURRENT in headless; no mode fallback; PDF opens and dimensions/fonts/raster quality verified |
| Reusable template/batch | Q basic layout/atlas and sequential batch; atlas driving incomplete | Stage2 batch and B_TEMPLATE_DATA staging | Stable print-job schema, per-job results, controlled publication | P1 | stage2; orchestrator/staging/strategies.py | Multiple regions create distinct correct outputs; failure not reported as whole-job PASS |
| Print QA | No dedicated full preflight found | Stage2 broken/A4/required elements/legend; normalized layout validator | Real MXD-to-validator adapter; visual review; label/raster checks | P0 | orchestrator/validators/layout.py; export QA | Defective fixtures rejected; actual PDF rendered and reviewed before ready=true |

## Architecture decision
Reuse Stage2 and isolated disk file worker, not Stage3 CURRENT rebuilding. Existing legacy stage2 MCP build traverses Attached bridge despite editing a disk template copy. Explicit dual-mode inspection does not establish dual-mode export. New headless build must retain auth, expiry, target identity, overwrite and unknown-outcome rules; never fallback to CURRENT. Bridge remains Python2.7.

## Actual Windows evidence
- ArcPy 10.6.1 import/install info PASS: tsk_e9c86dc91de940caa47bb7bfd4d0a94f exit0.
- Real disk MXD inspection PASS: tsk_31721be39fbc4ab591bc1ff94a8d4f6d exit0.
- Input: D:\3-Ikbalzohr\Project\arcmap_agent_testing_project\PETA A4 BUOL AGRI LESTARI - ADMINISTRASI - Testing.mxd
- Input SHA256: 976731c8415addc79488e3bf3d773a390b4108bb64d05f6ffaba91ee07c903b0.
- ArcPy page values: 29.69689272711879 by 20.997375328083994 (native page units; PDF size independently unverified).
- Main frame Layers: scale70000, WGS_1984_UTM_Zone_51N. Insets New Data Frame scale3500000 and New Data Frame 2 scale23000000, both GCS_WGS_1984.
- Enumerated layers reported isBroken=false. IMPORTANT: only main company polygon points into testing SHP; roads/rivers/desa/clips and ECW basemaps/insets reference sibling original PT BUOL AGRI LESTARI project. Do not rewrite originals; enumerate testing copies and rebind the working MXD explicitly.
- Template includes legend, North Arrow, Double Alternating Scale Bar, title PETA ADMINISTRASI, company text, source/CRS/scale text. Most text names empty: name-based recipes need explicit normalization on copy. CRS text contains typo Transverse Mecrator. Grid presence/correctness not established by ArcPy element listing.
- Source cross-check receipt tsk_044e29c9b7454fdf96fd4be486c955e9 exit0. Stage2 export writes direct paths at default400 DPI; QA does not prove print readiness.

## Remaining acceptance / resume
No product code or test added, no PDF generated, no regression/live-MCP acceptance. Next inspect testing SHP/Basemap inputs and real reference image, normalize only working-copy roles, implement explicit authenticated print job reusing file worker, add failing tests then minimal code, run licensed export and structural/visual PDF review. Do not claim first milestone complete from this audit.

Quota sampled usage_api 2026-11-07T17:10:38.829761+00:00: Session87% used, Weekly32% used. Recheck before next batch; pause at any used_percent>90. Both read-only audit subagents completed, no writers active. Prior access checkpoint agentRoot diagnosis is superseded: correct profile agent-dev works. Public ArcMap ping orphan tsk_b379751660824496999fd0e48c3a155b remains separate unresolved evidence; no replay or bypass performed.

QUOTA_PAUSE: usage_api 2026-11-07T17:11:47.711430+00:00 Session used91%, Weekly used32%. Stop before implementation/export; both audit children completed. Resume with fresh quota/access checks and docs/ARCMAP_PRINT_READY_AUDIT_20261108.md. No product code, original MXD, installed payload or services changed; no PDF/tests/commit/push.

## Milestone 1 implementation — 8 November 2026 (Windows source, no installation deployment)

This section supersedes the earlier audit-only outcome for the **source vertical slice**. The public installed MCP catalog has not been changed in this phase.

### Implemented, architecture, and file changes
- New `stage2/print_ready.py`: standalone ArcPy 10.6.1/Python 2.7 headless job on an isolated **copy** of the input MXD. Reuses `stage2.engine.export_map`, the existing layout and legend. The input and `Contoh Layout` were not saved or modified. Requires A4 landscape, exact 1:70,000 scale, expected CRS, three map frames with two inset layout elements, legend consistency, surround/title/source, readable minimum font 6 pt, in-page element bounds and zero broken sources.
- Only exact file-basename matches from testing `SHP/` and `Basemap/` are rebound. Seven dataset references were rebound; the two source-dependent invisible `CLIP_*` layers missing from testing data were removed **only from the working copy**. No silent use of sibling original project datasets.
- `orchestrator/adapters/file_worker/worker27.py` and `arcgis_process.py`: new `print_ready_template` operation through isolated Python2.7 process, timeout 300 s; independent structural PDF/PNG QA from Python3 `orchestrator/validators/pdf_export.py`; save `structural_qa.json` alongside exported files.
- `mcp_server/tools/print_ready.py`, `server.py`, `services.py`: authenticated `arcmap_print_ready_template(mode='headless', template_mxd, data_root, output_root, scale=70000, dpi=400, main_frame='Layers', expected_crs='WGS_1984_UTM_Zone_51N')`. Requires authorized ArcMap write context and save/export policy under independent headless lock. `mode='attached'` is explicitly rejected; there is no `CURRENT` fallback. Public tool exists **in source only**, not deployed/activated in installed MCP catalog.
- `tests/arcmap/test_print_ready.py` contains 16 focused tests and `test_execution_modes.py` contains two new authenticated SDK/dispatch cases plus updated truthful export-capabilities contract.

### Verified execution and output
- Direct licensed ArcPy 10.6.1 export exit0: task `tsk_76d226a9ff654470b3de3f2b832df207`.
- Actual `ArcGISProcessFileWorker.print_ready_template()` isolated subprocess exit0: tasks `tsk_6f7e6125cc2040908dae5b9445656f08` and `tsk_8ea8d59a8bef4a939cf664c77bd224c7`; latest output folder:
  `D:\3-Ikbalzohr\Project\arcmap_agent_testing_project\Hasil Peta\print_ready_m1_832cb8dfad06\`
- Latest files: `PETA A4 BUOL AGRI LESTARI - ADMINISTRASI.pdf` (2,861,872 B, SHA256 `55946d9c5a588fd3d07907f029b1eed511cce5e71674e63b3fce7ac93934002d`), PNG (14,923,580 B, SHA256 `1ec728ad6037f8ef40c34606122f294e688b67a3f24948886c2fd24a05029bee`), `working.mxd`, `print_ready_report.json`, and `structural_qa.json`.
- Independent structural QA PASS: PDF 1.6, one page, 296.86 x 210.08 mm by `/MediaBox`, PNG signature and size 4675 x 3308 px consistent with requested 400 DPI, `structural_qa_pass=true`. Input MXD SHA256 unchanged `976731c8415addc79488e3bf3d773a390b4108bb64d05f6ffaba91ee07c903b0`.
- Visual observation of 115 DPI source-preview PNG `_validation/arcmap_print_ready_m1_preview.png`: main map, graticule/grid and edge coordinates, both inset maps, north arrow, scale bar, title, legend, attribution and CRS text are rendered. Two visual issues need review: CRS key/value text is very tight; some map labels are close to the neatline/edge. No actual PDF-to-image rendering by an independent PDF renderer or printer-margin acceptance yet.
- Focused: `test_print_ready.py` **16/16 PASS**; existing mode routing `19/19 PASS`; full ArcMap suite **117/117 PASS**, genuine outer exit0, task `tsk_237658cfec664581af79a901c664a76f`. The inner Stage3 fixture intentionally reproduces an isolated setup failure, but outer suite is 117 PASS, 0 failures.
- Current public `arcmap_ping` in this chat ended `BRIDGE_TIMEOUT` (task `tsk_eb54ca0dc26146fc8974b0dad264dc71`), no replay. The headless disk file worker works without the live Desktop bridge.

### Acceptance status and remaining work
- **SOURCE_VERTICAL_SLICE = PASS** for real ArcPy worker export, real output files, static QA and core source tests.
- **PDF_STRUCTURAL_QA = PASS**. **PRINT_READY_ACCEPTED = FALSE** because PDF raster-render parity, font embedding, collision/edge label analysis, grid numeric correctness, source attribution accuracy, inset extent correctness, physical printer margins and cartographic visual sign-off remain unverified.
- **INSTALLED_MCP_TOOL = NOT_DEPLOYED** and **PUBLIC_OAUTH_CALL = NOT_RUN**. Existing ArcMap Desktop/Add-In/Live Bridge, Core/Tunnel and production installation were not restarted or modified.
- Next milestone: independently render the PDF, resolve close CRS copy and edge text on working copy, verify native grid objects + graticule values, review printer-safe margin, add independent label collision/legend sync QA, then deploy through the established backed-up isolated ArcMap service process, verify public OAuth invocation, and only then mark end-to-end ChatGPT-to-PDF acceptance.
