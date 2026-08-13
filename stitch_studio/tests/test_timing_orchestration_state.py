import unittest
import re

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
        
        segment_thresholds = {}
        for _idx, _rewritten in rewrite_state_by_id.items():
            segment_thresholds[_idx] = timeline_options.get("hard_max_local_speed", 1.30) if _rewritten else 1.10
        
        self.assertEqual(segment_thresholds[10], 1.30)
        self.assertEqual(segment_thresholds[11], 1.10)

    def test_punctuation_only_change(self):
        old = "Tôi phải chạy."
        new = "Tôi phải chạy!"
        self.assertEqual(
            normalize_retry_text_for_change_detection(old),
            normalize_retry_text_for_change_detection(new)
        )

    def test_all_items_unchanged(self):
        old = "Không đổi gì cả"
        new = "  Không đổi gì cả  "
        self.assertEqual(
            normalize_retry_text_for_change_detection(old),
            normalize_retry_text_for_change_detection(new)
        )
