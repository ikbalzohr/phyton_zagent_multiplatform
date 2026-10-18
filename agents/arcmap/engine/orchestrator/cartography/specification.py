from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from .metadata import build_crs_block, build_provenance, build_title_lines
from .administration import AdministrativeLocationReasoner
from .insets import InsetPlanner
from .reference_contract import normalize_reference_analysis
from .profiles import get_profile
from .profile_selector import CartographicProfileSelector
from .reference import ReferenceLayoutInterpreter
from .scale_grid import build_scale_grid_spec
from .semantics import DatasetSemanticInterpreter, infer_administrative_location


class CartographicSpecificationBuilder:
    def __init__(self):
        self.semantic = DatasetSemanticInterpreter()
        self.reference = ReferenceLayoutInterpreter()
        self.administration = AdministrativeLocationReasoner()
        self.insets = InsetPlanner()
        self.profile_selector = CartographicProfileSelector()

    def build(self, goal, context=None, datasets=None, reference_analysis=None):
        goal = deepcopy(goal or {})
        context = deepcopy(context or {})
        profile_choice = self.profile_selector.select(
            goal,
            reference_analysis=reference_analysis or goal.get("reference_analysis") or {},
        )
        profile_name = profile_choice["profile"]
        profile = get_profile(profile_name, goal.get("profile_overrides"))
        semantic_layers = self.semantic.interpret(datasets or goal.get("datasets") or [])
        main_basemap = self.semantic.choose_main_basemap(semantic_layers)
        main_basemap_path = str((main_basemap or {}).get("path") or "")
        for row in semantic_layers:
            role = row.get("semantic_role")
            if role == "inset":
                row["main_map_selected"] = False
            elif role == "basemap":
                row["main_map_selected"] = (
                    bool(main_basemap_path)
                    and str(row.get("path") or "") == main_basemap_path
                )
                if not row["main_map_selected"]:
                    row["selection_reason"] = "alternate_basemap_not_selected"
            else:
                row["main_map_selected"] = True
        main_rows = [
            x for x in semantic_layers
            if x.get("semantic_role") != "inset"
            and bool(x.get("main_map_selected", True))
        ]
        normalized_reference = normalize_reference_analysis(reference_analysis or goal.get("reference_analysis"))
        reference = self.reference.interpret(normalized_reference)
        dataframe_state = (
            goal.get("dataframe_state")
            or context.get("dataframe")
            or context.get("map")
            or {}
        )
        scale_grid = build_scale_grid_spec(dataframe_state, profile)
        project_boundary = self.semantic.choose(main_rows, "project_boundary", required=False)
        inset_plan = self.insets.plan(self.semantic, semantic_layers, profile)
        insets = inset_plan.get("items") or []
        title = goal.get("title") or "PETA ADMINISTRASI"
        project_name = goal.get("project_name") or goal.get("company_name") or ""
        admin_resolution = self.administration.resolve(
            explicit=goal.get("administrative_location") or {},
            samples=goal.get("dataset_samples") or [],
        )
        admin = admin_resolution.get("location") or {}
        admin_inference = {
            "location": admin,
            "conflicts": admin_resolution.get("conflicts") or {},
            "sources": admin_resolution.get("sources") or {},
            "missing": admin_resolution.get("missing") or [],
        }
        year = goal.get("year") or datetime.now().year
        sr = (
            goal.get("spatial_reference")
            or dataframe_state.get("spatial_reference")
            or dataframe_state.get("crs")
            or {}
        )
        outputs = deepcopy(goal.get("outputs") or {})
        outputs.setdefault("formats", ["PDF", "PNG"])
        outputs.setdefault("dpi", 400)
        outputs.setdefault("output_subdir", "Hasil Peta")
        outputs.setdefault("save_mxd", True)

        persistence = {
            "mode": "CURRENT_MXD_IN_PLACE",
            "require_active_document": True,
            "require_document_in_project_root": True,
            "create_recovery_checkpoint": True,
            "save_current_mxd": True,
            "create_final_mxd_copy": False,
            "output_subdir": outputs.get("output_subdir", "Hasil Peta"),
        }
        if goal.get("persistence"):
            persistence.update(goal["persistence"])

        return {
            "schema_version": "1.0",
            "spec_type": "cartographic_product",
            "profile_name": profile_name,
            "profile_selection": profile_choice,
            "profile": profile,
            "reference_target": reference,
            "persistence": persistence,
            "title": {
                "lines": build_title_lines(title, project_name, admin, year),
                "raw_title": title,
                "project_name": project_name,
                "administrative_location": admin,
                "year": int(year),
            },
            "semantic_layers": semantic_layers,
            "main_layers": main_rows,
            "project_boundary": project_boundary,
            "main_basemap": main_basemap,
            "layer_order": [
                x.get("layer_name") or x.get("name") or ""
                for x in self.semantic.layer_order(main_rows)
                if x.get("layer_name") or x.get("name")
            ],
            "layout": deepcopy(profile.get("layout") or {}),
            "typography": deepcopy(profile.get("typography") or {}),
            "scale_grid": scale_grid,
            "insets": {
                "count": len(insets),
                "items": insets,
                "required_count": inset_plan.get("required_count"),
                "config": deepcopy(profile.get("insets") or {}),
            },
            "crs": build_crs_block(sr),
            "provenance": build_provenance(semantic_layers, year=year),
            "administrative_inference": admin_inference,
            "outputs": outputs,
            "qa": deepcopy(profile.get("qa") or {}),
            "repair": deepcopy(profile.get("repair") or {"max_cycles": 3}),
            "accepted_warnings": list(goal.get("accepted_warnings") or []),
            "ignore_roles": list(goal.get("ignore_roles") or []),
            "notes": list(goal.get("cartographic_notes") or []),
        }
