from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from stitch_studio.rendering.effects import add_timeline_effects, load_effect_registry, normalized_effect_params
from stitch_studio.rendering.timeline_renderer import ExportSettings, render_project_timeline


class TimelineEffectsTest(unittest.TestCase):
    def test_registry_normalizes_and_clamps_params(self) -> None:
        identifier, params = normalized_effect_params({"params": {"effectId": "film_grain", "intensity": 99, "seed": -1}})
        self.assertEqual(identifier, "film_grain")
        self.assertEqual(params["intensity"], 1)
        self.assertEqual(params["seed"], 0)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_all_registered_effects_compile_in_native_ffmpeg(self) -> None:
        registry = load_effect_registry()
        effects = [
            {"id": f"fx-{identifier}", "kind": "effect", "start": 0, "duration": 0.4, "params": {"effectId": identifier}}
            for identifier in registry
        ]
        filters = ["testsrc2=s=128x72:r=24:d=0.4[base]"]
        output = add_timeline_effects(filters, "[base]", effects, width=128, height=72, fps=24)
        filters.append(f"{output}format=yuv420p[out]")
        with tempfile.TemporaryDirectory() as tmp:
            graph = Path(tmp) / "effects.ffgraph"
            output_path = Path(tmp) / "effects.mp4"
            graph.write_text(";".join(filters), encoding="utf-8")
            proc = subprocess.run(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-filter_complex_script", str(graph), "-map", "[out]", "-frames:v", "8", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertGreater(output_path.stat().st_size, 0)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
    def test_render_project_timeline_exports_stacked_effect_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=128x72:r=24:d=0.4",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source),
            ], check=True)
            effects = [
                {"id": f"fx-{identifier}", "kind": "effect", "track": "FX1", "name": identifier, "start": 0, "duration": 0.4, "params": {"effectId": identifier}}
                for identifier in load_effect_registry()
            ]
            state = {
                "fps": 24,
                "canvas": {"width": 128, "height": 72},
                "tracks": [{"id": "V1", "kind": "video"}, {"id": "FX1", "kind": "effect"}],
                "items": [{"id": "video", "kind": "video", "track": "V1", "name": "source", "start": 0, "duration": 0.4, "sourceStart": 0, "sourceAssetId": 1}, *effects],
            }
            project = SimpleNamespace(id=99, metadata={"timeline_state": state}, primary_video_id=None)
            storage = SimpleNamespace(get_asset=lambda asset_id: SimpleNamespace(path=source) if asset_id == 1 else None, get_project_asset=lambda _asset_id: None, get_video=lambda _video_id: None)
            work = root / "work"
            output_dir = root / "out"
            work.mkdir()
            output_dir.mkdir()
            result = render_project_timeline(
                project=project,
                storage=storage,
                config=SimpleNamespace(outputs_dir=work),
                settings=ExportSettings(file_name="effects", output_directory=output_dir, resolution="720p", aspect_ratio="16:9", fps=24),
            )
            self.assertTrue(Path(result["path"]).exists())
            self.assertGreater(Path(result["path"]).stat().st_size, 0)
