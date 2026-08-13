import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path

from stitch_studio.subtitle_timeline_scaler import SubtitleSegment
from stitch_studio.services import TranslationService

class DummyConfig:
    def __init__(self):
        self.gemini_api_key_path = None


class TestInitialTranslationRecovery(unittest.TestCase):
    def setUp(self):
        self.config = DummyConfig()

        self.storage = MagicMock()
        
        self.service = TranslationService(self.storage, self.config)

        
        # We will mock _gemini_client to return a mock client
        self.mock_client = MagicMock()
        self.mock_models = MagicMock()
        self.mock_client.models = self.mock_models
        self.service._gemini_client = MagicMock(return_value=self.mock_client)
        
        # We will inject responses for each call
        self.responses = []
        self.calls = []
        
        def mock_generate_content(*args, **kwargs):
            self.calls.append(kwargs.get("contents", ""))
            response_text = self.responses.pop(0) if self.responses else ""
            mock_response = MagicMock()
            mock_response.text = response_text
            return mock_response
            
        self.mock_models.generate_content.side_effect = mock_generate_content
        
    def _make_segments(self, ids):
        return [SubtitleSegment(index=i, start=0.0, end=1.0, text=f"text {i}") for i in ids]
        
    def test_complete_chunk(self):
        # PART 20 - REQUIRED TEST: COMPLETE CHUNK
        # Input [1,2,3,4], Returns all
        self.responses = [
            "1\n00:00:00,000 --> 00:00:01,000\nR1\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nR2\n\n"
            "3\n00:00:02,000 --> 00:00:03,000\nR3\n\n"
            "4\n00:00:03,000 --> 00:00:04,000\nR4"
        ]
        segments = self._make_segments([1, 2, 3, 4])
        
        results = self.service._translate_with_gemini(segments, "en", "vi")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(results, ["R1", "R2", "R3", "R4"])

    def test_one_missing_id(self):
        # PART 21 - REQUIRED TEST: ONE MISSING ID
        # Input [1,2,3,4], Returns [1,2,4], missing 3. Recovers 3.
        # Fallback will trigger first because full SRT fails.
        self.responses = [
            # 1. Full SRT fails (missing 3)
            "1\n00:00:00,000 --> 00:00:01,000\nR1\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nR2\n\n"
            "4\n00:00:03,000 --> 00:00:04,000\nR4",
            # Recovery 1 for full SRT (fails to get 3)
            "",
            # Recovery 2 for full SRT (fails to get 3)
            "",
            # 2. Fallback chunk 1 (missing 3)
            "1\n00:00:00,000 --> 00:00:01,000\nR1\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\nR2\n\n"
            "4\n00:00:03,000 --> 00:00:04,000\nR4",
            # 3. Recovery for 3
            "3\n00:00:02,000 --> 00:00:03,000\nR3"
        ]
        segments = self._make_segments([1, 2, 3, 4])
        
        results = self.service._translate_with_gemini(segments, "en", "vi")
        
        self.assertIn("\n1\n00:00:", self.calls[0]) # Full SRT
        self.assertIn("\n1\n00:00:", self.calls[3]) # Chunk 1 initial
        self.assertIn("\n3\n00:00:", self.calls[4]) # Recovery for 3
        self.assertNotIn("\n1\n00:00:", self.calls[4]) # Shouldn't resend 1
        self.assertEqual(results, ["R1", "R2", "R3", "R4"])

    def test_multiple_missing_ids(self):
        # PART 22 - REQUIRED TEST: MULTIPLE MISSING IDS
        ids = list(range(141, 151))
        segments = self._make_segments(ids)
        
        # 141..145 valid
        r1 = "\n\n".join([f"{i}\n00:00:00,000 --> 00:00:01,000\nR{i}" for i in range(141, 146)])
        # 146..150 recovery
        r2 = "\n\n".join([f"{i}\n00:00:00,000 --> 00:00:01,000\nR{i}" for i in range(146, 151)])
        
        self.responses = [
            r1, # Full SRT fails
            "", # Full SRT Recovery 1
            "", # Full SRT Recovery 2
            r1, # Chunk 1
            r2, # Recovery
        ]
        
        results = self.service._translate_with_gemini(segments, "en", "vi")
        
        self.assertIn("\n146\n00:00:", self.calls[4])
        self.assertNotIn("\n141\n00:00:", self.calls[4]) # Shouldn't resend 141-145
        self.assertEqual(results, [f"R{i}" for i in range(141, 151)])
        
    def test_partial_recovery(self):
        # PART 23 - REQUIRED TEST: PARTIAL RECOVERY
        ids = [146, 147, 148]
        segments = self._make_segments(ids)
        
        self.responses = [
            "", # Full SRT initial fails
            "", # Full SRT Recovery 1
            "", # Full SRT Recovery 2
            "", # Chunk 1 initial fails
            "146\n00:00:00,000 --> 00:00:01,000\nR146\n\n148\n00:00:00,000 --> 00:00:01,000\nR148", # Recovery 1
            "147\n00:00:00,000 --> 00:00:01,000\nR147", # Recovery 2
        ]
        
        results = self.service._translate_with_gemini(segments, "en", "vi")
        self.assertIn("\n147\n00:00:", self.calls[5])
        self.assertNotIn("\n146\n00:00:", self.calls[5])
        self.assertEqual(results, ["R146", "R147", "R148"])

    def test_unexpected_id(self):
        # PART 24 - REQUIRED TEST: UNEXPECTED ID
        segments = self._make_segments([1, 2, 3])
        
        self.responses = [
            "", "", "", # Full SRT fails
            # 1,2,3 valid, 999 ignored
            "1\n00:00:00,000 --> 00:00:01,000\nR1\n\n"
            "2\n00:00:00,000 --> 00:00:01,000\nR2\n\n"
            "3\n00:00:00,000 --> 00:00:01,000\nR3\n\n"
            "999\n00:00:00,000 --> 00:00:01,000\nR999"
        ]
        
        results = self.service._translate_with_gemini(segments, "en", "vi")
        self.assertEqual(results, ["R1", "R2", "R3"])

    def test_duplicate_id(self):
        # PART 25 - REQUIRED TEST: DUPLICATE ID
        segments = self._make_segments([1, 2, 3])
        
        self.responses = [
            "", "", "", # Full SRT fails
            # chunk 1
            "1\n00:00:00,000 --> 00:00:01,000\nR1\n\n"
            "2\n00:00:00,000 --> 00:00:01,000\nR2_a\n\n"
            "2\n00:00:00,000 --> 00:00:01,000\nR2_b\n\n"
            "3\n00:00:00,000 --> 00:00:01,000\nR3",
            
            # Recovery for 2
            "2\n00:00:00,000 --> 00:00:01,000\nR2_recovered",
        ]
        
        results = self.service._translate_with_gemini(segments, "en", "vi")
        self.assertEqual(results, ["R1", "R2_recovered", "R3"])

    def test_empty_block(self):
        # PART 26 - REQUIRED TEST: EMPTY BLOCK
        segments = self._make_segments([1, 2, 3])
        
        self.responses = [
            "", "", "", # Full SRT fails
            
            # Same for chunk
            "1\n00:00:00,000 --> 00:00:01,000\nR1\n\n"
            "2\n00:00:00,000 --> 00:00:01,000\n \n\n"
            "3\n00:00:00,000 --> 00:00:01,000\nR3",
            
            # Recovery for 2
            "2\n00:00:00,000 --> 00:00:01,000\nR2_recovered",
        ]
        
        results = self.service._translate_with_gemini(segments, "en", "vi")
        self.assertEqual(results, ["R1", "R2_recovered", "R3"])
        
    def test_chunk_size(self):
        # PART 27 - REQUIRED TEST: CHUNK SIZE (25)
        # 76 subtitles -> 25, 25, 25, 1
        segments = self._make_segments(range(1, 77))
        
        # 1. Full SRT fails
        self.responses.extend(["", "", ""])

        
        # 2. Chunk 1 (1-25)
        self.responses.append("\n\n".join([f"{i}\n00:00:00,000 --> 00:00:01,000\nR{i}" for i in range(1, 26)]))
        # 3. Chunk 2 (26-50)
        self.responses.append("\n\n".join([f"{i}\n00:00:00,000 --> 00:00:01,000\nR{i}" for i in range(26, 51)]))
        # 4. Chunk 3 (51-75)
        self.responses.append("\n\n".join([f"{i}\n00:00:00,000 --> 00:00:01,000\nR{i}" for i in range(51, 76)]))
        # 5. Chunk 4 (76-76)
        self.responses.append("76\n00:00:00,000 --> 00:00:01,000\nR76")
        
        results = self.service._translate_with_gemini(segments, "en", "vi")
        self.assertEqual(len(results), 76)
        self.assertEqual(results[0], "R1")
        self.assertEqual(results[75], "R76")

    def test_final_unresolved_id(self):
        # PART 28 - REQUIRED TEST: FINAL UNRESOLVED ID
        segments = self._make_segments([148, 149, 150])
        
        self.responses = [
            "148\n00:00:00,000 --> 00:00:01,000\nR148\n\n150\n00:00:00,000 --> 00:00:01,000\nR150", # Full SRT
            "", # Full SRT Recovery 1
            "", # Full SRT Recovery 2
            "148\n00:00:00,000 --> 00:00:01,000\nR148\n\n150\n00:00:00,000 --> 00:00:01,000\nR150", # Chunk 1
            "", # Recovery 1
            "", # Recovery 2
            "", # Final Single-ID recovery for 149
        ]
        
        with self.assertRaises(RuntimeError) as cm:
            self.service._translate_with_gemini(segments, "en", "vi")
            
        self.assertIn("[149]", str(cm.exception))
        self.assertNotIn("148", str(cm.exception))
        
    def test_vietnamese_routing(self):
        # PART 29 - REQUIRED TEST: VIETNAMESE ROUTING
        segments = self._make_segments([1, 2])
        self.responses = ["", "", "", "1\n00:00:00,000 --> 00:00:01,000\nR1\n\n2\n00:00:00,000 --> 00:00:01,000\nR2"]
        
        self.service._translate_with_gemini(segments, "zh", "vi")
        
        # It should use _VI_INITIAL_SRT_PROMPT somewhere in the prompt for recovery
        self.assertTrue(any("natural spoken Vietnamese" in c for c in self.calls))

    def test_english_routing(self):
        # PART 30 - REQUIRED TEST: ENGLISH ROUTING
        segments = self._make_segments([1, 2])
        self.responses = ["", "", "", "1\n00:00:00,000 --> 00:00:01,000\nR1\n\n2\n00:00:00,000 --> 00:00:01,000\nR2"]
        
        self.service._translate_with_gemini(segments, "zh", "en")
        
        self.assertTrue(any("natural spoken English" in c for c in self.calls))

if __name__ == '__main__':
    unittest.main()
