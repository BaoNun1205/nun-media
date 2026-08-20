"""Timeline video-effects registry and native FFmpeg filter builders.

The editable schema lives in ``frontend/src/config/videoEffects.json`` so the
inspector and the renderer validate the same effect ids/defaults.  This module
contains only renderer-specific FFmpeg translation.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "stitch_studio_web" / "frontend" / "src" / "config" / "videoEffects.json"


def load_effect_registry() -> dict[str, dict[str, Any]]:
    try:
        entries = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Video effect registry is unavailable.") from exc
    if not isinstance(entries, list):
        raise RuntimeError("Video effect registry is invalid.")
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            result[entry["id"]] = entry
    return result


def effect_id(item: dict[str, Any]) -> str:
    params = item.get("params") if isinstance(item.get("params"), dict) else {}
    return str(params.get("effectId") or params.get("id") or item.get("effectId") or "").strip().lower()


def normalized_effect_params(item: dict[str, Any], registry: dict[str, dict[str, Any]] | None = None) -> tuple[str, dict[str, float]]:
    registry = registry or load_effect_registry()
    identifier = effect_id(item)
    spec = registry.get(identifier)
    if not spec:
        raise ValueError(f"Unknown timeline effect: {identifier or item.get('name') or item.get('id')}")
    raw = item.get("params") if isinstance(item.get("params"), dict) else {}
    values: dict[str, float] = {}
    for parameter in spec.get("params") or []:
        if not isinstance(parameter, dict) or not isinstance(parameter.get("key"), str):
            continue
        key = parameter["key"]
        default = _number(parameter.get("default"), 0.0)
        minimum = _number(parameter.get("min"), -1_000_000.0)
        maximum = _number(parameter.get("max"), 1_000_000.0)
        values[key] = max(minimum, min(maximum, _number(raw.get(key), default)))
    return identifier, values


def add_timeline_effects(filters: list[str], current: str, effects: list[dict[str, Any]], *, width: int, height: int, fps: int) -> str:
    """Append ordered, time-bounded canvas effects and return the final label."""
    registry = load_effect_registry()
    output = current
    for index, item in enumerate(effects):
        identifier, params = normalized_effect_params(item, registry)
        start = _number(item.get("start"), 0.0)
        duration = max(0.05, _number(item.get("duration"), 0.05))
        end = start + duration
        enable = f"enable='between(t,{start:.6f},{end:.6f})'"
        out = f"[vfx{index}]"
        seed = int(params.get("seed", 1))
        intensity = params.get("intensity", params.get("amount", 0.3))
        if identifier == "film_grain":
            filters.append(f"{output}noise=alls={max(1, round(3 + intensity * 32))}:allf=t+u:all_seed={seed}:{enable}{out}")
        elif identifier == "vignette":
            filters.append(f"{output}vignette=angle={0.2 + intensity * 1.35:.5f}:mode=forward:eval=frame:{enable}{out}")
        elif identifier == "snow":
            layer = f"[fxsnow{index}]"
            threshold = 1 + round(intensity * 9)
            filters.append(
                f"nullsrc=s={width}x{height}:r={fps}:d={duration:.6f},"
                f"geq=lum='if(lt(random({seed}),{threshold}/1000),255,0)':cb=128:cr=128,"
                f"format=rgba,colorkey=0x000000:0.01:0.0,boxblur=1:1{layer}"
            )
            filters.append(f"{output}{layer}overlay=x=0:y=0:eof_action=pass:shortest=0:{enable}{out}")
        elif identifier == "rain":
            layer = f"[fxrain{index}]"
            spacing = max(18, int(96 - intensity * 62))
            speed = 90 + params.get("speed", 0.5) * 420
            filters.append(
                f"nullsrc=s={width}x{height}:r={fps}:d={duration:.6f},"
                f"geq=lum='if(lt(mod(X+Y*0.35+T*{speed:.2f},{spacing}),{1 + intensity * 2:.2f}),220,0)':cb=128:cr=128,"
                f"format=rgba,colorkey=0x000000:0.01:0.0{layer}"
            )
            filters.append(f"{output}{layer}overlay=x=0:y=0:eof_action=pass:shortest=0:{enable}{out}")
        elif identifier == "dust":
            warmth = params.get("warmth", 0.5)
            color = "0x%02x%02x%02x" % (int(180 + warmth * 55), int(188 + warmth * 30), int(195 - warmth * 75))
            layer = f"[fxdust{index}]"
            filters.append(f"color=c={color}@{0.025 + intensity * .16:.4f}:s={width}x{height}:r={fps}:d={duration:.6f},format=rgba{layer}")
            filters.append(f"{output}{layer}overlay=x=0:y=0:eof_action=pass:shortest=0:{enable}{out}")
        elif identifier == "vhs":
            shift = max(1, round(1 + intensity * 5))
            filters.append(f"{output}rgbashift=rh={shift}:bh=-{shift}:edge=wrap,noise=alls={max(2, round(5 + intensity * 22))}:allf=t+u:all_seed={seed}:{enable}{out}")
        elif identifier == "scanlines":
            spacing = int(params.get("spacing", 4))
            alpha = 0.05 + intensity * .45
            filters.append(f"{output}drawgrid=w=iw:h={spacing}:t=1:c=black@{alpha:.4f}:{enable}{out}")
        elif identifier == "rgb_split":
            shift = max(1, round(params.get("amount", 0.3) * 12))
            filters.append(f"{output}rgbashift=rh={shift}:bh=-{shift}:edge=wrap:{enable}{out}")
        elif identifier == "glitch":
            shift = max(1, round(2 + intensity * 9))
            filters.append(f"{output}rgbashift=rh={shift}:gv=-{shift}:bh={-shift}:edge=wrap,noise=alls={max(2, round(8 + intensity * 30))}:allf=t+u:all_seed={seed}:{enable}{out}")
        elif identifier == "glow":
            radius = 1 + params.get("radius", 0.35) * 12
            base, blurred = f"[fxbase{index}]", f"[fxblur{index}]"
            filters.append(f"{output}split=2{base}{blurred}")
            filters.append(f"{blurred}gblur=sigma={radius:.4f}[fxglow{index}]")
            filters.append(f"{base}[fxglow{index}]blend=all_mode=screen:all_opacity={0.1 + intensity * .65:.4f}:{enable}{out}")
        else:  # Kept defensive in case the schema gains an id without a renderer.
            raise ValueError(f"Unsupported timeline effect renderer: {identifier}")
        output = out
    return output


def _number(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default
