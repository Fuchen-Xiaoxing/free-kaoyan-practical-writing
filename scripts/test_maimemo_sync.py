#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_maimemo_sync.py - Unit Tests for MaiMemo (墨墨背单词) Sync Engine
"""

import unittest
import os
import sys
import json
import tempfile
from pathlib import Path

# Ensure scripts dir is on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from maimemo_sync import (
    find_word_highlight_ranges,
    update_notepad_content,
    format_mnemonic_note,
    MaimemoClient,
    sync_essay_vocabulary,
    DEFAULT_NOTEPAD_TITLE
)


class TestHighlightCalculation(unittest.TestCase):
    def test_exact_match_middle(self):
        sentence = "The library is expected to prolong opening hours to accommodate students."
        ranges = find_word_highlight_ranges(sentence, "accommodate")
        self.assertEqual(len(ranges), 1)
        start, end = ranges[0]["start"], ranges[0]["end"]
        self.assertEqual(sentence[start:end].lower(), "accommodate")
        self.assertEqual(start, 52)
        self.assertEqual(end, 63)

    def test_exact_match_beginning(self):
        sentence = "Accommodate student requests as much as possible."
        ranges = find_word_highlight_ranges(sentence, "accommodate")
        self.assertEqual(len(ranges), 1)
        start, end = ranges[0]["start"], ranges[0]["end"]
        self.assertEqual(start, 0)
        self.assertEqual(end, 11)
        self.assertEqual(sentence[start:end], "Accommodate")

    def test_inflection_match(self):
        sentence = "The university is accommodating more international students."
        ranges = find_word_highlight_ranges(sentence, "accommodate")
        self.assertEqual(len(ranges), 1)
        start, end = ranges[0]["start"], ranges[0]["end"]
        self.assertEqual(sentence[start:end].lower(), "accommodating")

    def test_fallback_unmatched(self):
        sentence = "This is a simple sentence."
        ranges = find_word_highlight_ranges(sentence, "prolong")
        self.assertEqual(len(ranges), 1)
        self.assertEqual(ranges[0]["start"], 0)


class TestNotepadContentUpdate(unittest.TestCase):
    def test_new_notepad_content(self):
        res = update_notepad_content("", "2011英二小作文", ["accommodate", "prolong"])
        expected = "# 2011英二小作文\naccommodate\nprolong"
        self.assertEqual(res, expected)

    def test_append_new_chapter_to_existing(self):
        existing = "# 2010英一小作文\nrecommend\nsuggest"
        res = update_notepad_content(existing, "2011英二小作文", ["accommodate"])
        self.assertIn("# 2010英一小作文", res)
        self.assertIn("# 2011英二小作文", res)
        self.assertTrue(res.endswith("accommodate"))

    def test_append_to_existing_chapter_with_dedup(self):
        existing = "# 2011英二小作文\naccommodate\n\n# 2012英一小作文\napply"
        res = update_notepad_content(existing, "2011英二小作文", ["accommodate", "prolong"])
        # Should not duplicate 'accommodate' in 2011 chapter
        lines = [line.strip() for line in res.split("\n") if line.strip()]
        accommodate_count = sum(1 for l in lines if l == "accommodate")
        self.assertEqual(accommodate_count, 1)
        self.assertIn("prolong", lines)
        # Verify 2012 chapter is still intact
        self.assertIn("# 2012英一小作文", res)
        self.assertIn("apply", res)

    def test_no_change_when_all_exist(self):
        existing = "# 2011英二小作文\naccommodate\nprolong"
        res = update_notepad_content(existing, "2011英二小作文", ["accommodate", "prolong"])
        self.assertEqual(res, existing)


class TestMnemonicFormatting(unittest.TestCase):
    def test_spelling_fix_format(self):
        data = {
            "spelling": "accommodate",
            "type": "spelling_fix",
            "misspelling": "acommodate",
            "usage_note": "常接 students 表示容纳与迎合",
            "grammar_note": "不定式作目的状语"
        }
        note = format_mnemonic_note(data)
        self.assertIn("【初稿纠偏】：初稿误拼为 acommodate，正确拼写为 accommodate", note)
        self.assertIn("【考研写作用法】：常接 students 表示容纳与迎合", note)
        self.assertIn("【原句语法剖析】：不定式作目的状语", note)

    def test_advanced_vocab_format(self):
        data = {
            "spelling": "prolong",
            "type": "advanced_vocab",
            "usage_note": "及物动词常搭 opening hours",
            "grammar_note": "be expected to 后接动原"
        }
        note = format_mnemonic_note(data)
        self.assertNotIn("【初稿纠偏】", note)
        self.assertIn("【考研写作用法】：及物动词常搭 opening hours", note)
        self.assertIn("【原句语法剖析】：be expected to 后接动原", note)


class TestMaimemoSyncPipeline(unittest.TestCase):
    def test_sync_mock_success(self):
        payload = {
            "chapter": "2011英二小作文",
            "task_id": "T2011-E2-ADV",
            "words": [
                {
                    "spelling": "accommodate",
                    "type": "spelling_fix",
                    "misspelling": "acommodate",
                    "sentence": "The library is expected to prolong opening hours to accommodate students.",
                    "translation": "图书馆预计将延长开放时间以方便学生。",
                    "usage_note": "考研高频动词，替换 meet",
                    "grammar_note": "不定式短语作目的状语"
                },
                {
                    "spelling": "prolong",
                    "type": "advanced_vocab",
                    "sentence": "The library is expected to prolong opening hours to accommodate students.",
                    "translation": "图书馆预计将延长开放时间以方便学生。",
                    "usage_note": "书面严谨，替换 lengthen",
                    "grammar_note": "核心不定式动词"
                }
            ]
        }
        res = sync_essay_vocabulary(payload, mock=True)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["notepad_title"], DEFAULT_NOTEPAD_TITLE)
        self.assertEqual(res["chapter"], "2011英二小作文")
        self.assertEqual(res["synced_words"], ["accommodate", "prolong"])
        self.assertEqual(res["phrases_created"], 2)
        self.assertEqual(res["notes_created"], 2)
        self.assertTrue(res["study_advance"])

    def test_empty_words_skipped(self):
        payload = {"chapter": "2011英二小作文", "words": []}
        res = sync_essay_vocabulary(payload, mock=True)
        self.assertEqual(res["status"], "skipped")

    def test_missing_token_error_in_real_mode(self):
        old_token = os.environ.pop("MAIMEMO_TOKEN", None)
        try:
            client = MaimemoClient(token="", mock=False)
            with self.assertRaises(ValueError) as ctx:
                client.request("GET", "/test")
            self.assertIn("MAIMEMO_TOKEN 未设置", str(ctx.exception))
        finally:
            if old_token is not None:
                os.environ["MAIMEMO_TOKEN"] = old_token


class TestKBManagerIntegration(unittest.TestCase):
    def test_kb_manager_maimemo_sync_mock(self):
        import subprocess
        payload = {
            "chapter": "2015英二小作文",
            "words": [
                {
                    "spelling": "appreciate",
                    "sentence": "I would appreciate it if you could consider my request.",
                    "usage_note": "I would appreciate it if 礼貌请求",
                    "grammar_note": "it 作形式宾语"
                }
            ]
        }
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".json") as f:
            json.dump(payload, f)
            temp_path = f.name

        try:
            cmd = [
                sys.executable,
                str(SCRIPT_DIR / "kb_manager.py"),
                "maimemo-sync",
                "--file", temp_path,
                "--mock",
                "--json"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
            output = json.loads(result.stdout)
            self.assertEqual(output["status"], "success")
            self.assertEqual(output["chapter"], "2015英二小作文")
            self.assertEqual(output["synced_words"], ["appreciate"])
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    unittest.main()
