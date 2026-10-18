from __future__ import annotations


class CartographicProfileSelector:
    def select(self, goal, reference_analysis=None):
        goal = goal or {}
        requested = str(goal.get("cartographic_profile") or "").strip()
        if requested and requested.lower() != "auto":
            return {
                "profile": requested,
                "reason": "explicit_profile",
                "confidence": 1.0,
            }

        map_type = " ".join([
            str(goal.get("map_type") or ""),
            str(goal.get("title") or ""),
            str(goal.get("raw_goal") or ""),
        ]).lower()
        reference = reference_analysis or goal.get("reference_analysis") or {}
        ref_type = str(reference.get("reference_type") or "").lower()
        orientation = str(
            ((reference.get("page") or {}).get("orientation"))
            or ((goal.get("layout") or {}).get("orientation"))
            or "landscape"
        ).lower()

        if "administr" in map_type or "administr" in ref_type:
            profile = (
                "administration_a4_portrait"
                if orientation == "portrait"
                else "administration_a4_landscape"
            )
            return {"profile": profile, "reason": "administration_semantics", "confidence": 0.96}

        if any(token in map_type for token in ("lokasi", "location", "situasi", "site")):
            return {"profile": "location_a4_landscape", "reason": "location_semantics", "confidence": 0.90}

        if any(token in map_type for token in ("tematik", "thematic", "tutupan", "kawasan", "landuse", "pippib")):
            return {"profile": "thematic_a4_landscape", "reason": "thematic_semantics", "confidence": 0.88}

        return {"profile": "simple_a4_landscape", "reason": "generic_fallback", "confidence": 0.65}
