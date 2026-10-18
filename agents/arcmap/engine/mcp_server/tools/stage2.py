from pathlib import Path

from orchestrator.adapters.file_worker.arcgis_process import ArcGISProcessFileWorker


_ENGINE_ROOT = Path(__file__).resolve().parents[2]
_STAGE2_FILE_WORKER = ArcGISProcessFileWorker(_ENGINE_ROOT, timeout_seconds=300)


def register(mcp, s):
    @mcp.tool()
    def arcmap_stage2_discover_data(data_root: str, max_items: int = 10000):
        """Discover supported GIS datasets through the isolated ArcGIS 10.6 file worker."""
        result = _STAGE2_FILE_WORKER.discover_data(
            data_root=data_root,
            max_items=max_items,
        )
        if not result.get("ok"):
            result.setdefault("code", "STAGE2_DISCOVERY_FAILED")
        return result

    @mcp.tool()
    def arcmap_stage2_preview_match(data_root: str, recipe: dict,
                                    max_items: int = 10000,
                                    min_score: float = 0.62):
        """Preview matching through the isolated ArcGIS 10.6 file worker."""
        result = _STAGE2_FILE_WORKER.preview_match(
            data_root=data_root,
            recipe=recipe or {},
            max_items=max_items,
            min_score=min_score,
        )
        if not result.get("ok"):
            result.setdefault("code", "STAGE2_PREVIEW_MATCH_FAILED")
        return result

    @mcp.tool()
    def arcmap_stage2_validate_template(template_mxd: str, profile: dict = None):
        """Validate an A4 template through the isolated ArcGIS 10.6 file worker."""
        result = _STAGE2_FILE_WORKER.validate_template(
            template_mxd=template_mxd,
            profile=profile or {},
        )
        if not result.get("ok") and "code" not in result:
            result["code"] = "STAGE2_TEMPLATE_INVALID"
        return result

    @mcp.tool()
    def arcmap_stage2_build_a4(template_mxd: str, data_root: str,
                               output_dir: str, recipe: dict,
                               profile: dict = None,
                               company_name: str = "",
                               map_type: str = "",
                               base_name: str = "",
                               snapshot_root: str = "",
                               save_mxd: bool = True):
        """Build a complete A4 map from template MXD + data folder, QA it, and export production outputs."""
        return s.call(
            "stage2_build_a4", "save",
            template_mxd=template_mxd,
            data_root=data_root,
            output_dir=output_dir,
            recipe=recipe,
            profile=profile or {},
            company_name=company_name,
            map_type=map_type,
            base_name=base_name,
            snapshot_root=snapshot_root,
            save_mxd=save_mxd,
        )

    @mcp.tool()
    def arcmap_stage2_batch_build(job_file: str):
        """Run multiple Stage 2 production jobs from one JSON job file."""
        return s.call("stage2_batch_build", "save", job_file=job_file)

    @mcp.tool()
    def arcmap_stage2_restore_checkpoint(checkpoint_mxd: str, target_mxd: str):
        """Restore a persistent full-MXD checkpoint to a target MXD path."""
        return s.call("stage2_restore_checkpoint", "destructive",
                      checkpoint_mxd=checkpoint_mxd, target_mxd=target_mxd)

    @mcp.tool()
    def arcmap_stage2_list_checkpoints(snapshot_root: str, job_id: str):
        """List persistent Stage 2 MXD checkpoints for a production job."""
        return s.call("stage2_list_checkpoints",
                      snapshot_root=snapshot_root, job_id=job_id)

    @mcp.tool()
    def arcmap_stage2_generic_gp(tool: str, args: list = None,
                                 kwargs: dict = None,
                                 allow_destructive: bool = False):
        """Run an installed ArcPy geoprocessing function through the guarded generic runner."""
        return s.call("stage2_generic_gp", "geoprocessing",
                      tool=tool, args=args or [], kwargs=kwargs or {},
                      allow_destructive=allow_destructive)
