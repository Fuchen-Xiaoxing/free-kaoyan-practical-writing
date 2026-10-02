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
    plan_notepad_update,
    format_mnemonic_note,
    MaimemoClient,
    sync_essay_vocabulary,
    DEFAULT_NOTEPAD_TITLE
)


class TestCrossRunIdempotency(unittest.TestCase):
    """P1-7: retrying a sync for the same chapter must not duplicate cards.

    POST /phrases and POST /notes always create new objects, so a naive retry
    pollutes the student's MaiMemo account with duplicate cards. The chapter
    content is the only cross-run ledger available through documented endpoints.
    """

    def test_plan_notepad_update_reports_added_words(self):
        # Brand new notepad -> everything is new
        content, added = plan_notepad_update("", "2011英二小作文", ["accommodate", "prolong"])
        self.assertEqual(added, ["accommodate", "prolong"])
        self.assertIn("# 2011英二小作文", content)

        # Same chapter again -> nothing is new
        content2, added2 = plan_notepad_update(content, "2011英二小作文", ["accommodate", "prolong"])
        self.assertEqual(added2, [], "already-present words must not be reported as new")
        self.assertEqual(content2, content)

        # Partially new -> only the missing one is reported
        _c3, added3 = plan_notepad_update(content, "2011英二小作文", ["accommodate", "refund"])
        self.assertEqual(added3, ["refund"])

    def test_second_sync_creates_no_duplicate_phrase_or_note(self):
        import maimemo_sync as ms

        state = {"content": "", "phrases": [], "notes": [], "review_ids": []}

        def fake_request(self, method, path, body=None):
            if path == "/vocabulary/query":
                spells = (body or {}).get("spellings", [])
                return {"success": True, "errors": [],
                        "data": {"voc": [{"id": f"voc_{w}", "spelling": w} for w in spells]}}
            if path.startswith("/notepads?") and method == "GET":
                return {"success": True, "errors": [], "data": {"notepads": [
                    {"id": "np1", "title": ms.DEFAULT_NOTEPAD_TITLE, "brief": "", "tags": ["考研"],
                     "status": "PUBLISHED"}]}}
            if path == "/notepads/np1" and method == "GET":
                return {"success": True, "errors": [],
                        "data": {"notepad": {"id": "np1", "content": state["content"]}}}
            if path == "/notepads/np1" and method == "POST":
                state["content"] = body["notepad"]["content"]
                return {"success": True, "errors": [], "data": {"id": "np1", "notepad": body["notepad"]}}
            if path == "/phrases":
                state["phrases"].append(body["phrase"]["phrase"])
                return {"success": True, "errors": [], "data": {"id": "ph1"}}
            if path == "/notes":
                state["notes"].append(body["note"]["note"])
                return {"success": True, "errors": [], "data": {"id": "nt1"}}
            if path == "/study/add_words":
                state["review_ids"] += [w["id"] for w in (body or {}).get("words", [])]
                return {"success": True, "errors": [], "data": {"added_count": len((body or {}).get("words", []))}}
            return {"success": True, "errors": [], "data": {}}

        payload = {
            "chapter": "2011英二小作文",
            "task_id": "T2011-E2-ADV",
            "words": [{
                "spelling": "accommodate",
                "type": "spelling_fix",
                "misspelling": "acommodate",
                "sentence": "The library is expected to accommodate students.",
                "translation": "图书馆预计将容纳学生。",
                "usage_note": "高频动词",
                "grammar_note": "不定式作目的状语",
            }],
        }

        original = ms.MaimemoClient.request
        ms.MaimemoClient.request = fake_request
        try:
            first = ms.sync_essay_vocabulary(payload, token="dummy")
            self.assertEqual(first["status"], "success")
            self.assertEqual(len(state["phrases"]), 1)
            self.assertEqual(len(state["notes"]), 1)
            self.assertEqual(len(state["review_ids"]), 1)

            second = ms.sync_essay_vocabulary(payload, token="dummy")
            self.assertEqual(second["status"], "success")
            self.assertEqual(len(state["phrases"]), 1, "retry duplicated the example phrase")
            self.assertEqual(len(state["notes"]), 1, "retry duplicated the mnemonic note")
            self.assertEqual(len(state["review_ids"]), 1, "retry re-pushed an already-synced word")
            self.assertEqual(second["already_synced_words"], ["accommodate"])
            self.assertEqual(second["synced_words"], [])
            self.assertTrue(second["remote_side_effects"]["idempotent_retry"])
        finally:
            ms.MaimemoClient.request = original


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
        """目标词不在例句中时必须返回空列表，绝不回落高亮句首。"""
        sentence = "This is a simple sentence."
        ranges = find_word_highlight_ranges(sentence, "prolong")
        self.assertEqual(ranges, [])


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
        old_token = os.environ.pop("MAIMEMO_SPELLING_TOKEN", None)
        try:
            client = MaimemoClient(token="", mock=False)
            with self.assertRaises(ValueError) as ctx:
                client.request("GET", "/test")
            self.assertIn("MAIMEMO_SPELLING_TOKEN 未设置", str(ctx.exception))
        finally:
            if old_token is not None:
                os.environ["MAIMEMO_SPELLING_TOKEN"] = old_token

    def test_env_spelling_token_resolution(self):
        old_token = os.environ.get("MAIMEMO_SPELLING_TOKEN")
        try:
            os.environ["MAIMEMO_SPELLING_TOKEN"] = "test_spell_tok_12345"
            client = MaimemoClient(token=None, mock=True)
            self.assertEqual(client.token, "test_spell_tok_12345")
        finally:
            if old_token is not None:
                os.environ["MAIMEMO_SPELLING_TOKEN"] = old_token
            else:
                os.environ.pop("MAIMEMO_SPELLING_TOKEN", None)

    def test_maimemo_token_is_ignored_for_isolation(self):
        """确保写作 Skill 绝不读取 MAIMEMO_TOKEN（阅读账号专用），保证账号物理隔离。"""
        old_spell = os.environ.pop("MAIMEMO_SPELLING_TOKEN", None)
        old_read = os.environ.get("MAIMEMO_TOKEN")
        try:
            os.environ["MAIMEMO_TOKEN"] = "reading_account_token_should_not_leak"
            client = MaimemoClient(token=None, mock=True)
            self.assertEqual(client.token, "")
        finally:
            if old_spell is not None:
                os.environ["MAIMEMO_SPELLING_TOKEN"] = old_spell
            if old_read is not None:
                os.environ["MAIMEMO_TOKEN"] = old_read
            else:
                os.environ.pop("MAIMEMO_TOKEN", None)

    def test_duplicate_spellings_are_deduped(self):
        """同一 spelling 重复出现时只同步一次，避免重复建例句/助记。"""
        payload = {
            "chapter": "2012英二小作文",
            "words": [
                {"spelling": "express", "sentence": "I am writing to express my dissatisfaction."},
                {"spelling": "Express", "sentence": "I am writing to express my dissatisfaction."},
            ],
        }
        res = sync_essay_vocabulary(payload, mock=True)
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["synced_words"], ["express"])
        self.assertEqual(res["phrases_created"], 1)

    def test_phrase_failures_surface_as_partial_failed(self):
        """P2-3: 例句创建全部失败时不得再返回 success（杜绝静默假成功）。"""
        payload = {
            "chapter": "2012英二小作文",
            "words": [
                {"spelling": "express", "sentence": "I am writing to express my dissatisfaction."},
                {"spelling": "lodge", "sentence": "I am writing to lodge a complaint."},
            ],
        }
        original = MaimemoClient.create_example_phrase

        def _boom(self, *a, **kw):
            raise RuntimeError("phrases endpoint rejected the payload")

        MaimemoClient.create_example_phrase = _boom
        try:
            res = sync_essay_vocabulary(payload, mock=True)
        finally:
            MaimemoClient.create_example_phrase = original

        self.assertEqual(res["status"], "partial_failed")
        self.assertEqual(res["phrases_created"], 0)
        self.assertEqual(res["phrases_failed"], 2)
        self.assertIn("例句创建全部失败", res["message"])

    def test_highlight_missing_is_reported(self):
        """目标词不在例句中时记录 highlight_missing，便于私教复核例句质量。"""
        payload = {
            "chapter": "2012英二小作文",
            "words": [
                {"spelling": "prolong", "sentence": "This sentence does not contain the target."},
            ],
        }
        res = sync_essay_vocabulary(payload, mock=True)
        self.assertEqual(res["status"], "success")
        self.assertIn("prolong", res["highlight_missing"])


class TestDataUnwrapping(unittest.TestCase):
    def test_unwrap_data_nested(self):
        resp = {"success": True, "data": {"voc": [{"id": "1", "spelling": "test"}]}, "errors": []}
        unwrapped = MaimemoClient._unwrap_data(resp)
        self.assertEqual(unwrapped, {"voc": [{"id": "1", "spelling": "test"}]})

    def test_unwrap_data_flat(self):
        resp = {"voc": [{"id": "1", "spelling": "test"}]}
        unwrapped = MaimemoClient._unwrap_data(resp)
        self.assertEqual(unwrapped, {"voc": [{"id": "1", "spelling": "test"}]})

    def test_unwrap_data_non_dict(self):
        self.assertEqual(MaimemoClient._unwrap_data([]), [])
        self.assertEqual(MaimemoClient._unwrap_data(None), None)


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
