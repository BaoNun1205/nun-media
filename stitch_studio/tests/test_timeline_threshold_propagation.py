import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import soundfile as sf
import numpy as np

from stitch_studio.subtitle_timeline_scaler import process_srt_slot_timeline, SubtitleSegment
from stitch_studio.services import process_and_register_srt_slot_timeline, Storage
from stitch_studio.models import VideoItem

class TestTimelineThresholdPropagation(unittest.TestCase):
    def test_process_and_register_srt_slot_timeline_propagation(self):
        # FIX 2 TEST - SERVICE PROPAGATION
        storage_mock = MagicMock(spec=Storage)
        video_mock = MagicMock(spec=VideoItem)
        video_mock.id = 1
        video_mock.metadata = {}
        
        timeline_options = {
            "text_retry_preferred_speed_threshold": {
                10: 1.30,
                11: 1.10,
            }
        }
        
        with patch('stitch_studio.services.process_srt_slot_timeline') as mock_process:
            mock_process.return_value = {"state": {}, "working_srt_path": "dummy.srt", "working_audio_path": "dummy.wav", "manifest_path": "dummy.json", "final_video_path": "dummy.mp4"}
            
            process_and_register_srt_slot_timeline(
                storage_mock,
                video_mock,
                rendered=[],
                output_dir=Path("."),
                engine="test",
                source_srt=Path("source.srt"),
                sample_rate=8000,
                timeline_options=timeline_options
            )
            
            # Verify it is called with the propagated dictionary
            mock_process.assert_called_once()
            _, kwargs = mock_process.call_args
            
            self.assertIn("text_retry_preferred_speed_threshold", kwargs)
            self.assertEqual(kwargs["text_retry_preferred_speed_threshold"], {10: 1.30, 11: 1.10})

    def test_default_float_policy(self):
        # FIX 2 TEST - DEFAULT FLOAT POLICY
        storage_mock = MagicMock(spec=Storage)
        video_mock = MagicMock(spec=VideoItem)
        video_mock.id = 1
        video_mock.metadata = {}
        
        timeline_options = {
            "text_retry_preferred_speed_threshold": 1.25
        }
        
        with patch('stitch_studio.services.process_srt_slot_timeline') as mock_process:
            mock_process.return_value = {"state": {}, "working_srt_path": "dummy.srt", "working_audio_path": "dummy.wav", "manifest_path": "dummy.json", "final_video_path": "dummy.mp4"}
            
            process_and_register_srt_slot_timeline(
                storage_mock,
                video_mock,
                rendered=[],
                output_dir=Path("."),
                engine="test",
                source_srt=Path("source.srt"),
                sample_rate=8000,
                timeline_options=timeline_options
            )
            
            # Verify global float policy is preserved
            mock_process.assert_called_once()
            _, kwargs = mock_process.call_args
            
            self.assertIn("text_retry_preferred_speed_threshold", kwargs)
            self.assertEqual(kwargs["text_retry_preferred_speed_threshold"], 1.25)

    def test_mixed_subtitle_policy(self):
        # FIX 2 TEST - MIXED SUBTITLE POLICY
        # ID 10 -> required speed 1.20, threshold 1.30 -> SPEED_ADJUSTED (accepted)
        # ID 11 -> required speed 1.25, threshold 1.10 -> TEXT_TOO_LONG (needs retry)
        video = VideoItem(1, "test", "", "test", Path("test.mp4"), "video", 2000, None, "ready", "")
        
        # Mock up audio segments so required_speed matches expected
        # required_speed = original_tts_duration / available
        sample_rate = 8000
        
        # ID 10: start 0, end 1 (available 1s). required = 1.20 -> audio len = 1.20s
        audio_10 = np.zeros(int(1.20 * sample_rate), dtype=np.float32)
        path_10 = Path("dummy_10.wav")
        sf.write(path_10, audio_10, sample_rate, subtype="FLOAT")
        
        # ID 11: start 1, end 2 (available 1s). required = 1.25 -> audio len = 1.25s
        audio_11 = np.zeros(int(1.25 * sample_rate), dtype=np.float32)
        path_11 = Path("dummy_11.wav")
        sf.write(path_11, audio_11, sample_rate, subtype="FLOAT")
        
        rendered = [
            (SubtitleSegment(10, 0, 1.0, "line 10"), path_10),
            (SubtitleSegment(11, 1.0, 2.0, "line 11"), path_11)
        ]
        
        thresholds = {
            10: 1.30,
            11: 1.10,
        }
        
        try:
            result = process_srt_slot_timeline(
                video,
                rendered,
                Path("."),
                sample_rate=sample_rate,
                max_speed=1.5,
                text_retry_preferred_speed_threshold=thresholds,
                safety_gap=0.0
            )
        except RuntimeError:
            pass # Expected because of TEXT_TOO_LONG
            
        import json
        manifest = Path(".") / "srt_slot_timeline.json"
        data = json.loads(manifest.read_text("utf-8"))
        
        segments = {row["index"]: row for row in data["segments"]}
        self.assertIn(10, segments)
        self.assertIn(11, segments)
        
        # ID 10 shouldn't be TEXT_TOO_LONG (it fits under 1.30)
        self.assertEqual(segments[10]["segment_status"], "SPEED_ADJUSTED")
        
        # ID 11 should be TEXT_TOO_LONG (exceeds 1.10)
        self.assertEqual(segments[11]["segment_status"], "TEXT_TOO_LONG")
        
        path_10.unlink(missing_ok=True)
        path_11.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)

