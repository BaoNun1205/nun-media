from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from stitch_studio.image_animation_expr import PRESETS_MAP, evaluate_channel_expr
from stitch_studio.srt import read_srt


DEFAULT_EXPORT_FPS = 30
VALID_FPS = {24, 25, 30, 50, 60}
VALID_RESOLUTIONS = {"720p", "1080p", "1440p", "4K"}
VALID_ASPECT_RATIOS = {"project", "16:9", "9:16", "1:1", "4:3"}
WINDOWS_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
RESOLUTION_HEIGHTS = {"720p": 720, "1080p": 1080, "1440p": 1440, "4K": 2160}
ASPECT_RATIO_VALUES = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0, "4:3": 4 / 3}
ENCODER_CACHE: dict[str, Any] | None = None


@dataclass
class ExportSettings:
    file_name: str
    output_directory: Path
    resolution: str = "1080p"
    aspect_ratio: str = "project"
    fps: int = DEFAULT_EXPORT_FPS


@dataclass
class RenderContext:
    project: Any
    timeline_state: dict[str, Any]
    width: int
    height: int
    fps: int
    duration: float
    output_path: Path
    tracks: list[dict[str, Any]]
    items: list[dict[str, Any]]
    storage: Any
    temp_dir: Path
    primary_video: Any | None = None


class InputRegistry:
    def __init__(self) -> None:
        self.args: list[str] = []
        self.count = 0

    def add(self, path: Path, *prefix: str) -> int:
        index = self.count
        self.args.extend([*prefix, "-i", str(path)])
        self.count += 1
        return index


def sanitize_export_filename(value: str) -> str:
    name = str(value or "").strip()
    if name.lower().endswith(".mp4"):
        name = name[:-4].strip()
    name = name.replace("..", " ")
    name = WINDOWS_INVALID_FILENAME.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        raise ValueError("Filename cannot be empty.")
    reserved = {
        "CON", "PRN", "AUX", "NUL",
        *{f"COM{i}" for i in range(1, 10)},
        *{f"LPT{i}" for i in range(1, 10)},
    }
    if name.upper() in reserved:
        name = f"{name} video"
    return name[:160]


def unique_output_path(directory: Path, file_name: str) -> Path:
    safe_name = sanitize_export_filename(file_name)
    base = directory / f"{safe_name}.mp4"
    if not base.exists():
        return base
    for index in range(1, 1000):
        candidate = directory / f"{safe_name} ({index}).mp4"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not choose a unique output filename.")


def output_dimensions(resolution: str, aspect_ratio: str, canvas: dict[str, Any] | None) -> tuple[int, int]:
    if resolution not in VALID_RESOLUTIONS:
        raise ValueError("Invalid export resolution.")
    if aspect_ratio not in VALID_ASPECT_RATIOS:
        raise ValueError("Invalid aspect ratio.")
    height = RESOLUTION_HEIGHTS[resolution]
    ratio = _project_ratio(canvas) if aspect_ratio == "project" else ASPECT_RATIO_VALUES[aspect_ratio]
    if ratio >= 1:
        width = int(round(height * ratio))
        out_height = height
    else:
        width = height
        out_height = int(round(height / ratio))
    return _even(width), _even(out_height)


def render_project_timeline(
    *,
    project: Any,
    storage: Any,
    config: Any,
    settings: ExportSettings,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to export the project timeline.")
    output_dir = settings.output_directory.expanduser().resolve()
    if not output_dir.exists() or not output_dir.is_dir():
        raise RuntimeError("Output folder does not exist.")
    if not os.access(output_dir, os.W_OK):
        raise RuntimeError("Output folder is not writable.")
    fps = int(settings.fps or DEFAULT_EXPORT_FPS)
    if fps not in VALID_FPS:
        raise RuntimeError("Invalid FPS. Choose 24, 25, 30, 50, or 60.")

    metadata = project.metadata or {}
    timeline_state = metadata.get("timeline_state") if isinstance(metadata.get("timeline_state"), dict) else {}
    items = timeline_state.get("items") or metadata.get("timeline") or []
    tracks = timeline_state.get("tracks") or []
    if not isinstance(items, list) or not items:
        raise RuntimeError("Timeline is empty.")
    if not isinstance(tracks, list):
        tracks = []

    width, height = output_dimensions(settings.resolution, settings.aspect_ratio, timeline_state.get("canvas"))
    active_items = [
        item for item in items
        if isinstance(item, dict) and not item.get("hidden") and _duration(item) > 0 and _start(item) + _duration(item) > 0
    ]
    if not active_items:
        raise RuntimeError("Timeline does not contain any active items.")
    duration = max(_start(item) + _duration(item) for item in active_items)
    output_path = unique_output_path(output_dir, settings.file_name)
    primary_video = storage.get_video(project.primary_video_id) if getattr(project, "primary_video_id", None) else None

    if progress:
        progress("Validating export settings")
    _validate_assets(project, storage, active_items)
    encoder = choose_h264_encoder(ffmpeg)

    with tempfile.TemporaryDirectory(prefix=f"stitch-export-{project.id}-", dir=str(config.outputs_dir)) as tmp:
        ctx = RenderContext(
            project=project,
            timeline_state=timeline_state,
            width=width,
            height=height,
            fps=fps,
            duration=duration,
            output_path=output_path,
            tracks=[track for track in tracks if isinstance(track, dict)],
            items=active_items,
            storage=storage,
            temp_dir=Path(tmp),
            primary_video=primary_video,
        )
        command, passes = build_ffmpeg_command(ffmpeg, ctx, encoder)
        if progress:
            progress("ffmpeg progress: 15% Rendering video")
        proc = _run_ffmpeg_with_progress(command, duration, progress)
        used_encoder = encoder["name"]
        if proc.returncode != 0 and encoder["name"] != "libx264":
            fallback = {"name": "libx264", "args": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]}
            command, passes = build_ffmpeg_command(ffmpeg, ctx, fallback)
            used_encoder = "libx264"
            if progress:
                progress("Hardware encoder failed; retrying with libx264")
            proc = _run_ffmpeg_with_progress(command, duration, progress)
        if proc.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
            output_path.unlink(missing_ok=True)
            raise RuntimeError(f"Could not export timeline: {(proc.stderr or proc.stdout)[-1600:]}")

    render_seconds = max(0.001, time.perf_counter() - started)
    speed = duration / render_seconds if duration > 0 else 0
    if progress:
        progress("Finalizing")
    return {
        "path": str(output_path),
        "fileName": output_path.name,
        "width": width,
        "height": height,
        "fps": fps,
        "duration": duration,
        "encoder": used_encoder,
        "videoEncodePasses": passes,
        "renderSeconds": render_seconds,
        "speedRatio": speed,
    }


def build_ffmpeg_command(ffmpeg: str, ctx: RenderContext, encoder: dict[str, Any]) -> tuple[list[str], int]:
    registry = InputRegistry()
    filters: list[str] = [f"color=c=black:s={ctx.width}x{ctx.height}:r={ctx.fps}:d={ctx.duration:.6f}[vbase0]"]
    current = "[vbase0]"

    visual_items = [
        item for item in _items_in_track_order(ctx)
        if _kind(item) in {"video", "image"} and _visual_enabled(ctx, item)
    ]
    unsupported_effects = [item for item in _items_in_track_order(ctx) if _kind(item) == "effect" and _visual_enabled(ctx, item)]
    if unsupported_effects:
        names = ", ".join(str(item.get("name") or item.get("id") or "effect") for item in unsupported_effects[:3])
        raise RuntimeError(f"Unsupported timeline effect for export: {names}")
    for layer_index, item in enumerate(visual_items):
        source = resolve_timeline_item_source(ctx.project, ctx.storage, item)
        if not source:
            raise RuntimeError(f"Missing media: {item.get('name') or item.get('id')}")
        if _kind(item) == "image":
            current = _add_image_layer(ctx, registry, filters, current, item, source, layer_index)
        else:
            current = _add_video_layer(ctx, registry, filters, current, item, source, layer_index)

    text_label = _add_text_and_subtitle_layers(ctx, filters, current)
    audio_label = _add_audio_layers(ctx, registry, filters)

    command = [ffmpeg, "-y", "-hide_banner", "-nostats", *registry.args, "-filter_complex", ";".join(filters)]
    command.extend(["-map", text_label, "-map", audio_label])
    command.extend([
        "-r", str(ctx.fps),
        *encoder["args"],
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        "-movflags", "+faststart",
        "-progress", "pipe:1",
        str(ctx.output_path),
    ])
    return command, 1


def resolve_timeline_item_source(project: Any, storage: Any, item: dict[str, Any]) -> Path | None:
    project_asset_id = item.get("projectAssetId")
    source_asset_id = item.get("sourceAssetId")
    source_video_id = item.get("sourceVideoId")
    if project_asset_id is not None:
        asset = storage.get_project_asset(int(project_asset_id))
        if asset and asset.project_id == project.id and asset.path.exists():
            return asset.path
    if source_asset_id is not None:
        asset = storage.get_asset(int(source_asset_id))
        if asset and asset.path.exists():
            return asset.path
    if source_video_id is not None:
        video = storage.get_video(int(source_video_id))
        if video and video.path.exists():
            return video.path
    return None


def choose_h264_encoder(ffmpeg: str) -> dict[str, Any]:
    global ENCODER_CACHE
    if ENCODER_CACHE:
        return dict(ENCODER_CACHE)
    candidates = [
        ("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p1", "-cq", "22"]),
        ("h264_qsv", ["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "23"]),
        ("h264_amf", ["-c:v", "h264_amf", "-quality", "speed", "-qp_i", "22", "-qp_p", "22"]),
    ]
    try:
        encoders = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, check=False).stdout
    except Exception:
        encoders = ""
    sink = "NUL" if sys.platform.startswith("win") else "/dev/null"
    for name, args in candidates:
        if name not in encoders:
            continue
        try:
            proc = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=s=16x16:d=0.1", "-frames:v", "1", *args, "-f", "null", sink],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if proc.returncode == 0:
                ENCODER_CACHE = {"name": name, "args": args}
                return dict(ENCODER_CACHE)
        except Exception:
            continue
    ENCODER_CACHE = {"name": "libx264", "args": ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]}
    return dict(ENCODER_CACHE)


def _add_video_layer(ctx: RenderContext, registry: InputRegistry, filters: list[str], current: str, item: dict[str, Any], source: Path, layer_index: int) -> str:
    speed = _speed(item)
    source_duration = _source_duration(item, speed)
    input_index = registry.add(source, "-ss", f"{_source_start(item):.6f}")
    clip = f"[vclip{layer_index}]"
    x, y, scale, rotation, opacity = _base_transform(item)
    chain = [
        f"[{input_index}:v:0]trim=start=0:duration={source_duration:.6f}",
        f"setpts=(PTS-STARTPTS)/{speed:.8f}+{_start(item):.6f}/TB",
        f"fps={ctx.fps}",
        "format=rgba",
        _scale_filter(ctx, scale),
    ]
    if abs(rotation) > 0.001:
        chain.append(f"rotate=a='{rotation:.6f}*PI/180':c=black@0:ow='hypot(iw,ih)':oh='hypot(iw,ih)'")
    if opacity < 0.999:
        chain.append(f"colorchannelmixer=aa={opacity:.6f}")
    filters.append(",".join(chain) + clip)
    out = f"[vbase{layer_index + 1}]"
    filters.append(f"{current}{clip}overlay=x='{ctx.width * x}-w/2':y='{ctx.height * y}-h/2':eof_action=pass:shortest=0:enable='between(t,{_start(item):.6f},{_end(item):.6f})'{out}")
    return out


def _add_image_layer(ctx: RenderContext, registry: InputRegistry, filters: list[str], current: str, item: dict[str, Any], source: Path, layer_index: int) -> str:
    input_index = registry.add(source, "-loop", "1", "-framerate", str(ctx.fps), "-t", f"{_duration(item):.6f}")
    start = _start(item)
    duration = _duration(item)
    x, y, scale, _rotation, opacity = _base_transform(item)
    anim = _animation_expressions(item, start, duration)
    scale_expr = f"{scale:.8f}*{anim['safe_scale']:.8f}*({anim['scale']})"
    clip = f"[vclip{layer_index}]"
    chain = [
        f"[{input_index}:v:0]setpts=PTS-STARTPTS+{start:.6f}/TB",
        "format=rgba",
    ]
    if anim["has_blur"]:
        raise RuntimeError(f"Unsupported image animation for export: blur preset on {item.get('name') or item.get('id')}")
    chain.extend(_image_alpha_fades(item, start, duration))
    chain.append(_scale_filter(ctx, scale_expr))
    if anim["rotation"] != "0.0":
        chain.append(f"rotate=a='({anim['rotation']})*PI/180':c=black@0:ow='hypot(iw,ih)':oh='hypot(iw,ih)'")
    if opacity < 0.999:
        chain.append(f"colorchannelmixer=aa={opacity:.6f}")
    filters.append(",".join(chain) + clip)
    out = f"[vbase{layer_index + 1}]"
    overlay_x = f"({ctx.width}*{x:.8f})-w/2+(({anim['translate_x']})/100)*{ctx.width}"
    overlay_y = f"({ctx.height}*{y:.8f})-h/2+(({anim['translate_y']})/100)*{ctx.height}"
    filters.append(f"{current}{clip}overlay=x='{overlay_x}':y='{overlay_y}':eof_action=pass:shortest=0:enable='between(t,{start:.6f},{_end(item):.6f})'{out}")
    return out


def _add_text_and_subtitle_layers(ctx: RenderContext, filters: list[str], current: str) -> str:
    label = _add_canvas_effects(ctx, filters, current)
    draw_index = 0
    for item in _items_in_track_order(ctx):
        if _kind(item) == "srt" and _visual_enabled(ctx, item):
            label, draw_index = _draw_srt_item(ctx, filters, label, item, draw_index)
        if _kind(item) == "text" and _visual_enabled(ctx, item):
            label, draw_index = _draw_text_item(ctx, filters, label, item, draw_index)
    if label == current:
        out = "[vout]"
        filters.append(f"{current}format=yuv420p{out}")
        return out
    return label


def _add_canvas_effects(ctx: RenderContext, filters: list[str], current: str) -> str:
    metadata = ctx.primary_video.metadata if ctx.primary_video and ctx.primary_video.metadata else {}
    effect = metadata.get("subtitle_blur_effect") if isinstance(metadata.get("subtitle_blur_effect"), dict) else {}
    if not effect.get("enabled"):
        return current
    area = effect.get("area") if isinstance(effect.get("area"), dict) else {}
    try:
        xmin = max(0, min(ctx.width - 2, int(round(ctx.width * float(area["xmin"])))))
        xmax = max(xmin + 2, min(ctx.width, int(round(ctx.width * float(area["xmax"])))))
        ymin = max(0, min(ctx.height - 2, int(round(ctx.height * float(area["ymin"])))))
        ymax = max(ymin + 2, min(ctx.height, int(round(ctx.height * float(area["ymax"])))))
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("Subtitle blur effect has an invalid area.")
    box_width = max(2, xmax - xmin)
    box_height = max(2, ymax - ymin)
    smallest = max(2, min(box_width, box_height))
    radius = max(16, min(90, max(1, (smallest - 1) // 2)))
    chroma_radius = max(8, min(45, max(1, radius // 2)))
    out = "[veffect0]"
    filters.append(
        f"{current}split[blurbase][blurregion];"
        f"[blurregion]crop={box_width}:{box_height}:{xmin}:{ymin},"
        f"boxblur=luma_radius={radius}:luma_power=10:chroma_radius={chroma_radius}:chroma_power=6[blurred];"
        f"[blurbase][blurred]overlay={xmin}:{ymin}{out}"
    )
    return out


def _draw_text_item(ctx: RenderContext, filters: list[str], current: str, item: dict[str, Any], draw_index: int) -> tuple[str, int]:
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    style = params.get("textStyle") if isinstance(params.get("textStyle"), dict) else {}
    position = params.get("textPosition") if isinstance(params.get("textPosition"), dict) else {}
    text = str(params.get("text") or item.get("name") or "Text")
    x = _clamp_float(position.get("x"), 0.5, 0.0, 1.0)
    y = _clamp_float(position.get("y"), 0.45, 0.0, 1.0)
    out = f"[vtext{draw_index}]"
    text_path = _write_text_file(ctx, draw_index, text)
    filters.append(f"{current}{_drawtext_filter(ctx, style, text_path, x, y, _start(item), _end(item), centered=True)}{out}")
    return out, draw_index + 1


def _draw_srt_item(ctx: RenderContext, filters: list[str], current: str, item: dict[str, Any], draw_index: int) -> tuple[str, int]:
    source = resolve_timeline_item_source(ctx.project, ctx.storage, item)
    if not source:
        raise RuntimeError(f"Missing subtitle media: {item.get('name') or item.get('id')}")
    style = _primary_subtitle_style(ctx)
    area = _primary_subtitle_area(ctx)
    vertical = str(style.get("verticalAlign") or "bottom")
    x = (area["xmin"] + area["xmax"]) / 2
    y = area["ymin"] if vertical == "top" else (area["ymin"] + area["ymax"]) / 2 if vertical == "middle" else area["ymax"]
    source_start = _source_start(item)
    item_start = _start(item)
    item_end = _end(item)
    label = current
    for segment in read_srt(source):
        start = item_start + max(0.0, segment.start - source_start)
        end = item_start + max(0.0, segment.end - source_start)
        start = max(item_start, start)
        end = min(item_end, end)
        if end <= start:
            continue
        out = f"[vtext{draw_index}]"
        text_path = _write_text_file(ctx, draw_index, segment.text)
        filters.append(f"{label}{_drawtext_filter(ctx, style, text_path, x, y, start, end, centered=True, vertical=vertical)}{out}")
        label = out
        draw_index += 1
    return label, draw_index


def _add_audio_layers(ctx: RenderContext, registry: InputRegistry, filters: list[str]) -> str:
    sources = []
    for item in _items_in_track_order(ctx):
        if not _audio_enabled(ctx, item):
            continue
        kind = _kind(item)
        if kind not in {"audio", "video"}:
            continue
        if kind == "video" and item.get("sourceAudioMuted"):
            continue
        source = resolve_timeline_item_source(ctx.project, ctx.storage, item)
        if source:
            if _path_has_stream(source, "a:0"):
                sources.append((item, source))
    labels: list[str] = []
    for index, (item, source) in enumerate(sources):
        speed = _speed(item)
        source_duration = _source_duration(item, speed)
        input_index = registry.add(source, "-ss", f"{_source_start(item):.6f}")
        label = f"[aclip{index}]"
        chain = [
            f"[{input_index}:a:0]atrim=start=0:duration={source_duration:.6f}",
            "asetpts=PTS-STARTPTS",
            *_atempo_filters(speed),
            f"volume={_volume_gain(item):.8f}",
        ]
        fade_in = min(_params_float(item, "audioFadeIn"), _duration(item))
        fade_out = min(_params_float(item, "audioFadeOut"), max(0.0, _duration(item) - fade_in))
        if fade_in > 0:
            chain.append(f"afade=t=in:st=0:d={fade_in:.6f}")
        if fade_out > 0:
            chain.append(f"afade=t=out:st={max(0.0, _duration(item) - fade_out):.6f}:d={fade_out:.6f}")
        chain.extend(["aresample=48000", "aformat=channel_layouts=stereo", f"adelay={int(round(_start(item) * 1000))}:all=1"])
        filters.append(",".join(chain) + label)
        labels.append(label)
    if not labels:
        filters.append(f"anullsrc=r=48000:cl=stereo:d={ctx.duration:.6f}[aout]")
    elif len(labels) == 1:
        filters.append(f"{labels[0]}atrim=duration={ctx.duration:.6f},alimiter=limit=0.98[aout]")
    else:
        filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0,atrim=duration={ctx.duration:.6f},alimiter=limit=0.98[aout]")
    return "[aout]"


def _run_ffmpeg_with_progress(command: list[str], duration: float, progress: Callable[[str], None] | None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    output_lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        output_lines.append(line)
        if progress and line.startswith("out_time_ms="):
            try:
                current = float(line.split("=", 1)[1].strip()) / 1_000_000
            except ValueError:
                continue
            percent = 15 + min(80, int((current / max(duration, 0.001)) * 80))
            progress(f"ffmpeg progress: {percent}% Rendering video")
    proc.wait()
    output = "".join(output_lines)
    return subprocess.CompletedProcess(command, proc.returncode, output, output)


def _validate_assets(project: Any, storage: Any, items: list[dict[str, Any]]) -> None:
    for item in items:
        if _kind(item) in {"video", "image", "audio", "srt"}:
            path = resolve_timeline_item_source(project, storage, item)
            if not path:
                raise RuntimeError(f"Missing media: {item.get('name') or item.get('id')}")


def _items_in_track_order(ctx: RenderContext) -> list[dict[str, Any]]:
    order = {str(track.get("id") or ""): index for index, track in enumerate(ctx.tracks)}
    return sorted(ctx.items, key=lambda item: (order.get(str(item.get("track") or ""), 9999), _start(item), str(item.get("id") or "")))


def _visual_enabled(ctx: RenderContext, item: dict[str, Any]) -> bool:
    if item.get("hidden"):
        return False
    track = _track(ctx, item)
    return not (track and track.get("hidden"))


def _audio_enabled(ctx: RenderContext, item: dict[str, Any]) -> bool:
    if item.get("muted") or item.get("hidden"):
        return False
    track = _track(ctx, item)
    return not (track and (track.get("muted") or track.get("hidden")))


def _track(ctx: RenderContext, item: dict[str, Any]) -> dict[str, Any] | None:
    track_id = str(item.get("track") or "")
    return next((track for track in ctx.tracks if str(track.get("id") or "") == track_id), None)


def _animation_expressions(item: dict[str, Any], start: float, duration: float) -> dict[str, Any]:
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    animation = params.get("imageAnimation") if isinstance(params.get("imageAnimation"), dict) else {}
    current = f"(t-{start:.6f})"
    combo_t = f"min(1,max(0,{current}/{max(duration, 0.001):.6f}))"
    in_cfg = animation.get("in") if isinstance(animation.get("in"), dict) else {}
    out_cfg = animation.get("out") if isinstance(animation.get("out"), dict) else {}
    combo_cfg = animation.get("combo") if isinstance(animation.get("combo"), dict) else {}
    in_dur = min(float(in_cfg.get("duration", 0.5) or 0.5), duration)
    out_dur = min(float(out_cfg.get("duration", 0.5) or 0.5), max(0.0, duration - in_dur))
    out_start = duration - out_dur
    in_t = f"min(1,max(0,{current}/{max(in_dur, 0.001):.6f}))"
    out_t = f"min(1,max(0,({current}-{out_start:.6f})/{max(out_dur, 0.001):.6f}))"
    specs = [
        (PRESETS_MAP.get(f"combo:{combo_cfg.get('presetId')}"), combo_t, duration > 0),
        (PRESETS_MAP.get(f"in:{in_cfg.get('presetId')}"), in_t, in_dur > 0),
        (PRESETS_MAP.get(f"out:{out_cfg.get('presetId')}"), out_t, out_dur > 0),
    ]
    scale, tx, ty, rot, opacity, blur = [], [], [], [], [], []
    safe_scale = 1.0
    for spec, t_expr, enabled in specs:
        if not spec or not enabled:
            continue
        channels = spec.get("channels", {})
        if "scale" in channels:
            scale.append(evaluate_channel_expr(channels["scale"], t_expr))
        if "translateX" in channels:
            tx.append(evaluate_channel_expr(channels["translateX"], t_expr))
        if "translateY" in channels:
            ty.append(evaluate_channel_expr(channels["translateY"], t_expr))
        if "rotation" in channels:
            rot.append(evaluate_channel_expr(channels["rotation"], t_expr))
        if "opacity" in channels:
            opacity.append(evaluate_channel_expr(channels["opacity"], t_expr))
        if "blur" in channels:
            blur.append(evaluate_channel_expr(channels["blur"], t_expr))
        safe_scale = max(safe_scale, float(spec.get("safeScale", 1.0) or 1.0))
    return {
        "scale": "*".join(scale) if scale else "1.0",
        "translate_x": "+".join(tx) if tx else "0.0",
        "translate_y": "+".join(ty) if ty else "0.0",
        "rotation": "+".join(rot) if rot else "0.0",
        "opacity": "*".join(opacity) if opacity else "1.0",
        "safe_scale": safe_scale,
        "has_blur": bool(blur),
    }


def _image_alpha_fades(item: dict[str, Any], start: float, duration: float) -> list[str]:
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    animation = params.get("imageAnimation") if isinstance(params.get("imageAnimation"), dict) else {}
    result: list[str] = []
    in_cfg = animation.get("in") if isinstance(animation.get("in"), dict) else {}
    out_cfg = animation.get("out") if isinstance(animation.get("out"), dict) else {}
    in_spec = PRESETS_MAP.get(f"in:{in_cfg.get('presetId')}")
    out_spec = PRESETS_MAP.get(f"out:{out_cfg.get('presetId')}")
    in_dur = min(float(in_cfg.get("duration", 0.5) or 0.5), duration)
    out_dur = min(float(out_cfg.get("duration", 0.5) or 0.5), max(0.0, duration - in_dur))
    if in_spec and "opacity" in in_spec.get("channels", {}) and in_dur > 0:
        result.append(f"fade=t=in:st={start:.6f}:d={in_dur:.6f}:alpha=1")
    if out_spec and "opacity" in out_spec.get("channels", {}) and out_dur > 0:
        result.append(f"fade=t=out:st={start + duration - out_dur:.6f}:d={out_dur:.6f}:alpha=1")
    return result


def _drawtext_filter(ctx: RenderContext, style: dict[str, Any], text_path: Path, x: float, y: float, start: float, end: float, *, centered: bool, vertical: str = "middle") -> str:
    canvas_h = _project_canvas_height(ctx)
    font_size = max(8, int(round(_style_float(style, "fontSize", 42) * ctx.height / canvas_h)))
    font = str(style.get("fontFamily") or "Segoe UI")
    align_y = "y"
    if vertical == "top":
        y_expr = f"{ctx.height * y:.2f}"
    elif vertical == "bottom":
        y_expr = f"{ctx.height * y:.2f}-text_h"
    else:
        y_expr = f"{ctx.height * y:.2f}-text_h/2"
    x_expr = f"{ctx.width * x:.2f}-text_w/2" if centered else f"{ctx.width * x:.2f}"
    color = _style_color(style, "fontColor", _style_color(style, "color", "0xFFFFFF"))
    outline = _style_color(style, "outlineColor", "0x000000")
    border = max(0, int(round(_style_float(style, "outline", _style_float(style, "outlineWidth", 0)))))
    box = "1" if style.get("background") or style.get("backgroundEnabled") else "0"
    box_color = _style_color(style, "backgroundColor", "0x000000")
    box_alpha = _style_float(style, "backgroundOpacity", 0.55)
    escaped_path = _escape_filter_path(text_path)
    return (
        "drawtext="
        f"textfile='{escaped_path}':font='{_escape_filter_text(font)}':fontsize={font_size}:"
        f"fontcolor={color}:borderw={border}:bordercolor={outline}:"
        f"box={box}:boxcolor={box_color}@{box_alpha:.3f}:boxborderw={int(_style_float(style, 'backgroundPaddingX', 8))}:"
        f"x='{x_expr}':{align_y}='{y_expr}':"
        f"enable='between(t,{start:.6f},{end:.6f})'"
    )


def _write_text_file(ctx: RenderContext, index: int, text: str) -> Path:
    path = ctx.temp_dir / f"text_{index}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _project_canvas_height(ctx: RenderContext) -> float:
    canvas = ctx.timeline_state.get("canvas") if isinstance(ctx.timeline_state.get("canvas"), dict) else {}
    return max(16.0, float(canvas.get("height") or ctx.height))


def _primary_subtitle_style(ctx: RenderContext) -> dict[str, Any]:
    metadata = ctx.primary_video.metadata if ctx.primary_video and ctx.primary_video.metadata else {}
    return metadata.get("subtitle_style") if isinstance(metadata.get("subtitle_style"), dict) else {}


def _primary_subtitle_area(ctx: RenderContext) -> dict[str, float]:
    metadata = ctx.primary_video.metadata if ctx.primary_video and ctx.primary_video.metadata else {}
    area = metadata.get("area_ratio") if isinstance(metadata.get("area_ratio"), dict) else None
    if not area:
        return {"xmin": 0.04, "xmax": 0.96, "ymin": 0.60, "ymax": 0.98}
    return {
        "xmin": _clamp_float(area.get("xmin"), 0.04, 0.0, 1.0),
        "xmax": _clamp_float(area.get("xmax"), 0.96, 0.0, 1.0),
        "ymin": _clamp_float(area.get("ymin"), 0.60, 0.0, 1.0),
        "ymax": _clamp_float(area.get("ymax"), 0.98, 0.0, 1.0),
    }


def _scale_filter(ctx: RenderContext, scale: str | float) -> str:
    value = f"{scale:.8f}" if isinstance(scale, float) else str(scale)
    contain = f"min({ctx.width}/iw,{ctx.height}/ih)"
    return f"scale=w='trunc(iw*{contain}*({value})/2)*2':h='trunc(ih*{contain}*({value})/2)*2':eval=frame"


def _atempo_filters(speed: float) -> list[str]:
    values: list[float] = []
    value = max(0.1, min(80.0, speed))
    while value > 2.0:
        values.append(2.0)
        value /= 2.0
    while value < 0.5:
        values.append(0.5)
        value /= 0.5
    values.append(value)
    return [f"atempo={item:.8f}" for item in values if abs(item - 1.0) > 0.0001]


def _base_transform(item: dict[str, Any]) -> tuple[float, float, float, float, float]:
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    transform = params.get("imageTransform") if isinstance(params.get("imageTransform"), dict) else params.get("transform") if isinstance(params.get("transform"), dict) else {}
    return (
        _clamp_float(transform.get("x"), 0.5, 0.0, 1.0),
        _clamp_float(transform.get("y"), 0.5, 0.0, 1.0),
        _clamp_float(transform.get("scale"), 1.0, 0.1, 10.0),
        _clamp_float(transform.get("rotation"), 0.0, -3600.0, 3600.0),
        _clamp_float(item.get("opacity"), 1.0, 0.0, 1.0),
    )


def _volume_gain(item: dict[str, Any]) -> float:
    db = _clamp_float(item.get("volumeDb"), 0.0, -60.0, 20.0)
    return 0.0 if db <= -60.0 else math.pow(10.0, db / 20.0)


def _project_ratio(canvas: dict[str, Any] | None) -> float:
    canvas = canvas if isinstance(canvas, dict) else {}
    width = _clamp_float(canvas.get("width"), 1920.0, 16.0, 16384.0)
    height = _clamp_float(canvas.get("height"), 1080.0, 16.0, 16384.0)
    return width / height


def _style_float(style: dict[str, Any], key: str, default: float) -> float:
    return _clamp_float(style.get(key), default, -10000.0, 10000.0)


def _style_color(style: dict[str, Any], key: str, default: str) -> str:
    raw = str(style.get(key) or default).strip()
    if raw.startswith("#") and len(raw) >= 7:
        return "0x" + raw[1:7]
    if raw.startswith("0x"):
        return raw[:8]
    return default


def _escape_filter_path(path: Path) -> str:
    value = path.resolve().as_posix()
    value = value.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    return value


def _escape_filter_text(value: str) -> str:
    return value.replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")


def _kind(item: dict[str, Any]) -> str:
    return str(item.get("kind") or "").lower()


def _start(item: dict[str, Any]) -> float:
    return _clamp_float(item.get("start"), 0.0, 0.0, 1_000_000.0)


def _duration(item: dict[str, Any]) -> float:
    return _clamp_float(item.get("duration"), 0.05, 0.05, 1_000_000.0)


def _end(item: dict[str, Any]) -> float:
    return _start(item) + _duration(item)


def _source_start(item: dict[str, Any]) -> float:
    return _clamp_float(item.get("sourceStart"), 0.0, 0.0, 1_000_000.0)


def _source_duration(item: dict[str, Any], speed: float) -> float:
    duration = max(0.05, _duration(item) * max(0.1, speed))
    if item.get("sourceEnd") is not None:
        duration = min(duration, max(0.05, _clamp_float(item.get("sourceEnd"), _source_start(item) + duration, 0.0, 1_000_000.0) - _source_start(item)))
    return duration


def _speed(item: dict[str, Any]) -> float:
    return _clamp_float(item.get("speed"), 1.0, 0.1, 80.0)


def _params_float(item: dict[str, Any], key: str) -> float:
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    return _clamp_float(params.get(key), 0.0, 0.0, 1_000_000.0)


def _clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return max(minimum, min(maximum, number))


def _even(value: int) -> int:
    value = max(2, int(round(value)))
    return value if value % 2 == 0 else value + 1


def _path_has_stream(path: Path, stream: str) -> bool:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                stream,
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
        return proc.returncode == 0 and bool(proc.stdout.strip())
    except Exception:
        return False
