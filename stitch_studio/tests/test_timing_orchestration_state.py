import unittest
import re

from stitch_studio.models import SubtitleSegment
from stitch_studio.services import _build_timing_retry_duration_metadata, build_timing_retry_optimizer_items

def normalize_retry_text_for_change_detection(text: str) -> str:
    return re.sub(r'[^\w\s]', '', " ".join((text or "").split())).casefold()

class TestTimingOrchestrationState(unittest.TestCase):
    def test_mixed_batch_state_tracking(self):
        # Simulate round 1
        correction_round = 1
        MAX_TIMING_CORRECTION_ROUNDS = 10
        rewrite_state_by_id = {}
        
        # Subtitle 10 and 11
        optimizer_items = [
            {"id": 10, "current_translation": "Quá dài quá dài quá dài", "required_speed": 1.25},
            {"id": 11, "current_translation": "Cũng quá dài luôn", "required_speed": 1.25},
        ]
        
        # Gemini returns 10 shortened, 11 unchanged
        replacements = {
            10: "Ngắn lại",
            11: "Cũng quá dài luôn"
        }
        
        current_map = {
            10: type('Segment', (), {'text': "Quá dài quá dài quá dài"}),
            11: type('Segment', (), {'text': "Cũng quá dài luôn"}),
        }
        
        changed = 0
        for item in optimizer_items:
            idx = item["id"]
            replacement = replacements.get(idx, "")
            segment = current_map.get(idx)
            if segment and replacement.strip():
                if normalize_retry_text_for_change_detection(segment.text) != normalize_retry_text_for_change_detection(replacement):
                    changed += 1
                    rewrite_state_by_id[idx] = True
                else:
                    rewrite_state_by_id[idx] = False
            else:
                rewrite_state_by_id[idx] = False
                
        self.assertEqual(changed, 1)
        self.assertEqual(rewrite_state_by_id[10], True)
        self.assertEqual(rewrite_state_by_id[11], False)
        
        # Next round, check thresholds
        correction_round = 2
        timeline_options = {"hard_max_local_speed": 1.30}
        
        segment_thresholds = {
            _idx: timeline_options.get("hard_max_local_speed", 1.30)
            for _idx in rewrite_state_by_id
        }
        
        self.assertEqual(segment_thresholds[10], 1.30)
        self.assertEqual(segment_thresholds[11], 1.30)

    def test_punctuation_only_change(self):
        old = "Tôi phải chạy."
        new = "Tôi phải chạy!"
        self.assertEqual(
            normalize_retry_text_for_change_detection(old),
            normalize_retry_text_for_change_detection(new)
        )

    def test_unrewritten_1_18x_uses_hard_retry_target(self):
        metadata = _build_timing_retry_duration_metadata(
            2.00,
            2.36,
            already_rewritten=False,
        )

        self.assertAlmostEqual(metadata["target_max_tts_duration"], 2.60)
        self.assertAlmostEqual(metadata["required_reduction_percent"], 0.0)

    def test_unrewritten_1_25x_uses_hard_retry_target(self):
        metadata = _build_timing_retry_duration_metadata(
            2.00,
            2.50,
            already_rewritten=False,
        )

        self.assertAlmostEqual(metadata["target_max_tts_duration"], 2.60)
        self.assertAlmostEqual(metadata["required_reduction_percent"], 0.0)

    def test_rewritten_over_hard_limit_uses_hard_retry_target(self):
        metadata = _build_timing_retry_duration_metadata(
            2.00,
            2.90,
            already_rewritten=True,
        )

        self.assertAlmostEqual(metadata["target_max_tts_duration"], 2.60)
        self.assertAlmostEqual(metadata["required_reduction_percent"], 10.344828, places=5)

    def test_overlong_ten_word_line_gets_lower_target_word_count(self):
        metadata = _build_timing_retry_duration_metadata(
            2.00,
            3.00,
            already_rewritten=False,
            current_translation="one two three four five six seven eight nine ten",
        )

        self.assertEqual(metadata["current_word_count"], 10)
        self.assertLess(metadata["target_max_words"], 10)
        self.assertEqual(metadata["target_max_words"], 7)

    def test_retry_recalculates_smaller_target_from_latest_text_and_duration(self):
        first_segments = [
            SubtitleSegment(1, 0.0, 2.0, "one two three four five six seven eight nine ten"),
        ]
        second_segments = [
            SubtitleSegment(1, 0.0, 2.0, "one two three four five six seven"),
        ]
        first_rows = [{"index": 1, "working_available_duration": 2.0, "original_tts_duration": 3.0, "segment_status": "TEXT_TOO_LONG"}]
        second_rows = [{"index": 1, "working_available_duration": 2.0, "original_tts_duration": 3.0, "segment_status": "TEXT_TOO_LONG"}]

        first_items = build_timing_retry_optimizer_items(
            current_segments=first_segments,
            rows=first_rows,
            still_too_long=first_rows,
            source_map={1: "source"},
            output_language="en",
            rewrite_state_by_id={},
        )
        second_items = build_timing_retry_optimizer_items(
            current_segments=second_segments,
            rows=second_rows,
            still_too_long=second_rows,
            source_map={1: "source"},
            output_language="en",
            rewrite_state_by_id={1: True},
        )

        self.assertEqual(first_items[0]["TARGET_MAX_WORDS"], 7)
        self.assertLess(second_items[0]["TARGET_MAX_WORDS"], first_items[0]["TARGET_MAX_WORDS"])

    def test_retry_target_is_forced_lower_than_previous_round(self):
        segments = [
            SubtitleSegment(1, 0.0, 2.0, "one two three four five six seven eight nine ten"),
        ]
        rows = [{"index": 1, "working_available_duration": 2.0, "original_tts_duration": 2.30, "segment_status": "TEXT_TOO_LONG"}]

        items = build_timing_retry_optimizer_items(
            current_segments=segments,
            rows=rows,
            still_too_long=rows,
            source_map={1: "source"},
            output_language="en",
            rewrite_state_by_id={1: True},
            previous_target_words_by_id={1: 8},
        )

        self.assertEqual(items[0]["TARGET_MAX_WORDS"], 7)

    def test_vietnamese_timing_retry_keeps_single_overlong_item(self):
        segments = [
            SubtitleSegment(index, float(index), float(index + 1), f"line {index}")
            for index in range(1, 6)
        ]
        rows = [
            {
                "index": index,
                "working_available_duration": 1.0,
                "original_tts_duration": 1.25 if index == 3 else 0.8,
                "segment_status": "TEXT_TOO_LONG" if index == 3 else "FIT",
            }
            for index in range(1, 6)
        ]
        items = build_timing_retry_optimizer_items(
            current_segments=segments,
            rows=rows,
            still_too_long=[rows[2]],
            source_map={index: f"source {index}" for index in range(1, 6)},
            output_language="vi",
            rewrite_state_by_id={},
        )

        self.assertEqual([item["id"] for item in items], [3])
        self.assertEqual([item["id"] for item in items if item["needs_timing_rewrite"]], [3])
        self.assertNotIn("context_group", items[0])

    def test_english_timing_retry_keeps_single_overlong_item(self):
        segments = [
            SubtitleSegment(index, float(index), float(index + 1), f"line {index}")
            for index in range(1, 6)
        ]
        rows = [
            {
                "index": index,
                "working_available_duration": 1.0,
                "original_tts_duration": 1.25 if index == 3 else 0.8,
                "segment_status": "TEXT_TOO_LONG" if index == 3 else "FIT",
            }
            for index in range(1, 6)
        ]
        items = build_timing_retry_optimizer_items(
            current_segments=segments,
            rows=rows,
            still_too_long=[rows[2]],
            source_map={index: f"source {index}" for index in range(1, 6)},
            output_language="en",
            rewrite_state_by_id={},
        )

        self.assertEqual([item["id"] for item in items], [3])
        self.assertNotIn("context_group", items[0])

    def test_fit_subtitle_is_not_sent_to_timing_retry(self):
        segments = [
            SubtitleSegment(1, 0.0, 2.0, "already fits"),
            SubtitleSegment(2, 2.0, 4.0, "one two three four five six seven eight nine ten"),
        ]
        rows = [
            {"index": 1, "working_available_duration": 2.0, "original_tts_duration": 2.40, "segment_status": "SPEED_ADJUSTED"},
            {"index": 2, "working_available_duration": 2.0, "original_tts_duration": 3.00, "segment_status": "TEXT_TOO_LONG"},
        ]

        items = build_timing_retry_optimizer_items(
            current_segments=segments,
            rows=rows,
            still_too_long=[rows[1]],
            source_map={1: "source 1", 2: "source 2"},
            output_language="en",
            rewrite_state_by_id={},
        )

        self.assertEqual([item["id"] for item in items], [2])

    def test_final_fit_after_tts_measurement_has_no_retry_items(self):
        segments = [
            SubtitleSegment(1, 0.0, 2.0, "short enough now"),
        ]
        rows = [
            {"index": 1, "working_available_duration": 2.0, "original_tts_duration": 2.55, "segment_status": "SPEED_ADJUSTED"},
        ]

        items = build_timing_retry_optimizer_items(
            current_segments=segments,
            rows=rows,
            still_too_long=[],
            source_map={1: "source"},
            output_language="en",
            rewrite_state_by_id={1: True},
            previous_target_words_by_id={1: 4},
        )

        self.assertEqual(items, [])

    def test_all_items_unchanged(self):
        old = "Không đổi gì cả"
        new = "  Không đổi gì cả  "
        self.assertEqual(
            normalize_retry_text_for_change_detection(old),
            normalize_retry_text_for_change_detection(new)
        )
