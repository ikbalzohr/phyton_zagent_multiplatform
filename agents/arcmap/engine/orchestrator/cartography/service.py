from __future__ import annotations

import os
from copy import deepcopy

from .acceptance import CartographicAcceptanceGate
from .layout import CartographicLayoutComposer
from .label_collision import LabelCollisionPolicy
from .labels import build_label_plan, build_recipe_operations as build_label_recipe_operations
from .repair import CartographicRepairEngine
from .specification import CartographicSpecificationBuilder
from .symbology import build_layer_order, build_recipe_operations as build_symbology_recipe_operations, build_symbology_plan
from .visual_qa import CartographicVisualQA


class CartographicCapabilityEngine:
    """
    Compiles a high-level map goal into an auditable cartographic program.

    The program is intentionally independent from ArcPy. It can be journaled by
    Tunnel, reviewed by Manager, executed against CURRENT MXD by the ArcMap
    bridge, visually validated, repaired within a bounded budget, and finally
    persisted to the same root MXD.
    """

    def __init__(self):
        self.spec_builder = CartographicSpecificationBuilder()
        self.visual_qa = CartographicVisualQA()
        self.acceptance = CartographicAcceptanceGate()
        self.layout_composer = CartographicLayoutComposer()
        self.label_collision = LabelCollisionPolicy()

    @staticmethod
    def _normalize_layer_names(rows):
        normalized = []
        for row in rows or []:
            item = deepcopy(row)
            if not item.get("layer_name"):
                name = item.get("name") or os.path.basename(str(item.get("path") or ""))
                item["layer_name"] = os.path.splitext(str(name))[0]
            normalized.append(item)
        return normalized

    @staticmethod
    def _canonicalize_layer_names(rows, goal):
        result = []
        used = {}
        project_name = str(
            (goal or {}).get("project_name")
            or (goal or {}).get("company_name")
            or "AREA STUDI"
        ).strip().upper()
        role_names = {
            "project_boundary": project_name,
            "road": "JALAN",
            "river": "SUNGAI DAN ALIRAN AIR",
            "admin_polygon": "DESA",
            "basemap": "BASEMAP",
        }
        for row in rows or []:
            item = deepcopy(row)
            role = str(item.get("semantic_role") or "")
            base = role_names.get(role)
            if not base:
                base = str(item.get("layer_name") or item.get("name") or "")
                base = os.path.splitext(os.path.basename(base))[0]
                base = base.replace("_PL", "").replace("_LN", "").replace("_PT", "")
                base = base.replace("_", " ").strip().upper() or role.upper() or "LAYER"
            count = used.get(base, 0) + 1
            used[base] = count
            item["source_layer_name"] = item.get("layer_name")
            item["layer_name"] = base if count == 1 else "%s %d" % (base, count)
            item["legend_name"] = item["layer_name"]
            result.append(item)
        return result

    @staticmethod
    def _section_boxes(layout):
        panel = (layout or {}).get("side_panel") or {}
        sections = (layout or {}).get("sections") or []
        x = float(panel.get("x") or 0)
        y = float(panel.get("y") or 0)
        w = float(panel.get("w") or 0)
        h = float(panel.get("h") or 0)
        total = sum(float(x.get("height") or 0) for x in sections) or 1.0
        top = y + h
        boxes = {}
        for section in sections:
            ratio = float(section.get("height") or 0) / total
            sh = h * ratio
            top -= sh
            boxes[section.get("id") or "section"] = {
                "x": x,
                "y": top,
                "w": w,
                "h": sh,
            }
        return boxes

    def compile(self, goal, context=None, datasets=None, reference_analysis=None):
        spec = self.spec_builder.build(
            goal,
            context=context,
            datasets=datasets,
            reference_analysis=reference_analysis,
        )
        spec["semantic_layers"] = self._canonicalize_layer_names(
            self._normalize_layer_names(spec.get("semantic_layers")),
            goal,
        )
        spec["main_layers"] = self._canonicalize_layer_names(
            self._normalize_layer_names(spec.get("main_layers")),
            goal,
        )
        ignored_roles = set(str(x).lower() for x in (spec.get("ignore_roles") or []))
        ignored_datasets = [
            str(x).lower()
            for x in ((goal or {}).get("ignore_datasets") or [])
            if str(x).strip()
        ]

        def _included(row):
            if str(row.get("semantic_role") or "").lower() in ignored_roles:
                return False
            haystack = " ".join([
                str(row.get("name") or ""),
                str(row.get("path") or ""),
                str(row.get("relative") or ""),
            ]).lower()
            return not any(token in haystack for token in ignored_datasets)

        spec["semantic_layers"] = [x for x in spec["semantic_layers"] if _included(x)]
        spec["main_layers"] = [x for x in spec["main_layers"] if _included(x)]
        spec["provenance"] = [
            row for row in (spec.get("provenance") or [])
            if not any(
                token in str((row or {}).get("source_path") or "").lower()
                for token in ignored_datasets
            )
        ]
        if isinstance(spec.get("insets"),dict):
            spec["insets"]["items"] = [
                row for row in (spec["insets"].get("items") or [])
                if _included(row)
            ]
            spec["insets"]["count"] = len(spec["insets"]["items"])

        profile = spec.get("profile") or {}
        symbology = build_symbology_plan(spec["main_layers"], profile)
        labels = build_label_plan(spec["main_layers"], profile)
        labels = self.label_collision.tune(
            labels,
            dataframe_scale=((spec.get("scale_grid") or {}).get("scale")),
            feature_counts=(goal or {}).get("feature_counts") or {},
        )
        layer_order = build_layer_order(symbology)
        spec["layer_order"] = layer_order

        composed_layout = self.layout_composer.compose(
            profile,
            reference_target=spec.get("reference_target") or {},
        )
        section_boxes = composed_layout.get("section_boxes") or {}
        title_lines = (spec.get("title") or {}).get("lines") or []
        crs = spec.get("crs") or {}
        provenance = spec.get("provenance") or []
        inset_items = (spec.get("insets") or {}).get("items") or []
        scale_grid = spec.get("scale_grid") or {}

        layout_program = {
            "paper": composed_layout.get("paper") or (profile.get("paper") or {}),
            "page_background_rgb": composed_layout.get("page_background_rgb"),
            "main_map_box": composed_layout.get("main_map_box") or {},
            "side_panel_box": composed_layout.get("side_panel_box") or {},
            "section_boxes": section_boxes,
            "title": {
                "lines": title_lines,
                "box": section_boxes.get("title"),
                "font_size_pt": ((profile.get("typography") or {}).get("title_pt") or 15.0),
            },
            "orientation_scale": {
                "box": section_boxes.get("orientation_scale"),
                "north_arrow": True,
                "scale_text": scale_grid.get("scale"),
                "scale_bar": scale_grid.get("scale_bar"),
            },
            "legend": {
                "box": section_boxes.get("legend"),
                "title": "LEGENDA",
                "items": [
                    {
                        "layer_name": row.get("layer_name"),
                        "role": row.get("role"),
                    }
                    for row in reversed(symbology)
                    if row.get("role") not in ("basemap", "inset")
                ],
            },
            "crs_block": {
                "box": section_boxes.get("crs"),
                "values": crs,
            },
            "provenance_block": {
                "box": section_boxes.get("provenance"),
                "items": provenance,
            },
            "insets_box": section_boxes.get("insets"),
            "grid": scale_grid.get("grid") or {},
        }

        program = {
            "schema_version": "1.0",
            "program_type": "CURRENT_MXD_IN_PLACE_CARTOGRAPHY",
            "specification": spec,
            "reference_target": spec.get("reference_target") or {},
            "data_frame": (goal or {}).get("data_frame") or "",
            "persistence": spec.get("persistence") or {},
            "layers": [
                {
                    "path": row.get("path"),
                    "layer_name": row.get("layer_name"),
                    "role": row.get("semantic_role"),
                    "required": row.get("semantic_role") in ("project_boundary", "basemap"),
                    "preferred": row.get("semantic_role") in ("road", "river", "admin_polygon"),
                    "visible": True,
                }
                for row in spec.get("main_layers") or []
            ],
            "layer_order": layer_order,
            "symbology": symbology,
            "labels": labels,
            "layout": layout_program,
            "insets": {
                "count": len(inset_items),
                "items": [
                    {
                        "name": item.get("name") or ("INSET_%02d" % (idx + 1)),
                        "path": item.get("path"),
                        "semantic_role": item.get("semantic_role"),
                        "source_name": item.get("source_name") or item.get("name"),
                    }
                    for idx, item in enumerate(inset_items)
                ],
                "highlight": ((profile.get("insets") or {})),
            },
            "scale_grid": scale_grid,
            "metadata": {
                "title": spec.get("title"),
                "crs": crs,
                "provenance": provenance,
                "administrative_inference": spec.get("administrative_inference") or {},
            },
            "qa": spec.get("qa") or {},
            "repair_policy": {
                "max_cycles": int((spec.get("repair") or {}).get("max_cycles") or 3),
            },
            "accepted_warnings": spec.get("accepted_warnings") or [],
        }

        recipe_operations = [{
            "action": "apply_cartographic_program",
            "params": {"program": program},
        }]
        recipe = {
            "name": "Cartographic program: %s" % ((spec.get("title") or {}).get("raw_title") or "map"),
            "operations": recipe_operations,
        }
        return {
            "ok": True,
            "specification": spec,
            "program": program,
            "recipe": recipe,
            "semantic_layer_count": len(spec.get("semantic_layers") or []),
            "symbology_count": len(symbology),
            "label_plan_count": len(labels),
            "inset_count": len(inset_items),
        }

    def evaluate_visual(self, metrics, specification, vision_feedback=None):
        return self.visual_qa.evaluate(metrics, specification, vision_feedback=vision_feedback)

    def propose_repair(self, qa_result, specification, cycle):
        engine = CartographicRepairEngine(
            max_cycles=int(((specification or {}).get("repair") or {}).get("max_cycles") or 3)
        )
        return engine.propose(qa_result, specification, cycle=cycle)

    def final_acceptance(self, technical_validation, visual_validation, artifacts, specification):
        return self.acceptance.evaluate(
            technical_validation,
            visual_validation,
            artifacts=artifacts,
            specification=specification,
        )
