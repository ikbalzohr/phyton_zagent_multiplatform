# ArcMap Global/Project ZAGENT.md — Implementation Audit (8 November 2026)

## Scope and approval
User approved implementation of the previously reviewed global and project cartographic rule documents (39 decisions). This checkpoint is not a claim of complete automated cartography equivalence with QGIS.

## Rule locations
- Repository copy: `agents/arcmap/ZAGENT.md`
- Installed global: `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform\agents\arcmap\ZAGENT.md`
- Project: `D:\3-Ikbalzohr\Project\arcmap_agent_testing_project\ZAGENT.md`
- Loader: `agents/arcmap/engine/orchestrator/cartographic_rules.py`
- ArcPy planner: `agents/arcmap/engine/stage2/cartographic_apply.py`

The service reads files for every new job, merges global -> project -> explicit scale override, validates supported fields, and sends a snapshot through the isolated Python 2.7 worker. Unrecognized JSON fields are refused; free-form exceptions require agent interpretation rather than silent arbitrary execution. A missing project file is created only when writing is permitted; read-only roots inherit global without a file. No global caching: changes are visible to the next job.

## Implemented deterministic behavior
- A4 landscape, PDF+PNG 400 dpi contract enforced; source MXD and `Contoh Layout` protected.
- Exact/candidate matching of the polygon activity layer with ambiguous or unavailable layer failure; source identity and coordinate reference checks.
- Automatic preferred scale selection with configurable area padding, plus positive-scale one-job override; inset context check/recentering.
- Arial text elements, 14 pt title minimum, 7 pt important-text minimum, numeric scale label adjustment, template zone cleanup and printer margin safeguards.
- Draw-order preset role classification and audit, legend role audit, output `resolved_rules.json` and `cartographic_decisions.json` upon successful export, `cartographic_failure.json` for a build-stage rule failure.
- Output remains a draft/candidate until independently reviewed; runtime must never claim final print acceptance from export alone.
- Project overrides cannot change security gates or file preservation policies.

## Known limitations (not silently accepted)
- ArcMap 10.6's `arcpy.mapping` cannot safely set every renderer style, rebuild all legend items/columns, modify every graticule grid interval, or optimize label collisions and callout lines with the currently available API/template. These are reported as warnings and require further cartographic engineering or human review.
- Unstructured human-language exceptions are accepted in Markdown as instructions for an agent, but deterministic worker execution halts pending their resolution into supported parameters; they are not executed as code.
- Two inset frames are validated and recentered if necessary; a reliable cartographic location marker and raster coverage check require additional work.

## Test and installation evidence
- Rules unit tests: 10 cases, including precedence, hot reload, project auto-create, read-only, invalid fields, explicit overrides, protective path guard, automatic scale calculation, and CRS projection failure.
- Full ArcMap regression: **134/134 PASS** (outer unittest exit code 0). An intentionally injected nested Stage3 fixture failure is expected inside its isolation test.
- Python2.7 compilation: PASS. Git `diff --check`: PASS.
- Installed deployment: 9 code/rules/QA files, all source-to-install SHA256 matches at install time.
- Backup: `D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent Multi Platform\agents\arcmap\artifacts\deployment_backups\cartography_rules_v1_20261108_131440`.
- ArcMap process restarted individually: PID 20260 -> 23912. Core PID 18944, Files 16036, Tunnel 17896, QGIS 19428 remained unchanged.

## Live input-data blocker
The sample main polygon `SHP\PT_BUOL_AGRI_LESTARI_PL.shp` has `.prj` stating `WGS_1984_Web_Mercator_Auxiliary_Sphere`, whereas the main layout uses `WGS_1984_UTM_Zone_51N`. Coordinate projection failed in ArcPy; the tool now safely returns `DATASET_CRS_METADATA_INCONSISTENT` rather than exporting a possibly misleading map. Original shapefile and `.prj` were **not modified**.

Authenticated public tool test with original data (`tsk_4f832bd13cac486e9ea7462f9f24c895`) reached the installed engine and produced that expected **FAIL**. This is a safety/validation PASS but a print-output FAIL. Do not call the sample PDF ready under the new policy until the source coordinate reference has been independently verified and corrected by an authorized GIS data custodian.

An isolated QA fixture copied relevant files into `Hasil Peta\_cartography_rules_isolated_qa` and assigned UTM 51N only to the copied main `.prj` for testing, never to the real source. That test also failed safely with `MAIN_ACTIVITY_SPATIAL_REFERENCE_UNKNOWN`; it is not an accepted PDF or evidence that the source CRS is UTM.

## Git scope
No commit/push was requested in the current approval. Do not include other preexisting untracked repository documents. Only stage and commit after explicit authorization.

## Final verification and service recovery

- Public ArcMap tool description updated with automatic scale selection (scale=0).
- A manual force-kill of the Core-owned ArcMap process exhausted the supervisor automatic recovery budget, temporarily removing the ArcMap process and listener. Restored successfully through the authenticated local-owner Core Dashboard lifecycle start action using CSRF and an idempotency key (operation be0b4313808c43e482f5f0d7f06dfbae, succeeded). Planned restarts must use Core lifecycle API rather than repeated process kills.
- Final observed: Core PID 18944, ArcMap PID 23912 owned by Core, Files PID 16036, Tunnel PID 17896, QGIS PID 19428. Port 19140 LISTEN. Other agents not restarted.
- Generalized independent QA script no longer hardcodes template-specific company name, scale, inset scales or geographic grid coordinates. Verifies selected scale against visible numeric scale label, grid interval from main map PDF words, Arial text font embedding with ESRINorth symbol exception.
- Regression check on previously reviewed m2 baseline PDF: independent QA automated PASS, reviewed PASS, errors zero. This checks backward compatibility only and is NOT a new final print output generated by adaptive rules.
- Public ArcMap tool correctly returned DATASET_CRS_METADATA_INCONSISTENT for current PT Buol Agri Lestari source. Original shapefile projection metadata conflicts with data frame and cannot be silently corrected. A separate experimental copied fixture was used only to test failure paths and also failed safely.
- Remaining implementation limitations: renderer style edits, fully dynamic legend and columns, advanced label collision/callouts, grid interval adaptation, and inset location markers. These must not be asserted as validated; current rules-engine is a foundation rather than full QGIS-equivalent automation.
- No commit or push during this request. Existing unrelated repo files were preserved.


## Koreksi hasil pemeriksaan CRS — 8 November 2026, tahap lanjutan

Diagnosis terdahulu yang menyebut metadata CRS shapefile utama tidak konsisten **sudah dibatalkan**. ArcMap `Describe(layer).extent` menggunakan koordinat data frame yang telah ditransformasi, sementara `spatialReference` tetap CRS dataset; penggunaan keduanya sebagai satu pasangan koordinat adalah bug engine. Verifikasi dataset asli menemukan EPSG:3857 yang benar, dengan overlay ArcMap EPSG:32651 UTM Zona 51N. Perbaikan telah diterapkan; print-ready public tool dan QA PDF+visual PASS. Rincian dan jejak uji: `docs/ARCMAP_CRS_ON_THE_FLY_ACCEPTANCE_20261108.md`.
