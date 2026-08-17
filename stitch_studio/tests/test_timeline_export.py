from __future__ import annotations

import unittest

from stitch_studio.rendering.timeline_renderer import output_dimensions, sanitize_export_filename
from stitch_studio.rendering.subtitle_ass_generator import generate_ass_file, CSS_PX_TO_ASS_PT, resolve_font_family
import tempfile
from pathlib import Path


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

    def test_ass_file_font_scaling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "test.ass"
            generate_ass_file(
                out_path=ass_path,
                timeline_width=1920,
                timeline_height=1080,
                project_canvas_height=1080,
                srt_events=[(0.0, 5.0, "Hello World")],
                text_events=[{
                    "start": 1.0,
                    "end": 4.0,
                    "text": "Header Text",
                    "style": {"fontSize": 60, "fontFamily": "Inter", "fontWeight": 900},
                    "x": 0.5,
                    "y": 0.3
                }],
                global_style={"fontSize": 50, "fontFamily": "Inter", "fontWeight": 800},
                subtitle_area={"xmin": 0.05, "xmax": 0.95, "ymin": 0.6, "ymax": 0.95}
            )
            content = ass_path.read_text(encoding="utf-8")
            # Font size 50 with CSS_PX_TO_ASS_PT (96/72) = 66.67
            expected_subtitle_size = f"{50.0 * CSS_PX_TO_ASS_PT:.2f}"
            expected_text_size = f"{60.0 * CSS_PX_TO_ASS_PT:.2f}"
            self.assertIn(expected_subtitle_size, content)
            self.assertIn(f"\\fs{expected_text_size}", content)
            self.assertIn("Dialogue: 0,", content)
            self.assertIn("Dialogue: 1,", content)


if __name__ == "__main__":
    unittest.main()

