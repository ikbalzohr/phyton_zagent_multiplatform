# Grand Plan Capability Ladder

- L0 Connection — implemented
- L1 Inspection — implemented
- L2 Basic Control — implemented
- L3 Layer & Data Management — core implementation included
- L4 Symbology & Labels — core implementation included
- L5 Geoprocessing / Spatial Analysis — core tools included, disabled by default
- L6 Layout Automation — text/element/scale primitives included; Map Profile extraction is next
- L7 Export — PDF/PNG/JPEG included
- L8 Full Map Generation — framework/profile registry included; requires live extraction of mapper templates and project-data rules
- L9 GIS Agent analytical/recommendation workflows — architecture-ready; requires domain-specific policies, validation, and data-provider modules

## Next production tasks

1. Extract exact layout/symbology metadata from the mapper's reference MXDs.
2. Build `Template Profile Administrasi`, `Kontur`, `Geologi`, `Pemantauan Lingkungan`, `Sampel`.
3. Add project-folder generator matching the mapper's established structure.
4. Add authoritative external data providers (government/OSM/DEM) one provider at a time with licensing and provenance metadata.
5. Integration tests on ArcMap 10.6.1 for every write tool.
6. Add batch map generation and map QA checks.
