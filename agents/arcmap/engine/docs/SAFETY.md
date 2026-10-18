# Safety Model

Default configuration:
- `allow_live_write=true`
- `allow_save=false`
- `allow_destructive_operations=false`
- `allow_geoprocessing=false`
- `allow_export=true`

Live edits are intentionally reviewable and unsaved.
Saving the MXD, removing layers, and creating persistent GIS outputs require explicit policy changes in `config/agent_config.json`.

Never store tunnel API keys in the repository. Use environment variables or an OS secret store.

## Immutable Manual baseline

Every persistent output path is blocked when it resolves inside `<optional legacy immutable baseline>`. The baseline may be read for reference, but the agent must never export, geoprocess, save, or otherwise write there.

`Near` is treated as destructive because ArcGIS adds `NEAR_*` fields directly to the input dataset. It therefore requires both `allow_geoprocessing=true` and `allow_destructive_operations=true`.
