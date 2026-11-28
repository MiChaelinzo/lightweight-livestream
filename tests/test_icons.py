import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools import generate_icons


class GeneratedIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = generate_icons.generated_files()

    def file(self, suffix):
        return next(data for path, data in self.files.items() if path.endswith(suffix))

    def test_tracked_icons_match_the_stdlib_generator(self):
        self.assertEqual(generate_icons.main(["--check"]), 0)

    def test_png_dimensions_and_formats_cover_install_metadata(self):
        expected = {
            "icon-192.png": (192, 192),
            "icon-512.png": (512, 512),
            "maskable-512.png": (512, 512),
            "apple-touch-icon-180.png": (180, 180),
        }
        for name, dimensions in expected.items():
            with self.subTest(name=name):
                data = self.file(name)
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(struct.unpack(">II", data[16:24]), dimensions)

    def test_desktop_containers_have_expected_headers(self):
        ico = self.file("lightstream.ico")
        self.assertEqual(struct.unpack("<HHH", ico[:6]), (0, 1, 6))
        icns = self.file("lightstream.icns")
        self.assertEqual(icns[:4], b"icns")
        self.assertEqual(struct.unpack(">I", icns[4:8])[0], len(icns))
        self.assertIn(b"ic10", icns)

    def test_svg_is_self_contained_and_web_icons_stay_small(self):
        svg = self.file(os.path.join("assets", "icons", "lightstream.svg"))
        self.assertIn(b"LightStream broadcast mark", svg)
        self.assertNotIn(b"<script", svg)
        self.assertNotIn(b"href=", svg)
        web_png_bytes = sum(len(data) for path, data in self.files.items()
                            if path.startswith(generate_icons.WEB_DIR) and path.endswith(".png"))
        self.assertLess(web_png_bytes, 70 * 1024)


if __name__ == "__main__":
    unittest.main()
