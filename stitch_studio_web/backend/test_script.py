import json
import sqlite3
from stitch_studio.template_analyzer import analyze_template_from_project

class MockProject:
    id = 1
    title = 'Test'
    metadata = {
        'timeline': [
            {'kind': 'image', 'projectAssetId': 100, 'sourceAssetId': 'sa1', 'sourceVideoId': 'sv1', 'transform': {'scale': 1.5}},
            {'kind': 'srt', 'projectAssetId': 101, 'sourceAssetId': 'sa2', 'text': 'Hello', 'segments': []}
        ],
        'timeline_state': {
            'items': [
                {'kind': 'image', 'projectAssetId': 100, 'sourceAssetId': 'sa1', 'sourceVideoId': 'sv1', 'transform': {'scale': 1.5}},
                {'kind': 'srt', 'projectAssetId': 101, 'sourceAssetId': 'sa2', 'text': 'Hello', 'segments': []}
            ]
        },
        'scene_state': {
            'foo': {'sourceAssetId': 'leak'}
        }
    }

class MockStorage:
    def __init__(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.execute('CREATE TABLE project_assets (id INTEGER PRIMARY KEY, name TEXT)')
        self.conn.execute('INSERT INTO project_assets (id, name) VALUES (100, \'Test Image\')')

res = analyze_template_from_project(MockProject(), MockStorage())
print(json.dumps(res, indent=2))
