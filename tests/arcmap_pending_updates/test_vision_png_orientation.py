"""Unit regression for ArcMap Vision bitmap vertical orientation.

No real ArcMap window, GDI calls or capture is performed. Tests NOT RUN.
"""
import importlib.util
import os
import struct
import sys
import tempfile
import types
import unittest
import zlib
from unittest.mock import patch


_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_CAPTURE = os.path.join(_ROOT, "agents", "arcmap", "engine",
                        "mcp_server", "window_capture.py")


def load_capture():
    fake_win32 = {
        name: types.ModuleType(name) for name in
        ("win32con", "win32gui", "win32process", "win32ui")
    }
    with patch.dict(sys.modules, fake_win32):
        spec = importlib.util.spec_from_file_location("unit_arcmap_window_capture", _CAPTURE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def png_rgb_rows(path):
    with open(path, "rb") as handle:
        data = handle.read()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    offset = 8
    width, height = None, None
    encoded = []
    while offset < len(data):
        size = struct.unpack(">I", data[offset:offset + 4])[0]
        code = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + size]
        offset += size + 12
        if code == b"IHDR":
            width, height = struct.unpack(">II", payload[:8])
        elif code == b"IDAT":
            encoded.append(payload)
        elif code == b"IEND":
            break
    unpacked = zlib.decompress(b"".join(encoded))
    stride = width * 3 + 1
    assert len(unpacked) == stride * height
    rows = []
    for i in range(height):
        row = unpacked[i * stride:(i + 1) * stride]
        assert row[0] == 0  # PNG filter type 0.
        rows.append(row[1:])
    return width, height, rows


class ArcMapVisionOrientationUnits(unittest.TestCase):
    def setUp(self):
        self.module = load_capture()

    def capture(self, bits, top_down=True, width=1, height=2, bpp=24, stride=4):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "orientation.png")
            self.module._write_png(path, bits, width, height, bpp, stride,
                                   source_top_down=top_down)
            return png_rgb_rows(path)

    def test_default_top_down_does_not_flip_red_over_green(self):
        # Two 24bpp BGR rows with a padding byte, top red and bottom green.
        bits = bytes([0, 0, 255, 0, 0, 255, 0, 0])
        w, h, rows = self.capture(bits)
        self.assertEqual((1, 2), (w, h))
        self.assertEqual(bytes([255, 0, 0]), rows[0])
        self.assertEqual(bytes([0, 255, 0]), rows[1])

    def test_bottom_up_driver_setting_reverses_rows_once(self):
        bits = bytes([0, 255, 0, 0, 0, 0, 255, 0])
        _, _, rows = self.capture(bits, top_down=False)
        self.assertEqual(bytes([255, 0, 0]), rows[0])
        self.assertEqual(bytes([0, 255, 0]), rows[1])

    def test_32bpp_bgra_pixel_conversion(self):
        bits = bytes([20, 30, 40, 255, 100, 110, 120, 255])
        _, _, rows = self.capture(bits, width=2, height=1, bpp=32, stride=8)
        self.assertEqual(bytes([40, 30, 20, 120, 110, 100]), rows[0])

    def test_unsupported_bpp_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(self.module.WindowCaptureError) as context:
                self.module._write_png(os.path.join(folder, "bad.png"),
                                       b"\0" * 8, 1, 2, 16, 4)
            self.assertEqual("ARCMAP_WINDOW_PIXEL_FORMAT_UNSUPPORTED",
                             context.exception.code)

    def test_png_row_order_has_no_rotate_or_horizontal_mirror(self):
        # Pixel A (red) left; pixel B (blue) right.
        bits = bytes([0, 0, 255, 255, 0, 0, 0, 0])
        width, height, rows = self.capture(bits, width=2, height=1, stride=8)
        self.assertEqual((2, 1), (width, height))
        self.assertEqual(bytes([255, 0, 0, 0, 0, 255]), rows[0])


if __name__ == "__main__":
    unittest.main()
