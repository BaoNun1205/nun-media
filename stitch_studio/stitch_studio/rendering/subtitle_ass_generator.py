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

def escape_ass_text(text: Any) -> str:
    """Escape plain text so ASS override parsing cannot eat user text."""
    value = str(text or "")
    return (
        value
        .replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )

def _font_weight_value(raw: Any, default: int = 800) -> int:
    if isinstance(raw, (int, float)):
        return int(raw)
    value = str(raw or "").strip().lower()
    if value.isdigit():
        return int(value)
    if value in {"bold", "bolder", "black", "heavy"}:
        return 800
    if value in {"normal", "regular", "book"}:
        return 400
    if value in {"light", "lighter"}:
        return 300
    return default

def _ass_flag(enabled: bool) -> int:
    return -1 if enabled else 0

def _normalized_text(style: Dict[str, Any], text: str) -> str:
    transform = str(style.get("textTransform") or "none").lower()
    if transform == "uppercase":
        return text.upper()
    if transform == "lowercase":
        return text.lower()
    if transform == "capitalize":
        return text.title()
    return text

def _ass_color_override(color: Any, opacity: float = 1.0) -> str:
    return format_ass_color(str(color or "#ffffff"), opacity)

def _style_line(
    *,
    name: str,
    style: Dict[str, Any],
    fallback_style: Dict[str, Any],
    font_scale: float,
    timeline_width: int,
    timeline_height: int,
    margin_l: int = 0,
    margin_r: int = 0,
    margin_v: int = 0,
    alignment: int = 5,
) -> Tuple[str, Dict[str, Any]]:
    merged = {**fallback_style, **(style or {})}
    font_family = str(merged.get("fontFamily") or "Inter")
    font_weight = _font_weight_value(merged.get("fontWeight"), 800)
    actual_font = resolve_font_family(font_family, font_weight)
    font_size = max(8.0, _clamp_float(merged.get("fontSize"), 50.0, 1.0, 1000.0) * font_scale)
    letter_spacing = _clamp_float(merged.get("letterSpacing"), 0.0, -100.0, 100.0) * font_scale
    opacity = _clamp_float(merged.get("opacity", 1.0), 1.0, 0.0, 1.0)
    primary_color = format_ass_color(str(merged.get("fontColor") or merged.get("color") or "0xFFFFFF"), opacity)
    outline_color = format_ass_color(str(merged.get("outlineColor") or "0x000000"), opacity)
    background_enabled = bool(merged.get("backgroundEnabled") or merged.get("background"))
    background_color = format_ass_color(
        str(merged.get("backgroundColor") or "0x000000"),
        _clamp_float(merged.get("backgroundOpacity"), 0.55, 0.0, 1.0),
    ) if background_enabled else format_ass_color("000000", 0.0)
    outline_width = _clamp_float(merged.get("outlineWidth") if merged.get("outlineWidth") is not None else merged.get("outline"), 0.0, 0.0, 100.0) * font_scale
    shadow_x = _clamp_float(merged.get("shadowOffsetX"), 0.0, -100.0, 100.0) * font_scale
    shadow_y = _clamp_float(merged.get("shadowOffsetY"), 0.0, -100.0, 100.0) * font_scale
    shadow_blur = _clamp_float(merged.get("shadowBlur"), 0.0, 0.0, 100.0) * font_scale
    glow_blur = _clamp_float(merged.get("glowBlur"), 0.0, 0.0, 100.0) * font_scale if merged.get("glowEnabled") else 0.0
    shadow_depth = max(abs(shadow_x), abs(shadow_y), shadow_blur, glow_blur)
    border_style = 3 if background_enabled else 1
    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:40] or "Text"
    line = (
        f"Style: {safe_name},{actual_font},{font_size:.2f},{primary_color},&H000000FF,{outline_color},{background_color},"
        f"{_ass_flag(font_weight >= 700)},{_ass_flag(str(merged.get('fontStyle') or '').lower() == 'italic')},"
        f"{_ass_flag(str(merged.get('textDecoration') or '').lower() == 'underline')},0,100,100,{letter_spacing:.2f},0,"
        f"{border_style},{outline_width:.2f},{shadow_depth:.2f},{alignment},{margin_l},{margin_r},{margin_v},1"
    )
    metrics = {
        "name": safe_name,
        "font": actual_font,
        "font_size": font_size,
        "pixel_font_size": max(8, int(round(font_size))),
        "font_weight": font_weight,
        "letter_spacing": letter_spacing,
        "max_width": max(1.0, timeline_width - 100),
        "line_height": _clamp_float(merged.get("lineHeight"), 1.05, 0.5, 4.0),
        "text_align": str(merged.get("textAlign") or "center"),
        "vertical_align": str(merged.get("verticalAlign") or "middle"),
        "style": merged,
    }
    return line, metrics

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
    ass_font_scale = scale_factor
    
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
    pixel_font_size = max(8, int(round(font_size)))
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

    text_style_metrics: List[Dict[str, Any]] = []
    for index, text_event in enumerate(text_events):
        t_style = text_event.get("style", {})
        style_line, metrics = _style_line(
            name=f"Text{index + 1}",
            style=t_style if isinstance(t_style, dict) else {},
            fallback_style={},
            font_scale=ass_font_scale,
            timeline_width=timeline_width,
            timeline_height=timeline_height,
            alignment=5,
        )
        ass_lines.append(style_line)
        text_style_metrics.append(metrics)
    
    ass_lines.append("")
    ass_lines.append("[Events]")
    ass_lines.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")
    
    for start, end, text in srt_events:
        source_text = _normalized_text(global_style, str(text or ""))
        wrapped_lines = wrap_text_deterministic(source_text, actual_font_name, pixel_font_size, font_weight, letter_spacing, effective_box_width)
        wrapped_lines = [escape_ass_text(line) for line in wrapped_lines]
        ass_text = r"\N".join(wrapped_lines)
        
        if v_align == "middle":
            x_pos = int((xmin_px + xmax_px) / 2)
            y_pos = int((ymin_px + ymax_px) / 2)
            ass_text = fr"{{\pos({x_pos},{y_pos})}}{ass_text}"
            
        start_str = format_ass_time(start)
        end_str = format_ass_time(end)
        
        ass_lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{ass_text}")
        
    # Process regular text events as well
    for index, text_event in enumerate(text_events):
        t_start = text_event["start"]
        t_end = text_event["end"]
        t_style_meta = text_style_metrics[index] if index < len(text_style_metrics) else {}
        t_style = t_style_meta.get("style", {}) if isinstance(t_style_meta.get("style"), dict) else {}
        t_text = _normalized_text(t_style, str(text_event["text"] or ""))
        t_x = text_event.get("x", 0.5)
        t_y = text_event.get("y", 0.45)
        
        max_width = _clamp_float(t_style.get("maxWidth"), t_style_meta.get("max_width", timeline_width - 100), 1.0, float(timeline_width))
        wrapped_lines = wrap_text_deterministic(
            t_text,
            str(t_style_meta.get("font") or "Inter"),
            int(t_style_meta.get("pixel_font_size") or 50),
            int(t_style_meta.get("font_weight") or 800),
            float(t_style_meta.get("letter_spacing") or 0.0),
            max_width,
        )
        wrapped_lines = [escape_ass_text(line) for line in wrapped_lines]
        t_ass_text = r"\N".join(wrapped_lines)
        
        pos_x = int(t_x * timeline_width)
        pos_y = int(t_y * timeline_height)
        align_tag = r"\an5"
        if str(t_style.get("textAlign") or "").lower() == "left":
            align_tag = r"\an4"
        elif str(t_style.get("textAlign") or "").lower() == "right":
            align_tag = r"\an6"
        style_name = str(t_style_meta.get("name") or "Default")
        effect = str(t_style.get("staticEffect") or "none").lower()
        effect_text = t_ass_text
        effect_color = t_style.get("secondaryOutlineColor") or t_style.get("shadowColor") or "#f02b36"
        if effect == "duotone":
            dx = int(round(4 * ass_font_scale))
            dy = int(round(2 * ass_font_scale))
            effect_override = fr"{{{align_tag}\pos({pos_x + dx},{pos_y + dy})\c{_ass_color_override(effect_color)}\bord0\shad0}}{effect_text}"
            ass_lines.append(f"Dialogue: 0,{format_ass_time(t_start)},{format_ass_time(t_end)},{style_name},,0,0,0,,{effect_override}")
        elif effect == "glitch":
            dx = max(1, int(round(2 * ass_font_scale)))
            dy = max(1, int(round(1 * ass_font_scale)))
            top_clip = fr"\clip(0,0,{timeline_width},{int(timeline_height * 0.52)})"
            bottom_clip = fr"\clip(0,{int(timeline_height * 0.46)},{timeline_width},{timeline_height})"
            top_override = fr"{{{align_tag}\pos({pos_x - dx},{pos_y}){top_clip}\c{_ass_color_override('#00f5ff')}\bord0\shad0}}{effect_text}"
            bottom_override = fr"{{{align_tag}\pos({pos_x + dx},{pos_y + dy}){bottom_clip}\c{_ass_color_override(effect_color)}\bord0\shad0}}{effect_text}"
            ass_lines.append(f"Dialogue: 0,{format_ass_time(t_start)},{format_ass_time(t_end)},{style_name},,0,0,0,,{top_override}")
            ass_lines.append(f"Dialogue: 0,{format_ass_time(t_start)},{format_ass_time(t_end)},{style_name},,0,0,0,,{bottom_override}")
        t_ass_text = fr"{{{align_tag}\pos({pos_x},{pos_y})}}{t_ass_text}"
        
        ass_lines.append(f"Dialogue: 1,{format_ass_time(t_start)},{format_ass_time(t_end)},{style_name},,0,0,0,,{t_ass_text}")

    out_path.write_text("\n".join(ass_lines), encoding="utf-8")
