from __future__ import annotations

import unittest
from datetime import datetime, timezone
import re

from src.media_ark.process_captures import (
    truncate_text,
    clean_token,
    extract_keywords,
    media_type_for_ext,
    normalize_filename_lookup,
    parse_query_datetime,
    now_utc_iso,
    is_process_alive,
)

class TestProcessCaptures(unittest.TestCase):
    def test_truncate_text(self):
        self.assertEqual(truncate_text("", max_chars=10), "")
        self.assertEqual(truncate_text(None, max_chars=10), "")
        self.assertEqual(truncate_text("hello", max_chars=10), "hello")
        self.assertEqual(truncate_text("hello world", max_chars=10), "hello w...")

    def test_clean_token(self):
        self.assertEqual(clean_token("Hello, World!"), "hello world")
        self.assertEqual(clean_token("  Test_Token-123  "), "test token 123")
        self.assertEqual(clean_token("abc"), "abc")

    def test_extract_keywords(self):
        # STOP_WORDS are ignored, length <= 3 ignored
        text = "The quick brown fox jumps over the lazy dog and the dog was happy"
        keywords = extract_keywords(text, top_n=3)
        self.assertIn("quick", keywords)
        self.assertIn("brown", keywords)
        self.assertNotIn("the", keywords)
        self.assertNotIn("and", keywords)
        self.assertNotIn("was", keywords)
        self.assertNotIn("dog", keywords) # Wait, 'dog' length is 3, so it's ignored!

    def test_media_type_for_ext(self):
        self.assertEqual(media_type_for_ext(".jpg"), "image")
        self.assertEqual(media_type_for_ext(".png"), "image")
        self.assertEqual(media_type_for_ext(".mp4"), "video")
        self.assertEqual(media_type_for_ext(".mov"), "video")
        self.assertEqual(media_type_for_ext(".pdf"), "document")
        self.assertEqual(media_type_for_ext(".unknown"), "document") # Fallback is document

    def test_normalize_filename_lookup(self):
        self.assertEqual(normalize_filename_lookup("test\u00a0file"), "test file")
        self.assertEqual(normalize_filename_lookup("  test   file  "), "test file")
        self.assertEqual(normalize_filename_lookup("test\u202ffile"), "test file")

    def test_parse_query_datetime(self):
        self.assertIsNone(parse_query_datetime(None))
        self.assertIsNone(parse_query_datetime("   "))
        self.assertEqual(parse_query_datetime("2026-06-20"), datetime(2026, 6, 20))
        
        parsed = parse_query_datetime("2026-06-20T15:30:00Z")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.hour, 15)
        
        self.assertIsNone(parse_query_datetime("invalid-date"))

    def test_now_utc_iso(self):
        val = now_utc_iso()
        self.assertTrue(val.endswith("Z"))
        self.assertNotIn("+00:00", val)
        # Should parse back successfully
        parsed = datetime.fromisoformat(val.replace("Z", "+00:00"))
        self.assertIsNotNone(parsed)

    def test_is_process_alive(self):
        self.assertFalse(is_process_alive(-1))
        self.assertFalse(is_process_alive(0))
        import os
        self.assertTrue(is_process_alive(os.getpid()))

if __name__ == "__main__":
    unittest.main()
