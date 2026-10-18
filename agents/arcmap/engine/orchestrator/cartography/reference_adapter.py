from __future__ import annotations

from copy import deepcopy

from .reference_contract import (
    REFERENCE_ANALYSIS_SCHEMA,
    normalize_reference_analysis,
    reference_analysis_prompt_contract,
)


class ReferenceImageAnalysisAdapter:
    """
    Contract boundary between the assistant/vision layer and deterministic GIS
    execution. ArcMap never needs to infer pixels itself: vision returns a
    normalized reference-analysis object, which is then frozen into the plan.
    """

    def request(self, image_ref, map_type="administration", hints=None):
        return {
            "kind": "cartographic_reference_analysis_request",
            "image_ref": str(image_ref or ""),
            "map_type": str(map_type or "administration"),
            "hints": deepcopy(hints or {}),
            "contract": reference_analysis_prompt_contract(),
            "default_target": deepcopy(REFERENCE_ANALYSIS_SCHEMA),
        }

    def accept(self, analysis):
        normalized = normalize_reference_analysis(analysis or {})
        errors = []
        regions = normalized.get("regions") or {}
        for region in ("main_map", "side_panel"):
            box = regions.get(region) or {}
            for key in ("x", "y", "w", "h"):
                value = box.get(key)
                if value is None:
                    errors.append("%s.%s missing" % (region, key))
                    continue
                try:
                    number = float(value)
                except Exception:
                    errors.append("%s.%s invalid" % (region, key))
                    continue
                if key in ("x", "y") and not (0.0 <= number <= 1.0):
                    errors.append("%s.%s out of range" % (region, key))
                if key in ("w", "h") and not (0.0 < number <= 1.0):
                    errors.append("%s.%s out of range" % (region, key))
        return {
            "ok": not errors,
            "analysis": normalized,
            "errors": errors,
        }

    def freeze(self, image_ref, analysis, map_type="administration"):
        checked = self.accept(analysis)
        return {
            "ok": checked["ok"],
            "source": {
                "image_ref": str(image_ref or ""),
                "map_type": str(map_type or "administration"),
            },
            "analysis": checked["analysis"],
            "errors": checked["errors"],
        }
