import unittest
from unittest.mock import MagicMock
from stitch_studio.services import TranslationService, _build_initial_srt_prompt
from stitch_studio.models import SubtitleSegment

class PromptConstructionTests(unittest.TestCase):
    def test_srt_content_placeholder_is_replaced(self) -> None:
        segments = [SubtitleSegment(1, 0.0, 1.0, "测试")]
        
        # Test English
        base_prompt_en = _build_initial_srt_prompt("en", "en")
        srt_content = TranslationService._segments_to_srt_text(segments)
        final_prompt_en = base_prompt_en.replace("{SRT_CONTENT}", srt_content)
        
        self.assertNotIn("{SRT_CONTENT}", final_prompt_en)
        self.assertEqual(final_prompt_en.count("测试"), 1)
        
        # Test Vietnamese
        base_prompt_vi = _build_initial_srt_prompt("vi", "vi")
        final_prompt_vi = base_prompt_vi.replace("{SRT_CONTENT}", srt_content)
        
        self.assertNotIn("{SRT_CONTENT}", final_prompt_vi)
        self.assertEqual(final_prompt_vi.count("测试"), 1)
