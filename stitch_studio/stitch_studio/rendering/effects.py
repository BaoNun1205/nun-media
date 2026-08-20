"""Effect-schema validation shared with the WebGPU client runtime.

Visual rendering intentionally lives in the browser WebGPU runtime. This module
does not translate effects to FFmpeg: doing so would silently render a different
effect from the Program Monitor.
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
    return {entry["id"]: entry for entry in entries if isinstance(entry, dict) and isinstance(entry.get("id"), str)}


def normalized_effect_params(item: dict[str, Any], registry: dict[str, dict[str, Any]] | None = None) -> tuple[str, dict[str, float]]:
    registry = registry or load_effect_registry()
    raw = item.get("params") if isinstance(item.get("params"), dict) else {}
    identifier = str(raw.get("effectId") or raw.get("id") or item.get("effectId") or "").strip().lower()
    spec = registry.get(identifier)
    if not spec:
        raise ValueError(f"Unknown timeline effect: {identifier or item.get('name') or item.get('id')}")
    values: dict[str, float] = {}
    for parameter in spec.get("params") or []:
        key = parameter.get("key") if isinstance(parameter, dict) else None
        if not isinstance(key, str):
            continue
        default = _number(parameter.get("default"), 0.0)
        values[key] = max(_number(parameter.get("min"), -1e6), min(_number(parameter.get("max"), 1e6), _number(raw.get(key), default)))
    return identifier, values


def _number(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default
