import logging
import math
import os
import winreg
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

try:
    from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication
    from PySide6.QtCore import QCoreApplication
except ImportError:
    QGuiApplication = None

_FONT_FILE_CACHE: Dict[str, str] = {}
_FONT_METRICS_CACHE: Dict[tuple, Any] = {}


def get_bundled_fonts_dir() -> Path:
    """Returns the Path to the bundled fonts directory."""
    current_dir = Path(__file__).resolve().parent  # rendering/
    package_dir = current_dir.parent  # stitch_studio/
    candidates = [
        package_dir / "assets" / "fonts",
        package_dir.parent / "assets" / "fonts",
        package_dir.parent / "stitch_studio" / "assets" / "fonts",
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            return c
    target = package_dir / "assets" / "fonts"
    target.mkdir(parents=True, exist_ok=True)
    return target


def resolve_font_family(family: str, weight: int = 400) -> str:
    """
    Normalize and return the requested font family name.
    Does NOT silently alter family names (e.g. Montserrat stays Montserrat, Anton stays Anton).
    """
    raw_family = str(family or "").strip().replace("'", "").replace('"', "")
    if not raw_family:
        return "Inter"
    return raw_family


def get_font_file_path(family: str, weight: int = 400) -> Optional[str]:
    """
    Resolve font family to a TTF/OTF path:
    1. Bundled fonts directory
    2. Windows system fonts (Registry)
    3. Returns None if not found, logging clearly without altering family.
    """
    cache_key = f"{family}_{weight}"
    if cache_key in _FONT_FILE_CACHE:
        return _FONT_FILE_CACHE[cache_key] or None

    family_clean = resolve_font_family(family, weight)
    family_lower = family_clean.lower()
    slug = family_lower.replace(" ", "-").replace("_", "-")

    # 1. Check bundled fonts directory
    fonts_dir = get_bundled_fonts_dir()
    if fonts_dir.exists():
        candidate_names = [
            f"{slug}.ttf",
            f"{slug}.otf",
            f"{family_lower}.ttf",
            f"{family_lower}.otf",
            f"{family_clean}.ttf",
            f"{family_clean}.otf",
            f"{slug}-regular.ttf",
            f"{slug}-bold.ttf" if weight >= 700 else f"{slug}-regular.ttf",
        ]
        for cname in candidate_names:
            cpath = fonts_dir / cname
            if cpath.exists():
                _FONT_FILE_CACHE[cache_key] = str(cpath)
                return str(cpath)

    # 2. Check Windows Registry for system fonts
    if os.name == "nt":
        font_keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        ]
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

    logger.info(f"[FontResolver] Font '{family_clean}' will be located by libass fontsdir/system font matching.")
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
        return textwrap.wrap(text, width=max_chars) or [text]

    lines = []
    paragraphs = text.split("\n")

    for para in paragraphs:
        if not para:
            lines.append("")
            continue

        words = para.split(" ")
        current_line = []
        current_width = 0
        space_width = metrics.horizontalAdvance(" ")

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
                    lines.append(" ".join(current_line))
                    current_line = [word]
                    current_width = word_width

        if current_line:
            lines.append(" ".join(current_line))

    return lines or [text]


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


def _ass_color_override(color: Any, opacity: float = 1.0) -> str:
    """Returns &H<AA><BB><GG><RR> for ASS override tags."""
    return format_ass_color(str(color or "#ffffff"), opacity)


def format_ass_time(seconds: float) -> str:
    """Format time in seconds to ASS timestamp format: H:MM:SS.cs"""
    seconds = max(0.0, float(seconds))
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


def get_ass_alignment_code(text_align: str = "center", vertical_align: str = "bottom") -> int:
    """Map text alignment and vertical alignment to ASS \\an1 - \\an9."""
    t_align = str(text_align or "center").strip().lower()
    v_align = str(vertical_align or "bottom").strip().lower()
    if v_align == "top":
        return 7 if t_align == "left" else 9 if t_align == "right" else 8
    elif v_align == "middle":
        return 4 if t_align == "left" else 6 if t_align == "right" else 5
    else:  # bottom
        return 1 if t_align == "left" else 3 if t_align == "right" else 2


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
    ) if background_enabled else format_ass_color("FFFFFF", 0.0)
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
        if math.isnan(val) or not math.isfinite(val):
            return default
        return max(min_val, min(max_val, val))
    except (TypeError, ValueError):
        return default


def build_text_dialogues(
    *,
    start: float,
    end: float,
    text: str,
    style: Dict[str, Any],
    style_name: str,
    timeline_width: int,
    timeline_height: int,
    font_scale: float,
    area: Optional[Dict[str, Any]] = None,
    position: Optional[Dict[str, Any]] = None,
    style_metrics: Optional[Dict[str, Any]] = None,
    base_layer: int = 0,
) -> List[str]:
    """
    Build one or more ASS Dialogue lines for an event (SRT or regular text),
    supporting explicit positioning (\\pos, \\an), multi-line wrapping,
    and visual effects (glitch, duotone, glow, secondary outline, shadow).
    """
    if end <= start or not text:
        return []

    start_str = format_ass_time(start)
    end_str = format_ass_time(end)

    merged_style = dict(style or {})
    source_text = _normalized_text(merged_style, str(text or ""))

    # Determine font and size metrics
    font_family = str(merged_style.get("fontFamily") or (style_metrics or {}).get("font") or "Inter")
    actual_font = resolve_font_family(font_family)
    font_size = max(8.0, _clamp_float(merged_style.get("fontSize"), 50.0, 1.0, 1000.0) * font_scale)
    pixel_font_size = max(8, int(round(font_size)))
    font_weight = _font_weight_value(merged_style.get("fontWeight"), 800)
    letter_spacing = _clamp_float(merged_style.get("letterSpacing"), 0.0, -100.0, 100.0) * font_scale

    # Determine alignment and positioning
    t_align = str(merged_style.get("textAlign") or "center").strip().lower()
    v_align = str(merged_style.get("verticalAlign") or ("bottom" if area else "middle")).strip().lower()
    align_code = get_ass_alignment_code(t_align, v_align)
    align_tag = fr"\an{align_code}"

    # Calculate coordinates and max width
    if position and isinstance(position, dict) and ("x" in position or "y" in position):
        pos_x = int(round(_clamp_float(position.get("x"), 0.5, 0.0, 1.0) * timeline_width))
        pos_y = int(round(_clamp_float(position.get("y"), 0.45, 0.0, 1.0) * timeline_height))
        max_wrap_width = _clamp_float(merged_style.get("maxWidth"), timeline_width - 100, 1.0, float(timeline_width))
    elif area and isinstance(area, dict) and "xmin" in area and "ymin" in area:
        xmin = _clamp_float(area.get("xmin"), 0.04, 0.0, 1.0)
        xmax = _clamp_float(area.get("xmax"), 0.96, 0.0, 1.0)
        ymin = _clamp_float(area.get("ymin"), 0.60, 0.0, 1.0)
        ymax = _clamp_float(area.get("ymax"), 0.98, 0.0, 1.0)
        xmin_px = xmin * timeline_width
        xmax_px = xmax * timeline_width
        ymin_px = ymin * timeline_height
        ymax_px = ymax * timeline_height

        box_w = max(1.0, xmax_px - xmin_px)
        bg_enabled = bool(merged_style.get("backgroundEnabled") or merged_style.get("background"))
        pad_x = _clamp_float(merged_style.get("backgroundPaddingX"), 8.0, 0.0, 100.0) * font_scale if bg_enabled else 11.0 * font_scale
        max_wrap_width = max(1.0, box_w - (pad_x * 2))

        if t_align == "left":
            pos_x = int(round(xmin_px))
        elif t_align == "right":
            pos_x = int(round(xmax_px))
        else:  # center
            pos_x = int(round((xmin_px + xmax_px) / 2))

        if v_align == "top":
            pos_y = int(round(ymin_px))
        elif v_align == "middle":
            pos_y = int(round((ymin_px + ymax_px) / 2))
        else:  # bottom
            pos_y = int(round(ymax_px))
    else:
        # Default bottom-center position
        pos_x = int(round(timeline_width * 0.5))
        pos_y = int(round(timeline_height * 0.90))
        max_wrap_width = max(1.0, timeline_width * 0.92)

    wrapped_lines = wrap_text_deterministic(source_text, actual_font, pixel_font_size, font_weight, letter_spacing, max_wrap_width)
    wrapped_lines = [escape_ass_text(line) for line in wrapped_lines]
    ass_text_content = r"\N".join(wrapped_lines)

    dialogue_lines: List[str] = []

    # Visual effects
    effect = str(merged_style.get("staticEffect") or "none").lower()
    glow_enabled = bool(merged_style.get("glowEnabled"))
    glow_blur = _clamp_float(merged_style.get("glowBlur"), 0.0, 0.0, 100.0) * font_scale if glow_enabled else 0.0
    glow_color = merged_style.get("glowColor") or merged_style.get("outlineColor") or "#ffffff"
    glow_strength = _clamp_float(merged_style.get("glowStrength"), 1.0, 0.0, 5.0)

    sec_outline_w = _clamp_float(merged_style.get("secondaryOutlineWidth"), 0.0, 0.0, 100.0) * font_scale
    sec_outline_c = merged_style.get("secondaryOutlineColor") or "#000000"

    outline_w = _clamp_float(merged_style.get("outlineWidth") if merged_style.get("outlineWidth") is not None else merged_style.get("outline"), 0.0, 0.0, 100.0) * font_scale

    # 1. Glitch Effect
    if effect == "glitch":
        dx = max(1, int(round(2 * font_scale)))
        dy = max(1, int(round(1 * font_scale)))
        cyan_color = _ass_color_override("#00f5ff")
        pink_color = _ass_color_override(sec_outline_c if sec_outline_c != "#000000" else "#ff2f7d")

        # Top cyan slice
        top_clip = fr"\clip(0,0,{timeline_width},{int(timeline_height * 0.52)})"
        top_override = fr"{{{align_tag}\pos({pos_x - dx},{pos_y}){top_clip}\c{cyan_color}\bord0\shad0}}"
        dialogue_lines.append(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{top_override}{ass_text_content}")

        # Bottom pink slice
        bot_clip = fr"\clip(0,{int(timeline_height * 0.46)},{timeline_width},{timeline_height})"
        bot_override = fr"{{{align_tag}\pos({pos_x + dx},{pos_y + dy}){bot_clip}\c{pink_color}\bord0\shad0}}"
        dialogue_lines.append(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{bot_override}{ass_text_content}")

    # 2. Duotone Effect
    elif effect == "duotone":
        dx = max(1, int(round(4 * font_scale)))
        dy = max(1, int(round(2 * font_scale)))
        dt_color = _ass_color_override(sec_outline_c if sec_outline_c != "#000000" else merged_style.get("shadowColor") or "#e02a34")
        dt_override = fr"{{{align_tag}\pos({pos_x + dx},{pos_y + dy})\c{dt_color}\bord0\shad0}}"
        dialogue_lines.append(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{dt_override}{ass_text_content}")

    # 3. Glow Layer (if enabled and no glitch/duotone)
    elif glow_enabled and glow_blur > 0:
        g_color = _ass_color_override(glow_color, opacity=min(1.0, 0.75 * glow_strength))
        g_bord = max(1.0, outline_w + glow_blur)
        g_blur = max(1.0, glow_blur * 1.5)
        glow_override = fr"{{{align_tag}\pos({pos_x},{pos_y})\c{g_color}\3c{g_color}\bord{g_bord:.2f}\blur{g_blur:.2f}\shad0}}"
        dialogue_lines.append(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{glow_override}{ass_text_content}")

    # 4. Secondary Outline Layer
    elif sec_outline_w > 0:
        sec_color = _ass_color_override(sec_outline_c)
        sec_bord = outline_w + sec_outline_w
        sec_override = fr"{{{align_tag}\pos({pos_x},{pos_y})\3c{sec_color}\bord{sec_bord:.2f}\shad0}}"
        dialogue_lines.append(f"Dialogue: 0,{start_str},{end_str},{style_name},,0,0,0,,{sec_override}{ass_text_content}")

    # Main text layer
    main_override = fr"{{{align_tag}\pos({pos_x},{pos_y})}}"
    layer = base_layer if len(dialogue_lines) == 0 else max(1, base_layer)
    dialogue_lines.append(f"Dialogue: {layer},{start_str},{end_str},{style_name},,0,0,0,,{main_override}{ass_text_content}")

    return dialogue_lines


def generate_ass_file(
    out_path: Path,
    timeline_width: int,
    timeline_height: int,
    project_canvas_height: float,
    srt_events: Union[List[Tuple[float, float, str]], List[Dict[str, Any]]],
    text_events: List[Dict[str, Any]],
    global_style: Dict[str, Any],
    subtitle_area: Dict[str, Any],
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
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    ]

    # 1. Default Subtitle Style
    xmin = _clamp_float(subtitle_area.get("xmin"), 0.04, 0.0, 1.0)
    xmax = _clamp_float(subtitle_area.get("xmax"), 0.96, 0.0, 1.0)
    ymin = _clamp_float(subtitle_area.get("ymin"), 0.60, 0.0, 1.0)
    ymax = _clamp_float(subtitle_area.get("ymax"), 0.98, 0.0, 1.0)

    xmin_px = xmin * timeline_width
    xmax_px = xmax * timeline_width
    ymin_px = ymin * timeline_height
    ymax_px = ymax * timeline_height

    v_align = str(global_style.get("verticalAlign") or "bottom").lower()
    t_align = str(global_style.get("textAlign") or "center").lower()
    align_code = get_ass_alignment_code(t_align, v_align)

    if v_align == "top":
        margin_v = int(ymin_px)
    elif v_align == "middle":
        margin_v = 0
    else:
        margin_v = int(timeline_height - ymax_px)

    margin_l = int(xmin_px)
    margin_r = int(timeline_width - xmax_px)

    default_style_line, default_metrics = _style_line(
        name="Default",
        style=global_style,
        fallback_style={},
        font_scale=ass_font_scale,
        timeline_width=timeline_width,
        timeline_height=timeline_height,
        margin_l=margin_l,
        margin_r=margin_r,
        margin_v=margin_v,
        alignment=align_code,
    )
    ass_lines.append(default_style_line)

    # 2. Styles for regular text events and distinct subtitle events
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

    # Process SRT events
    for item in srt_events:
        if isinstance(item, (tuple, list)):
            start = float(item[0])
            end = float(item[1])
            text = str(item[2] if len(item) > 2 else "")
            ev_style = global_style
            ev_area = subtitle_area
            ev_pos = None
        elif isinstance(item, dict):
            start = float(item.get("start") or 0.0)
            end = float(item.get("end") or 0.0)
            text = str(item.get("text") or "")
            ev_style = {**global_style, **(item.get("style") or {})}
            ev_area = item.get("area") or subtitle_area
            ev_pos = item.get("position")
        else:
            continue

        dialogues = build_text_dialogues(
            start=start,
            end=end,
            text=text,
            style=ev_style,
            style_name="Default",
            timeline_width=timeline_width,
            timeline_height=timeline_height,
            font_scale=ass_font_scale,
            area=ev_area,
            position=ev_pos,
            style_metrics=default_metrics,
            base_layer=0,
        )
        ass_lines.extend(dialogues)

    # Process regular Text events
    for index, text_event in enumerate(text_events):
        t_start = float(text_event.get("start") or 0.0)
        t_end = float(text_event.get("end") or 0.0)
        t_text = str(text_event.get("text") or "")
        t_style_meta = text_style_metrics[index] if index < len(text_style_metrics) else {}
        t_style = t_style_meta.get("style", {}) if isinstance(t_style_meta.get("style"), dict) else text_event.get("style", {})
        t_x = text_event.get("x", 0.5)
        t_y = text_event.get("y", 0.45)

        dialogues = build_text_dialogues(
            start=t_start,
            end=t_end,
            text=t_text,
            style=t_style,
            style_name=str(t_style_meta.get("name") or f"Text{index + 1}"),
            timeline_width=timeline_width,
            timeline_height=timeline_height,
            font_scale=ass_font_scale,
            position={"x": t_x, "y": t_y},
            style_metrics=t_style_meta,
            base_layer=1,
        )
        ass_lines.extend(dialogues)

    out_path.write_text("\n".join(ass_lines), encoding="utf-8")
