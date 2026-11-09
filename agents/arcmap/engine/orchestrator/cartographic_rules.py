"""Read project cartographic rules for ArcMap print jobs."""
import copy
import hashlib
import json
import os
import re
from pathlib import Path

class CartographicRuleError(ValueError):
    pass

DEFAULTS = {
    "format": {"paper": "A4", "orientation": "landscape", "dpi": 400, "outputs": ["PDF", "PNG"]},
    "layout": {"preserve_zones": True, "margin_mm": 5},
    "typography": {"family": "Arial", "title_min_pt": 14, "important_min_pt": 7},
    "scale": {"mode": "auto", "requested": 0, "padding_fraction": 0.12,
              "denominators": [1000, 2500, 5000, 10000, 15000, 25000, 50000, 70000,
                               75000, 100000, 150000, 250000, 500000, 1000000,
                               2500000, 5000000]},
    "area": {"layer": "", "dataset": "", "outline": "red", "fill": "transparent"},
    "layers": {"preset": "administration"},
    "legend": {"order": ["area", "road", "river", "administration", "other"],
               "columns_max": 2},
    "grid": {"inherit_template": True, "adaptive_interval": True},
    "insets": {"count": 2, "adaptive_extent": True},
    "qa": {"visual_required_for_final": True, "important_font_min_pt": 7},
}
BLOCK = re.compile(r"(?ms)^\`\`\`zagent-cartography\s*\n(.*?)^\`\`\`\s*$")

def _merge(base, extra, prefix=""):
    for key, value in extra.items():
        field = prefix + key
        if key not in base:
            raise CartographicRuleError("UNSUPPORTED_RULE: " + field)
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise CartographicRuleError("RULE_OBJECT_REQUIRED: " + field)
            _merge(base[key], value, field + ".")
        elif type(value) is not type(base[key]) and not (
                type(base[key]) in (int, float) and type(value) in (int, float)):
            raise CartographicRuleError("RULE_TYPE_INVALID: " + field)
        else:
            base[key] = copy.deepcopy(value)

def _read_rules(path):
    content = path.read_bytes()
    if len(content) > 128 * 1024:
        raise CartographicRuleError("RULE_DOCUMENT_TOO_LARGE")
    markdown = content.decode("utf-8-sig")
    blocks = BLOCK.findall(markdown)
    if len(blocks) != 1:
        raise CartographicRuleError("ONE_CARTOGRAPHY_BLOCK_REQUIRED: " + str(path))
    try:
        rules = json.loads(blocks[0])
    except ValueError as exc:
        raise CartographicRuleError("CARTOGRAPHY_JSON_INVALID: " + str(exc))
    if not isinstance(rules, dict):
        raise CartographicRuleError("CARTOGRAPHY_OBJECT_REQUIRED")
    return markdown, rules, hashlib.sha256(content).hexdigest()

def _validate(r):
    f = r["format"]
    if f != DEFAULTS["format"]:
        raise CartographicRuleError("FIXED_A4_PDF_PNG_400DPI_CONTRACT")
    if r["typography"]["family"].lower() != "arial":
        raise CartographicRuleError("ARIAL_REQUIRED")
    if (r["typography"]["title_min_pt"] < 14 or
            r["typography"]["important_min_pt"] < 7 or
            r["qa"]["important_font_min_pt"] < 7):
        raise CartographicRuleError("FONT_MINIMUM_TOO_LOW")
    scale = r["scale"]
    if scale["mode"] not in ("auto", "fixed"):
        raise CartographicRuleError("INVALID_SCALE_MODE")
    if scale["mode"] == "fixed" and not 1000 <= float(scale["requested"]) <= 100000000:
        raise CartographicRuleError("FIXED_SCALE_VALUE_REQUIRED")
    if not 0.02 <= scale["padding_fraction"] <= 0.40:
        raise CartographicRuleError("INVALID_SCALE_PADDING")
    ds = scale["denominators"]
    if (not ds or ds != sorted(set(ds)) or
            any(type(v) not in (int, float) or v < 1000 or v > 100000000 for v in ds)):
        raise CartographicRuleError("INVALID_STANDARD_SCALES")
    if (r["layout"]["margin_mm"] < 5 or r["insets"]["count"] != 2 or
            r["legend"]["columns_max"] not in (1, 2)):
        raise CartographicRuleError("REQUIRED_LAYOUT_CONTRACT")
    roles = r["legend"]["order"]
    if len(set(roles)) != len(roles) or not set(roles).issubset(
            {"area", "road", "river", "administration", "other"}):
        raise CartographicRuleError("INVALID_LEGEND_ORDER")
    if r["layers"]["preset"] not in ("administration", "environment", "mining"):
        raise CartographicRuleError("INVALID_LAYER_PRESET")

def _unresolved_exceptions(markdown):
    heading = re.search(r"(?im)^##\s+Pengecualian desain proyek\s*$", markdown)
    if heading is None:
        return []
    section = markdown[heading.end():]
    closing = re.search(r"(?m)^##\s+", section)
    if closing:
        section = section[:closing.start()]
    section = BLOCK.sub('', section)
    notes = []
    for line in section.splitlines():
        text = line.strip().lstrip("- ").strip()
        if text and not text.lower().startswith(
                ("belum ada", "tulis di sini", "aturan yang ambigu")):
            notes.append(text)
    return notes


def _create_project_if_authorized(project_root, path):
    if path.exists() or not os.access(str(project_root), os.W_OK):
        return False
    template = (
        "# ZAGENT.md — Aturan Kartografi Proyek\n\n"
        "Aturan desain proyek mewarisi ZAGENT.md global ArcMap.\n\n"
        "## Pengecualian desain proyek\n"
        "Belum ada pengecualian tambahan.\n\n"
        "```zagent-cartography\n{}\n```\n"
    )
    try:
        # Exclusive creation does not overwrite an independently-created file.
        with path.open("x", encoding="utf-8") as stream:
            stream.write(template)
        return True
    except (OSError, FileExistsError):
        return False


def resolve_rules(engine_root, project_root, scale_override=0):
    """Create a per-job snapshot; no caching, so changes are hot-reloaded."""
    engine_root, project_root = Path(engine_root).resolve(), Path(project_root).resolve()
    if not project_root.is_dir():
        raise CartographicRuleError("PROJECT_ROOT_NOT_FOUND")
    if any(part.lower() == "contoh layout" for part in project_root.parts):
        raise CartographicRuleError("PROTECTED_REFERENCE_NOT_PROJECT_ROOT")
    global_path = engine_root.parent / "ZAGENT.md"
    project_path = project_root / "ZAGENT.md"
    if not global_path.is_file():
        raise CartographicRuleError("GLOBAL_ARCMAP_RULES_NOT_INSTALLED")
    created = _create_project_if_authorized(project_root, project_path)
    resolved = copy.deepcopy(DEFAULTS)
    sources = []
    for layer, path in (("global", global_path), ("project", project_path)):
        if not path.exists():
            continue
        markdown, overrides, digest = _read_rules(path)
        _merge(resolved, overrides)
        sources.append({"layer": layer, "path": str(path), "sha256": digest})
        if layer == "project":
            exceptions = _unresolved_exceptions(markdown)
            if exceptions:
                raise CartographicRuleError(
                    "PROJECT_FREEFORM_EXCEPTION_NEEDS_INTERPRETATION: " +
                    " | ".join(exceptions[:6]))
    _validate(resolved)
    if type(scale_override) not in (int, float) or scale_override < 0:
        raise CartographicRuleError("INVALID_JOB_SCALE")
    if scale_override:
        if not 1000 <= float(scale_override) <= 100000000:
            raise CartographicRuleError("JOB_SCALE_OUT_OF_RANGE")
        resolved["scale"]["mode"] = "fixed"
        resolved["scale"]["requested"] = float(scale_override)
    return {"rules": resolved, "sources": sources,
            "project_file_created": created, "mode": "snapshot_per_job"}
