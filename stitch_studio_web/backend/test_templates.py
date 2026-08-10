import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STITCH_ROOT = ROOT / "stitch_studio"
if str(STITCH_ROOT) not in sys.path:
    sys.path.insert(0, str(STITCH_ROOT))

from stitch_studio.storage import Storage

def run_test():
    # Use a temporary DB for tests
    db_path = Path("test_templates.sqlite")
    if db_path.exists():
        db_path.unlink()
        
    storage = Storage(db_path)
    
    project = storage.create_project("Test Proj", [])
    project_id = project.id

    # Test CREATE
    manifest = {
        "version": 1,
        "name": "My Temp",
        "sourceProjectId": project_id,
        "inputs": [
            {"slotId": "image-slot-1", "kind": "image", "label": "Image"}
        ],
        "generated": [],
        "timelineTemplate": {
            "items": [],
            "timelineState": {"canvas": {"width": 1080, "height": 1920}, "fps": 30},
            "sceneState": {}
        }
    }
    
    template = storage.create_template("My Template", project_id, json.dumps(manifest))
    print(f"Created template ID: {template.id}")
    
    # Test LIST
    templates = storage.list_templates()
    print(f"List templates count: {len(templates)}")
    assert len(templates) == 1
    assert templates[0].name == "My Template"
    
    # Test GET
    fetched = storage.get_template(template.id)
    print(f"Get template name: {fetched.name}")
    assert fetched.id == template.id
    
    # Test DELETE
    success = storage.delete_template(template.id)
    print(f"Delete success: {success}")
    assert success is True
    
    templates_after = storage.list_templates()
    print(f"List templates count after delete: {len(templates_after)}")
    assert len(templates_after) == 0
    
    print("ALL TESTS PASSED")

if __name__ == '__main__':
    run_test()
