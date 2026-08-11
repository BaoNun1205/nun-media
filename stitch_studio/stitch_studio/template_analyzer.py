import json
from typing import Any, Dict, List, Optional
import uuid

from .template_timing import infer_timing_policy

def _sanitize_media_identity(obj: Any):
    """Recursively removes asset identity references to prevent stale bindings."""
    if isinstance(obj, dict):
        obj.pop("projectAssetId", None)
        obj.pop("sourceAssetId", None)
        obj.pop("sourceVideoId", None)
        if obj.get("kind") == "srt":
            obj.pop("segments", None)
            obj.pop("text", None)
        for v in obj.values():
            _sanitize_media_identity(v)
    elif isinstance(obj, list):
        for item in obj:
            _sanitize_media_identity(item)

def analyze_template_from_project(project: Any, storage: Any) -> Dict[str, Any]:
    """
    Analyzes a Workspace Project and its timeline to produce a Template Manifest.
    """
    metadata = project.metadata or {}
    timeline = metadata.get("timeline", [])
    
    # Deep copy state so we don't accidentally mutate the project in-memory
    timeline_state = json.loads(json.dumps(metadata.get("timeline_state", {})))
    scene_state = json.loads(json.dumps(metadata.get("scene_state", {})))
    
    # Analyze media sources used in timeline
    # We will deduplicate based on projectAssetId
    slot_map: Dict[int, str] = {}
    inputs: List[Dict[str, Any]] = []
    
    image_count = 0
    video_count = 0
    audio_count = 0
    
    # First pass: identify unique media inputs
    for item in timeline:
        kind = item.get("kind")
        if kind not in {"image", "video", "audio"}:
            continue
        
        asset_id = item.get("projectAssetId")
        if not asset_id:
            continue
            
        if asset_id not in slot_map:
            # Generate a new slot
            if kind == "image":
                image_count += 1
                slot_id = f"image-slot-{image_count}"
                label = f"Image {image_count}" if image_count > 1 else "Image"
            elif kind == "video":
                video_count += 1
                slot_id = f"video-slot-{video_count}"
                label = f"Video {video_count}" if video_count > 1 else "Video"
            elif kind == "audio":
                audio_count += 1
                slot_id = f"audio-slot-{audio_count}"
                label = f"Audio {audio_count}" if audio_count > 1 else "Audio"
            else:
                continue

            # We could append name to label from DB
            pa_row = storage.conn.execute("SELECT * FROM project_assets WHERE id = ?", (asset_id,)).fetchone()
            if pa_row:
                name = pa_row["name"]
            
            slot_map[asset_id] = slot_id
            inputs.append({
                "slotId": slot_id,
                "kind": kind,
                "label": label,
                "required": True,
                "behavior": "replace",
                "sourceProjectAssetId": asset_id
            })

    # Second pass: transform timeline items to template items
    template_timeline: List[Dict[str, Any]] = []
    has_srt = False
    for item in timeline:
        t_item = json.loads(json.dumps(item))
        kind = t_item.get("kind")
        
        if kind in {"image", "video", "audio"}:
            asset_id = t_item.get("projectAssetId")
            if asset_id:
                slot_id = slot_map.get(asset_id)
                if slot_id:
                    t_item["templateSource"] = {
                        "type": "media-slot",
                        "slotId": slot_id
                    }
        
        if kind == "srt":
            has_srt = True
            t_item["templateSource"] = {
                "type": "generated-srt"
            }
                
        template_timeline.append(t_item)

    # Build generated rules FIRST (needed for timing inference)
    generated: List[Dict[str, Any]] = []
    if has_srt:
        srt_source_slot = None
        audio_slots = [s["slotId"] for s in inputs if s["kind"] == "audio"]
        if len(audio_slots) == 1:
            srt_source_slot = audio_slots[0]
            
        generated.append({
            "kind": "subtitle",
            "source": {
                "type": "srt-from-audio",
                "slotId": srt_source_slot
            }
        })

    # Infer timing policy (pass generated rules for driver detection)
    project_duration = max([float(item.get("start", 0)) + float(item.get("duration", 0)) for item in template_timeline] + [0])
    timing_info = infer_timing_policy(template_timeline, project_duration, inputs, generated)
    
    for item in template_timeline:
        item_id = item.get("id")
        if item_id and item_id in timing_info["timingMap"]:
            item["templateTiming"] = timing_info["timingMap"][item_id]

    subtitle_style = metadata.get("subtitle_style")
    subtitle_area = metadata.get("subtitle_area")
    
    # Fallback to primary video metadata if the user set styles before creating the workspace project
    if (subtitle_style is None or subtitle_area is None) and getattr(project, "primary_video_id", None):
        video = storage.get_video(project.primary_video_id)
        if video and video.metadata:
            if subtitle_style is None:
                subtitle_style = video.metadata.get("subtitle_style")
            if subtitle_area is None:
                subtitle_area = video.metadata.get("subtitle_area")

    if "items" in timeline_state:
        timeline_state["items"] = template_timeline

    # Recursively sanitize all identity references out of the reusable states
    _sanitize_media_identity(template_timeline)
    _sanitize_media_identity(timeline_state)
    _sanitize_media_identity(scene_state)

    manifest = {
        "version": 2, # Bump version for new timing semantics
        "name": project.title + " Template",
        "sourceProjectId": project.id,
        "inputs": inputs,
        "generated": generated,
        "durationPolicy": timing_info["durationPolicy"],
        "timelineTemplate": {
            "items": template_timeline,
            "timelineState": timeline_state,
            "sceneState": scene_state,
            "subtitleStyle": subtitle_style,
            "subtitleArea": subtitle_area,
        }
    }
    
    return manifest
