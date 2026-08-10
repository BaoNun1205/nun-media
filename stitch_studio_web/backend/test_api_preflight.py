import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
STITCH_ROOT = ROOT / "stitch_studio"
if str(STITCH_ROOT) not in sys.path:
    sys.path.insert(0, str(STITCH_ROOT))

from fastapi.testclient import TestClient
from main import app, storage
import json

client = TestClient(app)

def run_tests():
    # 1. Create a project
    project = storage.create_project("Preflight Project", [])
    pid = project.id
    
    # Let's seed the project timeline with some media items
    metadata = {
        "timeline": [
            {"kind": "image", "projectAssetId": 100, "sourceAssetId": "sa1", "sourceVideoId": "sv1", "transform": {"scale": 1.5}},
            {"kind": "srt", "projectAssetId": 101, "sourceAssetId": "sa2", "text": "Hello", "segments": []}
        ],
        "timeline_state": {
            "items": [
                {"kind": "image", "projectAssetId": 100, "sourceAssetId": "sa1", "sourceVideoId": "sv1", "transform": {"scale": 1.5}},
                {"kind": "srt", "projectAssetId": 101, "sourceAssetId": "sa2", "text": "Hello", "segments": []}
            ],
            "canvas": {"width": 1920, "height": 1080},
            "fps": 30
        },
        "scene_state": {
            "foo": {"sourceAssetId": "leak"}
        }
    }
    # Update project
    storage.update_project_metadata(pid, metadata)
    storage.conn.execute('INSERT OR REPLACE INTO project_assets (id, project_id, kind, name, path) VALUES (100, ?, \'image\', \'Test Image\', \'\')', (pid,))
    storage.conn.execute('INSERT OR REPLACE INTO project_assets (id, project_id, kind, name, path) VALUES (101, ?, \'srt\', \'Test Subtitle\', \'\')', (pid,))
    storage.conn.commit()
    
    # 2. Call preview template
    resp = client.get(f"/api/projects/{pid}/template-preview")
    assert resp.status_code == 200, resp.text
    print("Preview passed.")
    
    # 3. Call save template
    resp = client.post(f"/api/projects/{pid}/templates", json={"name": "Test Preflight Template", "manifest": {}})
    assert resp.status_code == 200, resp.text
    template_data = resp.json()
    tid = template_data["template"]["id"]
    print(f"Save passed. Template ID: {tid}")
    
    # 4. Fetch list
    resp = client.get("/api/templates")
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["templates"]) > 0
    print("List passed.")
    
    # 5. Fetch single
    resp = client.get(f"/api/templates/{tid}")
    assert resp.status_code == 200, resp.text
    manifest = resp.json()["template"]["manifest"]
    
    # Assertions on manifest
    manifest_str = json.dumps(manifest)
    assert "sourceAssetId" not in manifest_str, "Leaked sourceAssetId"
    assert "sourceVideoId" not in manifest_str, "Leaked sourceVideoId"
    assert "segments" not in manifest_str, "Leaked segments"
    assert "text" not in manifest_str, "Leaked text"
    assert manifest["timelineTemplate"]["timelineState"]["canvas"]["width"] == 1920
    print("Manifest sanitization passed.")
    
    print("ALL API PREFLIGHT TESTS PASSED")

if __name__ == '__main__':
    run_tests()
