import math
import os
import winreg
from pathlib import Path
from typing import Any, Optional, Dict, Tuple, List

try:
    from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication
    from PySide6.QtCore import QCoreApplication
except ImportError:
    QGuiApplication = None

_FONT_FILE_CACHE: Dict[str, str] = {}
_FONT_METRICS_CACHE: Dict[tuple, Any] = {}

def get_font_file_path(family: str, weight: int = 400) -> Optional[str]:
    """Resolve the font family to an exact local TTF/OTF path using Windows Registry."""
    cache_key = f"{family}_{weight}"
    if cache_key in _FONT_FILE_CACHE:
        return _FONT_FILE_CACHE[cache_key] or None

    family_lower = family.lower().replace("'", "").replace('"', '')
    
    font_keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
    ]
    
    best_match = None
    best_match_path = None
    best_score = -1

    for root_key, sub_key in font_keys:
        try:
            with winreg.OpenKey(root_key, sub_key) as k:
                for i in range(10000):
                    try:
                        name, data, _type = winreg.EnumValue(k, i)
                        name_lower = name.lower()
                        if family_lower in name_lower:
                            score = 0
                            if family_lower == name_lower.split(" (truetype)")[0].strip():
                                score += 10
                            
                            is_bold = "bold" in name_lower or " bd " in name_lower
                            is_black = "black" in name_lower
                            is_light = "light" in name_lower
                            
                            if weight >= 700 and is_bold:
                                score += 5
                            elif weight >= 900 and is_black:
                                score += 5
                            elif weight <= 300 and is_light:
                                score += 5
                            elif 400 <= weight < 700 and not is_bold and not is_black and not is_light:
                                score += 5
                            
                            if score > best_score:
                                best_score = score
                                best_match = name
                                best_match_path = data
                    except OSError:
                        break
        except OSError:
            continue
            
    if best_match_path:
        if not os.path.isabs(best_match_path):
            best_match_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", best_match_path)
        
        if os.path.exists(best_match_path):
            _FONT_FILE_CACHE[cache_key] = best_match_path
            return best_match_path

    _FONT_FILE_CACHE[cache_key] = ""
    return None

def _get_qfont_metrics(family: str, size: int, weight: int, letter_spacing: float) -> Optional[Any]:
    if QGuiApplication is None:
        return None
        
    app = QGuiApplication.instance()
    if not app:
        import sys
        app = QGuiApplication(sys.argv)
        
    key = (family, size, weight, letter_spacing)
    if key in _FONT_METRICS_CACHE:
        return _FONT_METRICS_CACHE[key]
        
    font = QFont(family)
    font.setPixelSize(size)
    
    font.setWeight(QFont.Weight(weight) if hasattr(QFont.Weight, "Normal") else weight)
    
    if abs(letter_spacing) > 0.001:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, letter_spacing)
        
    metrics = QFontMetrics(font)
    _FONT_METRICS_CACHE[key] = metrics
    return metrics

def wrap_text_deterministic(text: str, family: str, size: int, weight: int, letter_spacing: float, max_width: float) -> List[str]:
    """Wrap text to max_width using actual font metrics. Returns a list of lines."""
    metrics = _get_qfont_metrics(family, size, weight, letter_spacing)
    
    if not metrics:
        char_width = max(size * 0.5, 1)
        max_chars = max(1, int(max_width / char_width))
        import textwrap
        return textwrap.wrap(text, width=max_chars)
        
    lines = []
    paragraphs = text.split('\n')
    
    for para in paragraphs:
        if not para:
            lines.append("")
            continue
            
        words = para.split(' ')
        current_line = []
        current_width = 0
        space_width = metrics.horizontalAdvance(' ')
        
        for word in words:
            word_width = metrics.horizontalAdvance(word)
            
            if not current_line:
                current_line.append(word)
                current_width = word_width
            else:
                if current_width + space_width + word_width <= max_width:
                    current_line.append(word)
                    current_width += space_width + word_width
                else:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                    current_width = word_width
                    
        if current_line:
            lines.append(' '.join(current_line))
            
    return lines

def format_ass_color(color_hex: str, opacity: float = 1.0) -> str:
    """Convert #RRGGBB or 0xRRGGBB + opacity to ASS color format &H<AA><BB><GG><RR>"""
    color_hex = str(color_hex).strip()
    if color_hex.startswith("#"):
        color_hex = color_hex[1:]
    elif color_hex.startswith("0x"):
        color_hex = color_hex[2:]
    else:
        color_hex = "FFFFFF"
        
    if len(color_hex) != 6:
        color_hex = "FFFFFF"
        
    r = color_hex[0:2]
    g = color_hex[2:4]
    b = color_hex[4:6]
    
    alpha = int((1.0 - opacity) * 255)
    alpha = max(0, min(255, alpha))
    
    return f"&H{alpha:02X}{b}{g}{r}"

def format_ass_time(seconds: float) -> str:
    """Format time in seconds to ASS timestamp format: H:MM:SS.cs"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def _clamp_float(val: Any, default: float, min_val: float, max_val: float) -> float:
    try:
        val = float(val)
        if math.isnan(val):
            return default
        return max(min_val, min(max_val, val))
    except (TypeError, ValueError):
        return default

CSS_PX_TO_ASS_PT = 96.0 / 72.0  # 1.3333333333333333

FONT_FALLBACK_MAP: Dict[str, str] = {
    "inter": "Segoe UI",
    "roboto": "Arial",
    "open sans": "Segoe UI",
    "lato": "Calibri",
    "nunito": "Segoe UI",
    "work sans": "Segoe UI",
    "dm sans": "Segoe UI",
    "ibm plex sans": "Segoe UI",
    "noto sans": "Segoe UI",
    "montserrat": "Segoe UI",
    "poppins": "Segoe UI",
    "oswald": "Impact",
    "archivo black": "Arial Black",
    "anton": "Impact",
    "bebas neue": "Impact",
    "outfit": "Segoe UI",
    "raleway": "Segoe UI",
    "manrope": "Segoe UI",
    "urbanist": "Segoe UI",
    "baloo 2": "Arial Rounded MT Bold",
    "fredoka": "Arial Rounded MT Bold",
    "rubik": "Segoe UI",
    "bangers": "Impact",
    "luckiest guy": "Arial Black",
    "lilita one": "Arial Black",
    "titan one": "Arial Black",
    "jetbrains mono": "Consolas",
    "fira code": "Consolas",
}

def resolve_font_family(family: str, weight: int = 400) -> str:
    """Resolve font family to an installed Windows font name, falling back gracefully if needed."""
    raw_family = str(family or "").strip().replace("'", "").replace('"', '')
    if not raw_family:
        return "Arial"
    if get_font_file_path(raw_family, weight):
        return raw_family
    family_lower = raw_family.lower()
    fallback = FONT_FALLBACK_MAP.get(family_lower)
    if fallback and get_font_file_path(fallback, weight):
        return fallback
    return raw_family

def generate_ass_file(
    out_path: Path,
    timeline_width: int,
    timeline_height: int,
    project_canvas_height: float,
    srt_events: List[Tuple[float, float, str]],  # start, end, text
    text_events: List[Dict[str, Any]], # start, end, style, text, position
    global_style: Dict[str, Any],
    subtitle_area: Dict[str, Any]
) -> None:
    """Generate a single .ass file for all subtitle and text events."""
    
    scale_factor = timeline_height / project_canvas_height if project_canvas_height > 0 else 1.0
    ass_font_scale = scale_factor * CSS_PX_TO_ASS_PT
    
    ass_lines = [
        "[Script Info]",
        "; Generated by Stitch Studio",
        "ScriptType: v4.00+",
        f"PlayResX: {timeline_width}",
        f"PlayResY: {timeline_height}",
        "WrapStyle: 1",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    ]
    
    font_family = str(global_style.get("fontFamily") or "Inter")
    font_weight_raw = global_style.get("fontWeight") or 800
    font_weight = int(font_weight_raw) if isinstance(font_weight_raw, (int, str)) and str(font_weight_raw).isdigit() else 800
    
    is_bold = -1 if font_weight >= 700 else 0
    actual_font_name = resolve_font_family(font_family, font_weight)
    
    font_size = max(8.0, _clamp_float(global_style.get("fontSize"), 50.0, 1.0, 1000.0) * ass_font_scale)
    pixel_font_size = max(8, int(round(_clamp_float(global_style.get("fontSize"), 50.0, 1.0, 1000.0) * scale_factor)))
    letter_spacing = _clamp_float(global_style.get("letterSpacing"), 0.0, -100.0, 100.0) * ass_font_scale
    
    primary_color = format_ass_color(str(global_style.get("fontColor") or global_style.get("color") or "0xFFFFFF"), _clamp_float(global_style.get("opacity", 1.0), 1.0, 0.0, 1.0))
    outline_color = format_ass_color(str(global_style.get("outlineColor") or "0x000000"), _clamp_float(global_style.get("opacity", 1.0), 1.0, 0.0, 1.0))
    
    outline_width = _clamp_float(global_style.get("outlineWidth") or global_style.get("outline"), 0.0, 0.0, 100.0) * ass_font_scale
    shadow_x = _clamp_float(global_style.get("shadowOffsetX"), 0.0, -100.0, 100.0) * ass_font_scale
    shadow_y = _clamp_float(global_style.get("shadowOffsetY"), 0.0, -100.0, 100.0) * ass_font_scale
    shadow_depth = max(abs(shadow_x), abs(shadow_y))
    
    xmin = _clamp_float(subtitle_area.get("xmin"), 0.04, 0.0, 1.0)
    xmax = _clamp_float(subtitle_area.get("xmax"), 0.96, 0.0, 1.0)
    ymin = _clamp_float(subtitle_area.get("ymin"), 0.60, 0.0, 1.0)
    ymax = _clamp_float(subtitle_area.get("ymax"), 0.98, 0.0, 1.0)
    
    xmin_px = xmin * timeline_width
    xmax_px = xmax * timeline_width
    ymin_px = ymin * timeline_height
    ymax_px = ymax * timeline_height
    
    box_width_px = max(1.0, xmax_px - xmin_px)
    box_height_px = max(1.0, ymax_px - ymin_px)
    
    bg_enabled = global_style.get("backgroundEnabled") or global_style.get("background")
    pad_x = _clamp_float(global_style.get("backgroundPaddingX"), 8.0, 0.0, 100.0) * scale_factor if bg_enabled else 11.0 * scale_factor
    pad_y = _clamp_float(global_style.get("backgroundPaddingY"), 3.0, 0.0, 100.0) * scale_factor if bg_enabled else 7.0 * scale_factor
    
    effective_box_width = box_width_px - (pad_x * 2)
    
    bg_color_hex = str(global_style.get("backgroundColor") or "0x000000")
    bg_opacity = _clamp_float(global_style.get("backgroundOpacity"), 0.55, 0.0, 1.0)
    bg_color_ass = format_ass_color(bg_color_hex, bg_opacity) if bg_enabled else format_ass_color("000000", 0.0)
    border_style = 3 if bg_enabled else 1 
    
    v_align = str(global_style.get("verticalAlign") or "bottom")
    t_align = str(global_style.get("textAlign") or "center")
    
    if v_align == "top":
        align_code = 7 if t_align == "left" else 9 if t_align == "right" else 8
        margin_v = int(ymin_px)
    elif v_align == "middle":
        align_code = 4 if t_align == "left" else 6 if t_align == "right" else 5
        margin_v = 0
    else: 
        align_code = 1 if t_align == "left" else 3 if t_align == "right" else 2
        margin_v = int(timeline_height - ymax_px)
        
    margin_l = int(xmin_px)
    margin_r = int(timeline_width - xmax_px)
    
    ass_lines.append(
        f"Style: Default,{actual_font_name},{font_size:.2f},{primary_color},&H000000FF,{outline_color},{bg_color_ass},{is_bold},0,0,0,100,100,{letter_spacing:.2f},0,{border_style},{outline_width:.2f},{shadow_depth:.2f},{align_code},{margin_l},{margin_r},{margin_v},1"
    )
    
    ass_lines.append("")
    ass_lines.append("[Events]")
    ass_lines.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")
    
    for start, end, text in srt_events:
        wrapped_lines = wrap_text_deterministic(text, actual_font_name, pixel_font_size, font_weight, letter_spacing / CSS_PX_TO_ASS_PT, effective_box_width)
        ass_text = r"\N".join(wrapped_lines)
        
        if v_align == "middle":
            x_pos = int((xmin_px + xmax_px) / 2)
            y_pos = int((ymin_px + ymax_px) / 2)
            ass_text = fr"{{\pos({x_pos},{y_pos})}}{ass_text}"
            
        start_str = format_ass_time(start)
        end_str = format_ass_time(end)
        
        ass_lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{ass_text}")
        
    # Process regular text events as well
    for text_event in text_events:
        t_start = text_event["start"]
        t_end = text_event["end"]
        t_text = text_event["text"]
        t_style = text_event.get("style", {})
        t_x = text_event.get("x", 0.5)
        t_y = text_event.get("y", 0.45)
        
        t_font_family = str(t_style.get("fontFamily") or "Inter")
        t_font_weight = int(t_style.get("fontWeight") or 800)
        t_actual_font = resolve_font_family(t_font_family, t_font_weight)
        t_is_bold = r"\b1" if t_font_weight >= 700 else r"\b0"
        
        t_font_size = max(8.0, _clamp_float(t_style.get("fontSize"), 50.0, 1.0, 1000.0) * ass_font_scale)
        t_pixel_font_size = max(8, int(round(_clamp_float(t_style.get("fontSize"), 50.0, 1.0, 1000.0) * scale_factor)))
        t_letter_spacing = _clamp_float(t_style.get("letterSpacing"), 0.0, -100.0, 100.0) * ass_font_scale
        
        t_color = format_ass_color(str(t_style.get("fontColor") or t_style.get("color") or "0xFFFFFF"), _clamp_float(t_style.get("opacity", 1.0), 1.0, 0.0, 1.0))
        t_outline_color = format_ass_color(str(t_style.get("outlineColor") or "0x000000"), _clamp_float(t_style.get("opacity", 1.0), 1.0, 0.0, 1.0))
        t_outline_width = _clamp_float(t_style.get("outlineWidth") or t_style.get("outline"), 0.0, 0.0, 100.0) * ass_font_scale
        
        # Free-form text wraps at timeline_width - 100
        wrapped_lines = wrap_text_deterministic(t_text, t_actual_font, t_pixel_font_size, t_font_weight, t_letter_spacing / CSS_PX_TO_ASS_PT, timeline_width - 100)
        t_ass_text = r"\N".join(wrapped_lines)
        
        # Position mapping
        pos_x = int(t_x * timeline_width)
        pos_y = int(t_y * timeline_height)
        t_ass_text = fr"{{\pos({pos_x},{pos_y})}}{{\fn{t_actual_font}}}{t_is_bold}{{\fs{t_font_size:.2f}}}{{\c{t_color}}}{{\3c{t_outline_color}}}{{\bord{t_outline_width:.2f}}}{{\an5}}{t_ass_text}"
        
        ass_lines.append(f"Dialogue: 1,{format_ass_time(t_start)},{format_ass_time(t_end)},Default,,0,0,0,,{t_ass_text}")

    out_path.write_text("\n".join(ass_lines), encoding="utf-8")
