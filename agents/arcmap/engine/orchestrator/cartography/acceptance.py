from __future__ import annotations


class CartographicAcceptanceGate:
    def evaluate(self, technical_validation, visual_validation, artifacts=None, specification=None):
        technical = technical_validation or {}
        visual = visual_validation or {}
        artifacts = artifacts or []
        spec = specification or {}
        required = set(str(x).upper() for x in ((spec.get("qa") or {}).get("require_artifacts") or ["PDF", "PNG"]))
        present = set()
        for item in artifacts:
            if isinstance(item, dict):
                present.add(str(item.get("kind") or item.get("format") or "").upper())
            else:
                path = str(item)
                if "." in path:
                    present.add(path.rsplit(".", 1)[-1].upper())
        missing = sorted(required - present)
        errors = []
        if not technical.get("ok"):
            errors.append({"code": "TECHNICAL_VALIDATION_FAILED", "details": technical})
        if not visual.get("ok"):
            errors.append({"code": "CARTOGRAPHIC_VISUAL_VALIDATION_FAILED", "details": visual})
        if missing:
            errors.append({"code": "REQUIRED_ARTIFACT_MISSING", "formats": missing})
        return {
            "ok": not errors,
            "status": "CARTOGRAPHIC_ACCEPTED" if not errors else "CARTOGRAPHIC_NOT_ACCEPTED",
            "technical_validation": technical,
            "visual_validation": visual,
            "required_artifacts": sorted(required),
            "present_artifacts": sorted(present),
            "errors": errors,
        }
