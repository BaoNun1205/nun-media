import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path("d:/nun-media/stitch_studio").resolve()))

from stitch_studio.rendering.timeline_renderer import render_project_timeline, ExportSettings

class MockVideo:
    def __init__(self, path):
        self.path = Path(path)
        self.metadata = {"subtitle_style": {"fontSize": 42}, "area_ratio": {"xmin":0,"xmax":1,"ymin":0.5,"ymax":1}}

class MockAsset:
    def __init__(self, path):
        self.path = Path(path)
        self.project_id = 1

class MockStorage:
    def get_video(self, id):
        if id == 100: return MockVideo('d:/nun-media/scratch/dummy_video.mp4')
        return None
    def get_asset(self, id):
        if id == 101: return MockAsset('d:/nun-media/scratch/dummy_image.jpg')
        if id == 102: return MockAsset('d:/nun-media/scratch/dummy_audio.m4a')
        if id == 103: return MockAsset('d:/nun-media/scratch/dummy.srt')
        return None
    def get_project_asset(self, id):
        return self.get_asset(id)

class MockProject:
    id = 1
    title = 'test'
    primary_video_id = 100
    metadata = {}

class MockConfig:
    outputs_dir = Path(tempfile.gettempdir())

def run_test(name, items):
    print(f"\n--- Running Test: {name} ---")
    project = MockProject()
    project.metadata['timeline_state'] = {
        'canvas': {'width': 1280, 'height': 720},
        'items': items,
        'tracks': [{'id': 't1'}, {'id': 't2'}]
    }
    settings = ExportSettings(file_name=f'test_{name.replace(" ", "_")}.mp4', output_directory=MockConfig.outputs_dir)
    try:
        res = render_project_timeline(project=project, storage=MockStorage(), config=MockConfig(), settings=settings)
        print(f"SUCCESS: {res['path']}")
    except Exception as e:
        import traceback
        traceback.print_exc()

# A. 1 video only
run_test("A_1_video", [
    {'id': 'v1', 'kind': 'video', 'start': 0.0, 'duration': 1.0, 'sourceStart': 0.0, 'track': 't1', 'sourceVideoId': 100}
])

# B. 1 video + audio
run_test("B_1_video_audio", [
    {'id': 'v1', 'kind': 'video', 'start': 0.0, 'duration': 1.0, 'sourceStart': 0.0, 'track': 't1', 'sourceVideoId': 100},
    {'id': 'a1', 'kind': 'audio', 'start': 0.0, 'duration': 1.0, 'sourceStart': 0.0, 'track': 't2', 'sourceAssetId': 102}
])

# C. 1 video + image
run_test("C_1_video_image", [
    {'id': 'v1', 'kind': 'video', 'start': 0.0, 'duration': 1.0, 'sourceStart': 0.0, 'track': 't1', 'sourceVideoId': 100},
    {'id': 'i1', 'kind': 'image', 'start': 0.0, 'duration': 1.0, 'sourceStart': 0.0, 'track': 't2', 'sourceAssetId': 101, 'params': {'transform': {'x':0.5, 'y':0.5, 'scale':1.0}}}
])

# D. 1 video + image animation
run_test("D_1_video_image_anim", [
    {'id': 'v1', 'kind': 'video', 'start': 0.0, 'duration': 1.0, 'sourceStart': 0.0, 'track': 't1', 'sourceVideoId': 100},
    {'id': 'i1', 'kind': 'image', 'start': 0.0, 'duration': 1.0, 'sourceStart': 0.0, 'track': 't2', 'sourceAssetId': 101, 'params': {
        'transform': {'x':0.5, 'y':0.5, 'scale':1.0},
        'imageAnimation': {'combo': {'presetId': 'zoom_in'}}
    }}
])

# E. video + image + text + SRT + audio
run_test("E_all", [
    {'id': 'v1', 'kind': 'video', 'start': 0.0, 'duration': 1.0, 'sourceStart': 0.0, 'track': 't1', 'sourceVideoId': 100},
    {'id': 'a1', 'kind': 'audio', 'start': 0.0, 'duration': 1.0, 'sourceStart': 0.0, 'track': 't2', 'sourceAssetId': 102},
    {'id': 'i1', 'kind': 'image', 'start': 0.0, 'duration': 1.0, 'sourceStart': 0.0, 'track': 't2', 'sourceAssetId': 101, 'params': {'transform': {'x':0.5, 'y':0.5, 'scale':1.0}}},
    {'id': 't1', 'kind': 'text', 'start': 0.0, 'duration': 1.0, 'track': 't2', 'params': {'text': 'Some text', 'textPosition': {'x':0.5, 'y':0.2}}},
    {'id': 's1', 'kind': 'srt', 'start': 0.0, 'duration': 1.0, 'sourceStart': 0.0, 'track': 't2', 'sourceAssetId': 103}
])
