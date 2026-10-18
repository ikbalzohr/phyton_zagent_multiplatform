from __future__ import annotations

import math
import os
from copy import deepcopy

from .vision_feedback import normalize_visual_feedback

try:
    from PIL import Image, ImageStat
except Exception:  # optional runtime capability
    Image = None
    ImageStat = None


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, float(value)))


def _box_pixels(box, width, height):
    box = box or {}
    x = int(round(_clamp(box.get("x") or 0) * width))
    y_norm = _clamp(box.get("y") or 0)
    w = int(round(_clamp(box.get("w") or 0) * width))
    h = int(round(_clamp(box.get("h") or 0) * height))
    # Cartographic normalized coordinates use bottom-left origin while PIL uses top-left.
    y = int(round((1.0 - y_norm - _clamp(box.get("h") or 0)) * height))
    x2 = max(x + 1, min(width, x + max(1, w)))
    y2 = max(y + 1, min(height, y + max(1, h)))
    return (max(0, x), max(0, y), x2, y2)


def _sample_ratio(image, predicate, max_side=512):
    if Image is None:
        return None
    img = image.convert("RGB")
    w, h = img.size
    scale = min(1.0, float(max_side) / float(max(w, h)))
    if scale < 1.0:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    pixels = list(img.getdata())
    if not pixels:
        return 0.0
    count = sum(1 for pixel in pixels if predicate(pixel))
    return float(count) / float(len(pixels))


def _mean_abs_similarity(a, b, size=(128, 128)):
    if Image is None:
        return None
    a = a.convert("RGB").resize(size)
    b = b.convert("RGB").resize(size)
    pa = list(a.getdata())
    pb = list(b.getdata())
    if not pa or len(pa) != len(pb):
        return None
    total = 0.0
    for left, right in zip(pa, pb):
        total += (
            abs(int(left[0]) - int(right[0]))
            + abs(int(left[1]) - int(right[1]))
            + abs(int(left[2]) - int(right[2]))
        ) / 765.0
    mean = total / float(len(pa))
    return _clamp(1.0 - mean)


def _edge_color_ratio(image, predicate, thickness_ratio=0.025):
    if Image is None:
        return None
    img = image.convert("RGB")
    w, h = img.size
    thickness = max(1, int(round(min(w, h) * thickness_ratio)))
    strips = [
        img.crop((0, 0, w, thickness)),
        img.crop((0, max(0, h - thickness), w, h)),
        img.crop((0, 0, thickness, h)),
        img.crop((max(0, w - thickness), 0, w, h)),
    ]
    weighted = 0.0
    total_pixels = 0
    for strip in strips:
        pixels = list(strip.getdata())
        total_pixels += len(pixels)
        weighted += sum(1 for pixel in pixels if predicate(pixel))
    return float(weighted) / float(total_pixels or 1)


class RenderedImageInspector:
    """
    Lightweight pixel-level cartographic QA. This is not a substitute for a
    multimodal reasoner, but it provides deterministic evidence between render
    cycles and can trigger bounded repair without human intervention.
    """

    def available(self):
        return Image is not None

    def inspect(self, preview_path, specification, reference_image=None):
        spec = deepcopy(specification or {})
        if Image is None:
            return {
                "ok": False,
                "available": False,
                "status": "UNAVAILABLE",
                "feedback": normalize_visual_feedback({
                    "observations": ["Pillow is unavailable; pixel-level QA skipped."],
                }),
            }
        if not preview_path or not os.path.isfile(str(preview_path)):
            return {
                "ok": False,
                "available": True,
                "status": "PREVIEW_NOT_FOUND",
                "feedback": normalize_visual_feedback({
                    "observations": ["Rendered preview path was not found."],
                }),
            }

        with Image.open(str(preview_path)) as src:
            image = src.convert("RGB")
            width, height = image.size
            reference = spec.get("reference_target") or {}
            regions = reference.get("regions") or {}
            main_box = regions.get("main_map") or ((spec.get("layout") or {}).get("main_map") or {})
            panel_box = regions.get("side_panel") or ((spec.get("layout") or {}).get("side_panel") or {})
            main = image.crop(_box_pixels(main_box, width, height))
            panel = image.crop(_box_pixels(panel_box, width, height))

            whitespace = _sample_ratio(
                main,
                lambda p: p[0] >= 242 and p[1] >= 242 and p[2] >= 242,
            )
            project_red = _sample_ratio(
                main,
                lambda p: p[0] >= 180 and p[1] <= 110 and p[2] <= 110,
            )
            river_cyan = _sample_ratio(
                main,
                lambda p: p[0] <= 130 and p[1] >= 120 and p[2] >= 150,
            )
            road_light = _sample_ratio(
                main,
                lambda p: abs(p[0] - p[1]) <= 18 and abs(p[1] - p[2]) <= 18 and 165 <= p[0] <= 245,
            )
            panel_white = _sample_ratio(
                panel,
                lambda p: p[0] >= 238 and p[1] >= 238 and p[2] >= 238,
            )
            page_green = _edge_color_ratio(
                image,
                lambda p: p[1] >= 220 and p[0] >= 160 and p[0] <= 235 and p[2] >= 145 and p[2] <= 225,
            )

            similarity = None
            if reference_image and os.path.isfile(str(reference_image)):
                try:
                    with Image.open(str(reference_image)) as ref:
                        similarity = _mean_abs_similarity(image, ref)
                except Exception:
                    similarity = None

        issues = []
        observations = []
        qa = spec.get("qa") or {}
        roles = set(
            str(row.get("semantic_role") or "")
            for row in (spec.get("semantic_layers") or [])
        )

        if whitespace is not None and whitespace > float(qa.get("max_whitespace_ratio") or 0.18):
            issues.append({
                "code": "WHITESPACE_EXCESSIVE",
                "severity": "warning",
                "actual": round(whitespace, 4),
            })
        if project_red is not None and project_red < 0.00025:
            issues.append({
                "code": "PROJECT_BOUNDARY_NOT_VISIBLE",
                "severity": "error",
                "actual_red_pixel_ratio": round(project_red, 6),
            })
        if "river" in roles and river_cyan is not None and river_cyan < 0.0001:
            issues.append({
                "code": "RIVER_LOW_CONTRAST",
                "severity": "warning",
                "actual_cyan_pixel_ratio": round(river_cyan, 6),
            })
        if "road" in roles and road_light is not None and road_light < 0.0001:
            issues.append({
                "code": "ROAD_LOW_CONTRAST",
                "severity": "warning",
                "actual_light_road_pixel_ratio": round(road_light, 6),
            })
        if panel_white is not None and panel_white < 0.55:
            issues.append({
                "code": "REFERENCE_LAYOUT_MISMATCH",
                "severity": "warning",
                "reason": "side_panel_not_predominantly_white",
                "actual": round(panel_white, 4),
            })
        if similarity is not None:
            minimum_pixel = float(qa.get("min_pixel_reference_similarity") or 0.0)
            if minimum_pixel and similarity < minimum_pixel:
                issues.append({
                    "code": "REFERENCE_LAYOUT_MISMATCH",
                    "severity": "warning",
                    "reason": "low_pixel_similarity",
                    "actual": round(similarity, 4),
                    "minimum": minimum_pixel,
                })

        metrics = {
            "label_overlap_ratio": None,
            "whitespace_ratio": whitespace,
            "project_boundary_contrast": project_red,
            "road_readability": road_light,
            "river_readability": river_cyan,
            "legend_readability": panel_white,
            "title_readability": panel_white,
            "inset_readability": panel_white,
            "grid_readability": None,
            "panel_balance": panel_white,
            "reference_similarity": similarity,
            "page_background_signal": page_green,
            "preview_width": width,
            "preview_height": height,
        }

        penalties = 0.0
        for issue in issues:
            penalties += 0.16 if issue.get("severity") == "error" else 0.06
        if similarity is not None:
            score = 0.25 * _clamp(similarity) + 0.75 * max(0.0, 1.0 - penalties)
        else:
            score = max(0.0, 1.0 - penalties)

        feedback = normalize_visual_feedback({
            "score": _clamp(score),
            "issues": issues,
            "metrics": metrics,
            "observations": observations,
        })
        return {
            "ok": True,
            "available": True,
            "status": "ANALYZED",
            "preview_path": str(preview_path),
            "reference_image": str(reference_image or "") or None,
            "feedback": feedback,
            "metrics": metrics,
        }
