from __future__ import annotations

import unittest

from stitch_studio.rendering.timeline_renderer import output_dimensions, sanitize_export_filename


class TimelineExportSettingsTest(unittest.TestCase):
    def test_resolution_and_aspect_mapping(self) -> None:
        canvas = {"width": 1080, "height": 1920}
        self.assertEqual(output_dimensions("1080p", "16:9", canvas), (1920, 1080))
        self.assertEqual(output_dimensions("1080p", "9:16", canvas), (1080, 1920))
        self.assertEqual(output_dimensions("1080p", "1:1", canvas), (1080, 1080))
        self.assertEqual(output_dimensions("720p", "16:9", canvas), (1280, 720))
        self.assertEqual(output_dimensions("4K", "16:9", canvas), (3840, 2160))

    def test_project_aspect_uses_canvas_ratio(self) -> None:
        self.assertEqual(output_dimensions("1080p", "project", {"width": 1080, "height": 1920}), (1080, 1920))
        self.assertEqual(output_dimensions("720p", "project", {"width": 1000, "height": 1000}), (720, 720))

    def test_filename_sanitize_blocks_paths(self) -> None:
        self.assertEqual(sanitize_export_filename(r"..\bad/name?.mp4"), "bad name")
        with self.assertRaises(ValueError):
            sanitize_export_filename("...")


if __name__ == "__main__":
    unittest.main()
