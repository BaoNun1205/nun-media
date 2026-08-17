import unittest
from types import SimpleNamespace
from stitch_studio.rendering.timeline_renderer import (
    output_dimensions,
    sanitize_export_filename,
    _primary_subtitle_style,
    _primary_subtitle_area,
    RenderContext,
)
from stitch_studio.rendering.subtitle_ass_generator import generate_ass_file, resolve_font_family
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

    def test_primary_subtitle_style_and_area_from_workspace_project(self) -> None:
        project_meta = {
            "subtitle_style": {"fontFamily": "Impact", "fontSize": 54, "outline": 7, "fontColor": "#ffffff", "outlineColor": "#000000"},
            "subtitle_area": {"xmin": 0.10, "xmax": 0.90, "ymin": 0.50, "ymax": 0.85},
        }
        mock_proj = SimpleNamespace(id=1, metadata=project_meta)
        ctx = RenderContext(
            project=mock_proj,
            timeline_state={},
            width=1920,
            height=1080,
            fps=30,
            duration=10.0,
            output_path=Path("dummy.mp4"),
            tracks=[],
            items=[],
            storage=None,
            temp_dir=Path("."),
            primary_video=None,
        )

        style = _primary_subtitle_style(ctx)
        self.assertEqual(style.get("fontFamily"), "Impact")
        self.assertEqual(style.get("outline"), 7)
        self.assertEqual(style.get("fontColor"), "#ffffff")

        area = _primary_subtitle_area(ctx)
        self.assertAlmostEqual(area["xmin"], 0.10)
        self.assertAlmostEqual(area["xmax"], 0.90)
        self.assertAlmostEqual(area["ymin"], 0.50)
        self.assertAlmostEqual(area["ymax"], 0.85)

    def test_ass_file_preset_and_position_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "test.ass"
            # White / Black Outline preset style
            preset_style = {
                "fontFamily": "Segoe UI",
                "fontSize": 50,
                "fontColor": "#ffffff",
                "outlineColor": "#000000",
                "outline": 7,
                "fontWeight": 900,
            }
            # Custom area at 40%-75% of height
            custom_area = {"xmin": 0.08, "xmax": 0.92, "ymin": 0.40, "ymax": 0.75}

            generate_ass_file(
                out_path=ass_path,
                timeline_width=1920,
                timeline_height=1080,
                project_canvas_height=1080,
                srt_events=[(0.0, 5.0, "In the middle of my final state graduation exam, I")],
                text_events=[],
                global_style=preset_style,
                subtitle_area=custom_area,
            )
            content = ass_path.read_text(encoding="utf-8")
            
            # 1. Check style header: font, size, bold (-1), outline=7.00, primary colour white, outline colour black
            self.assertIn("Style: Default,Segoe UI,50.00,&H00ffffff,&H000000FF,&H00000000,&HFFFFFFFF,-1,0,0,0,100,100,0.00,0,1,7.00,0.00,2,153,153,270,1", content)
            
            # 2. Check margins based on custom_area:
            # margin_l = 0.08 * 1920 = 153
            # margin_r = 1920 - (0.92 * 1920) = 153
            # margin_v = 1080 - (0.75 * 1080) = 270
            self.assertIn(",153,153,270,1", content)
            
            # 3. Check dialogue event text
            self.assertIn("Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,", content)

    def test_ass_file_exports_timeline_text_style_and_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "text.ass"
            generate_ass_file(
                out_path=ass_path,
                timeline_width=1920,
                timeline_height=1080,
                project_canvas_height=1080,
                srt_events=[],
                text_events=[{
                    "start": 1.0,
                    "end": 4.5,
                    "text": "edited title",
                    "x": 0.25,
                    "y": 0.40,
                    "style": {
                        "fontFamily": "Impact",
                        "fontSize": 64,
                        "fontColor": "#ff3338",
                        "outlineColor": "#ffffff",
                        "outline": 6,
                        "fontWeight": "bold",
                        "textTransform": "uppercase",
                        "backgroundEnabled": True,
                        "backgroundColor": "#000000",
                        "backgroundOpacity": 0.75,
                    },
                }],
                global_style={},
                subtitle_area={},
            )
            content = ass_path.read_text(encoding="utf-8")

            self.assertIn("Style: Text1,Impact,64.00,&H003833ff,&H000000FF,&H00ffffff,&H3F000000,-1,0,0,0,100,100,0.00,0,3,6.00", content)
            self.assertIn("Dialogue: 1,0:00:01.00,0:00:04.50,Text1,,0,0,0,,{\\an5\\pos(480,432)}EDITED TITLE", content)

    def test_ass_file_text_weight_accepts_normal_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "normal.ass"
            generate_ass_file(
                out_path=ass_path,
                timeline_width=1280,
                timeline_height=720,
                project_canvas_height=720,
                srt_events=[],
                text_events=[{"start": 0, "end": 1, "text": "Normal", "style": {"fontWeight": "normal"}}],
                global_style={},
                subtitle_area={},
            )
            content = ass_path.read_text(encoding="utf-8")
            self.assertIn("Style: Text1,", content)
            self.assertIn(",0,0,0,0,100,100,", content)

    def test_ass_file_exports_static_text_effect_layers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "effect.ass"
            generate_ass_file(
                out_path=ass_path,
                timeline_width=1920,
                timeline_height=1080,
                project_canvas_height=1080,
                srt_events=[],
                text_events=[{
                    "start": 0,
                    "end": 2,
                    "text": "FX",
                    "x": 0.5,
                    "y": 0.5,
                    "style": {"staticEffect": "duotone", "secondaryOutlineColor": "#e02a34"},
                }],
                global_style={},
                subtitle_area={},
            )
            content = ass_path.read_text(encoding="utf-8")
            self.assertIn("Dialogue: 0,0:00:00.00,0:00:02.00,Text1,,0,0,0,,{\\an5\\pos(964,542)\\c&H00342ae0\\bord0\\shad0}FX", content)
            self.assertIn("Dialogue: 1,0:00:00.00,0:00:02.00,Text1,,0,0,0,,{\\an5\\pos(960,540)}FX", content)


if __name__ == "__main__":
    unittest.main()
