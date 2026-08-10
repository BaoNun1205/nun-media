import json
from typing import Any, Dict, List, Optional
import uuid

def analyze_template_from_project(project: Any, storage: Any) -> Dict[str, Any]:
    """
    Analyzes a Workspace Project and its timeline to produce a Template Manifest.
    """
    metadata = project.metadata or {}
    timeline = metadata.get("timeline", [])
    timeline_state = metadata.get("timeline_state", {})
    scene_state = metadata.get("scene_state", {})
    
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
        t_item = dict(item)
        kind = t_item.get("kind")
        
        if kind in {"image", "video", "audio"} and "projectAssetId" in t_item:
            asset_id = t_item.pop("projectAssetId")
            slot_id = slot_map.get(asset_id)
            if slot_id:
                t_item["templateSource"] = {
                    "type": "media-slot",
                    "slotId": slot_id
                }
        
        if kind == "srt":
            has_srt = True
            if "projectAssetId" in t_item:
                t_item.pop("projectAssetId")
            
            t_item["templateSource"] = {
                "type": "generated-srt"
            }
            if "segments" in t_item:
                t_item.pop("segments")
                
        template_timeline.append(t_item)

    generated: List[Dict[str, Any]] = []
    if has_srt:
        srt_source_slot = None
        audio_slots = [s["slotId"] for s in inputs if s["kind"] == "audio"]
        if len(audio_slots) >= 1:
            srt_source_slot = audio_slots[0]
            
        generated.append({
            "kind": "subtitle",
            "source": {
                "type": "srt-from-audio",
                "slotId": srt_source_slot
            }
        })

    subtitle_style = metadata.get("subtitle_style")
    subtitle_area = metadata.get("subtitle_area")

    manifest = {
        "version": 1,
        "name": project.title + " Template",
        "sourceProjectId": project.id,
        "inputs": inputs,
        "generated": generated,
        "timelineTemplate": {
            "items": template_timeline,
            "timelineState": timeline_state,
            "sceneState": scene_state,
            "subtitleStyle": subtitle_style,
            "subtitleArea": subtitle_area,
        }
    }
    
    return manifest
