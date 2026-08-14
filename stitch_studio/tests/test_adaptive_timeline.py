from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from stitch_studio.models import SubtitleSegment, VideoItem
from stitch_studio.services import GEMINI_TIMING_RETRY_PROMPT, TranslationService, _build_timing_retry_prompt, _clean_capcut_tts_text, _load_tts_segment_cache, _tts_generation_signature, process_and_register_plain_tts
from stitch_studio.srt import write_srt
from stitch_studio.storage import Storage
from stitch_studio.subtitle_timeline_scaler import (
    HARD_MAX_LOCAL_SPEED,
    MIN_WORKING_SPEED,
    build_atempo_chain,
    process_adaptive_timeline,
    process_srt_slot_timeline,
    select_adaptive_working_speed,
)


class AdaptiveAnalysisTests(unittest.TestCase):
    def test_capcut_cleaner_keeps_short_spoken_lines(self) -> None:
        self.assertEqual(_clean_capcut_tts_text("OK."), "OK.")
        self.assertEqual(_clean_capcut_tts_text("No."), "No.")
        self.assertEqual(_clean_capcut_tts_text("Go now"), "Go now")

    def test_all_voice_fits_at_one(self) -> None:
        speed, analysis = select_adaptive_working_speed([1.0, 1.0], [0.0, 2.0], video_duration=4.0)
        self.assertEqual(speed, 1.0)
        self.assertEqual(analysis["fit_at_1_0"], 2)

    def test_selects_about_point_nine(self) -> None:
        gap = 5.0
        duration = HARD_MAX_LOCAL_SPEED * (gap / 0.9 - 0.12)
        speed, _ = select_adaptive_working_speed([duration], [0.0], video_duration=gap)
        self.assertAlmostEqual(speed, 0.9, places=3)

    def test_selects_about_point_eight_three(self) -> None:
        gap = 5.0
        duration = HARD_MAX_LOCAL_SPEED * (gap / 0.83 - 0.12)
        speed, _ = select_adaptive_working_speed([duration], [0.0], video_duration=gap)
        self.assertAlmostEqual(speed, 0.83, places=3)

    def test_plain_tts_does_not_pad_to_standalone_duration(self) -> None:
        with TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            storage = Storage(root / "library.sqlite3")
            source = root / "standalone_tts_source.txt"
            source.write_text("plain text", encoding="utf-8")
            video_id = storage.upsert_video(
                title="Text To Speech",
                source_url="standalone:tts",
                source="standalone:tts",
                path=source,
                media_type="audio",
                duration_ms=42_154,
                size_bytes=source.stat().st_size,
                metadata={"standalone_tts": True, "input_mode": "text"},
            )
            video = storage.get_video(video_id)
            self.assertIsNotNone(video)
            srt_path = root / "source.srt"
            segment = SubtitleSegment(1, 0.0, 41.154, "plain text")
            write_srt([segment], srt_path)
            audio_path = root / "segment_0001_original.wav"
            sample_rate = 8_000
            original_audio = np.sin(2 * np.pi * 220 * np.arange(round(25.43 * sample_rate)) / sample_rate).astype(np.float32) * 0.1
            sf.write(audio_path, original_audio, sample_rate, subtype="FLOAT")

            result = process_and_register_plain_tts(
                storage,
                video,
                [(segment, audio_path)],
                root / "out",
                engine="test",
                source_srt=srt_path,
                sample_rate=sample_rate,
            )

            self.assertAlmostEqual(result["state"]["final_audio_duration"], 25.43, places=3)
            self.assertEqual(result["state"]["actual_samples"], len(original_audio))
            storage.close()

    def test_never_selects_below_point_seven(self) -> None:
        speed, _ = select_adaptive_working_speed([20.0], [0.0], video_duration=5.0)
        self.assertEqual(speed, MIN_WORKING_SPEED)

    def test_timelapse_options_can_select_lower_working_speed(self) -> None:
        speed, analysis = select_adaptive_working_speed(
            [20.0],
            [0.0],
            video_duration=5.0,
            min_working_speed=0.58,
            preferred_max_local_speed=1.28,
            hard_max_local_speed=1.55,
            safety_gap=0.06,
        )
        self.assertEqual(speed, 0.58)
        self.assertEqual(analysis["hard_max_local_speed"], HARD_MAX_LOCAL_SPEED)

    def test_handles_more_than_one_thousand_subtitles(self) -> None:
        starts = [index * 1.0 for index in range(1200)]
        speed, analysis = select_adaptive_working_speed([0.5] * 1200, starts, video_duration=1201.0)
        self.assertEqual(speed, 1.0)
        self.assertEqual(analysis["segments"], 1200)

    def test_atempo_chain_supports_ratios_outside_single_filter_range(self) -> None:
        self.assertEqual(build_atempo_chain(4.0).count("atempo="), 2)
        self.assertEqual(build_atempo_chain(0.25).count("atempo="), 2)

    def test_original_tts_cache_uses_generation_signature(self) -> None:
        with TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            audio = root / "segment_0001_original.wav"
            sf.write(audio, np.zeros(100, dtype=np.float32), 8_000)
            signature = _tts_generation_signature(engine="capcut", voice="narrator", rate="1.0")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps([{"index": 1, "text": "hello", "wav": str(audio), "generation_signature": signature}]), encoding="utf-8")
            self.assertIn(1, _load_tts_segment_cache(manifest, signature))
            self.assertNotIn(1, _load_tts_segment_cache(manifest, _tts_generation_signature(engine="capcut", voice="other")))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg/ffprobe required")
class AdaptiveIntegrationTests(unittest.TestCase):
    def test_fit_pipeline_preserves_silence_and_exact_sample_count(self) -> None:
        with TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            video_path = self._video_file(root, 4.0)
            rendered = self._rendered(root, [(1, 1.0, 1.4, 0.5), (2, 2.5, 2.9, 0.5)])
            original_starts = [item[0].start for item in rendered]
            result = process_adaptive_timeline(self._video(video_path, 4_000), rendered, root / "out", sample_rate=8_000)
            state = result["state"]
            self.assertEqual(state["selected_working_speed"], 1.0)
            self.assertEqual(state["final_validation_status"], "VALID")
            self.assertEqual(state["target_samples"], 32_000)
            self.assertEqual(state["actual_samples"], 32_000)
            audio, sr = sf.read(result["voiceover_path"], dtype="float32")
            self.assertEqual(sr, 8_000)
            self.assertLess(float(np.max(np.abs(audio[:6_000]))), 1e-6)
            manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
            self.assertEqual([row["original_start_time"] for row in manifest["segments"]], original_starts)
            self.assertAlmostEqual(manifest["segments"][0]["final_start_time"], 1.0)
            self.assertAlmostEqual(state["final_audio_duration"], 4.0)
            self.assertAlmostEqual(state["final_video_duration"], 4.0, delta=0.08)

    def test_local_speed_adjusted_status_up_to_hard_max(self) -> None:
        with TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            video_path = self._video_file(root, 22.0)
            specs = [(index + 1, index * 2.0, index * 2.0 + 0.5, 0.5) for index in range(9)]
            specs.append((10, 18.0, 18.5, 2.2))
            specs.append((11, 20.0, 20.5, 0.5))
            rendered = self._rendered(root, specs)
            result = process_adaptive_timeline(self._video(video_path, 22_000), rendered, root / "out", sample_rate=8_000, text_retry_preferred_speed_threshold=1.30)
            statuses = [row["segment_status"] for row in result["segments"]]
            self.assertEqual(statuses[9], "SPEED_ADJUSTED")
            self.assertNotIn("OVERLAP", statuses)

    def test_text_too_long_blocks_export_without_cutting_original(self) -> None:
        with TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            video_path = self._video_file(root, 3.0)
            rendered = self._rendered(root, [(1, 0.0, 0.5, 5.0), (2, 1.0, 1.5, 0.5)])
            original_frames = sf.info(rendered[0][1]).frames
            with self.assertRaisesRegex(RuntimeError, "TEXT_TOO_LONG"):
                process_adaptive_timeline(self._video(video_path, 3_000), rendered, root / "out", sample_rate=8_000)
            self.assertEqual(sf.info(rendered[0][1]).frames, original_frames)
            self.assertFalse((root / "out" / "voiceover.wav").exists())

    def test_srt_slot_timeline_blocks_above_one_point_three_after_full_pass(self) -> None:
        with TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            video_path = self._video_file(root, 3.0)
            rendered = self._rendered(root, [(1, 0.0, 0.5, 5.0), (2, 1.0, 1.5, 0.5)])
            with self.assertRaisesRegex(RuntimeError, "TEXT_TOO_LONG"):
                process_srt_slot_timeline(self._video(video_path, 3_000), rendered, root / "out", sample_rate=8_000, max_speed=1.5, text_retry_preferred_speed_threshold=1.30)
            manifest = json.loads((root / "out" / "srt_slot_timeline.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["state"]["max_speed"], 1.3)
            self.assertEqual(len(manifest["segments"]), 2)
            self.assertEqual(manifest["segments"][0]["segment_status"], "TEXT_TOO_LONG")
            self.assertFalse((root / "out" / "voiceover.wav").exists())

    def test_srt_slot_timeline_required_speed_cases(self) -> None:
        cases = [
            (1.90, "FIT", 1.00),
            (2.20, "SPEED_ADJUSTED", 1.10),
            (2.40, "SPEED_ADJUSTED", 1.20),
        ]
        for voice_duration, expected_status, expected_speed in cases:
            with self.subTest(voice_duration=voice_duration):
                with TemporaryDirectory() as raw_dir:
                    root = Path(raw_dir)
                    video_path = self._video_file(root, 3.0)
                    rendered = self._rendered(root, [(1, 0.0, 2.0, voice_duration)])
                    result = process_srt_slot_timeline(self._video(video_path, 3_000), rendered, root / "out", sample_rate=8_000, max_speed=1.5, safety_gap=0.0, text_retry_preferred_speed_threshold=1.30)
                    row = result["segments"][0]
                    self.assertEqual(row["segment_status"], expected_status)
                    self.assertAlmostEqual(row["required_local_speed"], voice_duration / 2.0, places=6)
                    self.assertAlmostEqual(row["applied_local_speed"], expected_speed, places=2)
                    self.assertLessEqual(row["applied_local_speed"], 1.2)

    def test_srt_slot_timeline_marks_one_point_three_one_text_too_long(self) -> None:
        with TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            video_path = self._video_file(root, 3.0)
            rendered = self._rendered(root, [(1, 0.0, 2.0, 2.62)])
            with self.assertRaisesRegex(RuntimeError, "TEXT_TOO_LONG"):
                process_srt_slot_timeline(self._video(video_path, 3_000), rendered, root / "out", sample_rate=8_000, max_speed=1.5, safety_gap=0.0)
            manifest = json.loads((root / "out" / "srt_slot_timeline.json").read_text(encoding="utf-8"))
            row = manifest["segments"][0]
            self.assertEqual(row["segment_status"], "TEXT_TOO_LONG")
            self.assertAlmostEqual(row["required_local_speed"], 1.31, places=6)

    def test_srt_slot_force_fit_speeds_above_one_point_three(self) -> None:
        with TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            video_path = self._video_file(root, 3.0)
            rendered = self._rendered(root, [(1, 0.0, 2.0, 3.4)])
            result = process_srt_slot_timeline(
                self._video(video_path, 3_000),
                rendered,
                root / "out",
                sample_rate=8_000,
                safety_gap=0.0,
                force_fit_overlong=True,
            )
            row = result["segments"][0]
            self.assertEqual(row["segment_status"], "SPEED_ADJUSTED")
            self.assertGreater(row["applied_local_speed"], 1.3)
            self.assertTrue((root / "out" / "voiceover.wav").exists())
            self.assertTrue(result["state"]["force_fit_overlong"])

    def test_srt_slot_text_too_long_does_not_shift_following_subtitle(self) -> None:
        with TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            video_path = self._video_file(root, 5.0)
            rendered = self._rendered(root, [(1, 0.0, 2.0, 4.0), (2, 2.5, 4.5, 1.9)])
            with self.assertRaisesRegex(RuntimeError, "TEXT_TOO_LONG"):
                process_srt_slot_timeline(self._video(video_path, 5_000), rendered, root / "out", sample_rate=8_000, max_speed=1.5, safety_gap=0.0)
            manifest = json.loads((root / "out" / "srt_slot_timeline.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["segments"][0]["segment_status"], "TEXT_TOO_LONG")
            self.assertEqual(manifest["segments"][1]["segment_status"], "FIT")
            self.assertFalse(manifest["segments"][1]["late_start"])

    def test_srt_slot_timeline_uses_exact_required_speed_not_hard_max(self) -> None:
        with TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            video_path = self._video_file(root, 2.0)
            rendered = self._rendered(root, [(1, 0.0, 1.0, 1.0)])
            result = process_srt_slot_timeline(self._video(video_path, 2_000), rendered, root / "out", sample_rate=8_000, max_speed=1.5, safety_gap=0.12, text_retry_preferred_speed_threshold=1.30)
            row = result["segments"][0]
            self.assertEqual(row["segment_status"], "SPEED_ADJUSTED")
            self.assertAlmostEqual(row["required_local_speed"], 1.0 / 0.88, places=6)
            self.assertAlmostEqual(row["applied_local_speed"], row["required_local_speed"], places=6)
            self.assertLessEqual(row["applied_local_speed"], 1.2)

    def test_srt_slot_timeline_pads_short_audio_without_slowing_it(self) -> None:
        with TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            video_path = self._video_file(root, 2.0)
            rendered = self._rendered(root, [(1, 0.0, 1.0, 0.25)])
            original_audio, _ = sf.read(rendered[0][1], dtype="float32")
            result = process_srt_slot_timeline(self._video(video_path, 2_000), rendered, root / "out", sample_rate=8_000, max_speed=1.5)
            row = result["segments"][0]
            processed_audio, _ = sf.read(row["processed_tts_path"], dtype="float32")

            self.assertEqual(row["segment_status"], "FIT")
            self.assertEqual(row["applied_local_speed"], 1.0)
            np.testing.assert_allclose(processed_audio[: len(original_audio)], original_audio, atol=1e-6)
            self.assertLess(float(np.max(np.abs(processed_audio[len(original_audio) :]))), 1e-6)

    def test_gemini_timing_retry_uses_central_prompt_and_batches_ids(self) -> None:
        calls: list[str] = []
        requested_ids = list(range(1, 101))

        class FakeModels:
            def generate_content(self, *, model: str, contents: str):
                del model
                calls.append(contents)
                return SimpleNamespace(text=json.dumps([{"id": item_id, "text": f"S{item_id}"} for item_id in requested_ids]))

        service = TranslationService.__new__(TranslationService)
        service._gemini_client = lambda: SimpleNamespace(models=FakeModels())  # type: ignore[attr-defined]
        replacements = service.optimize_timing_translations(
            [
                {
                    "id": item_id,
                    "output_language": "vi",
                    "source_text": f"src {item_id}",
                    "current_translation": f"current {item_id}",
                    "previous_context": "prev",
                    "next_context": "next",
                    "available_seconds": 1.0,
                    "voice_seconds": 2.0,
                    "max_local_speed": 1.30,
                    "target_max_tts_duration": 1.30,
                    "required_reduction_percent": 35.0,
                    "correction_round": 2,
                }
                for item_id in requested_ids
            ],
            correction_round=2,
        )
        self.assertEqual(replacements[1], "S1")
        self.assertEqual(replacements[100], "S100")
        self.assertEqual(len(calls), 10)
        
        # Check that it renders real values into the simplified Vietnamese retry prompt
        self.assertIn("Rút gọn câu tiếng Việt sau còn tối đa 1 từ.", calls[0])
        self.assertIn("Bắt buộc không vượt quá 1 từ.", calls[0])
        self.assertIn("Câu hiện tại:\ncurrent 1", calls[0])
        self.assertIn('"id": 1', calls[0])
        self.assertIn('"target_max_words": 1', calls[0])
        self.assertIn('"current_translation": "current 1"', calls[0])
        self.assertNotIn("{TARGET_MAX_WORDS}", calls[0])
        self.assertNotIn("{CURRENT_TRANSLATION}", calls[0])
        self.assertNotIn('"source_text":', calls[0])
        self.assertNotIn('"output_language":', calls[0])
        self.assertNotIn('"available_seconds":', calls[0])
        self.assertNotIn('"voice_seconds":', calls[0])
        self.assertNotIn('"previous_context":', calls[0])
        self.assertNotIn('"next_context":', calls[0])
        self.assertNotIn('"correction_round":', calls[0])
        self.assertNotIn("TIMING OPTIMIZATION CONTEXT", calls[0])
        self.assertNotIn("required_reduction_percent` is", calls[0])
        self.assertNotIn("Use SOURCE_TEXT", calls[0])

    def test_timing_retry_prompt_uses_language_specific_rules(self) -> None:
        vietnamese_prompt = _build_timing_retry_prompt("vi")
        english_prompt = _build_timing_retry_prompt("en")

        self.assertIn("Rút gọn từng câu tiếng Việt", vietnamese_prompt)
        self.assertNotIn("{TARGET_MAX_WORDS}", vietnamese_prompt)
        self.assertNotIn("{CURRENT_TRANSLATION}", vietnamese_prompt)
        self.assertNotIn("available duration", vietnamese_prompt)
        self.assertNotIn("source_text", vietnamese_prompt)
        self.assertNotIn("context", vietnamese_prompt.lower())
        self.assertNotIn("American English", vietnamese_prompt)
        self.assertIn("American English", english_prompt)
        self.assertIn("Use contractions", english_prompt)

    def test_gemini_timing_retry_ignores_empty_replacements(self) -> None:
        class FakeModels:
            def generate_content(self, *, model: str, contents: str):
                del model, contents
                return SimpleNamespace(text=json.dumps([
                    {"id": 1, "text": "Short enough."},
                    {"id": 2, "text": ""},
                ]))

        service = TranslationService.__new__(TranslationService)
        service._gemini_client = lambda: SimpleNamespace(models=FakeModels())  # type: ignore[attr-defined]
        replacements = service.optimize_timing_translations(
            [
                {"ID": 1, "CURRENT": "This is too long.", "AVAILABLE_SECONDS": 1, "VOICE_SECONDS": 2},
                {"ID": 2, "CURRENT": "Still too long.", "AVAILABLE_SECONDS": 1, "VOICE_SECONDS": 2},
            ],
        )

        self.assertEqual(replacements, {1: "Short enough."})

    def test_translation_service_rejects_non_gemini_engine(self) -> None:
        service = TranslationService.__new__(TranslationService)
        with self.assertRaisesRegex(RuntimeError, "Unsupported translation engine"):
            service.translate_srt(self._video(Path("unused.mp4"), 1_000), Path("unused.srt"), engine="local-engine")

    def test_zero_duration_subtitle_is_rejected(self) -> None:
        self._assert_bad_timeline([SubtitleSegment(1, 1.0, 1.0, "bad")])

    def test_reversed_timeline_is_rejected(self) -> None:
        self._assert_bad_timeline([SubtitleSegment(1, 2.0, 2.5, "one"), SubtitleSegment(2, 1.0, 1.5, "two")])

    def test_duplicate_start_is_rejected(self) -> None:
        self._assert_bad_timeline([SubtitleSegment(1, 1.0, 1.5, "one"), SubtitleSegment(2, 1.0, 1.6, "two")])

    def test_project_state_survives_restart(self) -> None:
        with TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            storage = Storage(root / "library.sqlite3")
            video_id = storage.upsert_video(title="test", source_url="", source="test", path=root / "video.mp4", media_type="video", duration_ms=1_000, size_bytes=0, metadata={})
            storage.update_video_metadata(video_id, {"tts_timeline": {"timing_mode": "adaptive", "selected_working_speed": 0.83}})
            storage.close()
            reopened = Storage(root / "library.sqlite3")
            self.assertEqual(reopened.get_video(video_id).metadata["tts_timeline"]["selected_working_speed"], 0.83)
            reopened.close()

    def _assert_bad_timeline(self, segments: list[SubtitleSegment]) -> None:
        with TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            video_path = self._video_file(root, 4.0)
            rendered = []
            for segment in segments:
                path = root / f"{segment.index}.wav"
                sf.write(path, np.zeros(4_000, dtype=np.float32), 8_000)
                rendered.append((segment, path))
            with self.assertRaises(RuntimeError):
                process_adaptive_timeline(self._video(video_path, 4_000), rendered, root / "out", sample_rate=8_000)

    @staticmethod
    def _rendered(root: Path, specs: list[tuple[int, float, float, float]]):
        rendered = []
        sample_rate = 8_000
        for index, start, end, duration in specs:
            path = root / f"segment_{index:04d}_original.wav"
            tone = np.sin(2 * np.pi * 220 * np.arange(round(duration * sample_rate)) / sample_rate).astype(np.float32) * 0.1
            sf.write(path, tone, sample_rate, subtype="FLOAT")
            rendered.append((SubtitleSegment(index, start, end, f"line {index}"), path))
        return rendered

    @staticmethod
    def _video_file(root: Path, duration: float) -> Path:
        path = root / "source.mp4"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s=320x180:d={duration}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], capture_output=True, check=True)
        return path

    @staticmethod
    def _video(path: Path, duration_ms: int) -> VideoItem:
        return VideoItem(1, "test", "", "test", path, "video", duration_ms, None, "ready", "")


if __name__ == "__main__":
    unittest.main()
