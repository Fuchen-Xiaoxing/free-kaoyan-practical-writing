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

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
if (SKILL_ROOT / "knowledge_base").exists():
    REPO_ROOT = SKILL_ROOT
    KB_ROOT = SKILL_ROOT / "knowledge_base"
else:
    REPO_ROOT = SKILL_ROOT.parent
    KB_ROOT = REPO_ROOT / "knowledge_base"
SCRIPT_PATH = SCRIPT_DIR / "kb_manager.py"
sys.path.insert(0, str(SCRIPT_DIR))
from kb_manager import is_id_match

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
        for t1_cand in [KB_ROOT / "user_brain" / "task1_expressions.jsonl", KB_ROOT / "user_brain" / "task1" / "expressions.jsonl"]:
            if t1_cand.exists():
                with open(t1_cand, "r", encoding="utf-8") as f:
                    records = [json.loads(l) for l in f if "optimize [system]" not in l]
                with open(t1_cand, "w", encoding="utf-8") as f:
                    for r in records:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def test_06_batch_update_mastery_and_evidence(self):
        """C5, C6, C7: Test batch-update mastery transition evidence."""
        # Ensure clean state in all task1 file candidates
        for t1_cand in [KB_ROOT / "user_brain" / "task1_expressions.jsonl", KB_ROOT / "user_brain" / "task1" / "expressions.jsonl"]:
            if t1_cand.exists():
                with open(t1_cand, "r", encoding="utf-8") as f:
                    records = [json.loads(l) for l in f if l.strip()]
                records = [r for r in records if not (is_id_match(r.get("id"), "T1_ADV_001") or is_id_match(r.get("id"), "T1_ADV_002"))]
                with open(t1_cand, "w", encoding="utf-8") as f:
                    for r in records:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")

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
        for t1_cand in [KB_ROOT / "user_brain" / "task1_expressions.jsonl", KB_ROOT / "user_brain" / "task1" / "expressions.jsonl"]:
            if t1_cand.exists():
                with open(t1_cand, "r", encoding="utf-8") as f:
                    records = [json.loads(l) for l in f if l.strip()]
                records = [r for r in records if not (is_id_match(r.get("id"), "T1_ADV_001") or is_id_match(r.get("id"), "T1_ADV_002"))]
                with open(t1_cand, "w", encoding="utf-8") as f:
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
        """Verify that KAOYAN_USER_BRAIN decodes to external directory and init --reset provisions clean slate (0 records)."""
        temp_dir = tempfile.mkdtemp(prefix="test_ub_")
        try:
            env = dict(self.env)
            if "KB_ROOT" in env:
                del env["KB_ROOT"]
            env["KAOYAN_USER_BRAIN"] = temp_dir
            res = self.run_cmd(["init", "--reset"], env=env)
            self.assertEqual(res.returncode, 0, f"init --reset failed: {res.stderr}\n{res.stdout}")
            self.assertIn("纯净白纸初始化", res.stdout)

            ub_t1 = Path(temp_dir) / "user_brain" / "task1_expressions.jsonl"
            self.assertTrue(ub_t1.exists(), "task1_expressions.jsonl was not provisioned")

            # Read and verify records: must be 0 records
            with open(ub_t1, "r", encoding="utf-8") as f:
                lines = [json.loads(l) for l in f if l.strip()]
            self.assertEqual(len(lines), 0, "User brain must be clean slate with 0 records upon init!")

            # Check shared morphemes: also clean slate (0 records)
            ub_sh = Path(temp_dir) / "user_brain" / "shared" / "morphemes.jsonl"
            self.assertTrue(ub_sh.exists())
            with open(ub_sh, "r", encoding="utf-8") as f:
                sh_lines = [json.loads(l) for l in f if l.strip()]
            self.assertEqual(len(sh_lines), 0)

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
    def test_17_anchor_limit_parameter(self):
        """Verify 'anchor' --limit parameter correctly restricts output count."""
        # 1. Default without --limit outputs all matches
        res_all = self.run_cmd(["anchor", "--genre", "advice"])
        self.assertEqual(res_all.returncode, 0)
        self.assertIn("共 10 篇", res_all.stdout)

        # 2. --limit 1 outputs exactly 1 anchor and truncation notification
        res_lim1 = self.run_cmd(["anchor", "--genre", "advice", "--limit", "1"])
        self.assertEqual(res_lim1.returncode, 0)
        self.assertIn("共 1 篇", res_lim1.stdout)
        self.assertIn("【范文锚点 #1】", res_lim1.stdout)
        self.assertNotIn("【范文锚点 #2】", res_lim1.stdout)
        self.assertIn("• [提示] 已按最新年份展示前 1 篇真题标尺", res_lim1.stdout)

        # 3. --limit 2 outputs exactly 2 anchors
        res_lim2 = self.run_cmd(["anchor", "--genre", "advice", "--limit", "2"])
        self.assertEqual(res_lim2.returncode, 0)
        self.assertIn("共 2 篇", res_lim2.stdout)
        self.assertIn("【范文锚点 #1】", res_lim2.stdout)
        self.assertIn("【范文锚点 #2】", res_lim2.stdout)
        self.assertNotIn("【范文锚点 #3】", res_lim2.stdout)

    def test_18_check_essay_file_mode_and_missing_file(self):
        """Verify 'check-essay --file' reads from file correctly and handles missing files gracefully."""
        # 1. Existing file
        test_content = (
            "Dear Professor Wang,\n\n"
            "    I am Li Ming, writing to consult you about the upcoming seminar.\n"
            "    Could you please advise whether we don't need to submit the paper in advance?\n"
            "    I look forward to your guidance.\n\n"
            "Yours sincerely,\n"
            "Li Ming"
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".txt") as tf:
            tf.write(test_content)
            temp_path = tf.name

        try:
            res = self.run_cmd(["check-essay", "--file", temp_path, "--json"])
            self.assertEqual(res.returncode, 0, f"check-essay --file failed: {res.stderr}")
            data = json.loads(res.stdout)
            self.assertGreater(data["body_total"], 0)
            self.assertEqual(len(data["contractions"]), 1)  # "don't"
            self.assertEqual(data["contractions"][0][1], "don't")
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        # 2. Missing file error handling
        res_missing = self.run_cmd(["check-essay", "--file", "non_existent_dummy_file.txt"])
        self.assertNotEqual(res_missing.returncode, 0)
        self.assertIn("指定的文件不存在", res_missing.stderr + res_missing.stdout)

    def test_19_anchors_sanitization_no_exclamation_or_contractions(self):
        """Verify all anchors in task1_past_papers.jsonl have zero exclamation marks and zero contractions."""
        anc_file = KB_ROOT / "anchors" / "task1_past_papers.jsonl"
        with open(anc_file, "r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f]

        self.assertGreater(len(records), 0)
        for r in records:
            iid = r.get("id")
            for k in ["official_model", "model_essay", "model_essay_v1", "model_essay_v2"]:
                val = r.get(k, "")
                if val:
                    self.assertEqual(val.count("!"), 0, f"{iid} {k} contains exclamation marks!")
                    # Check contractions
                    contr = [w for w in val.split() if any(c in w for c in ["'", "’"]) and w.lower() in [
                        "i'm", "i’m", "it's", "it’s", "don't", "don’t", "can't", "can’t", "you'll", "you’ll",
                        "they'll", "they’ll", "we'd", "we’d", "you're", "you’re", "isn't", "isn’t"
                    ]]
                    self.assertEqual(len(contr), 0, f"{iid} {k} contains contractions: {contr}")

            for expr in r.get("extractable_expressions", []):
                self.assertEqual(expr.count("!"), 0, f"{iid} extractable expr contains '!': {expr}")

    def test_20_batch_update_example(self):
        """Verify 'batch-update --example' outputs valid JSON schema and exits 0."""
        res = self.run_cmd(["batch-update", "--example"])
        self.assertEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertIn("task_id", data)
        self.assertIn("status_updates", data)
        self.assertIn("new_items", data)
        self.assertGreater(len(data["new_items"]), 0)

    def test_21_archive_example_and_auto_word_count(self):
        """Verify 'archive --example' works, and archive automatically computes body word count when omitted."""
        # 1. archive --example
        res_ex = self.run_cmd(["archive", "--example"])
        self.assertEqual(res_ex.returncode, 0)
        self.assertIn("archive", res_ex.stdout)

        # 2. archive with omitted word_count
        test_essay = (
            "Dear Li Ming,\n\n"
            "    Congratulations on your admission to such a prestigious university. I am writing to offer some suggestions on how to get prepared for university life.\n\n"
            "    To begin with, you had better learn to manage your monthly budget by keeping a record of your spending, or you may run out of money before the month ends. Besides, you are encouraged to get along with your roommates, who will be your closest companions for the next four years. As for your studies, it is never too early to gain exposure to your major, which will undoubtedly help you navigate your career path.\n\n"
            "    Anyway, I wish you a fulfilling and rewarding university life.\n\n"
            "                                        Yours sincerely,\n"
            "                                        Zhang Wei\n"
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".md") as tf:
            tf.write(test_essay)
            temp_path = tf.name

        try:
            res_arch = self.run_cmd([
                "archive",
                "--title", "Test Auto Word Count",
                "--genre", "advice",
                "--year", "2011",
                "--task-id", "TEST-AUTO-WC",
                "--file", temp_path
            ])
            self.assertEqual(res_arch.returncode, 0, f"archive failed: {res_arch.stderr}\n{res_arch.stdout}")
            self.assertIn("[OK] 范文已成功归档至:", res_arch.stdout)

            # Find generated archive file and inspect word count header
            archives_dir = KB_ROOT / "user_brain" / "satisfaction_archives" / "task1"
            arch_files = list(archives_dir.glob("*_Test_Auto_Word_Count.md"))
            self.assertGreater(len(arch_files), 0)
            with open(arch_files[0], "r", encoding="utf-8") as af:
                arch_text = af.read()
            self.assertIn("- **字数统计**：109 词", arch_text)

            # Cleanup test archive file
            arch_files[0].unlink()
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_22_admission_rules_tolerance(self):
        """Verify check_admission_rules tolerates '考纲核心' and phrase without explicit verb_phrase."""
        if str(SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPT_DIR))
        from kb_manager import check_admission_rules

        # 1. Tolerates synonymous exam_band
        item1 = {
            "category": "phrase",
            "source": "2011真题",
            "intent": "了解领域",
            "expression": "gain exposure to [field]",
            "exam_band": "考纲核心"
        }
        ok, reason = check_admission_rules(item1)
        self.assertTrue(ok, f"Expected OK, got: {reason}")
        self.assertEqual(item1["exam_band"], "大纲内")
        self.assertEqual(item1["verb_phrase"], "gain exposure to [field]")

        # 2. Strict rejection on invalid category
        item2 = {
            "category": "invalid_cat",
            "source": "2011真题",
            "intent": "测试"
        }
        ok2, reason2 = check_admission_rules(item2)
        self.assertFalse(ok2)
        self.assertIn("Invalid category", reason2)

    def test_23_prompt_command_purity_and_gating(self):
        """Verify 'prompt' command: pure projection without models, precise exam_type filter, and --full rejection."""
        # 1. Precise single paper with --exam-type
        res = self.run_cmd(["prompt", "--year", "2011", "--exam-type", "2"])
        self.assertEqual(res.returncode, 0)
        self.assertIn("2011 English II · advice", res.stdout)
        self.assertIn("Zhang Wei", res.stdout)
        self.assertIn("Directions", res.stdout)
        # Verify 100% NO model essay text in output
        self.assertNotIn("I am immensely thrilled", res.stdout)
        self.assertNotIn("Congratulations on your admission to such a prestigious university!", res.stdout)
        self.assertNotIn("Dear Li Ming,", res.stdout)
        self.assertNotIn("Yours sincerely,", res.stdout)

        # 2. JSON output purity
        res_json = self.run_cmd(["prompt", "--year", "2011", "--exam-type", "2", "--json"])
        self.assertEqual(res_json.returncode, 0)
        data = json.loads(res_json.stdout)
        self.assertEqual(data["year"], "2011")
        self.assertEqual(data["exam_type"], "English II")
        self.assertEqual(data["mandated_signoff"], "Zhang Wei")
        self.assertNotIn("official_model", data)
        self.assertNotIn("extractable_expressions", data)
        self.assertNotIn("model_advanced", data)

        # 3. Dual papers without --exam-type
        res_dual = self.run_cmd(["prompt", "--year", "2011"])
        self.assertEqual(res_dual.returncode, 0)
        self.assertIn("共检索到 2 篇", res_dual.stdout)
        self.assertIn("2011 English I · recommendation", res_dual.stdout)
        self.assertIn("2011 English II · advice", res_dual.stdout)

        # 4. Strict argument rejection: --full must FAIL
        res_full = self.run_cmd(["prompt", "--year", "2011", "--exam-type", "2", "--full"])
        self.assertNotEqual(res_full.returncode, 0)
        self.assertIn("unrecognized arguments: --full", res_full.stderr + res_full.stdout)

    def test_24_dual_warehouse_morpheme_routing_and_sync(self):
        """Verify dual-warehouse architecture: shared morphemes routed to shared/ and sentences to task1/."""
        temp_dir = tempfile.mkdtemp(prefix="test_ub_dual_")
        try:
            env = dict(self.env)
            if "KB_ROOT" in env:
                del env["KB_ROOT"]
            env["KAOYAN_USER_BRAIN"] = temp_dir
            res_init = self.run_cmd(["init", "--reset"], env=env)
            self.assertEqual(res_init.returncode, 0)

            shared_file = Path(temp_dir) / "user_brain" / "shared" / "morphemes.jsonl"
            task1_file = Path(temp_dir) / "user_brain" / "task1" / "expressions.jsonl"
            task2_file = Path(temp_dir) / "user_brain" / "task2" / "expressions.jsonl"
            self.assertTrue(shared_file.exists(), "shared/morphemes.jsonl missing")
            self.assertTrue(task1_file.exists(), "task1/expressions.jsonl missing")
            self.assertTrue(task2_file.exists(), "task2/expressions.jsonl missing")

            # 1. Batch update with a morpheme
            batch_morph = {
                "task_id": "T2011-E2-ADV",
                "new_items": [
                    {
                        "data": {
                            "type": "morpheme",
                            "text": "navigate one's career path",
                            "meaning": "规划职业发展道路",
                            "source": "2011真题实战",
                            "mastery": "学习中"
                        }
                    }
                ]
            }
            res_bm = self.run_cmd(["batch-update", "--data", json.dumps(batch_morph, ensure_ascii=False)], env=env)
            self.assertEqual(res_bm.returncode, 0)
            self.assertIn("追加至 shared", res_bm.stdout)

            with open(shared_file, "r", encoding="utf-8") as f:
                shared_lines = [json.loads(l) for l in f if l.strip()]
            self.assertTrue(any("navigate one's career path" in (it.get("text") or "") for it in shared_lines))

            # 2. Batch update with a functional sentence
            batch_sen = {
                "task_id": "T2011-E2-ADV",
                "new_items": [
                    {
                        "data": {
                            "category": "functional_sentence",
                            "genre": "advice",
                            "expression": "If I were you, I would [action].",
                            "intent": "虚拟语气提建议",
                            "source": "2011真题实战",
                            "slots": {"[action]": "建议动作"}
                        }
                    }
                ]
            }
            res_bs = self.run_cmd(["batch-update", "--data", json.dumps(batch_sen, ensure_ascii=False)], env=env)
            self.assertEqual(res_bs.returncode, 0)
            self.assertIn("追加至 task1", res_bs.stdout)

            with open(task1_file, "r", encoding="utf-8") as f:
                t1_lines = [json.loads(l) for l in f if l.strip()]
            self.assertTrue(any("If I were you, I would [action]." in (it.get("expression") or it.get("text") or "") for it in t1_lines))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_25_slim_schema_and_zero_emojis(self):
        """Verify query output conforms to zero emojis rule and 3-column format."""
        res_q = self.run_cmd(["query", "--genre", "advice", "--limit", "5"])
        self.assertEqual(res_q.returncode, 0)
        out = res_q.stdout

        # Check zero emojis in query output
        emojis = [c for c in out if ord(c) > 0x1F000 or (0x2600 <= ord(c) <= 0x27BF and ord(c) != 0x2794)]
        self.assertEqual(len(emojis), 0, f"Found emojis in query output: {emojis}")

        # Check 3 columns
        self.assertIn("【一、本题可用已掌握】", out)
        self.assertIn("【二、本题建议新学】", out)
        self.assertIn("【三、本题建议结构/模板】", out)

        # Check zero emojis in status
        res_s = self.run_cmd(["status"])
        self.assertEqual(res_s.returncode, 0)
        s_out = res_s.stdout
        s_emojis = [c for c in s_out if ord(c) > 0x1F000 or (0x2600 <= ord(c) <= 0x27BF and ord(c) != 0x2794)]
        self.assertEqual(len(s_emojis), 0, f"Found emojis in status output: {s_emojis}")

    def test_26_two_tier_query_borrowing_on_clean_brain(self):
        """Verify that on a clean slate (0 user items), query borrows from system seeds and tags with [系统借调]."""
        temp_dir = tempfile.mkdtemp(prefix="test_ub_borrow_")
        try:
            env = dict(self.env)
            if "KB_ROOT" in env:
                del env["KB_ROOT"]
            env["KAOYAN_USER_BRAIN"] = temp_dir
            self.run_cmd(["init", "--reset"], env=env)

            # Query advice
            res = self.run_cmd(["query", "--genre", "advice", "--limit", "4"], env=env)
            self.assertEqual(res.returncode, 0, f"query failed: {res.stderr}\n{res.stdout}")
            self.assertIn("[系统借调]", res.stdout, "Clean user brain must borrow from seeds with [系统借调] tag")
            self.assertIn("宁缺毋滥", res.stdout)

            # JSON mode
            res_json = self.run_cmd(["query", "--genre", "advice", "--limit", "4", "--json"], env=env)
            self.assertEqual(res_json.returncode, 0)
            items = json.loads(res_json.stdout)
            self.assertTrue(len(items) > 0)
            self.assertTrue(all(it.get("is_borrowed") is True for it in items))
            self.assertTrue(all(it.get("source_tier") == "system_seeds" for it in items))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_27_two_tier_query_user_brain_precedence(self):
        """Verify that user brain assets take 100% precedence, leaving zero system借调 when stock is sufficient."""
        temp_dir = tempfile.mkdtemp(prefix="test_ub_prec_")
        try:
            env = dict(self.env)
            if "KB_ROOT" in env:
                del env["KB_ROOT"]
            env["KAOYAN_USER_BRAIN"] = temp_dir
            self.run_cmd(["init", "--reset"], env=env)

            # Seed user brain with 3 user items
            user_items = [
                {
                    "category": "functional_sentence",
                    "genre": "advice",
                    "section": "opening",
                    "intent": "用户首段自主建议表达",
                    "expression": "I am pleased to put forward some suggestions for [target].",
                    "slots": {"[target]": "建议目标"},
                    "source": "真题实战",
                    "mastery": "稳定"
                },
                {
                    "category": "functional_sentence",
                    "genre": "advice",
                    "section": "body",
                    "intent": "用户次段举措表达",
                    "expression": "It is highly recommended that you should [action].",
                    "slots": {"[action]": "具体动作"},
                    "source": "真题实战",
                    "mastery": "敢用"
                },
                {
                    "category": "template",
                    "genre": "advice",
                    "section": "body",
                    "intent": "用户专属建议信模板",
                    "blocks": ["Dear Sir,", "Body paragraph", "Yours sincerely"],
                    "source": "真题实战",
                    "mastery": "稳定"
                }
            ]
            for it in user_items:
                res_add = self.run_cmd(["append", "--target", "task1", "--data", json.dumps(it, ensure_ascii=False)], env=env)
                self.assertEqual(res_add.returncode, 0)
                self.assertIn("[ADDED]", res_add.stdout)

            # Query with limit 3: should be fulfilled 100% by user brain
            res_q = self.run_cmd(["query", "--genre", "advice", "--limit", "3"], env=env)
            self.assertEqual(res_q.returncode, 0)
            self.assertNotIn("[系统借调]", res_q.stdout, "Sufficient user brain items must not trigger system borrowing")

            res_json = self.run_cmd(["query", "--genre", "advice", "--limit", "3", "--json"], env=env)
            self.assertEqual(res_json.returncode, 0)
            items = json.loads(res_json.stdout)
            self.assertEqual(len(items), 3)
            self.assertTrue(all(it.get("is_borrowed") is False for it in items))
            self.assertTrue(all(it.get("source_tier") == "user_brain" for it in items))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_28_progressive_privatization_lifecycle(self):
        """Verify the full lifecycle: clean slate -> borrowed from seed -> practiced & promoted -> user brain precedence."""
        temp_dir = tempfile.mkdtemp(prefix="test_ub_life_")
        try:
            env = dict(self.env)
            if "KB_ROOT" in env:
                del env["KB_ROOT"]
            env["KAOYAN_USER_BRAIN"] = temp_dir
            self.run_cmd(["init", "--reset"], env=env)

            # 1. Initially clean slate
            res_st1 = self.run_cmd(["status"], env=env)
            self.assertIn("100% 纯净白纸", res_st1.stdout)

            # 2. Query borrows T1_ADV_SEN_001 from system
            res_q1 = self.run_cmd(["query", "--genre", "advice", "--limit", "3"], env=env)
            self.assertIn("[系统借调]", res_q1.stdout)

            # 3. User practices and batch updates to promote
            update_payload = {
                "task_id": "T2011-E2-ADV",
                "status_updates": [
                    {
                        "id": "T1_ADV_001",
                        "status": "敢用",
                        "independent": True,
                        "note": "实战用对，提升入库"
                    }
                ]
            }
            res_upd = self.run_cmd(["batch-update", "--data", json.dumps(update_payload, ensure_ascii=False)], env=env)
            self.assertEqual(res_upd.returncode, 0)
            self.assertIn("未接触 ➔ 稳定", res_upd.stdout)

            # 4. Status reflects 1 promoted item
            res_st2 = self.run_cmd(["status"], env=env)
            self.assertIn("个人词句外脑总数: 1 条", res_st2.stdout)

            # 5. Querying with limit 1 now returns user's promoted asset without borrowing tag
            res_q2 = self.run_cmd(["query", "--genre", "advice", "--limit", "1"], env=env)
            self.assertNotIn("[系统借调]", res_q2.stdout)
            self.assertIn("T1_ADV_SEN_001", res_q2.stdout)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()


