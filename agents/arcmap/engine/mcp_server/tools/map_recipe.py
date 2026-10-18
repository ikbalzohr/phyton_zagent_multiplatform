def register(mcp, s):
    @mcp.tool()
    def arcmap_get_map_recipe_schema():
        """Return the safe full-map recipe schema and allowed reversible actions."""
        return s.call("get_map_recipe_schema")

    @mcp.tool()
    def arcmap_validate_map_recipe(recipe: dict):
        """Validate a full-map recipe without changing ArcMap."""
        return s.call("validate_map_recipe", recipe=recipe)

    @mcp.tool()
    def arcmap_apply_map_recipe(recipe: dict, atomic: bool = True,
                                dry_run: bool = False):
        """Apply a reversible full-map recipe. On atomic failure, live state and captured styles are restored."""
        return s.call("apply_map_recipe", "live_write", recipe=recipe,
                      atomic=atomic, dry_run=dry_run)

    @mcp.tool()
    def arcmap_rollback_map_recipe(run_id: str):
        """Rollback a prior successful map-recipe run, including captured symbology."""
        return s.call("rollback_map_recipe", "live_write", run_id=run_id)
