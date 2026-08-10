import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path("d:/nun-media/stitch_studio").resolve()))

from stitch_studio.rendering.timeline_renderer import render_project_timeline, ExportSettings

class MockProject:
    id = 1
    title = 'test'
    primary_video_id = None
    metadata = {}

class MockStorage:
    def get_video(self, id): return None
    def get_asset(self, id): return None
    def get_project_asset(self, id): return None

class MockConfig:
    outputs_dir = Path(tempfile.gettempdir())

project = MockProject()
# 300 text items => big enough filter graph, but fast enough to render (no real video)
project.metadata['timeline_state'] = {
    'canvas': {'width': 1920, 'height': 1080},
    'items': [
        {'id': f'txt_{i}', 'kind': 'text', 'start': i * 0.1, 'duration': 0.1, 'track': 't1', 'params': {'text': f'hello world {i}'}} for i in range(300)
    ],
    'tracks': [{'id': 't1'}]
}

settings = ExportSettings(file_name='test_export.mp4', output_directory=MockConfig.outputs_dir)

def on_progress(msg):
    print("PROGRESS:", msg)

try:
    res = render_project_timeline(project=project, storage=MockStorage(), config=MockConfig(), settings=settings, progress=on_progress)
    print("SUCCESS!")
    print(res)
except Exception as e:
    import traceback
    traceback.print_exc()
