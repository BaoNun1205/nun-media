import os
import pytest
from stitch_studio.rendering.subtitle_ass_generator import (
    resolve_font_family,
    get_font_file_path,
    normalize_text_style,
    normalize_text_position,
    get_ass_alignment_code,
    _get_rounded_rect_vector,
    _font_weight_value,
    build_text_dialogues,
    _FONT_FILE_CACHE
)

def test_font_weight_value():
    assert _font_weight_value("thin") == 100
    assert _font_weight_value("extralight") == 200
    assert _font_weight_value("light") == 300
    assert _font_weight_value("normal") == 400
    assert _font_weight_value("medium") == 500
    assert _font_weight_value("semibold") == 600
    assert _font_weight_value("bold") == 700
    assert _font_weight_value("extrabold") == 800
    assert _font_weight_value("black") == 900
    assert _font_weight_value(600) == 600

def test_normalize_text_style():
    # Legacy minimal style
    minimal = normalize_text_style({})
    assert minimal["fontFamily"] == "Inter"
    assert minimal["fontWeight"] == 800
    assert minimal["outlineWidth"] == 0.0
    assert minimal["secondaryOutlineWidth"] == 0.0
    assert minimal["shadowEnabled"] is False
    assert minimal["glowEnabled"] is False
    assert minimal["backgroundEnabled"] is False
    assert minimal["verticalAlign"] == "middle"
    assert minimal["backgroundRadius"] == 0.0

    # Full style preserving user values
    full = normalize_text_style({
        "fontFamily": "Montserrat",
        "fontWeight": 700,
        "outlineWidth": 4.5,
        "secondaryOutlineWidth": 2.0,
        "shadowEnabled": True,
        "glowEnabled": True,
        "backgroundEnabled": True,
        "verticalAlign": "top",
        "backgroundRadius": 15.0
    })
    assert full["fontFamily"] == "Montserrat"
    assert full["fontWeight"] == 700
    assert full["outlineWidth"] == 4.5
    assert full["secondaryOutlineWidth"] == 2.0
    assert full["shadowEnabled"] is True
    assert full["glowEnabled"] is True
    assert full["backgroundEnabled"] is True
    assert full["verticalAlign"] == "top"
    assert full["backgroundRadius"] == 15.0

def test_normalize_position():
    # Legacy missing position
    pos1 = normalize_text_position(None, None, default_v_align="bottom")
    assert pos1["mode"] == "default"
    assert pos1["x"] == 0.5
    assert pos1["y"] == 0.9

    pos2 = normalize_text_position(None, None, default_v_align="middle")
    assert pos2["mode"] == "default"
    assert pos2["x"] == 0.5
    assert pos2["y"] == 0.45

    # Exact position
    pos3 = normalize_text_position({"x": 0.2, "y": 0.3}, None)
    assert pos3["mode"] == "exact"
    assert pos3["x"] == 0.2
    assert pos3["y"] == 0.3

    # Area
    pos4 = normalize_text_position(None, {"xmin": 0.1, "xmax": 0.9, "ymin": 0.1, "ymax": 0.9})
    assert pos4["mode"] == "area"
    assert pos4["xmin"] == 0.1
    assert pos4["ymax"] == 0.9

def test_ass_alignment_code():
    assert get_ass_alignment_code("left", "top") == 7
    assert get_ass_alignment_code("center", "top") == 8
    assert get_ass_alignment_code("right", "top") == 9
    assert get_ass_alignment_code("left", "middle") == 4
    assert get_ass_alignment_code("center", "middle") == 5
    assert get_ass_alignment_code("right", "middle") == 6
    assert get_ass_alignment_code("left", "bottom") == 1
    assert get_ass_alignment_code("center", "bottom") == 2
    assert get_ass_alignment_code("right", "bottom") == 3

def test_background_radius():
    # Radius = 0
    vec0 = _get_rounded_rect_vector(100, 50, 0)
    assert "m 0 0" in vec0
    assert "b" not in vec0  # No bezier curves

    # Radius > 0
    vec1 = _get_rounded_rect_vector(100, 50, 10)
    assert "m 10 0" in vec1
    assert "b" in vec1  # Bezier curves present for rounded corners

def test_font_resolver_mock(monkeypatch):
    # Setup mock bundled directory
    class MockPath:
        def __init__(self, name):
            self.name = name
            self.stem = name.split(".")[0]
        def is_file(self): return True
        def __str__(self): return f"mock/fonts/{self.name}"

    def mock_iterdir(self):
        return [
            MockPath("montserrat.ttf"),
            MockPath("montserrat-bold.ttf"),
            MockPath("montserrat-medium.ttf"),
            MockPath("anton.ttf"),
        ]
        
    class MockDir:
        def exists(self): return True
        def iterdir(self): return mock_iterdir(self)
        def is_dir(self): return True
        
    monkeypatch.setattr("stitch_studio.rendering.subtitle_ass_generator.get_bundled_fonts_dir", lambda: MockDir())
    
    _FONT_FILE_CACHE.clear()

    # Exact base font
    p1 = get_font_file_path("Montserrat", 400)
    assert p1.endswith("montserrat.ttf")
    
    _FONT_FILE_CACHE.clear()

    # Exact bold font
    p2 = get_font_file_path("Montserrat", 700)
    assert p2.endswith("montserrat-bold.ttf")
    
    _FONT_FILE_CACHE.clear()
    
    # Nearest weight (600 requested -> 500 or 700? 700 wins? wait, 600 to 500 is 100, 600 to 700 is 100)
    # distance tie breaker uses filename: "montserrat-bold.ttf" vs "montserrat-medium.ttf" -> 'b' comes first
    p3 = get_font_file_path("Montserrat", 600)
    assert p3.endswith("montserrat-bold.ttf")
    
    _FONT_FILE_CACHE.clear()

    # Nearest weight (200 requested -> 400 is closest available)
    p4 = get_font_file_path("Montserrat", 200)
    assert p4.endswith("montserrat.ttf")
    
    _FONT_FILE_CACHE.clear()

    # Single font fallback
    p5 = get_font_file_path("Anton", 700)
    assert p5.endswith("anton.ttf")
    
    _FONT_FILE_CACHE.clear()

def test_background_radius_dialogue():
    # Test background dialogue with radius
    style = normalize_text_style({
        "backgroundEnabled": True,
        "backgroundColor": "#ff0000",
        "backgroundRadius": 10.0,
        "backgroundPaddingX": 5.0,
        "backgroundPaddingY": 5.0,
    })
    
    dialogues = build_text_dialogues(
        start=0.0,
        end=1.0,
        text="Hello",
        style=style,
        style_name="TestStyle",
        timeline_width=1920,
        timeline_height=1080,
        font_scale=1.0,
        position={"x": 0.5, "y": 0.5},
    )
    
    # Dialogues should have a background vector layer and a text layer
    # bg_radius > 0 uses \p1
    assert any("\\p1" in d and "m " in d for d in dialogues)
    
def test_background_radius_zero_dialogue():
    # Test background dialogue without radius
    style = normalize_text_style({
        "backgroundEnabled": True,
        "backgroundColor": "#ff0000",
        "backgroundRadius": 0.0,
    })
    
    dialogues = build_text_dialogues(
        start=0.0,
        end=1.0,
        text="Hello",
        style=style,
        style_name="TestStyle",
        timeline_width=1920,
        timeline_height=1080,
        font_scale=1.0,
        position={"x": 0.5, "y": 0.5},
    )
    
    # Dialogues should NOT use \p1 if radius is 0
    assert not any("\\p1" in d for d in dialogues)
    assert any("TestStyle_bg" in d for d in dialogues)
