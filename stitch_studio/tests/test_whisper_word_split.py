import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from stitch_studio.config import AppConfig
from stitch_studio.models import SubtitleSegment, VideoItem
from stitch_studio.services import TranscriptionService, _split_whisper_segment_by_words
from stitch_studio.srt import read_srt


class WhisperWordSplitTests(unittest.TestCase):
    def test_split_disabled_when_max_words_is_none_or_zero(self) -> None:
        seg = SimpleNamespace(
            start=1.0,
            end=5.0,
            text="Đây là một câu phụ đề mẫu gồm nhiều từ.",
            words=[SimpleNamespace(start=1.0, end=5.0, word="Đây là một câu phụ đề mẫu gồm nhiều từ.")],
        )
        res_none = _split_whisper_segment_by_words(seg, None, time_scale=1.0)
        self.assertEqual(len(res_none), 1)
        self.assertEqual(res_none[0].text, "Đây là một câu phụ đề mẫu gồm nhiều từ.")
        self.assertAlmostEqual(res_none[0].start, 1.0)
        self.assertAlmostEqual(res_none[0].end, 5.0)

        res_zero = _split_whisper_segment_by_words(seg, 0, time_scale=1.0)
        self.assertEqual(len(res_zero), 1)

    def test_split_by_word_timestamps(self) -> None:
        # 10 words with distinct timestamps
        words_data = [
            (" Xin", 0.0, 0.4),
            (" chào", 0.4, 0.8),
            (" tất", 0.8, 1.1),
            (" cả", 1.1, 1.4),
            (" các", 1.4, 1.7),
            (" bạn", 1.7, 2.0),
            (" đã", 2.0, 2.3),
            (" đến", 2.3, 2.6),
            (" với", 2.6, 2.9),
            (" video", 2.9, 3.5),
        ]
        words = [SimpleNamespace(word=w, start=s, end=e) for w, s, e in words_data]
        seg = SimpleNamespace(
            start=0.0,
            end=3.5,
            text="Xin chào tất cả các bạn đã đến với video",
            words=words,
        )

        # Split into max 8 words per line: 10 words -> chunk 1: 8 words, chunk 2: 2 words
        chunks_8 = _split_whisper_segment_by_words(seg, max_words=8, time_scale=1.0)
        self.assertEqual(len(chunks_8), 2)
        self.assertEqual(chunks_8[0].text, "Xin chào tất cả các bạn đã đến")
        self.assertAlmostEqual(chunks_8[0].start, 0.0)
        self.assertAlmostEqual(chunks_8[0].end, 2.6)

        self.assertEqual(chunks_8[1].text, "với video")
        self.assertAlmostEqual(chunks_8[1].start, 2.6)
        self.assertAlmostEqual(chunks_8[1].end, 3.5)

        # Split into max 5 words per line: 10 words -> 2 chunks of 5
        chunks_5 = _split_whisper_segment_by_words(seg, max_words=5, time_scale=1.0)
        self.assertEqual(len(chunks_5), 2)
        self.assertEqual(chunks_5[0].text, "Xin chào tất cả các")
        self.assertAlmostEqual(chunks_5[0].start, 0.0)
        self.assertAlmostEqual(chunks_5[0].end, 1.7)
        self.assertEqual(chunks_5[1].text, "bạn đã đến với video")
        self.assertAlmostEqual(chunks_5[1].start, 1.7)
        self.assertAlmostEqual(chunks_5[1].end, 3.5)

    def test_split_scales_with_time_scale(self) -> None:
        words = [
            SimpleNamespace(word=" Một", start=1.0, end=2.0),
            SimpleNamespace(word=" Hai", start=2.0, end=3.0),
            SimpleNamespace(word=" Ba", start=3.0, end=4.0),
        ]
        seg = SimpleNamespace(start=1.0, end=4.0, text="Một Hai Ba", words=words)
        chunks = _split_whisper_segment_by_words(seg, max_words=2, time_scale=0.5)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].text, "Một Hai")
        self.assertAlmostEqual(chunks[0].start, 0.5)
        self.assertAlmostEqual(chunks[0].end, 1.5)
        self.assertEqual(chunks[1].text, "Ba")
        self.assertAlmostEqual(chunks[1].start, 1.5)
        self.assertAlmostEqual(chunks[1].end, 2.0)

    def test_fallback_when_word_timestamps_missing(self) -> None:
        seg = SimpleNamespace(
            start=0.0,
            end=10.0,
            text="one two three four five six seven eight nine ten",
            words=None,
        )
        chunks = _split_whisper_segment_by_words(seg, max_words=4, time_scale=1.0)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].text, "one two three four")
        self.assertAlmostEqual(chunks[0].start, 0.0)
        self.assertAlmostEqual(chunks[0].end, 4.0)
        self.assertEqual(chunks[1].text, "five six seven eight")
        self.assertAlmostEqual(chunks[1].start, 4.0)
        self.assertAlmostEqual(chunks[1].end, 8.0)
        self.assertEqual(chunks[2].text, "nine ten")
        self.assertAlmostEqual(chunks[2].start, 8.0)
        self.assertAlmostEqual(chunks[2].end, 10.0)

    def test_empty_segment_returns_empty_list(self) -> None:
        seg = SimpleNamespace(start=0.0, end=1.0, text="   ", words=[])
        self.assertEqual(_split_whisper_segment_by_words(seg, max_words=8, time_scale=1.0), [])

    def test_generate_srt_with_max_words_per_line(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            cfg = AppConfig(
                downloads_dir=tmp_path / "downloads",
                outputs_dir=tmp_path / "outputs",
                models_dir=tmp_path / "models",
                db_path=tmp_path / "db.json",
            )
            storage = MagicMock()
            service = TranscriptionService(cfg, storage)

            # Mock whisper model
            mock_model = MagicMock()
            words_data = [
                (" Một", 0.0, 0.5),
                (" hai", 0.5, 1.0),
                (" ba", 1.0, 1.5),
                (" bốn", 1.5, 2.0),
                (" năm", 2.0, 2.5),
                (" sáu", 2.5, 3.0),
            ]
            words = [SimpleNamespace(word=w, start=s, end=e) for w, s, e in words_data]
            mock_segment = SimpleNamespace(start=0.0, end=3.0, text="Một hai ba bốn năm sáu", words=words)
            mock_info = SimpleNamespace(language="vi", duration=3.0)
            mock_model.transcribe.return_value = ([mock_segment], mock_info)
            service._get_whisper_model = MagicMock(return_value=mock_model)

            video_file = tmp_path / "test_video.mp4"
            video_file.write_bytes(b"dummy")
            video = VideoItem(
                id=1,
                title="test",
                source_url="test://video",
                source="test",
                path=video_file,
                media_type="video",
                duration_ms=3000,
                size_bytes=100,
                status="ready",
                created_at="2026-08-17 00:00:00",
            )

            # Generate with max_words_per_line = 3
            srt_path = service.generate_srt(video, model_name="tiny", max_words_per_line=3)

            # Verify transcribe call passed word_timestamps=True
            mock_model.transcribe.assert_called_once()
            call_kwargs = mock_model.transcribe.call_args[1]
            self.assertTrue(call_kwargs.get("word_timestamps"))

            # Verify output srt file content
            segments = read_srt(srt_path)
            self.assertEqual(len(segments), 2)
            self.assertEqual(segments[0].text, "Một hai ba")
            self.assertEqual(segments[1].text, "bốn năm sáu")


if __name__ == "__main__":
    unittest.main()
