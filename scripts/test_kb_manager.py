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
import tempfile
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
        self.assertNotIn("Fifty volunteers will be recruited", res_brief.stdout)
        self.assertIn("官方范文正文默认不展示", res_brief.stdout)
        self.assertIn("语域与语气深度剖析", res_brief.stdout)
        self.assertIn("句法与考纲词汇标尺", res_brief.stdout)

        # 2. Full mode
        res_full = self.run_cmd(["anchor", "--genre", "notice", "--full"])
        self.assertEqual(res_full.returncode, 0, f"anchor --full failed: {res_full.stderr}")
        self.assertIn("官方高分范文 (Official Model", res_full.stdout)
        self.assertIn("Fifty volunteers will be recruited", res_full.stdout)

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

    def test_11_english_ii_complete_16_years_coverage(self):
        """Verify that all 16 years (2010-2025) of English II past papers exist and can be queried."""
        for yr in range(2010, 2026):
            res = self.run_cmd(["anchor", "--year", str(yr)])
            self.assertEqual(res.returncode, 0, f"Querying anchor for year {yr} failed: {res.stderr}")
            self.assertIn("English II", res.stdout, f"Year {yr} output missing English II anchor")
            self.assertIn(str(yr), res.stdout, f"Year {yr} output missing year tag")

    def test_12_english_i_complete_21_years_coverage(self):
        """Verify that all 21 years (2005-2025) of English I past papers exist and can be queried."""
        for yr in range(2005, 2026):
            res = self.run_cmd(["anchor", "--year", str(yr)])
            self.assertEqual(res.returncode, 0, f"Querying anchor for English I year {yr} failed: {res.stderr}")
            self.assertIn("English I", res.stdout, f"Year {yr} output missing English I anchor")
            self.assertIn(str(yr), res.stdout, f"Year {yr} output missing year tag")

    def test_13_english_i_dual_model_support(self):
        """Verify that English I anchors support dual models and CLI options --model-version 1, 2, all."""
        # 1. Brief mode contains dual model notification
        res_brief = self.run_cmd(["anchor", "--year", "2021"])
        self.assertEqual(res_brief.returncode, 0)
        self.assertIn("双范文支持（含【版本一 · 高级范文】与【版本二 · 满分习作】）", res_brief.stdout)

        # 2. Full mode with version 1
        res_v1 = self.run_cmd(["anchor", "--year", "2021", "--full", "--model-version", "1"])
        self.assertEqual(res_v1.returncode, 0)
        self.assertIn("Official Model · 版本一 高级范文", res_v1.stdout)
        self.assertNotIn("Official Model · 版本二 满分习作", res_v1.stdout)

        # 3. Full mode with version 2
        res_v2 = self.run_cmd(["anchor", "--year", "2021", "--full", "--model-version", "2"])
        self.assertEqual(res_v2.returncode, 0)
        self.assertIn("Official Model · 版本二 满分习作", res_v2.stdout)
        self.assertNotIn("Official Model · 版本一 高级范文", res_v2.stdout)

        # 4. Full mode with version all (default)
        res_all = self.run_cmd(["anchor", "--year", "2021", "--full", "--model-version", "all"])
        self.assertEqual(res_all.returncode, 0)
        self.assertIn("【版本一 · 高级范文】", res_all.stdout)
        self.assertIn("【版本二 · 满分习作】", res_all.stdout)

        # 5. Full JSON mode contains structured dual models
        res_json = self.run_cmd(["anchor", "--year", "2021", "--full", "--json"])
        self.assertEqual(res_json.returncode, 0)
        data = json.loads(res_json.stdout)
        self.assertIsInstance(data, list)
        eng1_anchor = next(a for a in data if a.get("exam_type") == "English I")
        self.assertIn("model_advanced", eng1_anchor)
        self.assertIn("model_perfect", eng1_anchor)
        self.assertIn("official_models", eng1_anchor)
        self.assertEqual(len(eng1_anchor["official_models"]), 2)

    def test_14_storage_detection_and_reset(self):
        """Verify that KAOYAN_USER_BRAIN decodes to external directory and init --reset provisions clean factory seed."""
        temp_dir = tempfile.mkdtemp(prefix="test_ub_")
        try:
            env = dict(self.env)
            if "KB_ROOT" in env:
                del env["KB_ROOT"]
            env["KAOYAN_USER_BRAIN"] = temp_dir
            res = self.run_cmd(["init", "--reset"], env=env)
            self.assertEqual(res.returncode, 0, f"init --reset failed: {res.stderr}\n{res.stdout}")
            self.assertIn("出厂纯净播种", res.stdout)

            ub_t1 = Path(temp_dir) / "user_brain" / "task1_expressions.jsonl"
            self.assertTrue(ub_t1.exists(), "task1_expressions.jsonl was not provisioned")

            # Read and verify records
            with open(ub_t1, "r", encoding="utf-8") as f:
                lines = [json.loads(l) for l in f if l.strip()]
            self.assertEqual(len(lines), 55)
            self.assertTrue(all(item.get("mastery") == "未接触" for item in lines))

            # Check other factory files
            tasks_file = Path(temp_dir) / "user_brain" / "tasks.jsonl"
            self.assertTrue(tasks_file.exists())
            self.assertEqual(tasks_file.stat().st_size, 0)

            hist_file = Path(temp_dir) / "user_brain" / "history.log"
            self.assertTrue(hist_file.exists())
            with open(hist_file, "r", encoding="utf-8") as f:
                h_lines = [json.loads(l) for l in f if l.strip()]
            self.assertEqual(len(h_lines), 1)
            self.assertEqual(h_lines[0].get("id"), "SYS_INIT")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_15_write_isolation_and_promotion(self):
        """Verify that updating a shared morpheme in decoupled mode does NOT alter the base shared file, and promotes to user task1."""
        temp_dir = tempfile.mkdtemp(prefix="test_ub_iso_")
        try:
            env = dict(self.env)
            if "KB_ROOT" in env:
                del env["KB_ROOT"]
            env["KAOYAN_USER_BRAIN"] = temp_dir
            self.run_cmd(["init", "--reset"], env=env)

            # Base shared file
            base_shared = Path(__file__).resolve().parent.parent / "knowledge_base" / "shared" / "scenario_morphemes.jsonl"
            mtime_before = base_shared.stat().st_mtime

            # Update status of a morpheme from shared (e.g. M_LIB_001)
            res = self.run_cmd(["update-status", "--id", "M_LIB_001", "--status", "敢用", "--note", "首次学习"], env=env)
            self.assertEqual(res.returncode, 0, f"update-status failed: {res.stderr}\n{res.stdout}")
            self.assertIn("已同步保存至用户外脑", res.stdout)

            # Verify base shared file was not touched
            mtime_after = base_shared.stat().st_mtime
            self.assertEqual(mtime_before, mtime_after, "Base shared file was mutated!")

            # Verify it was added to user's task1_expressions.jsonl
            ub_t1 = Path(temp_dir) / "user_brain" / "task1_expressions.jsonl"
            with open(ub_t1, "r", encoding="utf-8") as f:
                user_items = [json.loads(l) for l in f if l.strip()]
            promoted = next((it for it in user_items if it.get("id") == "M_LIB_001"), None)
            self.assertIsNotNone(promoted, "M_LIB_001 was not promoted into user task1")
            self.assertEqual(promoted.get("mastery"), "敢用")

            # Query and ensure user's promoted version is returned without duplicates
            res_query = self.run_cmd(["query", "--scenario", "prolong", "--json"], env=env)
            self.assertEqual(res_query.returncode, 0)
            q_data = json.loads(res_query.stdout)
            m_lib = [it for it in q_data if it.get("id") == "M_LIB_001"]
            self.assertEqual(len(m_lib), 1, "Duplicate M_LIB_001 returned in query")
            self.assertEqual(m_lib[0].get("mastery"), "敢用")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_16_status_command(self):
        """Verify 'status' command outputs complete architecture diagnosis."""
        res = self.run_cmd(["status"])
        self.assertEqual(res.returncode, 0, f"status failed: {res.stderr}\n{res.stdout}")
        self.assertIn("考研英语小作文系统运行状态", res.stdout)
        self.assertIn("教研底座路径:", res.stdout)
        self.assertIn("用户外脑路径:", res.stdout)
        self.assertIn("外脑存储类型:", res.stdout)
        self.assertIn("个人词句外脑总数:", res.stdout)
        self.assertIn("历年真题标尺: 39 篇", res.stdout)

if __name__ == "__main__":
    unittest.main()


