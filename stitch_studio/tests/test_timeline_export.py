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

    def test_req1_montserrat_bold_outline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "montserrat.ass"
            style = {
                "fontFamily": "Montserrat",
                "fontWeight": 900,
                "fontSize": 60,
                "fontColor": "#ffffff",
                "outlineColor": "#000000",
                "outlineWidth": 5,
            }
            generate_ass_file(
                out_path=ass_path,
                timeline_width=1920,
                timeline_height=1080,
                project_canvas_height=1080,
                srt_events=[{"start": 0, "end": 3, "text": "Montserrat Subtitle", "style": style}],
                text_events=[],
                global_style=style,
                subtitle_area={"xmin": 0.05, "xmax": 0.95, "ymin": 0.70, "ymax": 0.95},
            )
            content = ass_path.read_text(encoding="utf-8")
            self.assertIn("Style: Default,Montserrat,60.00,&H00ffffff,&H000000FF,&H00000000,&HFFFFFFFF,-1", content)
            self.assertNotIn("Segoe UI", content)
            self.assertIn("Dialogue: 0,0:00:00.00,0:00:03.00,Default,,0,0,0,,{\\an2\\pos(960,1026)}Montserrat Subtitle", content)

    def test_req2_anton_and_bebas_neue_no_impact_fallback(self) -> None:
        self.assertEqual(resolve_font_family("Anton"), "Anton")
        self.assertEqual(resolve_font_family("Bebas Neue"), "Bebas Neue")
        self.assertEqual(resolve_font_family("Poppins"), "Poppins")
        self.assertEqual(resolve_font_family("Montserrat"), "Montserrat")
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "anton.ass"
            generate_ass_file(
                out_path=ass_path,
                timeline_width=1920,
                timeline_height=1080,
                project_canvas_height=1080,
                srt_events=[{"start": 1, "end": 4, "text": "Anton Text", "style": {"fontFamily": "Anton"}}],
                text_events=[],
                global_style={"fontFamily": "Anton"},
                subtitle_area={},
            )
            content = ass_path.read_text(encoding="utf-8")
            self.assertIn("Style: Default,Anton,", content)
            self.assertNotIn("Impact", content)

    def test_req3_glow_preset_multi_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "glow.ass"
            style = {
                "fontFamily": "Inter",
                "fontSize": 50,
                "fontColor": "#ffffff",
                "outlineColor": "#ff1f67",
                "outline": 2,
                "glowEnabled": True,
                "glowColor": "#ff1f67",
                "glowBlur": 10,
                "glowStrength": 1.2,
            }
            generate_ass_file(
                out_path=ass_path,
                timeline_width=1920,
                timeline_height=1080,
                project_canvas_height=1080,
                srt_events=[{"start": 0, "end": 2, "text": "Glow Sub", "style": style}],
                text_events=[],
                global_style=style,
                subtitle_area={"xmin": 0.1, "xmax": 0.9, "ymin": 0.8, "ymax": 0.95},
            )
            content = ass_path.read_text(encoding="utf-8")
            # Glow layer (layer 0) with blur and border + main layer (layer 1)
            self.assertIn("blur", content)
            self.assertIn("Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,", content)
            self.assertIn("Dialogue: 1,0:00:00.00,0:00:02.00,Default,,0,0,0,,", content)

    def test_req4_glitch_preset_multi_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "glitch.ass"
            style = {
                "fontColor": "#00ff48",
                "staticEffect": "glitch",
                "secondaryOutlineColor": "#ff1f7a",
            }
            generate_ass_file(
                out_path=ass_path,
                timeline_width=1920,
                timeline_height=1080,
                project_canvas_height=1080,
                srt_events=[{"start": 0, "end": 2, "text": "Glitch Sub", "style": style}],
                text_events=[],
                global_style=style,
                subtitle_area={},
            )
            content = ass_path.read_text(encoding="utf-8")
            self.assertIn(r"\clip", content)
            self.assertIn("Dialogue: 0,", content)
            self.assertIn("Dialogue: 1,", content)

    def test_req5_duotone_preset_multi_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "duotone.ass"
            style = {
                "fontColor": "#ffd21a",
                "staticEffect": "duotone",
                "secondaryOutlineColor": "#e02a34",
            }
            generate_ass_file(
                out_path=ass_path,
                timeline_width=1920,
                timeline_height=1080,
                project_canvas_height=1080,
                srt_events=[{"start": 0, "end": 2, "text": "Duotone Sub", "style": style}],
                text_events=[],
                global_style=style,
                subtitle_area={},
            )
            content = ass_path.read_text(encoding="utf-8")
            self.assertIn(r"\c&H00342ae0\bord0\shad0", content)
            self.assertIn("Dialogue: 0,", content)
            self.assertIn("Dialogue: 1,", content)

    def test_req6_subtitle_bottom_center_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "bottom_center.ass"
            generate_ass_file(
                out_path=ass_path,
                timeline_width=1920,
                timeline_height=1080,
                project_canvas_height=1080,
                srt_events=[(0, 3, "Bottom Center Subtitle")],
                text_events=[],
                global_style={"textAlign": "center", "verticalAlign": "bottom"},
                subtitle_area={"xmin": 0.10, "xmax": 0.90, "ymin": 0.70, "ymax": 0.95},
            )
            content = ass_path.read_text(encoding="utf-8")
            # x = (0.10 + 0.90)/2 * 1920 = 960, y = 0.95 * 1080 = 1026, alignment = \an2
            self.assertIn(r"{\an2\pos(960,1026)}Bottom Center Subtitle", content)

    def test_req7_subtitle_repositioned_custom_area(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "repositioned.ass"
            # Repositioned to top-left
            generate_ass_file(
                out_path=ass_path,
                timeline_width=1920,
                timeline_height=1080,
                project_canvas_height=1080,
                srt_events=[(0, 3, "Top Left Subtitle")],
                text_events=[],
                global_style={"textAlign": "left", "verticalAlign": "top"},
                subtitle_area={"xmin": 0.05, "xmax": 0.60, "ymin": 0.10, "ymax": 0.30},
            )
            content = ass_path.read_text(encoding="utf-8")
            # x = 0.05 * 1920 = 96, y = 0.10 * 1080 = 108, alignment = \an7
            self.assertIn(r"{\an7\pos(96,108)}Top Left Subtitle", content)

    def test_req8_regular_text_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "regular_text.ass"
            generate_ass_file(
                out_path=ass_path,
                timeline_width=1920,
                timeline_height=1080,
                project_canvas_height=1080,
                srt_events=[],
                text_events=[{
                    "start": 0,
                    "end": 5,
                    "text": "Heading Title",
                    "x": 0.5,
                    "y": 0.25,
                    "style": {"fontFamily": "Montserrat", "fontSize": 80, "textAlign": "center", "verticalAlign": "middle"}
                }],
                global_style={},
                subtitle_area={},
            )
            content = ass_path.read_text(encoding="utf-8")
            self.assertIn("Style: Text1,Montserrat,80.00,", content)
            self.assertIn(r"{\an5\pos(960,270)}Heading Title", content)

    def test_req9_legacy_backward_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ass_path = Path(tmp) / "legacy.ass"
            # srt_events as old tuple (start, end, text) without extra keys
            generate_ass_file(
                out_path=ass_path,
                timeline_width=1280,
                timeline_height=720,
                project_canvas_height=720,
                srt_events=[(1.5, 3.5, "Legacy Event")],
                text_events=[],
                global_style={},
                subtitle_area={},
            )
            content = ass_path.read_text(encoding="utf-8")
            self.assertIn("Style: Default,Inter,", content)
            self.assertIn("Legacy Event", content)


if __name__ == "__main__":
    unittest.main()
