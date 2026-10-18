import ctypes
import os
import struct
import zlib

import win32con
import win32gui
import win32process
import win32ui


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PW_RENDERFULLCONTENT = 0x00000002
_MAX_DIMENSION = 16384
_MAX_PIXELS = 80 * 1000 * 1000


class WindowCaptureError(RuntimeError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = str(code)
        self.details = details or {}


def _process_image_path(pid):
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        raise WindowCaptureError(
            "ARCMAP_PROCESS_OPEN_FAILED",
            "Could not open ArcMap process for image-path validation.",
            {"pid": int(pid), "win32_error": int(ctypes.get_last_error() or 0)},
        )
    try:
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size))
        if not ok:
            raise WindowCaptureError(
                "ARCMAP_PROCESS_PATH_FAILED",
                "Could not resolve ArcMap process image path.",
                {"pid": int(pid), "win32_error": int(ctypes.get_last_error() or 0)},
            )
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def _main_window_for_pid(pid):
    candidates = []

    def collect(hwnd, _):
        try:
            _, owner_pid = win32process.GetWindowThreadProcessId(hwnd)
            if int(owner_pid) != int(pid) or not win32gui.IsWindowVisible(hwnd):
                return
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = max(0, int(right) - int(left))
            height = max(0, int(bottom) - int(top))
            if width <= 0 or height <= 0:
                return
            title = win32gui.GetWindowText(hwnd) or ""
            arcmap_title = 1 if "arcmap" in title.lower() else 0
            candidates.append(
                (arcmap_title, width * height, int(hwnd), title,
                 (int(left), int(top), int(right), int(bottom)))
            )
        except Exception:
            return

    win32gui.EnumWindows(collect, None)
    if not candidates:
        raise WindowCaptureError(
            "ARCMAP_WINDOW_NOT_FOUND",
            "No visible top-level ArcMap window was found for the live bridge PID.",
            {"pid": int(pid)},
        )
    candidates.sort(reverse=True)
    _, _, hwnd, title, rect = candidates[0]
    return hwnd, title, rect


def _sample_colors(bits, width, height, bpp, stride, max_samples=4096):
    bytes_per_pixel = bpp // 8
    if bytes_per_pixel not in (3, 4):
        return set()
    total = max(1, int(width) * int(height))
    step = max(1, total // max_samples)
    colors = set()
    for pixel_index in range(0, total, step):
        y = pixel_index // width
        x = pixel_index % width
        offset = y * stride + x * bytes_per_pixel
        if offset + bytes_per_pixel > len(bits):
            continue
        b = bits[offset]
        g = bits[offset + 1]
        r = bits[offset + 2]
        colors.add((r, g, b))
        if len(colors) >= 32:
            break
    return colors


def _png_chunk(chunk_type, data):
    payload = chunk_type + data
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(data))
        + payload
        + struct.pack(">I", crc)
    )


def _write_png(path, bits, width, height, bpp, stride, source_top_down=True):
    bytes_per_pixel = bpp // 8
    if bytes_per_pixel not in (3, 4):
        raise WindowCaptureError(
            "ARCMAP_WINDOW_PIXEL_FORMAT_UNSUPPORTED",
            "ArcMap window capture returned an unsupported bitmap format.",
            {"bits_per_pixel": int(bpp)},
        )

    row_size = int(width) * 3 + 1
    raw = bytearray(row_size * int(height))
    write_offset = 0

    # GetBitmapBits on the ArcMap compatible DDB arrives top-down on the
    # affected driver. The old unconditional vertical flip inverted Vision.
    # A legacy bottom-up driver can be selected explicitly when required.
    for out_y in range(int(height)):
        src_y = out_y if source_top_down else int(height) - 1 - out_y
        src_offset = src_y * int(stride)
        raw[write_offset] = 0
        write_offset += 1
        row = bits[src_offset:src_offset + int(stride)]
        for x in range(int(width)):
            offset = x * bytes_per_pixel
            raw[write_offset] = row[offset + 2]
            raw[write_offset + 1] = row[offset + 1]
            raw[write_offset + 2] = row[offset]
            write_offset += 3

    header = struct.pack(
        ">IIBBBBB",
        int(width),
        int(height),
        8,
        2,
        0,
        0,
        0,
    )
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _png_chunk(b"IEND", b"")
    )
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as stream:
        stream.write(payload)


def capture_arcmap_window(pid, output_path):
    pid = int(pid)
    if pid <= 0:
        raise WindowCaptureError(
            "ARCMAP_PID_REQUIRED",
            "Live ArcMap bridge did not provide a valid ArcMap PID.",
            {"pid": pid},
        )

    process_path = _process_image_path(pid)
    if os.path.basename(process_path).lower() != "arcmap.exe":
        raise WindowCaptureError(
            "ARCMAP_PROCESS_MISMATCH",
            "Live bridge PID does not belong to ArcMap.exe.",
            {"pid": pid, "process_path": process_path},
        )

    hwnd, title, rect = _main_window_for_pid(pid)
    if win32gui.IsIconic(hwnd):
        raise WindowCaptureError(
            "ARCMAP_WINDOW_MINIMIZED",
            "ArcMap window is minimized; restore it before window capture.",
            {"pid": pid, "hwnd": int(hwnd), "title": title},
        )

    left, top, right, bottom = rect
    width = int(right) - int(left)
    height = int(bottom) - int(top)
    if (
        width <= 0
        or height <= 0
        or width > _MAX_DIMENSION
        or height > _MAX_DIMENSION
        or width * height > _MAX_PIXELS
    ):
        raise WindowCaptureError(
            "ARCMAP_WINDOW_BOUNDS_INVALID",
            "ArcMap window dimensions are outside the safe capture bounds.",
            {"rect": list(rect), "width": width, "height": height},
        )

    window_dc = None
    source_dc = None
    memory_dc = None
    bitmap = None
    bits = None
    info = None
    method = "PrintWindow"

    try:
        window_dc = win32gui.GetWindowDC(hwnd)
        if not window_dc:
            raise WindowCaptureError(
                "ARCMAP_WINDOW_DC_FAILED",
                "Could not acquire the ArcMap window device context.",
                {"pid": pid, "hwnd": int(hwnd)},
            )

        source_dc = win32ui.CreateDCFromHandle(window_dc)
        memory_dc = source_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(source_dc, width, height)
        memory_dc.SelectObject(bitmap)

        print_ok = int(
            ctypes.windll.user32.PrintWindow(
                int(hwnd),
                int(memory_dc.GetSafeHdc()),
                PW_RENDERFULLCONTENT,
            )
        )
        bits = bitmap.GetBitmapBits(True)
        info = bitmap.GetInfo()
        bpp = int(info.get("bmBitsPixel") or 0)
        stride = int(info.get("bmWidthBytes") or 0)
        colors = _sample_colors(bits, width, height, bpp, stride)

        if not print_ok or len(colors) < 4:
            memory_dc.BitBlt(
                (0, 0),
                (width, height),
                source_dc,
                (0, 0),
                win32con.SRCCOPY,
            )
            bits = bitmap.GetBitmapBits(True)
            info = bitmap.GetInfo()
            bpp = int(info.get("bmBitsPixel") or 0)
            stride = int(info.get("bmWidthBytes") or 0)
            colors = _sample_colors(bits, width, height, bpp, stride)
            method = "BitBltFallback"

        if len(colors) < 4:
            raise WindowCaptureError(
                "ARCMAP_WINDOW_CAPTURE_BLANK",
                "ArcMap window capture produced an effectively blank image.",
                {
                    "pid": pid,
                    "hwnd": int(hwnd),
                    "method": method,
                    "sample_color_count": len(colors),
                },
            )

        row_order = (os.environ.get("ZAGENT_ARCMAP_CAPTURE_ROW_ORDER") or "top-down").strip().lower()
        if row_order not in ("top-down", "bottom-up"):
            raise WindowCaptureError("ARCMAP_ROW_ORDER_INVALID", "Expected top-down or bottom-up")
        _write_png(
            output_path,
            bits,
            width,
            height,
            int(info.get("bmBitsPixel") or 0),
            int(info.get("bmWidthBytes") or 0),
            source_top_down=(row_order == "top-down"),
        )
    finally:
        if memory_dc is not None:
            try:
                memory_dc.DeleteDC()
            except Exception:
                pass
        if source_dc is not None:
            try:
                source_dc.DeleteDC()
            except Exception:
                pass
        if window_dc:
            try:
                win32gui.ReleaseDC(hwnd, window_dc)
            except Exception:
                pass
        if bitmap is not None:
            try:
                win32gui.DeleteObject(bitmap.GetHandle())
            except Exception:
                pass

    return {
        "pid": pid,
        "hwnd": int(hwnd),
        "title": title,
        "process_path": process_path,
        "rect": [left, top, right, bottom],
        "dimensions": [width, height],
        "method": method,
        "visible": bool(win32gui.IsWindowVisible(hwnd)),
        "minimized": bool(win32gui.IsIconic(hwnd)),
        "bytes": os.path.getsize(output_path),
        "pixel_format_bpp": int(info.get("bmBitsPixel") or 0),
        "source_row_order": row_order,
        "png_row_order": "top-down",
    }
