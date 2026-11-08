"""Independent ArcMap print-export acceptance (PyMuPDF + Pillow; no ArcPy).

Invocation example:
 python maintenance/arcmap_print_ready_pdf_qa.py --job-dir PATH --vendor PATH --visual-reviewed

The export tool never self-certifies cartography. This independent step
re-renders the PDF, checks embedded fonts, scales, grids, typography and margins.
Only an explicitly reviewed run can mark an acceptance report as accepted.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect(job_dir: Path, dpi=400, visual_reviewed=False):
    try:
        import fitz
        from PIL import Image, ImageChops, ImageStat
    except ImportError as exc:
        return {"ok": False, "errors": ["PDF_RENDER_DEPENDENCY_MISSING: " + str(exc)],
                "print_ready_accepted": False}

    report_path = job_dir / "print_ready_report.json"
    errors, warnings, metrics = [], [], {}
    if not report_path.is_file():
        return {"ok": False, "errors": ["SOURCE_PRINT_REPORT_MISSING"],
                "print_ready_accepted": False}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    exported = report.get("exports") or {}
    pdf = Path((exported.get("PDF") or {}).get("path") or "")
    png = Path((exported.get("PNG") or {}).get("path") or "")
    if (not pdf.is_file() or not png.is_file() or
            pdf.resolve().parent != job_dir.resolve() or
            png.resolve().parent != job_dir.resolve()):
        return {"ok": False, "errors": ["REPORT_EXPORT_PATH_INVALID"],
                "print_ready_accepted": False}
    if not report.get("original_unchanged"):
        errors.append("ORIGINAL_MXD_NOT_VERIFIED")
    original = Path(report.get("original_mxd", ""))
    if not original.is_file() or _sha256(original) != report.get("original_sha256"):
        errors.append("ORIGINAL_MXD_HASH_CHANGED")
    qa = report.get("qa") or {}
    if int(round(float(qa.get("scale", 0)))) != 70000:
        errors.append("MAP_SCALE_NOT_70000")
    if qa.get("crs") != "WGS_1984_UTM_Zone_51N":
        errors.append("MAIN_CRS_MISMATCH")
    frames = qa.get("frames") or []
    if len(frames) != 3 or not all("scale" in item for item in frames):
        errors.append("THREE_FRAMES_NOT_VERIFIED")
    if qa.get("broken_sources") or qa.get("outside_page") or qa.get("small_fonts"):
        errors.append("ARCMAP_SOURCE_PREFLIGHT_FAILED")

    try:
        with __import__("fitz").open(str(pdf)) as doc:
            if len(doc) != 1:
                errors.append("PDF_PAGE_COUNT")
            page = doc[0]
            width_mm = page.rect.width * 25.4 / 72
            height_mm = page.rect.height * 25.4 / 72
            metrics["page_mm"] = [round(width_mm, 2), round(height_mm, 2)]
            if abs(width_mm - 297) > 1.2 or abs(height_mm - 210) > 1.2:
                errors.append("PDF_NOT_A4_LANDSCAPE")
            words = page.get_text("words")
            text_content = page.get_text("text")
            metrics["word_count"] = len(words)
            required = ("PETA ADMINISTRASI", "PT BUOL AGRI LESTARI",
                        "Transverse Mercator", "Sumber Data dan Riwayat Peta",
                        "LEGENDA", "SKALA 1 : 3.500.000",
                        "SKALA 1 : 23.000.000")
            for token in required:
                if token not in text_content:
                    errors.append("PDF_TEXT_MISSING: " + token)
            if text_content.count("INSET PETA") != 2:
                errors.append("INSET_TITLES_NOT_TWO")

            for name, pattern, lower, upper in (
                ("longitude", r"121\u00b0(\d{1,2})'0\"E", 20, 35),
                ("latitude", r"1\u00b0(\d{1,2})'0\"N", 1, 15),
            ):
                series = sorted({int(t) for t in re.findall(pattern, text_content)
                                 if lower <= int(t) <= upper})
                metrics["main_grid_" + name + "_minutes"] = series
                if len(series) < 5 or any((b-a) != 1 for a, b in zip(series, series[1:])):
                    errors.append("GRID_NUMERIC_INTERVAL_INVALID_" + name.upper())

            if words:
                margins = [min(w[0], w[1], page.rect.width - w[2],
                               page.rect.height - w[3]) for w in words]
                metrics["minimum_text_margin_pt"] = round(min(margins), 2)
                if min(margins) + 0.35 < 5.0 * 72.0 / 25.4:
                    errors.append("PRINTER_TEXT_MARGIN_UNSAFE")
            else:
                errors.append("PDF_TEXT_NOT_SELECTABLE")

            crs_left = [word for word in words if word[4] == "System" and
                        0.47 * page.rect.width < word[0] < 0.9 * page.rect.width]
            crs_values = [word for word in words if word[4] == "WGS" and
                          0.7 * page.rect.width < word[0] < 0.95 * page.rect.width]
            same_line = [(v[0] - k[2]) for k in crs_left for v in crs_values
                         if abs(v[1] - k[1]) <= 3]
            if not same_line or min(same_line) < 8.0:
                errors.append("CRS_COLUMNS_COLLIDE")
            else:
                metrics["crs_column_gap_pt"] = round(min(same_line), 2)

            embedded = []
            for font in page.get_fonts(full=True):
                try:
                    data = doc.extract_font(font[0])[3]
                    embedded.append({"name": font[3], "bytes": len(data)})
                except Exception:
                    embedded.append({"name": font[3], "bytes": 0})
            metrics["embedded_fonts"] = embedded
            if not embedded or any(font["bytes"] < 1024 for font in embedded):
                errors.append("FONT_NOT_EMBEDDED")

            factor = 1.8
            out = job_dir / "independent_pdf_render.png"
            page.get_pixmap(matrix=fitz.Matrix(factor, factor), alpha=False).save(str(out))
        pdf_img = Image.open(str(out)).convert("RGB")
        arc_img = Image.open(str(png)).convert("RGB").resize(
            pdf_img.size, Image.Resampling.LANCZOS)
        channels = [round(value, 2) for value in
                    ImageStat.Stat(ImageChops.difference(pdf_img, arc_img)).mean]
        metrics["pdf_png_mae_rgb"] = channels
        metrics["independent_render"] = str(out)
        if max(channels) > 12.0:
            errors.append("PDF_PNG_RENDER_PARITY_FAILED")
        preview = job_dir / "independent_pdf_preview.jpg"
        width = 1400
        pdf_img.resize((width, round(pdf_img.height * width / pdf_img.width)),
                       Image.Resampling.LANCZOS).save(str(preview), quality=85)
        metrics["preview"] = str(preview)
    except Exception as exc:
        errors.append("INDEPENDENT_PDF_QA_FAILED: " + str(exc))

    warnings.append("Underlying dataset attribution was not externally fact-checked.")
    warnings.append("Physical printer color profile, feed and ink proof remain device-dependent.")
    automated_pass = not errors
    accepted = automated_pass and bool(visual_reviewed)
    outcome = {"ok": automated_pass, "automated_qa_pass": automated_pass,
               "visual_reviewed": bool(visual_reviewed),
               "print_ready_accepted": accepted,
               "errors": errors, "warnings": warnings, "metrics": metrics,
               "input_pdf_sha256": _sha256(pdf), "input_png_sha256": _sha256(png)}
    (job_dir / "independent_print_acceptance.json").write_text(
        json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
    return outcome


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", required=True, type=Path)
    parser.add_argument("--vendor", type=Path)
    parser.add_argument("--dpi", type=int, default=400)
    parser.add_argument("--visual-reviewed", action="store_true")
    args = parser.parse_args()
    if args.vendor:
        sys.path.insert(0, str(args.vendor))
    result = inspect(args.job_dir, args.dpi, args.visual_reviewed)
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result.get("print_ready_accepted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
