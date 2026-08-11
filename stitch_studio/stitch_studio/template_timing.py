"""
Template Timing Service
=======================
Responsible for:
  1. Inferring timing policies when saving a template  (infer_timing_policy)
  2. Migrating legacy v1 manifests to include timing    (migrate_manifest_timing)
  3. Resolving timeline durations at instantiation time  (resolve_template_timing)
"""
import json
from typing import Any, Dict, List, Optional

# Tolerance for float comparisons (≈2 frames at 30fps or 50ms)
TOLERANCE = 0.1


def infer_timing_policy(
    timeline: List[Dict[str, Any]],
    project_duration: float,
    inputs: List[Dict[str, Any]],
    generated: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Analyzes the original project timeline and assigns each item a durationMode.
    Also determines the global durationPolicy (which slot drives project duration).

    durationMode values:
      "media"     – duration follows the new media file for this slot
      "project"   – duration follows the new master/project duration
      "fixed"     – keeps absolute duration from template
      "generated" – duration will be determined by generated content (e.g. SRT)
    """
    generated = generated or []

    # --- Determine driver slot ---
    # If we have a generated SRT rule, the audio slot it uses is the strongest candidate.
    driver_slot_id = None
    for gen in generated:
        src = gen.get("source", {})
        if src.get("type") == "srt-from-audio" and src.get("slotId"):
            driver_slot_id = src["slotId"]
            break

    # Fallback: first audio slot
    if not driver_slot_id:
        for inp in inputs:
            if inp.get("kind") == "audio":
                driver_slot_id = inp.get("slotId")
                break

    # Fallback: first video slot
    if not driver_slot_id:
        for inp in inputs:
            if inp.get("kind") == "video":
                driver_slot_id = inp.get("slotId")
                break

    # --- Build slot lookup for quick reference ---
    # Map slotId → kind from inputs
    slot_kind_map: Dict[str, str] = {}
    for inp in inputs:
        slot_kind_map[inp.get("slotId", "")] = inp.get("kind", "")

    # --- Classify each item ---
    timing_map: Dict[str, Dict[str, Any]] = {}

    for item in timeline:
        item_id = item.get("id")
        if not item_id:
            continue

        kind = item.get("kind")
        start = float(item.get("start", 0))
        duration = float(item.get("duration", 0))
        end = start + duration

        mode = "fixed"  # default: keep absolute timing

        # --- Generated SRT ---
        ts = item.get("templateSource")
        if kind == "srt" or (isinstance(ts, dict) and ts.get("type") == "generated-srt"):
            mode = "generated"

        # --- Media slots (Audio / Video) ---
        elif kind in {"audio", "video"}:
            if isinstance(ts, dict) and ts.get("type") == "media-slot":
                mode = "media"

        # --- Project-duration visuals ---
        # An image/text/overlay that spans (nearly) the full project is "project" mode.
        elif kind in {"image", "text", "overlay"}:
            if project_duration > 0 and start <= TOLERANCE and abs(end - project_duration) <= TOLERANCE:
                mode = "project"

        timing_map[item_id] = {"durationMode": mode}

    return {
        "timingMap": timing_map,
        "durationPolicy": {
            "driverSlotId": driver_slot_id,
        },
    }


def migrate_manifest_timing(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """
    For legacy v1 manifests that don't have templateTiming on items or
    durationPolicy on the manifest, infer them on-the-fly so instantiation
    works correctly.

    Returns a *new* manifest dict (does not mutate the original).
    """
    manifest = json.loads(json.dumps(manifest))  # deep copy

    items = manifest.get("timelineTemplate", {}).get("items", [])
    inputs = manifest.get("inputs", [])
    generated = manifest.get("generated", [])

    # Check if any item already has templateTiming
    has_timing = any(item.get("templateTiming") for item in items)
    has_policy = "durationPolicy" in manifest

    if has_timing and has_policy:
        return manifest  # already migrated

    # Calculate original project duration from items
    project_duration = max(
        [float(item.get("start", 0)) + float(item.get("duration", 0)) for item in items] + [0]
    )

    timing_info = infer_timing_policy(items, project_duration, inputs, generated)

    # Apply templateTiming to each item
    for item in items:
        item_id = item.get("id")
        if item_id and item_id in timing_info["timingMap"]:
            item["templateTiming"] = timing_info["timingMap"][item_id]

    # Apply durationPolicy to manifest
    manifest["durationPolicy"] = timing_info["durationPolicy"]

    return manifest


def resolve_template_timing(
    manifest: Dict[str, Any],
    slot_metadata: Dict[str, Dict[str, Any]],
    original_project_duration: float,
) -> Dict[str, Any]:
    """
    Given a manifest (with templateTiming on items and durationPolicy),
    and actual new media durations, resolve the final timeline.

    slot_metadata: { slot_id: {"duration": float (seconds), ...} }

    Returns: {
        "masterDuration": float,
        "resolvedItems": List[Dict]
    }
    """
    # --- Step 1: Ensure timing info exists (handle legacy manifests) ---
    manifest = migrate_manifest_timing(manifest)

    # --- Step 2: Determine new master duration ---
    duration_policy = manifest.get("durationPolicy", {})
    driver_slot_id = duration_policy.get("driverSlotId")

    new_master_duration = original_project_duration

    if driver_slot_id and driver_slot_id in slot_metadata:
        driver_dur = slot_metadata[driver_slot_id].get("duration", 0)
        if driver_dur > 0:
            new_master_duration = driver_dur
    else:
        # Fallback: use max duration across all media slots
        durations = [m.get("duration", 0) for m in slot_metadata.values() if m.get("duration", 0) > 0]
        if durations:
            new_master_duration = max(durations)

    # --- Step 3: Resolve each item ---
    items = manifest.get("timelineTemplate", {}).get("items", [])
    resolved_items: List[Dict[str, Any]] = []

    for item in items:
        new_item = json.loads(json.dumps(item))  # deep copy
        timing = new_item.get("templateTiming", {})
        mode = timing.get("durationMode", "fixed")

        start = float(new_item.get("start", 0))
        duration = float(new_item.get("duration", 0))

        if mode == "media":
            # Find the slot this item uses
            src = new_item.get("templateSource", {})
            if isinstance(src, dict) and src.get("type") == "media-slot":
                slot_id = src.get("slotId")
                if slot_id and slot_id in slot_metadata:
                    new_media_dur = slot_metadata[slot_id].get("duration", 0)
                    if new_media_dur > 0:
                        source_start = float(new_item.get("sourceStart", 0))
                        new_duration = max(0, new_media_dur - source_start)

                        new_item["duration"] = new_duration
                        new_item["sourceDuration"] = new_media_dur
                        # Update sourceEnd if it was present (meaning "end of file")
                        if "sourceEnd" in new_item:
                            new_item["sourceEnd"] = source_start + new_duration

        elif mode == "project":
            new_duration = max(0, new_master_duration - start)
            new_item["duration"] = new_duration

        elif mode == "generated":
            # Tentatively set to master duration; will be overwritten when SRT completes
            new_duration = max(0, new_master_duration - start)
            new_item["duration"] = new_duration

        elif mode == "fixed":
            pass  # keep original start/duration

        resolved_items.append(new_item)

    # --- Step 4: Calculate actual project duration from resolved items ---
    actual_project_duration = 0.0
    for item in resolved_items:
        item_end = float(item.get("start", 0)) + float(item.get("duration", 0))
        actual_project_duration = max(actual_project_duration, item_end)

    return {
        "masterDuration": actual_project_duration,
        "resolvedItems": resolved_items,
    }
