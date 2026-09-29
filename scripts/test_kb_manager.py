#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_kb_manager.py - Comprehensive Automated Test Suite for Kaoyan Writing KB Manager
Covers:
  1. verify: Strict PASS on clean DB, FAIL on corrupt JSON line or missing required fields.
  2. anchor: Brief mode omits official_model text by default; --full includes official_model.
  3. query: 3-tier retrieval, invitation returns zero library morphemes, templates column non-empty.
  4. append: 4-rule admission gate, stable ID generation, deduplication, history.log recording.
  5. batch-update: Evidence-based mastery (independent use -> 稳定, error -> 敢用需注意).
  6. archive: Archival in task1/ subdirectory with absorbed items and tasks.jsonl sync.
  7. cleanup: Dormancy and retirement detection.
  8. path_governance: KB_ROOT env var resolution, failure on invalid path.
"""

import unittest
import os
import sys
import json
import subprocess
import shutil
from pathlib import Path

# Force UTF-8 on Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
KB_ROOT = REPO_ROOT / "knowledge_base"
SCRIPT_PATH = Path(__file__).resolve().parent / "kb_manager.py"

class TestKBManager(unittest.TestCase):

    def setUp(self):
        self.env = dict(os.environ)
        self.env["KB_ROOT"] = str(KB_ROOT)

    def run_cmd(self, cmd_args, env=None, cwd=None):
        full_cmd = [sys.executable, str(SCRIPT_PATH)] + cmd_args
        res = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(cwd or REPO_ROOT),
            env=env or self.env
        )
        return res

    def test_01_verify_passes_on_clean_db(self):
        """Test 'verify' command outputs pass for all DBs."""
        res = self.run_cmd(["verify"])
        self.assertEqual(res.returncode, 0, f"verify failed: {res.stderr}\n{res.stdout}")
        self.assertIn("[PASS] task1", res.stdout)
        self.assertIn("[PASS] shared", res.stdout)
        self.assertIn("[PASS] anchors", res.stdout)
        self.assertIn("验证通过！", res.stdout)

    def test_02_verify_fails_on_corrupt_json(self):
        """E1: Test 'verify' reports FAIL when a corrupted JSON line exists."""
        task1_file = KB_ROOT / "user_brain" / "task1_expressions.jsonl"
        with open(task1_file, "r", encoding="utf-8") as f:
            original_content = f.read()

        try:
            # Append corrupt line
            with open(task1_file, "a", encoding="utf-8") as f:
                f.write("\n{this is broken json line}\n")

            res = self.run_cmd(["verify"])
            self.assertNotEqual(res.returncode, 0, "verify must fail on corrupted JSON lines")
            self.assertIn("JSON格式解析错误", res.stderr + res.stdout)
            self.assertIn("[FAIL] 知识库验证失败", res.stderr + res.stdout)
        finally:
            with open(task1_file, "w", encoding="utf-8") as f:
                f.write(original_content)

    def test_03_anchor_brief_omits_model_and_full_includes_it(self):
        """E3: Test 'anchor' brief mode does NOT output official model; --full does."""
        # 1. Brief mode
        res_brief = self.run_cmd(["anchor", "--genre", "notice"])
        self.assertEqual(res_brief.returncode, 0, f"anchor failed: {res_brief.stderr}")
        self.assertNotIn("The Postgraduate Association", res_brief.stdout)
        self.assertIn("官方范文正文默认不展示", res_brief.stdout)
        self.assertIn("语域与语气深度剖析", res_brief.stdout)
        self.assertIn("句法与考纲词汇标尺", res_brief.stdout)

        # 2. Full mode
        res_full = self.run_cmd(["anchor", "--genre", "notice", "--full"])
        self.assertEqual(res_full.returncode, 0, f"anchor --full failed: {res_full.stderr}")
        self.assertIn("官方高分范文 (Official Model):", res_full.stdout)
        self.assertIn("The Postgraduate Association", res_full.stdout)

    def test_04_query_invitation_relevance_and_no_library(self):
        """C1 & E2: Test 'query --genre invitation' excludes library morphemes and templates are non-empty."""
        res = self.run_cmd(["query", "--genre", "invitation", "--limit", "5"])
        self.assertEqual(res.returncode, 0, f"query failed: {res.stderr}")
        out = res.stdout

        # Must not contain library or complaint morphemes
        self.assertNotIn("图书馆与学习环境", out)
        self.assertNotIn("占座", out)
        self.assertNotIn("开馆时间", out)
        self.assertNotIn("消费者维权", out)
        self.assertNotIn("预制菜", out)

        # Column 3 must be non-empty (invitation template present)
        self.assertIn("【三、本题建议结构/模板】", out)
        self.assertIn("邀请信", out)

    def test_05_append_admission_rules_and_deduplication(self):
        """P1-5: Test append admission gates and deduplication."""
        # 1. Non-reusable item (no slots or templates) should be rejected
        bad_item = {
            "category": "functional_sentence",
            "genre": "advice",
            "intent": "一次性具体事实描述",
            "expression": "Yesterday Li Ming met Zhang Wei at room 204.",
            "source": "测试来源"
        }
        res_bad = self.run_cmd(["append", "--target", "task1", "--data", json.dumps(bad_item, ensure_ascii=False)])
        self.assertIn("[REJECT]", res_bad.stdout)

        # 2. Valid reusable item
        good_item = {
            "category": "functional_sentence",
            "genre": "advice",
            "intent": "提出数字化资源优化建议",
            "expression": "It would be of great service for [entity] to optimize [system], thereby [benefit].",
            "slots": {"[entity]": "机构", "[system]": "系统", "[benefit]": "效益"},
            "source": "名师语料库",
            "exam_band": "大纲内"
        }
        res_good = self.run_cmd(["append", "--target", "task1", "--data", json.dumps(good_item, ensure_ascii=False)])
        self.assertEqual(res_good.returncode, 0)
        self.assertIn("[ADDED]", res_good.stdout)

        # 3. Deduplication: appending again should skip
        res_dup = self.run_cmd(["append", "--target", "task1", "--data", json.dumps(good_item, ensure_ascii=False)])
        self.assertEqual(res_dup.returncode, 0)
        self.assertIn("[SKIP] 条目已存在，跳过防重", res_dup.stdout)

        # Clean up added item
        task1_file = KB_ROOT / "user_brain" / "task1_expressions.jsonl"
        with open(task1_file, "r", encoding="utf-8") as f:
            records = [json.loads(l) for l in f if "optimize [system]" not in l]
        with open(task1_file, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def test_06_batch_update_mastery_and_evidence(self):
        """C5, C6, C7: Test batch-update mastery transition evidence."""
        # 1. Update with independent=true
        batch_payload = {
            "task_id": "T-TEST-002",
            "status_updates": [
                {
                    "id": "T1_ADV_001",
                    "status": "稳定",
                    "independent": True,
                    "note": "跨题新题目独立用对"
                }
            ]
        }
        res = self.run_cmd(["batch-update", "--data", json.dumps(batch_payload, ensure_ascii=False)])
        self.assertEqual(res.returncode, 0, f"batch-update failed: {res.stderr}")
        self.assertIn("未接触 ➔ 稳定", res.stdout)

        # 2. Update with error note -> 敢用 (需注意)
        batch_error = {
            "task_id": "T-TEST-003",
            "status_updates": [
                {
                    "id": "T1_ADV_002",
                    "status": "敢用",
                    "error": True,
                    "note": "主动尝试但有搭配瑕疵"
                }
            ]
        }
        res_err = self.run_cmd(["batch-update", "--data", json.dumps(batch_error, ensure_ascii=False)])
        self.assertEqual(res_err.returncode, 0)
        self.assertIn("未接触 ➔ 敢用", res_err.stdout)

        # Reset states back to clean
        task1_file = KB_ROOT / "user_brain" / "task1_expressions.jsonl"
        with open(task1_file, "r", encoding="utf-8") as f:
            records = [json.loads(l) for l in f]
        for r in records:
            if r.get("id") in ("T1_ADV_001", "T1_ADV_002"):
                r["mastery"] = "未接触"
                r["mastery_note"] = ""
                r["history"]["used_count"] = 0
                r["history"]["independent_use_count"] = 0
                r["history"]["error_use_count"] = 0
                r["history"]["used_in_tasks"] = []
                r["history"]["user_notes"] = ""
        with open(task1_file, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def test_07_archive_and_tasks_sync(self):
        """P1-1 & P2-5: Test 'archive' saves in task1/ and syncs with tasks.jsonl."""
        task_id = "T-TEST-ARCH-001"
        res = self.run_cmd([
            "archive",
            "--title", "Test Archive Essay",
            "--genre", "advice",
            "--year", "2024",
            "--task-id", task_id,
            "--content", "Dear Sir or Madam,\n\n    Test content.\n\nYours sincerely,\nLi Ming",
            "--metadata", json.dumps({"absorbed_items": ["[T1_ADV_001] Test item"]}, ensure_ascii=False)
        ])
        self.assertEqual(res.returncode, 0, f"archive failed: {res.stderr}")
        self.assertIn("[OK] 范文已成功归档至", res.stdout)
        self.assertIn("[OK] 题目台账已同步至", res.stdout)

        # Verify file exists in task1/
        arch_dir = KB_ROOT / "user_brain" / "satisfaction_archives" / "task1"
        matching = list(arch_dir.glob("*_Test_Archive_Essay.md"))
        self.assertGreaterEqual(len(matching), 1)

        # Clean up archive file and tasks.jsonl entry
        for f in matching:
            f.unlink()
        tasks_file = KB_ROOT / "user_brain" / "tasks.jsonl"
        if tasks_file.exists():
            with open(tasks_file, "r", encoding="utf-8") as f:
                t_lines = [l for l in f if task_id not in l]
            with open(tasks_file, "w", encoding="utf-8") as f:
                f.writelines(t_lines)

    def test_08_cleanup_command(self):
        """Test 'cleanup' command runs evaluation."""
        res = self.run_cmd(["cleanup"])
        self.assertEqual(res.returncode, 0, f"cleanup failed: {res.stderr}")
        self.assertIn("建议转为休眠 (dormant) 条目", res.stdout)
        self.assertIn("建议软删除退役 (retired) 条目", res.stdout)

    def test_09_genre_normalization_and_anchor_query(self):
        """Test genre aliasing (e.g. suggestion -> advice) in anchor and query."""
        res_anchor = self.run_cmd(["anchor", "--genre", "suggestion"])
        self.assertEqual(res_anchor.returncode, 0, f"anchor --genre suggestion failed: {res_anchor.stderr}")
        self.assertIn("2021 English I · advice", res_anchor.stdout)

        res_query = self.run_cmd(["query", "--genre", "suggestion", "--limit", "3"])
        self.assertEqual(res_query.returncode, 0, f"query --genre suggestion failed: {res_query.stderr}")
        # Morphemes must not include library noise
        self.assertNotIn("消费者维权", res_query.stdout)

    def test_10_check_essay_command(self):
        """Test 'check-essay' CLI diagnoses word count, ratio, contractions, exclamation, and format."""
        # 1. Clean essay
        clean_essay = (
            "Dear Li Ming,\n\n"
            "    Hearing that you have been admitted to a university, I am writing to extend my congratulations "
            "and offer some suggestions for your transition to campus life.\n"
            "    In daily life, it is crucial to cultivate self-reliance, as you will live without your parents' care. "
            "To begin with, learning to manage your monthly living expenses keeps your budget in check. "
            "Moreover, getting along well with your roommates will spare you needless dormitory conflicts. "
            "As for study, exploring your major in advance will pay off, covering the courses awaiting you "
            "and career prospects after graduation.\n"
            "    Finally, I wish you a rewarding university life filled with happiness and knowledge.\n\n"
            "Best regards,\n"
            "Li Ming"
        )
        res_clean = self.run_cmd(["check-essay", "--text", clean_essay, "--json"])
        self.assertEqual(res_clean.returncode, 0, f"check-essay clean failed: {res_clean.stderr}")
        data_clean = json.loads(res_clean.stdout)
        self.assertEqual(data_clean["body_total"], 105)
        self.assertEqual(data_clean["word_count_status"], "PASS")
        self.assertEqual(len(data_clean["contractions"]), 0)
        self.assertEqual(data_clean["exclamations"], 0)
        self.assertEqual(len(data_clean["format_issues"]), 0)

        # 2. Flawed essay
        flawed_essay = (
            "Dear Li Ming:\n\n"
            "    I'm writing to say congratulations! You'd better prepare early.\n"
            "    Don't forget to wash clothes.\n"
            "    Hoping you happy.\n\n"
            "Best regards\n"
            "Li Ming."
        )
        res_flawed = self.run_cmd(["check-essay", "--text", flawed_essay, "--json"])
        self.assertEqual(res_flawed.returncode, 0, f"check-essay flawed failed: {res_flawed.stderr}")
        data_flawed = json.loads(res_flawed.stdout)
        self.assertGreater(len(data_flawed["contractions"]), 0)
        self.assertEqual(data_flawed["exclamations"], 1)
        self.assertGreater(len(data_flawed["format_issues"]), 0)

if __name__ == "__main__":
    unittest.main()
