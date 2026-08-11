"""
Quick integration test for template timing resolution.
Simulates the exact bug scenario:
  - Template saved with audio=26:15, image=26:15, SRT=26:15
  - New audio = 12:00 (720s)
  - Expected: everything resolves to ~12:00, not 26:15
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STITCH_ROOT = ROOT / "stitch_studio"
if str(STITCH_ROOT) not in sys.path:
    sys.path.insert(0, str(STITCH_ROOT))

from stitch_studio.template_timing import resolve_template_timing, migrate_manifest_timing

# Simulate a legacy v1 template manifest (NO templateTiming, NO durationPolicy)
TEMPLATE_AUDIO_DURATION = 26 * 60 + 15  # 26:15 = 1575s
NEW_AUDIO_DURATION = 12 * 60  # 12:00 = 720s

manifest_v1 = {
    "version": 1,
    "name": "Test Template",
    "inputs": [
        {"slotId": "audio-slot-1", "kind": "audio", "label": "Audio", "required": True, "behavior": "replace"},
        {"slotId": "image-slot-1", "kind": "image", "label": "Image", "required": True, "behavior": "replace"},
    ],
    "generated": [
        {"kind": "subtitle", "source": {"type": "srt-from-audio", "slotId": "audio-slot-1"}}
    ],
    "timelineTemplate": {
        "items": [
            {
                "id": "item-audio-1",
                "kind": "audio",
                "track": "A1",
                "name": "Narration",
                "start": 0,
                "duration": TEMPLATE_AUDIO_DURATION,
                "sourceStart": 0,
                "sourceDuration": TEMPLATE_AUDIO_DURATION,
                "templateSource": {"type": "media-slot", "slotId": "audio-slot-1"},
            },
            {
                "id": "item-image-1",
                "kind": "image",
                "track": "V1",
                "name": "Background",
                "start": 0,
                "duration": TEMPLATE_AUDIO_DURATION,
                "templateSource": {"type": "media-slot", "slotId": "image-slot-1"},
            },
            {
                "id": "item-srt-1",
                "kind": "srt",
                "track": "S1",
                "name": "Subtitles",
                "start": 0,
                "duration": TEMPLATE_AUDIO_DURATION,
                "templateSource": {"type": "generated-srt"},
            },
            {
                "id": "item-title-1",
                "kind": "text",
                "track": "V1",
                "name": "Intro Title",
                "start": 0,
                "duration": 3,  # 3-second fixed title
            },
        ],
        "timelineState": {"version": 2, "fps": 30, "items": []},
        "sceneState": {},
    }
}

slot_metadata = {
    "audio-slot-1": {"duration": NEW_AUDIO_DURATION},
    # image-slot-1 has no duration (images don't have duration)
}

print("=" * 60)
print("TEST: Legacy v1 manifest migration + timing resolution")
print("=" * 60)
print(f"Template audio duration: {TEMPLATE_AUDIO_DURATION}s ({TEMPLATE_AUDIO_DURATION/60:.0f}:{TEMPLATE_AUDIO_DURATION%60:02.0f})")
print(f"New audio duration:      {NEW_AUDIO_DURATION}s ({NEW_AUDIO_DURATION/60:.0f}:{NEW_AUDIO_DURATION%60:02.0f})")
print()

# Step 1: Test migration
migrated = migrate_manifest_timing(manifest_v1)
print("--- After migration ---")
for item in migrated["timelineTemplate"]["items"]:
    mode = item.get("templateTiming", {}).get("durationMode", "???")
    print(f"  {item['name']:20s}  kind={item['kind']:6s}  durationMode={mode}")
print(f"  durationPolicy.driverSlotId = {migrated.get('durationPolicy', {}).get('driverSlotId')}")
print()

assert migrated["durationPolicy"]["driverSlotId"] == "audio-slot-1", "Driver should be audio-slot-1"

# Check modes
item_modes = {item["id"]: item.get("templateTiming", {}).get("durationMode") for item in migrated["timelineTemplate"]["items"]}
assert item_modes["item-audio-1"] == "media", f"Audio should be 'media', got {item_modes['item-audio-1']}"
assert item_modes["item-image-1"] == "project", f"Image (full-project) should be 'project', got {item_modes['item-image-1']}"
assert item_modes["item-srt-1"] == "generated", f"SRT should be 'generated', got {item_modes['item-srt-1']}"
assert item_modes["item-title-1"] == "fixed", f"Title should be 'fixed', got {item_modes['item-title-1']}"
print("Migration modes: PASS")

# Step 2: Test resolution
result = resolve_template_timing(manifest_v1, slot_metadata, TEMPLATE_AUDIO_DURATION)
print()
print("--- After resolution ---")
print(f"  masterDuration = {result['masterDuration']}s")
for item in result["resolvedItems"]:
    print(f"  {item['name']:20s}  start={item['start']:.1f}  duration={item['duration']:.1f}")

assert abs(result["masterDuration"] - NEW_AUDIO_DURATION) < 1.0, \
    f"Master duration should be ~{NEW_AUDIO_DURATION}, got {result['masterDuration']}"

for item in result["resolvedItems"]:
    if item["id"] == "item-audio-1":
        assert abs(item["duration"] - NEW_AUDIO_DURATION) < 1.0, \
            f"Audio duration should be ~{NEW_AUDIO_DURATION}, got {item['duration']}"
    elif item["id"] == "item-image-1":
        assert abs(item["duration"] - NEW_AUDIO_DURATION) < 1.0, \
            f"Image (project) duration should be ~{NEW_AUDIO_DURATION}, got {item['duration']}"
    elif item["id"] == "item-srt-1":
        assert abs(item["duration"] - NEW_AUDIO_DURATION) < 1.0, \
            f"SRT (generated) duration should be ~{NEW_AUDIO_DURATION}, got {item['duration']}"
    elif item["id"] == "item-title-1":
        assert abs(item["duration"] - 3) < 0.1, \
            f"Title (fixed) duration should be ~3, got {item['duration']}"

print()
print("Resolution durations: PASS")

# Step 3: Test with LONGER audio
print()
print("=" * 60)
print("TEST: Longer audio (40 min)")
print("=" * 60)
LONG_AUDIO = 40 * 60
result2 = resolve_template_timing(manifest_v1, {"audio-slot-1": {"duration": LONG_AUDIO}}, TEMPLATE_AUDIO_DURATION)
print(f"  masterDuration = {result2['masterDuration']}s = {result2['masterDuration']/60:.0f} min")
for item in result2["resolvedItems"]:
    print(f"  {item['name']:20s}  start={item['start']:.1f}  duration={item['duration']:.1f}")

assert abs(result2["masterDuration"] - LONG_AUDIO) < 1.0, \
    f"Master duration should be ~{LONG_AUDIO}, got {result2['masterDuration']}"

for item in result2["resolvedItems"]:
    if item["id"] == "item-audio-1":
        assert abs(item["duration"] - LONG_AUDIO) < 1.0
    elif item["id"] == "item-image-1":
        assert abs(item["duration"] - LONG_AUDIO) < 1.0
    elif item["id"] == "item-title-1":
        assert abs(item["duration"] - 3) < 0.1

print()
print("Longer audio: PASS")
print()
print("=" * 60)
print("ALL TIMING TESTS PASSED!")
print("=" * 60)
