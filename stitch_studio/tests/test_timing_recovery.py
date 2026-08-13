import json
import unittest
from types import SimpleNamespace
from stitch_studio.services import TranslationService

class TestTimingRecovery(unittest.TestCase):
    def setUp(self):
        self.service = TranslationService.__new__(TranslationService)
        self.calls = []
        self.responses = []
        
        class FakeModels:
            def generate_content(inner_self, *, model, contents, config=None):
                self.calls.append(contents)
                if not self.responses:
                    return SimpleNamespace(text="[]")
                return SimpleNamespace(text=json.dumps(self.responses.pop(0)))
                
        self.service._gemini_client = lambda: SimpleNamespace(models=FakeModels())  # type: ignore[attr-defined]

    def _make_items(self, ids):
        return [
            {
                "id": item_id,
                "output_language": "vi",
                "source_text": f"src {item_id}",
                "current_translation": f"current {item_id}",
                "correction_round": 2,
            }
            for item_id in ids
        ]

    def test_complete_response(self):
        # PART 21 — REQUIRED TEST: COMPLETE RESPONSE
        self.responses = [
            [{"id": 12, "text": "R12"}, {"id": 13, "text": "R13"}, {"id": 14, "text": "R14"}]
        ]
        replacements = self.service.optimize_timing_translations(self._make_items([12, 13, 14]))
        
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(replacements, {12: "R12", 13: "R13", 14: "R14"})

    def test_one_missing_id(self):
        # PART 22 — REQUIRED TEST: ONE MISSING ID
        self.responses = [
            [{"id": 12, "text": "R12"}, {"id": 14, "text": "R14"}, {"id": 15, "text": "R15"}], # Misses 13
            [{"id": 13, "text": "R13_recovered"}] # Recovers 13
        ]
        replacements = self.service.optimize_timing_translations(self._make_items([12, 13, 14, 15]))
        
        self.assertEqual(len(self.calls), 2)
        # Check that the second call only asks for ID 13
        self.assertIn('"id": 13,', self.calls[1])
        self.assertNotIn('"id": 12,', self.calls[1])
        self.assertEqual(replacements, {12: "R12", 13: "R13_recovered", 14: "R14", 15: "R15"})

    def test_multiple_missing_ids(self):
        # PART 23 — REQUIRED TEST: MULTIPLE MISSING IDS
        self.responses = [
            [{"id": 12, "text": "R12"}, {"id": 15, "text": "R15"}, {"id": 17, "text": "R17"}], # Misses 13,14,16
            [{"id": 13, "text": "R13"}, {"id": 14, "text": "R14"}, {"id": 16, "text": "R16"}]  # Recovers them
        ]
        replacements = self.service.optimize_timing_translations(self._make_items([12, 13, 14, 15, 16, 17]))
        
        self.assertEqual(len(self.calls), 2)
        self.assertIn('"id": 13', self.calls[1])
        self.assertIn('"id": 14', self.calls[1])
        self.assertIn('"id": 16', self.calls[1])
        self.assertEqual(replacements, {12: "R12", 13: "R13", 14: "R14", 15: "R15", 16: "R16", 17: "R17"})

    def test_missing_id_never_recovers(self):
        # PART 24 — REQUIRED TEST: MISSING ID NEVER RECOVERS
        self.responses = [
            [{"id": 12, "text": "R12"}, {"id": 14, "text": "R14"}], # Misses 13
            [{"id": 12, "text": "ignore"}], # Missing 13 again (attempt 1)
            [{"id": 14, "text": "ignore"}]  # Missing 13 again (attempt 2)
        ]
        # Should gracefully finish and return what it has.
        replacements = self.service.optimize_timing_translations(self._make_items([12, 13, 14]))
        self.assertEqual(len(self.calls), 3) # 1 initial + 2 recoveries
        self.assertEqual(replacements, {12: "R12", 14: "R14"})

    def test_unexpected_id(self):
        # PART 25 — REQUIRED TEST: UNEXPECTED ID
        self.responses = [
            [{"id": 12, "text": "R12"}, {"id": 13, "text": "R13"}, {"id": 999, "text": "R999"}]
        ]
        replacements = self.service.optimize_timing_translations(self._make_items([12, 13]))
        
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(replacements, {12: "R12", 13: "R13"})
        self.assertNotIn(999, replacements)

    def test_duplicate_id(self):
        # PART 26 — REQUIRED TEST: DUPLICATE ID
        self.responses = [
            [{"id": 12, "text": "A"}, {"id": 12, "text": "B"}, {"id": 13, "text": "C"}],
            [{"id": 12, "text": "recovered"}]
        ]
        replacements = self.service.optimize_timing_translations(self._make_items([12, 13]))
        
        self.assertEqual(len(self.calls), 2)
        # ID 13 should be accepted in first call
        # ID 12 should be discarded in first call, so retried
        self.assertIn('"id": 12,', self.calls[1])
        self.assertNotIn('"id": 13,', self.calls[1])
        self.assertEqual(replacements, {12: "recovered", 13: "C"})

    def test_empty_text(self):
        # PART 27 — REQUIRED TEST: EMPTY TEXT
        self.responses = [
            [{"id": 12, "text": ""}, {"id": 13, "text": "valid"}],
            [{"id": 12, "text": "recovered"}]
        ]
        replacements = self.service.optimize_timing_translations(self._make_items([12, 13]))
        
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(replacements, {12: "recovered", 13: "valid"})

    def test_small_batching(self):
        # PART 28 — REQUIRED TEST: SMALL BATCHING
        # 25 items -> chunks of 10, 10, 5
        self.responses = [
            [{"id": i, "text": f"R{i}"} for i in range(1, 11)],
            [{"id": i, "text": f"R{i}"} for i in range(11, 21)],
            [{"id": i, "text": f"R{i}"} for i in range(21, 26)]
        ]
        items = self._make_items(list(range(1, 26)))
        replacements = self.service.optimize_timing_translations(items)
        
        self.assertEqual(len(self.calls), 3) # 3 chunks, no missing
        for i in range(1, 26):
            self.assertEqual(replacements[i], f"R{i}")

    def test_recovery_preserves_correction_round(self):
        # PART 29 — REQUIRED TEST: CORRECTION ROUND IS NOT INCREMENTED
        self.responses = [
            [{"id": 12, "text": "R12"}], # Misses 13
            [{"id": 13, "text": "R13"}]
        ]
        items = self._make_items([12, 13])
        # Set correction round specifically
        for item in items:
            item["correction_round"] = 2
            
        self.service.optimize_timing_translations(items)
        
        self.assertEqual(len(self.calls), 2)
        self.assertIn('"correction_round": 2', self.calls[1])
        self.assertNotIn('"correction_round": 3', self.calls[1])
