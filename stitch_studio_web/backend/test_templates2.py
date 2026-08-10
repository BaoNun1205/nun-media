import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STITCH_ROOT = ROOT / "stitch_studio"
if str(STITCH_ROOT) not in sys.path:
    sys.path.insert(0, str(STITCH_ROOT))

from stitch_studio.storage import Storage

def run_test():
    db_path = Path("test_templates.sqlite")
    if db_path.exists():
        db_path.unlink()
        
    storage = Storage(db_path)
    
    project = storage.create_project("Test Proj", [])
    project_id = project.id

    manifest = {
        "version": 1,
        "name": "My Temp",
        "sourceProjectId": project_id,
        "inputs": [],
        "generated": [],
        "timelineTemplate": {"items": [], "timelineState": {}, "sceneState": {}}
    }
    
    template = storage.create_template("My Template", project_id, json.dumps(manifest))
    
    print("Deleting source project...")
    storage.conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    storage.conn.commit()
    
    templates_after = storage.list_templates()
    print(f"List templates count after source project delete: {len(templates_after)}")
    assert len(templates_after) == 1
    assert templates_after[0].source_project_id is None
    
    # Check restart persistence
    storage2 = Storage(db_path)
    templates_restart = storage2.list_templates()
    print(f"List templates count after restart: {len(templates_restart)}")
    assert len(templates_restart) == 1
    
    print("ALL TESTS PASSED")

if __name__ == '__main__':
    run_test()
