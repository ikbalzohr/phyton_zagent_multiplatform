"""Safe Smart Corner Digitizer MCP surface, ArcMap 10.6.1.

No tool here saves MXD. Mutating operations are guarded as destructive,
and Zagent Dev upstream mode must reject them before reaching ArcMap.
"""


def register(mcp, s):
    @mcp.tool()
    def arcmap_smart_corner_preflight(source_layer: str, target_layer: str,
                                     data_frame: str = "", feature_oid: int = None,
                                     id_field: str = "Id"):
        """Read-only shapefile polygon/point checks, CRS, current feature and fingerprints."""
        return s.call("smart_corner_preflight", source_layer=source_layer,
                      target_layer=target_layer, data_frame=data_frame,
                      feature_oid=feature_oid, id_field=id_field)

    @mcp.tool()
    def arcmap_smart_corner_preview(source_layer: str, target_layer: str,
                                    data_frame: str = "", feature_oid: int = None,
                                    min_turn_deg: float = 45.0,
                                    straight_turn_deg: float = 3.0,
                                    collinear_tolerance_m: float = 0.05,
                                    coordinate_epsilon_m: float = 1e-8,
                                    min_segment_length_m: float = 0.0,
                                    include_straight: bool = False):
        """Read-only detection; preview includes exact vertex XY and turn metrics.

        Does not alter source/target SHP, current selection, map layout or MXD.
        Review-class candidates are excluded from automatic output.
        """
        return s.call("smart_corner_preview", source_layer=source_layer,
                      target_layer=target_layer, data_frame=data_frame,
                      feature_oid=feature_oid, min_turn_deg=min_turn_deg,
                      straight_turn_deg=straight_turn_deg,
                      collinear_tolerance_m=collinear_tolerance_m,
                      coordinate_epsilon_m=coordinate_epsilon_m,
                      min_segment_length_m=min_segment_length_m,
                      include_straight=include_straight)

    @mcp.tool()
    def arcmap_smart_corner_review(preview_id: str, expected_revision: str,
                                   include_vertex_indices: list[int] = None,
                                   exclude_vertex_indices: list[int] = None):
        """Read-only review of corner candidate indices, sequenced clockwise.

        Each review supplies the complete include/exclude override set.
        """
        return s.call("smart_corner_review", preview_id=preview_id,
                      expected_revision=expected_revision,
                      include_vertex_indices=include_vertex_indices or [],
                      exclude_vertex_indices=exclude_vertex_indices or [])

    @mcp.tool()
    def arcmap_smart_corner_commit(preview_id: str, expected_revision: str,
                                   idempotency_key: str,
                                   confirm_commit: bool = False,
                                   confirm_replace_nonempty: bool = False,
                                   expected_target_count: int = None,
                                   dry_run: bool = True,
                                   write_mode: str = "replace",
                                   id_field: str = "Id",
                                   label_field: str = "",
                                   label_prefix: str = "Pt"):
        """Guarded SHP replacement; cannot commit by default.

        Requires prior explicit review, confirmed revision, target fingerprint,
        explicit replace confirmation and permissive Safe Mode policy.
        Never saves CURRENT MXD; writes backup and durable journal first.
        """
        return s.call("smart_corner_commit", "destructive",
                      preview_id=preview_id, expected_revision=expected_revision,
                      idempotency_key=idempotency_key, confirm_commit=confirm_commit,
                      confirm_replace_nonempty=confirm_replace_nonempty,
                      expected_target_count=expected_target_count,
                      dry_run=dry_run, write_mode=write_mode, id_field=id_field,
                      label_field=label_field, label_prefix=label_prefix)

    @mcp.tool()
    def arcmap_smart_corner_validate(preview_id: str = "", commit_id: str = "",
                                      include_straight: bool = False):
        """Read-only preview freshness or post-commit record/count/fingerprint check."""
        return s.call("smart_corner_validate", preview_id=preview_id,
                      commit_id=commit_id, include_straight=include_straight)

    @mcp.tool()
    def arcmap_smart_corner_status(commit_id: str):
        """Read immutable on-disk commit journal; never replay an uncertain commit."""
        return s.call("smart_corner_status", commit_id=commit_id)

    @mcp.tool()
    def arcmap_smart_corner_rollback(commit_id: str,
                                     confirm_rollback: bool = False):
        """Explicit, guarded rollback from SHA-verified full sidecar backup.

        Only confirmed commits with unchanged target hashes qualify. All other
        outcomes require manual reconciliation, not a blind filesystem retry.
        """
        return s.call("smart_corner_rollback", "destructive",
                      commit_id=commit_id, confirm_rollback=confirm_rollback)
