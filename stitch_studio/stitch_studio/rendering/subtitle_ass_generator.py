import logging
import math
import os
import winreg
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

try:
    from PySide6.QtGui import QFont, QFontMetrics, QGuiApplication, QFontDatabase
    from PySide6.QtCore import QCoreApplication
except ImportError:
    QGuiApplication = None
    QFontDatabase = None

_FONT_FILE_CACHE: Dict[str, str] = {}
_FONT_METRICS_CACHE: Dict[tuple, Any] = {}
_LOADED_QT_FONTS = set()


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
        candidates = []
        for p in fonts_dir.iterdir():
            if not p.is_file():
                continue
            name_lower = p.name.lower()
            if name_lower == f"{slug}.ttf" or name_lower == f"{slug}.otf":
                candidates.append((400, p))
            elif name_lower.startswith(f"{slug}-") and name_lower.endswith(('.ttf', '.otf')):
                stem = p.stem.lower()
                suffix = stem[len(slug)+1:]
                candidates.append((_font_weight_value(suffix, 400), p))

        if candidates:
            # Sort by distance to requested weight, then by name for stability
            candidates.sort(key=lambda c: (abs(c[0] - weight), c[1].name))
            best_match = candidates[0][1]
            logger.debug(f"Using bundled font: {family_clean} (weight {weight}) -> {best_match.name}")
            _FONT_FILE_CACHE[cache_key] = str(best_match)
            return str(best_match)

    # 2. Check Windows Registry for system fonts
    if os.name == "nt":
        font_keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        ]
        best_match_path = None
        sys_candidates = []
        for root_key, sub_key in font_keys:
            try:
                with winreg.OpenKey(root_key, sub_key) as k:
                    for i in range(10000):
                        try:
                            name, data, _type = winreg.EnumValue(k, i)
                            name_lower = name.lower()
                            # e.g., "Arial (TrueType)" or "Arial Bold (TrueType)"
                            actual_name = name_lower.split(" (truetype)")[0].strip()
                            if actual_name.startswith(family_lower):
                                # Determine weight from name
                                suffix = actual_name[len(family_lower):].strip()
                                sys_weight = _font_weight_value(suffix, 400) if suffix else 400
                                sys_candidates.append((sys_weight, data, actual_name))
                        except OSError:
                            break
            except OSError:
                continue

        if sys_candidates:
            # Prefer nearest weight, then exact family name, then alphabetically
            sys_candidates.sort(key=lambda c: (abs(c[0] - weight), 0 if c[2] == family_lower else 1, c[2]))
            best_match_path = sys_candidates[0][1]

        if best_match_path:
            if not os.path.isabs(best_match_path):
                best_match_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", best_match_path)
            if os.path.exists(best_match_path):
                logger.debug(f"Using system font: {family_clean} (weight {weight}) -> {os.path.basename(best_match_path)}")
                _FONT_FILE_CACHE[cache_key] = best_match_path
                return best_match_path

    logger.warning(f"Requested font '{family_clean}' weight {weight} not found. Tried bundled fonts and system fonts. Libass/Qt will fallback.")
    _FONT_FILE_CACHE[cache_key] = ""
    return None


def _get_qfont_metrics(family: str, size: int, weight: int, letter_spacing: float) -> Optional[Any]:
    if QGuiApplication is None:
        return None
    app = QGuiApplication.instance()
    if not app:
        import sys
        app = QGuiApplication(sys.argv)
    
    font_path = get_font_file_path(family, weight)
    if font_path and QFontDatabase and font_path not in _LOADED_QT_FONTS:
        QFontDatabase.addApplicationFont(font_path)
        _LOADED_QT_FONTS.add(font_path)

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


def _measure_text_bounding_box(lines: List[str], family: str, size: int, weight: int, letter_spacing: float, line_height: float) -> Tuple[float, float]:
    """Measure the exact width and height of a wrapped text block."""
    metrics = _get_qfont_metrics(family, size, weight, letter_spacing)
    if metrics:
        max_w = 0.0
        total_h = 0.0
        for i, line in enumerate(lines):
            rect = metrics.boundingRect(line)
            w = rect.width()
            max_w = max(max_w, float(w))
            if i == 0:
                total_h += float(metrics.height())
            else:
                total_h += float(metrics.height()) * line_height
        return max_w, total_h
    
    # Headless fallback estimation
    max_chars = max((len(line) for line in lines), default=0)
    est_w = max_chars * size * 0.55
    est_h = len(lines) * size * line_height if len(lines) > 1 else size * 1.15
    return est_w, est_h


def _get_rounded_rect_vector(w: float, h: float, r: float) -> str:
    """Generate an ASS vector drawing for a rounded rectangle."""
    r = min(r, w / 2, h / 2)
    if r <= 0:
        return f"m 0 0 l {int(round(w))} 0 l {int(round(w))} {int(round(h))} l 0 {int(round(h))}"
        
    k = r * 0.55228
    
    def ir(val: float) -> int:
        return int(round(val))
        
    return (
        f"m {ir(r)} 0 "
        f"l {ir(w-r)} 0 "
        f"b {ir(w-r+k)} 0 {ir(w)} {ir(r-k)} {ir(w)} {ir(r)} "
        f"l {ir(w)} {ir(h-r)} "
        f"b {ir(w)} {ir(h-r+k)} {ir(w-r+k)} {ir(h)} {ir(w-r)} {ir(h)} "
        f"l {ir(r)} {ir(h)} "
        f"b {ir(r-k)} {ir(h)} 0 {ir(h-r+k)} 0 {ir(h-r)} "
        f"l 0 {ir(r)} "
        f"b 0 {ir(r-k)} {ir(r-k)} 0 {ir(r)} 0"
    )

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
    WEIGHT_MAP = {
        "thin": 100, "hairline": 100,
        "extralight": 200, "ultralight": 200,
        "light": 300, "lighter": 300,
        "normal": 400, "regular": 400, "book": 400,
        "medium": 500,
        "semibold": 600, "demibold": 600,
        "bold": 700, "bolder": 700,
        "extrabold": 800, "ultrabold": 800, "heavy": 800,
        "black": 900,
    }
    return WEIGHT_MAP.get(value, default)


def _ass_flag(enabled: bool) -> int:
    return -1 if enabled else 0


def _normalized_text(style: Dict[str, Any], text: str) -> str:
    transform = str(style.get("textTransform") or "none").lower()
    if transform == "uppercase":
        text = text.upper()
    elif transform == "lowercase":
        text = text.lower()
    elif transform == "capitalize":
        text = text.title()
    return text


def normalize_text_style(raw_style: Optional[Dict[str, Any]], fallback_style: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Standardize text style providing sensible defaults for missing properties.
    Ensures that both SRT and regular Text items share a common styling baseline.
    """
    s = dict(fallback_style or {})
    s.update(raw_style or {})
    
    return {
        "fontFamily": str(s.get("fontFamily") or "Inter"),
        "fontSize": _clamp_float(s.get("fontSize"), 42.0, 1.0, 1000.0),
        "fontWeight": _font_weight_value(s.get("fontWeight"), 800),
        "fontStyle": str(s.get("fontStyle") or "normal").lower(),
        "color": _ass_color_override(s.get("color") or "#ffffff"),
        
        "outlineWidth": _clamp_float(s.get("outlineWidth") if s.get("outlineWidth") is not None else s.get("outline"), 0.0, 0.0, 100.0),
        "outlineColor": _ass_color_override(s.get("outlineColor") or "#000000"),
        
        "secondaryOutlineWidth": _clamp_float(s.get("secondaryOutlineWidth"), 0.0, 0.0, 100.0),
        "secondaryOutlineColor": _ass_color_override(s.get("secondaryOutlineColor") or "#000000"),
        
        "shadowEnabled": bool(s.get("shadowEnabled")),
        "shadowColor": _ass_color_override(s.get("shadowColor") or "#000000"),
        "shadowOffsetX": _clamp_float(s.get("shadowOffsetX"), 0.0, -100.0, 100.0),
        "shadowOffsetY": _clamp_float(s.get("shadowOffsetY"), 0.0, -100.0, 100.0),
        "shadowBlur": _clamp_float(s.get("shadowBlur"), 0.0, 0.0, 100.0),
        
        "glowEnabled": bool(s.get("glowEnabled")),
        "glowColor": _ass_color_override(s.get("glowColor") or s.get("outlineColor") or "#ffffff"),
        "glowStrength": _clamp_float(s.get("glowStrength"), 1.0, 0.0, 5.0),
        "glowBlur": _clamp_float(s.get("glowBlur"), 0.0, 0.0, 100.0),
        
        "backgroundEnabled": bool(s.get("backgroundEnabled") or s.get("background")),
        "backgroundColor": _ass_color_override(s.get("backgroundColor") or "#000000"),
        "backgroundOpacity": _clamp_float(s.get("backgroundOpacity"), 0.5, 0.0, 1.0),
        "backgroundPaddingX": _clamp_float(s.get("backgroundPaddingX"), 8.0, 0.0, 100.0),
        "backgroundPaddingY": _clamp_float(s.get("backgroundPaddingY"), 8.0, 0.0, 100.0),
        "backgroundRadius": _clamp_float(s.get("backgroundRadius"), 0.0, 0.0, 100.0),
        
        "textAlign": str(s.get("textAlign") or "center").strip().lower(),
        "verticalAlign": str(s.get("verticalAlign") or "middle").strip().lower(),
        "lineHeight": _clamp_float(s.get("lineHeight"), 1.05, 0.5, 4.0),
        "letterSpacing": _clamp_float(s.get("letterSpacing"), 0.0, -100.0, 100.0),
        
        "staticEffect": str(s.get("staticEffect") or "none").lower(),
        "textTransform": str(s.get("textTransform") or "none").lower(),
        "textDecoration": str(s.get("textDecoration") or "none").lower(),
    }


def normalize_text_position(position: Optional[Dict[str, Any]], area: Optional[Dict[str, Any]], default_v_align: str = "middle") -> Dict[str, Any]:
    """
    Standardize positioning for text and subtitles.
    Supports legacy area bounds and exact (x, y) coordinates.
    """
    if position and isinstance(position, dict) and ("x" in position or "y" in position):
        return {
            "mode": "exact",
            "x": _clamp_float(position.get("x"), 0.5, 0.0, 1.0),
            "y": _clamp_float(position.get("y"), 0.45, 0.0, 1.0),
        }
    if area and isinstance(area, dict) and "xmin" in area and "ymin" in area:
        return {
            "mode": "area",
            "xmin": _clamp_float(area.get("xmin"), 0.04, 0.0, 1.0),
            "xmax": _clamp_float(area.get("xmax"), 0.96, 0.0, 1.0),
            "ymin": _clamp_float(area.get("ymin"), 0.60, 0.0, 1.0),
            "ymax": _clamp_float(area.get("ymax"), 0.98, 0.0, 1.0),
        }
    
    # Fallback to bottom center (common for subtitles)
    return {
        "mode": "default",
        "x": 0.5,
        "y": 0.9 if default_v_align == "bottom" else 0.45,
    }


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
    name: str,
    style: Dict[str, Any],
    fallback_style: Dict[str, Any],
    font_scale: float,
    timeline_width: int,
    timeline_height: int,
    alignment: int,
    is_bg_layer: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """Generate an ASS Style line and return metrics."""
    merged = normalize_text_style(style, fallback_style)
    
    font_family = merged["fontFamily"]
    font_weight = merged["fontWeight"]
    actual_font = resolve_font_family(font_family, font_weight)
    font_size = merged["fontSize"] * font_scale
    letter_spacing = merged["letterSpacing"] * font_scale
    
    # We ignore standard opacity here since ASS manages alpha in colors,
    # but some old projects might rely on global opacity
    opacity = _clamp_float(style.get("opacity", 1.0), 1.0, 0.0, 1.0)
    
    background_enabled = merged["backgroundEnabled"]
    outline_width_raw = merged["outlineWidth"]
    
    if is_bg_layer and background_enabled:
        primary_color = "&HFFFFFFFF"  # Transparent text
        bg_opacity = merged["backgroundOpacity"]
        outline_color = format_ass_color(merged["backgroundColor"], bg_opacity)
        background_color = outline_color
        outline_width = merged["backgroundPaddingX"] * font_scale
        border_style = 3
        shadow_depth = 0.0
    else:
        primary_color = format_ass_color(merged["color"], opacity)
        outline_color = format_ass_color(merged["outlineColor"], opacity)
        background_color = format_ass_color("FFFFFF", 0.0)
        outline_width = outline_width_raw * font_scale
        border_style = 1
        shadow_x = merged["shadowOffsetX"] * font_scale
        shadow_y = merged["shadowOffsetY"] * font_scale
        shadow_blur = merged["shadowBlur"] * font_scale
        glow_blur = merged["glowBlur"] * font_scale if merged["glowEnabled"] else 0.0
        shadow_depth = max(abs(shadow_x), abs(shadow_y), shadow_blur, glow_blur)

    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:40] or "Text"
    line = (
        f"Style: {safe_name},{actual_font},{font_size:.2f},{primary_color},&H000000FF,{outline_color},{background_color},"
        f"{_ass_flag(font_weight >= 700)},{_ass_flag(merged['fontStyle'] == 'italic')},"
        f"{_ass_flag(merged['textDecoration'] == 'underline')},0,100,100,{letter_spacing:.2f},0,"
        f"{border_style},{outline_width:.2f},{shadow_depth:.2f},{alignment},10,10,10,1"
    )
    metrics = {
        "name": safe_name,
        "font": actual_font,
        "font_size": font_size,
        "pixel_font_size": max(8, int(round(font_size))),
        "font_weight": font_weight,
        "letter_spacing": letter_spacing,
        "max_width": max(1.0, timeline_width - 100),
        "line_height": merged["lineHeight"],
        "text_align": merged["textAlign"],
        "vertical_align": merged["verticalAlign"],
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

    merged_style = normalize_text_style(style)
    source_text = _normalized_text(merged_style, str(text or ""))

    # Determine font and size metrics
    font_family = merged_style["fontFamily"]
    font_weight = merged_style["fontWeight"]
    actual_font = resolve_font_family(font_family, font_weight)
    font_size = merged_style["fontSize"] * font_scale
    pixel_font_size = max(8, int(round(font_size)))
    letter_spacing = merged_style["letterSpacing"] * font_scale

    # Determine alignment and positioning
    t_align = merged_style["textAlign"]
    v_align = merged_style["verticalAlign"]
    align_code = get_ass_alignment_code(t_align, v_align)
    align_tag = fr"\an{align_code}"

    # Calculate coordinates and max width
    pos = normalize_text_position(position, area, default_v_align=v_align)
    bg_enabled = merged_style["backgroundEnabled"]
    pad_x = merged_style["backgroundPaddingX"] * font_scale if bg_enabled else 11.0 * font_scale
    pad_y = merged_style["backgroundPaddingY"] * font_scale
    
    if pos["mode"] == "exact":
        pos_x = int(round(pos["x"] * timeline_width))
        pos_y = int(round(pos["y"] * timeline_height))
        max_wrap_width = _clamp_float(merged_style.get("maxWidth"), timeline_width - 100, 1.0, float(timeline_width))
    elif pos["mode"] == "area":
        xmin_px = pos["xmin"] * timeline_width
        xmax_px = pos["xmax"] * timeline_width
        ymin_px = pos["ymin"] * timeline_height
        ymax_px = pos["ymax"] * timeline_height

        box_w = max(1.0, xmax_px - xmin_px)
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
        pos_x = int(round(timeline_width * pos["x"]))
        pos_y = int(round(timeline_height * pos["y"]))
        max_wrap_width = max(1.0, timeline_width * 0.92)

    wrapped_lines = wrap_text_deterministic(source_text, actual_font, pixel_font_size, font_weight, letter_spacing, max_wrap_width)
    wrapped_lines = [escape_ass_text(line) for line in wrapped_lines]
    ass_text_content = r"\N".join(wrapped_lines)

    dialogue_lines: List[str] = []

    # Visual effects
    effect = merged_style["staticEffect"]
    
    bg_enabled = merged_style["backgroundEnabled"]
    bg_radius = merged_style["backgroundRadius"] * font_scale
    
    glow_enabled = merged_style["glowEnabled"]
    glow_blur = merged_style["glowBlur"] * font_scale if glow_enabled else 0.0
    glow_color = merged_style["glowColor"]
    glow_strength = merged_style["glowStrength"]

    sec_outline_w = merged_style["secondaryOutlineWidth"] * font_scale
    sec_outline_c = merged_style["secondaryOutlineColor"]

    outline_w = merged_style["outlineWidth"] * font_scale

    shadow_enabled = merged_style["shadowEnabled"]
    shadow_x = merged_style["shadowOffsetX"] * font_scale
    shadow_y = merged_style["shadowOffsetY"] * font_scale
    shadow_blur = merged_style["shadowBlur"] * font_scale
    shadow_color = merged_style["shadowColor"]

    base_layer = 0
    
    # 0. Background Layer
    if bg_enabled:
        if bg_radius > 0:
            # Draw rounded rectangle using vector shapes
            pad_y = merged_style["backgroundPaddingY"] * font_scale
            w, h = _measure_text_bounding_box(wrapped_lines, actual_font, pixel_font_size, font_weight, letter_spacing, merged_style["lineHeight"])
            w += pad_x * 2
            h += pad_y * 2
            
            vec = _get_rounded_rect_vector(w, h, bg_radius)
            bg_opacity = merged_style["backgroundOpacity"]
            alpha_hex = f"{max(0, min(255, int((1.0 - bg_opacity) * 255))):02X}"
            raw_c = format_ass_color(merged_style["backgroundColor"])
            bgr = raw_c[4:] # skip &HAA
            
            bg_px, bg_py = pos_x, pos_y
            if t_align == "left": bg_px -= pad_x
            elif t_align == "right": bg_px += pad_x
            
            if v_align == "top": bg_py -= pad_y
            elif v_align == "bottom": bg_py += pad_y
            
            bg_override = fr"{{{align_tag}\pos({int(round(bg_px))},{int(round(bg_py))})\1c&H{bgr}&\1a&H{alpha_hex}&\bord0\shad0\p1}}"
            dialogue_lines.append(f"Dialogue: {base_layer},{start_str},{end_str},{style_name},,0,0,0,,{bg_override}{vec}")
        else:
            # Standard BorderStyle=3 rectangle
            bg_override = fr"{{{align_tag}\pos({pos_x},{pos_y})}}"
            dialogue_lines.append(f"Dialogue: {base_layer},{start_str},{end_str},{style_name}_bg,,0,0,0,,{bg_override}{ass_text_content}")
        base_layer += 1

    # 1. Glitch Effect
    if effect == "glitch":
        dx = max(1, int(round(2 * font_scale)))
        dy = max(1, int(round(1 * font_scale)))
        cyan_color = _ass_color_override("#00f5ff")
        pink_color = _ass_color_override(sec_outline_c if sec_outline_c != "#000000" else "#ff2f7d")

        # Top cyan slice
        top_clip = fr"\clip(0,0,{timeline_width},{int(timeline_height * 0.52)})"
        top_override = fr"{{{align_tag}\pos({pos_x - dx},{pos_y}){top_clip}\c{cyan_color}\bord0\shad0}}"
        dialogue_lines.append(f"Dialogue: {base_layer},{start_str},{end_str},{style_name},,0,0,0,,{top_override}{ass_text_content}")

        # Bottom pink slice
        bot_clip = fr"\clip(0,{int(timeline_height * 0.46)},{timeline_width},{timeline_height})"
        bot_override = fr"{{{align_tag}\pos({pos_x + dx},{pos_y + dy}){bot_clip}\c{pink_color}\bord0\shad0}}"
        dialogue_lines.append(f"Dialogue: {base_layer},{start_str},{end_str},{style_name},,0,0,0,,{bot_override}{ass_text_content}")
        base_layer += 1

    # 2. Duotone Effect
    elif effect == "duotone":
        dx = max(1, int(round(4 * font_scale)))
        dy = max(1, int(round(2 * font_scale)))
        dt_color = _ass_color_override(sec_outline_c if sec_outline_c != "#000000" else merged_style.get("shadowColor") or "#e02a34")
        dt_override = fr"{{{align_tag}\pos({pos_x + dx},{pos_y + dy})\c{dt_color}\bord0\shad0}}"
        dialogue_lines.append(f"Dialogue: {base_layer},{start_str},{end_str},{style_name},,0,0,0,,{dt_override}{ass_text_content}")
        base_layer += 1

    # 3. Glow Layer (if enabled and no glitch/duotone)
    if effect not in ("glitch", "duotone"):
        if glow_enabled and glow_blur > 0:
            # Layer 0 for glow: large blur, lower alpha
            g_color_large = _ass_color_override(glow_color, opacity=min(1.0, 0.4 * glow_strength))
            g_bord_large = max(1.0, outline_w + glow_blur * 1.5)
            g_blur_large = max(1.0, glow_blur * 2.0)
            glow_over_large = fr"{{{align_tag}\pos({pos_x},{pos_y})\c{g_color_large}\3c{g_color_large}\bord{g_bord_large:.2f}\blur{g_blur_large:.2f}\shad0}}"
            dialogue_lines.append(f"Dialogue: {base_layer},{start_str},{end_str},{style_name},,0,0,0,,{glow_over_large}{ass_text_content}")
            base_layer += 1
            
            # Layer 1 for glow: tighter blur, higher alpha
            g_color_tight = _ass_color_override(glow_color, opacity=min(1.0, 0.8 * glow_strength))
            g_bord_tight = max(1.0, outline_w + glow_blur * 0.7)
            g_blur_tight = max(1.0, glow_blur)
            glow_over_tight = fr"{{{align_tag}\pos({pos_x},{pos_y})\c{g_color_tight}\3c{g_color_tight}\bord{g_bord_tight:.2f}\blur{g_blur_tight:.2f}\shad0}}"
            dialogue_lines.append(f"Dialogue: {base_layer},{start_str},{end_str},{style_name},,0,0,0,,{glow_over_tight}{ass_text_content}")
            base_layer += 1

    # 4. Shadow Layer
    if shadow_enabled and (abs(shadow_x) > 0 or abs(shadow_y) > 0 or shadow_blur > 0):
        s_pos_x = pos_x + shadow_x
        s_pos_y = pos_y + shadow_y
        s_color = _ass_color_override(shadow_color)
        s_bord = max(1.0, outline_w)
        s_blur_tag = fr"\blur{shadow_blur:.2f}" if shadow_blur > 0 else ""
        shadow_override = fr"{{{align_tag}\pos({s_pos_x},{s_pos_y})\c{s_color}\3c{s_color}\bord{s_bord:.2f}{s_blur_tag}\shad0}}"
        dialogue_lines.append(f"Dialogue: {base_layer},{start_str},{end_str},{style_name},,0,0,0,,{shadow_override}{ass_text_content}")
        base_layer += 1

    # 5. Secondary Outline Layer
    if sec_outline_w > 0:
        sec_color = _ass_color_override(sec_outline_c)
        sec_bord = outline_w + sec_outline_w
        sec_override = fr"{{{align_tag}\pos({pos_x},{pos_y})\3c{sec_color}\bord{sec_bord:.2f}\shad0}}"
        dialogue_lines.append(f"Dialogue: {base_layer},{start_str},{end_str},{style_name},,0,0,0,,{sec_override}{ass_text_content}")
        base_layer += 1

    # Main text layer
    main_override = fr"{{{align_tag}\pos({pos_x},{pos_y})}}"
    dialogue_lines.append(f"Dialogue: {base_layer},{start_str},{end_str},{style_name},,0,0,0,,{main_override}{ass_text_content}")

    return dialogue_lines


def generate_ass_file(
    out_path: Path,
    timeline_width: int,
    timeline_height: int,
    project_canvas_height: float,
    events: List[Dict[str, Any]],
    global_style: Dict[str, Any],
    subtitle_area: Dict[str, Any],
) -> None:
    """Generate a single .ass file for all subtitle and text events."""
    import json
    import hashlib
    
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

    styles_cache: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    
    # Pre-process events to deduplicate styles
    for event in events:
        ev_style = event.get("style") or global_style
        # Stable hash of the style dict
        style_hash = hashlib.md5(json.dumps(ev_style, sort_keys=True).encode("utf-8")).hexdigest()
        
        if style_hash not in styles_cache:
            style_name = f"Style_{len(styles_cache)}"
            
            # Generate the primary style line
            style_line, metrics = _style_line(
                name=style_name,
                style=ev_style,
                fallback_style=global_style,
                font_scale=ass_font_scale,
                timeline_width=timeline_width,
                timeline_height=timeline_height,
                alignment=5, # Overridden per event via \\an
                is_bg_layer=False,
            )
            ass_lines.append(style_line)
            
            # If background is enabled, generate the bg style line
            if metrics["style"]["backgroundEnabled"]:
                bg_style_line, _ = _style_line(
                    name=f"{style_name}_bg",
                    style=ev_style,
                    fallback_style=global_style,
                    font_scale=ass_font_scale,
                    timeline_width=timeline_width,
                    timeline_height=timeline_height,
                    alignment=5,
                    is_bg_layer=True,
                )
                ass_lines.append(bg_style_line)
                
            styles_cache[style_hash] = (style_name, metrics)
            
        event["_style_name"] = styles_cache[style_hash][0]
        event["_style_metrics"] = styles_cache[style_hash][1]

    ass_lines.append("")
    ass_lines.append("[Events]")
    ass_lines.append("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text")

    # Generate dialogues for unified events
    for event in events:
        start = float(event.get("start") or 0.0)
        end = float(event.get("end") or 0.0)
        text = str(event.get("text") or "")
        ev_style = event.get("style") or global_style
        ev_area = event.get("area") or subtitle_area
        ev_pos = event.get("position")
        
        style_name = event["_style_name"]
        style_metrics = event["_style_metrics"]

        dialogues = build_text_dialogues(
            start=start,
            end=end,
            text=text,
            style=ev_style,
            style_name=style_name,
            timeline_width=timeline_width,
            timeline_height=timeline_height,
            font_scale=ass_font_scale,
            area=ev_area,
            position=ev_pos,
            style_metrics=style_metrics,
        )
        ass_lines.extend(dialogues)

    out_path.write_text("\n".join(ass_lines), encoding="utf-8")
