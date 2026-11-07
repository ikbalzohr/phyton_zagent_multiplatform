"""Independent structural preflight for ArcMap 10.6 PDF/PNG exports.

Standard library only; checks PDF page box / count, PNG IHDR, and matching
requested A4 landscape at DPI. Not a rasterized PDF or visual cartographic QA.
"""
from __future__ import annotations
import os
import re
import struct

A4_LANDSCAPE_MM = (297.0, 210.0)
_MEDIA_BOX = re.compile(rb'/MediaBox\s*\[\s*([-+\d.]+)\s+([-+\d.]+)\s+([-+\d.]+)\s+([-+\d.]+)\s*\]')
_PAGE = re.compile(rb'/Type\s*/Page\b')
_PNG = b'\x89PNG\r\n\x1a\n'


def validate_pdf_png(pdf_path: str, png_path: str, dpi: int = 400) -> dict:
    errors = []
    warnings = [
        'Visual QA is still required for grid, labels, insets, raster detail, '
        'font embedding, bleed and physical printer margins.'
    ]
    metrics = {}
    if not (isinstance(dpi, int) and 150 <= dpi <= 600):
        return {'ok': False, 'errors': ['DPI_OUT_OF_RANGE'], 'warnings': warnings}
    try:
        if not os.path.isfile(pdf_path) or not os.path.isfile(png_path):
            return {'ok': False, 'errors': ['EXPORT_FILE_MISSING'],
                    'warnings': warnings}
        with open(pdf_path, 'rb') as handle:
            pdf = handle.read()
        if not pdf.startswith(b'%PDF-'):
            errors.append('PDF_HEADER_INVALID')
        if b'%%EOF' not in pdf[-1024:]:
            errors.append('PDF_EOF_MISSING')
        boxes = _MEDIA_BOX.findall(pdf)
        if len(boxes) != 1:
            errors.append('PDF_MEDIABOX_AMBIGUOUS_OR_MISSING')
        else:
            x0, y0, x1, y1 = [float(item) for item in boxes[0]]
            width = (x1 - x0) * 25.4 / 72.0
            height = (y1 - y0) * 25.4 / 72.0
            metrics['pdf_page_mm'] = [round(width, 3), round(height, 3)]
            if abs(width - A4_LANDSCAPE_MM[0]) > 1.0 or abs(height - A4_LANDSCAPE_MM[1]) > 1.0:
                errors.append('PDF_PAGE_NOT_A4_LANDSCAPE')
        pages = len(_PAGE.findall(pdf))
        metrics['pdf_page_count'] = pages
        if pages != 1:
            errors.append('PDF_NOT_SINGLE_PAGE')
        metrics['pdf_size_bytes'] = len(pdf)
        if len(pdf) < 4096:
            errors.append('PDF_TOO_SMALL')
        with open(png_path, 'rb') as handle:
            header = handle.read(64)
        if len(header) < 24 or header[:8] != _PNG or header[12:16] != b'IHDR':
            errors.append('PNG_HEADER_INVALID')
        else:
            w, h = struct.unpack('>II', header[16:24])
            metrics['png_dimensions_px'] = [w, h]
            expected_w = A4_LANDSCAPE_MM[0] * dpi / 25.4
            expected_h = A4_LANDSCAPE_MM[1] * dpi / 25.4
            tolerance = max(12.0, dpi * 0.02)
            if abs(w - expected_w) > tolerance or abs(h - expected_h) > tolerance:
                errors.append('PNG_DPI_OR_PAGE_MISMATCH')
        metrics['png_size_bytes'] = os.path.getsize(png_path)
        if metrics['png_size_bytes'] < 4096:
            errors.append('PNG_TOO_SMALL')
    except (OSError, ValueError, struct.error, OverflowError) as exc:
        errors.append('STRUCTURAL_QA_READ_FAILED: ' + str(exc))
    return {
        'ok': not errors,
        'structural_qa_pass': not errors,
        'print_ready_accepted': False,
        'errors': errors,
        'warnings': warnings,
        'metrics': metrics,
        'requested_dpi': dpi,
    }
