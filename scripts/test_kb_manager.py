#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_kb_manager.py - Comprehensive Automated Test Suite for Kaoyan Writing KB Manager
Covers:
  1. verify: Strict PASS on clean DB, FAIL on corrupt JSON line or missing required fields.
  2. anchor: Brief mode omits reference model text by default; --full includes reference model.
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
import io
import json
import hashlib
import datetime
import subprocess
import shutil
import contextlib
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

    def isolated_env(self, temp_dir):
        """写入型用例专用：教研底座保持只读（KB_BUILTIN_ROOT），个人外脑落到临时目录。

        这样测试永远不会污染仓库自带的 knowledge_base/user_brain。
        """
        env = dict(os.environ)
        env.pop("KB_ROOT", None)
        env["KB_BUILTIN_ROOT"] = str(KB_ROOT)
        env["KAOYAN_USER_BRAIN"] = str(temp_dir)
        return env

    def init_isolated_brain(self, temp_dir):
        env = self.isolated_env(temp_dir)
        res = self.run_cmd(["init", "--reset"], env=env)
        self.assertEqual(res.returncode, 0, f"init failed: {res.stderr}")
        return env

    def test_01_verify_passes_on_clean_db(self):
        """Test 'verify' command outputs pass for all DBs."""
        res = self.run_cmd(["verify"])
        self.assertEqual(res.returncode, 0, f"verify failed: {res.stderr}\n{res.stdout}")
        self.assertIn("[PASS] task1", res.stdout)
        self.assertIn("[PASS] shared", res.stdout)
        self.assertIn("[PASS] anchors", res.stdout)
        self.assertIn("验证通过！", res.stdout)

    def test_02_verify_fails_on_corrupt_json(self):
        """E1: Test 'verify' reports FAIL when a corrupted JSON line exists (on a temp KB copy)."""
        temp_root = tempfile.mkdtemp(prefix="test_corrupt_")
        try:
            kb_copy = Path(temp_root) / "knowledge_base"
            shutil.copytree(KB_ROOT, kb_copy)
            env = dict(os.environ)
            env["KB_ROOT"] = str(kb_copy)

            task1_file = kb_copy / "user_brain" / "task1_expressions.jsonl"
            task1_file.parent.mkdir(parents=True, exist_ok=True)
            if not task1_file.exists():
                task1_file.write_text("", encoding="utf-8")

            # Append corrupt line
            with open(task1_file, "a", encoding="utf-8") as f:
                f.write("\n{this is broken json line}\n")

            res = self.run_cmd(["verify"], env=env)
            self.assertNotEqual(res.returncode, 0, "verify must fail on corrupted JSON lines")
            self.assertIn("JSON格式解析错误", res.stderr + res.stdout)
            self.assertIn("[FAIL] 知识库验证失败", res.stderr + res.stdout)

            # 仓库自带底座绝不能被本用例改动
            repo_file = KB_ROOT / "user_brain" / "task1_expressions.jsonl"
            if repo_file.exists():
                self.assertNotIn("broken json line", repo_file.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def test_03_anchor_brief_omits_model_and_full_includes_it(self):
        """E3: Test 'anchor' brief mode does NOT output reference model; --full does."""
        # 1. Brief mode
        res_brief = self.run_cmd(["anchor", "--genre", "notice"])
        self.assertEqual(res_brief.returncode, 0, f"anchor failed: {res_brief.stderr}")
        self.assertNotIn("Fifty volunteers will be recruited", res_brief.stdout)
        self.assertIn("参考范文正文默认不展示", res_brief.stdout)
        self.assertIn("语域与语气深度剖析", res_brief.stdout)
        self.assertIn("句法与考纲词汇标尺", res_brief.stdout)

        # 2. Full mode
        res_full = self.run_cmd(["anchor", "--genre", "notice", "--full"])
        self.assertEqual(res_full.returncode, 0, f"anchor --full failed: {res_full.stderr}")
        self.assertIn("高分参考范文 (Reference Model", res_full.stdout)
        self.assertIn("仅供私教后台研读，S0~S2 严禁直接贴给学员", res_full.stdout)
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
        """P1-5: Test append admission gates and deduplication (isolated user brain)."""
        temp_dir = tempfile.mkdtemp(prefix="test_append_iso_")
        try:
            env = self.init_isolated_brain(temp_dir)

            # 1. Non-reusable item (no slots or templates) should be rejected
            bad_item = {
                "category": "functional_sentence",
                "genre": "advice",
                "intent": "一次性具体事实描述",
                "expression": "Yesterday Li Ming met Zhang Wei at room 204.",
                "source": "测试来源"
            }
            res_bad = self.run_cmd(["append", "--target", "task1", "--data", json.dumps(bad_item, ensure_ascii=False)], env=env)
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
            res_good = self.run_cmd(["append", "--target", "task1", "--data", json.dumps(good_item, ensure_ascii=False)], env=env)
            self.assertEqual(res_good.returncode, 0)
            self.assertIn("[ADDED]", res_good.stdout)

            # 3. Deduplication: appending again should skip
            res_dup = self.run_cmd(["append", "--target", "task1", "--data", json.dumps(good_item, ensure_ascii=False)], env=env)
            self.assertEqual(res_dup.returncode, 0)
            self.assertIn("[SKIP] 条目已存在，跳过防重", res_dup.stdout)

            # 写入必须落在临时外脑内，而不是仓库自带的 knowledge_base
            written = list(Path(temp_dir).rglob("expressions.jsonl"))
            self.assertTrue(any("optimize [system]" in f.read_text(encoding="utf-8") for f in written),
                            f"appended item not found in isolated brain: {written}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_06_batch_update_mastery_and_evidence(self):
        """C5, C6, C7: Test batch-update mastery transition evidence (isolated user brain)."""
        temp_dir = tempfile.mkdtemp(prefix="test_batch_iso_")
        try:
            env = self.init_isolated_brain(temp_dir)

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
            res = self.run_cmd(["batch-update", "--data", json.dumps(batch_payload, ensure_ascii=False)], env=env)
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
            res_err = self.run_cmd(["batch-update", "--data", json.dumps(batch_error, ensure_ascii=False)], env=env)
            self.assertEqual(res_err.returncode, 0)
            self.assertIn("未接触 ➔ 敢用", res_err.stdout)

            # 3. 未命中的 ID 必须被显式报告（不再静默无操作）
            batch_miss = {
                "task_id": "T-TEST-004",
                "status_updates": [{"id": "T1_NOT_EXIST_999", "status": "稳定"}]
            }
            res_miss = self.run_cmd(["batch-update", "--data", json.dumps(batch_miss, ensure_ascii=False)], env=env)
            self.assertEqual(res_miss.returncode, 0)
            self.assertIn("[MISS]", res_miss.stdout)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_07_archive_and_tasks_sync(self):
        """P1-1 & P2-5: Test 'archive' saves a model essay and syncs the task ledger exactly once."""
        temp_dir = tempfile.mkdtemp(prefix="test_archive_iso_")
        try:
            env = self.init_isolated_brain(temp_dir)
            task_id = "T-TEST-ARCH-001"
            res = self.run_cmd([
                "archive",
                "--title", "Test Archive Essay",
                "--genre", "advice",
                "--year", "2024",
                "--task-id", task_id,
                "--content", "Dear Sir or Madam,\n\n    Test content.\n\nYours sincerely,\nLi Ming",
                "--metadata", json.dumps({"absorbed_items": ["[T1_ADV_001] Test item"]}, ensure_ascii=False)
            ], env=env)
            self.assertEqual(res.returncode, 0, f"archive failed: {res.stderr}")
            self.assertIn("[OK] 范文已成功归档至", res.stdout)
            self.assertIn("[OK] 题目台账已同步至", res.stdout)

            matching = list(Path(temp_dir).rglob("*_Test_Archive_Essay.md"))
            self.assertGreaterEqual(len(matching), 1, f"archive md not found under {temp_dir}")

            # 台账必须只有一行（paths["tasks"] 与 user_task1_tasks 指向同一文件时不得重复写入）
            ledger_rows = []
            for ledger in Path(temp_dir).rglob("tasks.jsonl"):
                ledger_rows += [l for l in ledger.read_text(encoding="utf-8").splitlines() if task_id in l]
            self.assertEqual(len(ledger_rows), 1, f"ledger duplicated: {ledger_rows}")

            # 重复归档同一 task_id 必须 upsert，而不是继续堆行
            res2 = self.run_cmd([
                "archive",
                "--title", "Test Archive Essay",
                "--genre", "advice",
                "--year", "2024",
                "--task-id", task_id,
                "--content", "Dear Sir or Madam,\n\n    Test content v2.\n\nYours sincerely,\nLi Ming",
            ], env=env)
            self.assertEqual(res2.returncode, 0, f"re-archive failed: {res2.stderr}")
            ledger_rows2 = []
            for ledger in Path(temp_dir).rglob("tasks.jsonl"):
                ledger_rows2 += [l for l in ledger.read_text(encoding="utf-8").splitlines() if task_id in l]
            self.assertEqual(len(ledger_rows2), 1, f"ledger not idempotent: {ledger_rows2}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

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
        # 注意：收件人刻意使用 Wang Ming，避免触发"收件人与署名重名"红线（署名统一为 Li Ming）
        clean_essay = (
            "Dear Wang Ming,\n\n"
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
        self.assertIn("Reference Model · 版本一 高级范文", res_v1.stdout)
        self.assertNotIn("Reference Model · 版本二 满分习作", res_v1.stdout)

        # 3. Full mode with version 2
        res_v2 = self.run_cmd(["anchor", "--year", "2021", "--full", "--model-version", "2"])
        self.assertEqual(res_v2.returncode, 0)
        self.assertIn("Reference Model · 版本二 满分习作", res_v2.stdout)
        self.assertNotIn("Reference Model · 版本一 高级范文", res_v2.stdout)

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

            # v2 双仓规范布局（唯一权威表示）
            ub_t1 = Path(temp_dir) / "user_brain" / "task1" / "expressions.jsonl"
            self.assertTrue(ub_t1.exists(), "task1/expressions.jsonl was not provisioned")

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

            # Check ledger: task1/tasks.jsonl (v2)
            tasks_file = Path(temp_dir) / "user_brain" / "task1" / "tasks.jsonl"
            self.assertTrue(tasks_file.exists())
            self.assertEqual(tasks_file.stat().st_size, 0)

            # 扁平遗留文件与 task2 均不得再被创建（本 skill 只有小作文 task1）
            self.assertFalse((Path(temp_dir) / "user_brain" / "task1_expressions.jsonl").exists(),
                             "legacy flat task1_expressions.jsonl must not be provisioned")
            self.assertFalse((Path(temp_dir) / "user_brain" / "tasks.jsonl").exists(),
                             "legacy flat tasks.jsonl must not be provisioned")
            self.assertFalse((Path(temp_dir) / "user_brain" / "task2").exists(),
                             "task2 must not be provisioned")

            hist_file = Path(temp_dir) / "user_brain" / "history.log"
            self.assertTrue(hist_file.exists())
            with open(hist_file, "r", encoding="utf-8") as f:
                h_lines = [json.loads(l) for l in f if l.strip()]
            self.assertEqual(len(h_lines), 1)
            self.assertEqual(h_lines[0].get("id"), "SYS_INIT")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_15_write_isolation_and_promotion(self):
        """Verify that promoting a shared morpheme does NOT alter the base seed, and lands in the personal shared warehouse."""
        temp_dir = tempfile.mkdtemp(prefix="test_ub_iso_")
        try:
            env = dict(self.env)
            if "KB_ROOT" in env:
                del env["KB_ROOT"]
            env["KAOYAN_USER_BRAIN"] = temp_dir
            self.run_cmd(["init", "--reset"], env=env)

            # 出厂底座：paths["shared"] 指向 seeds/shared_morphemes.seed.jsonl（只读）
            kb_root = Path(__file__).resolve().parent.parent / "knowledge_base"
            base_shared = kb_root / "seeds" / "shared_morphemes.seed.jsonl"
            mtime_before = base_shared.stat().st_mtime
            hash_before = hashlib.sha256(base_shared.read_bytes()).hexdigest()

            # Update status of a morpheme from the built-in base (e.g. M_LIB_001)
            res = self.run_cmd(["update-status", "--id", "M_LIB_001", "--status", "敢用", "--note", "首次学习"], env=env)
            self.assertEqual(res.returncode, 0, f"update-status failed: {res.stderr}\n{res.stdout}")
            self.assertIn("已沉淀至个人共享仓", res.stdout)

            # Verify base seed file was not touched (neither mtime nor bytes)
            self.assertEqual(mtime_before, base_shared.stat().st_mtime, "Base seed file was mutated!")
            self.assertEqual(hash_before, hashlib.sha256(base_shared.read_bytes()).hexdigest(),
                             "Base seed file content changed!")

            # 借调转正必须落到个人共享语素仓，而不是小作文专属仓
            ub_sh = Path(temp_dir) / "user_brain" / "shared" / "morphemes.jsonl"
            with open(ub_sh, "r", encoding="utf-8") as f:
                user_items = [json.loads(l) for l in f if l.strip()]
            promoted = next((it for it in user_items if it.get("id") == "M_LIB_001"), None)
            self.assertIsNotNone(promoted, "M_LIB_001 was not promoted into the personal shared warehouse")
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
        temp_dir = tempfile.mkdtemp(prefix="test_archwc_iso_")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".md") as tf:
            tf.write(test_essay)
            temp_path = tf.name

        try:
            env = self.init_isolated_brain(temp_dir)
            res_arch = self.run_cmd([
                "archive",
                "--title", "Test Auto Word Count",
                "--genre", "advice",
                "--year", "2011",
                "--task-id", "TEST-AUTO-WC",
                "--file", temp_path
            ], env=env)
            self.assertEqual(res_arch.returncode, 0, f"archive failed: {res_arch.stderr}\n{res_arch.stdout}")
            self.assertIn("[OK] 范文已成功归档至:", res_arch.stdout)

            # Find generated archive file and inspect word count header
            arch_files = list(Path(temp_dir).rglob("*_Test_Auto_Word_Count.md"))
            self.assertGreater(len(arch_files), 0, f"archive md not found under {temp_dir}")
            arch_text = arch_files[0].read_text(encoding="utf-8")
            self.assertIn("- **字数统计**：109 词", arch_text)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            shutil.rmtree(temp_dir, ignore_errors=True)

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
            self.assertTrue(shared_file.exists(), "shared/morphemes.jsonl missing")
            self.assertTrue(task1_file.exists(), "task1/expressions.jsonl missing")
            self.assertFalse((Path(temp_dir) / "user_brain" / "task2").exists(),
                             "task2 must not exist: this skill only covers Section A (task1)")

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

    def test_29_settle_documented_payload_archives_and_ledger_once(self):
        """P0-1/P0-2: SKILL.md 文档化载荷（顶层 essay_content）必须真实归档，且台账只写一行。"""
        temp_dir = tempfile.mkdtemp(prefix="test_settle_doc_")
        try:
            env = self.init_isolated_brain(temp_dir)
            payload = {
                "task_id": "T2012-E2-DOC",
                "title": "投诉网购电子词典（2012英二）",
                "genre": "complaint",
                "year": "2012",
                "exam_type": "2",
                "essay_content": (
                    "Dear Sir or Madam,\n\n    I am writing to lodge a formal complaint regarding the electronic dictionary.\n\n"
                    "                                        Yours faithfully,\n                                        Zhang Wei\n"
                ),
                "batch": {"status_updates": [], "new_items": []},
            }
            payload_file = Path(temp_dir) / "settle_doc.json"
            payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            res = self.run_cmd(["settle", "--file", str(payload_file), "--mock"], env=env)
            self.assertEqual(res.returncode, 0, f"settle failed: {res.stderr}\n{res.stdout}")
            self.assertIn("范文归档与题目台账登记完成", res.stdout)

            md_files = list(Path(temp_dir).rglob("*_complaint_*.md"))
            self.assertEqual(len(md_files), 1, f"expected exactly 1 archive, got {md_files}")

            ledger_rows = []
            for ledger in Path(temp_dir).rglob("tasks.jsonl"):
                ledger_rows += [l for l in ledger.read_text(encoding="utf-8").splitlines() if "T2012-E2-DOC" in l]
            self.assertEqual(len(ledger_rows), 1, f"ledger must contain exactly one row: {ledger_rows}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_30_settle_preflight_failures_are_nonzero_and_zero_write(self):
        """P0-1/P2-1: 缺正文 / 墨墨词卡缺 spelling / 晋级 ID 不存在，均须非零退出且零写入。"""
        temp_dir = tempfile.mkdtemp(prefix="test_settle_pf_")
        try:
            env = self.init_isolated_brain(temp_dir)
            base = {
                "task_id": "T-PF",
                "title": "前置校验",
                "genre": "complaint",
                "year": "2012",
                "exam_type": "2",
                "essay_content": "Dear Sir or Madam,\n\n    Body.\n\nYours faithfully,\nZhang Wei\n",
            }

            cases = []
            no_content = dict(base)
            no_content.pop("essay_content")
            cases.append(("no content", no_content))
            bad_word = dict(base, maimemo={"chapter": "2012英二小作文", "words": [{"sentence": "x"}]})
            cases.append(("word without spelling", bad_word))
            bad_id = dict(base, batch={"status_updates": [{"id": "T1_NOT_EXIST_999", "status": "稳定"}]})
            cases.append(("unmatched status id", bad_id))

            for label, payload in cases:
                payload_file = Path(temp_dir) / f"case_{label.replace(' ', '_')}.json"
                payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                res = self.run_cmd(["settle", "--file", str(payload_file), "--mock"], env=env)
                self.assertNotEqual(res.returncode, 0, f"[{label}] settle must fail, got 0\n{res.stdout}")
                self.assertIn("前置校验未通过", res.stderr + res.stdout, f"[{label}] missing preflight failure message")

            self.assertEqual(len(list(Path(temp_dir).rglob("*.md"))), 0, "no archive may be written on preflight failure")
            ledger_rows = []
            for ledger in Path(temp_dir).rglob("tasks.jsonl"):
                ledger_rows += [l for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(ledger_rows, [], f"ledger must stay empty: {ledger_rows}")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_31_settle_rolls_back_local_writes_on_failure(self):
        """P2-1: 本地链路失败必须整体回滚（外脑 JSONL / 台账 / 新归档恢复原状）。"""
        import types
        if str(SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPT_DIR))
        import kb_manager

        temp_dir = tempfile.mkdtemp(prefix="test_settle_rb_")
        saved_env = dict(os.environ)
        original_archive = kb_manager.cmd_archive
        try:
            env = self.init_isolated_brain(temp_dir)
            os.environ["KB_BUILTIN_ROOT"] = env["KB_BUILTIN_ROOT"]
            os.environ["KAOYAN_USER_BRAIN"] = env["KAOYAN_USER_BRAIN"]
            os.environ.pop("KB_ROOT", None)

            paths = kb_manager.get_paths()
            task1_file = Path(paths["user_task1"])
            ledger_file = Path(paths["tasks"])
            before_t1 = task1_file.read_text(encoding="utf-8") if task1_file.exists() else ""
            before_ledger = ledger_file.read_text(encoding="utf-8") if ledger_file.exists() else ""

            payload = {
                "task_id": "T-RB",
                "title": "回滚验证",
                "genre": "complaint",
                "year": "2012",
                "exam_type": "2",
                "essay_content": "Dear Sir or Madam,\n\n    Body.\n\nYours faithfully,\nZhang Wei\n",
                "batch": {
                    "status_updates": [],
                    "new_items": [{
                        "target": "task1",
                        "data": {
                            "category": "functional_sentence",
                            "genre": "complaint",
                            "section": "opening",
                            "expression": "I am writing to lodge a formal complaint regarding [Product].",
                            "intent": "投诉信开篇定调",
                            "mastery": "敢用",
                        },
                    }],
                },
            }
            payload_file = Path(temp_dir) / "settle_rb.json"
            payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            def _boom(_args):
                raise SystemExit(1)

            kb_manager.cmd_archive = _boom
            args = types.SimpleNamespace(
                file=str(payload_file), data=None, token=None, mock=True,
                dry_run=False, json=False, example=False,
            )
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                with self.assertRaises(SystemExit) as ctx:
                    kb_manager.cmd_settle(args)
            self.assertEqual(ctx.exception.code, 1)

            after_t1 = task1_file.read_text(encoding="utf-8") if task1_file.exists() else ""
            after_ledger = ledger_file.read_text(encoding="utf-8") if ledger_file.exists() else ""
            self.assertEqual(before_t1, after_t1, "user brain must be rolled back")
            self.assertEqual(before_ledger, after_ledger, "ledger must be rolled back")
            self.assertEqual(len(list(Path(temp_dir).rglob("*.md"))), 0, "no archive may survive rollback")
        finally:
            kb_manager.cmd_archive = original_archive
            os.environ.clear()
            os.environ.update(saved_env)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_32_query_mine_cross_genre_recall(self):
        """P1-1/P1-2: query --mine 必须跨文类召回个人资产，并能判定初稿命中。"""
        temp_dir = tempfile.mkdtemp(prefix="test_mine_")
        try:
            env = self.init_isolated_brain(temp_dir)
            seed_item = {
                "category": "functional_sentence",
                "genre": "advice",
                "section": "opening",
                "register": "neutral_formal",
                "intent": "分词状语前置开篇",
                "expression": "Knowing that you are preparing for [event], I am writing to [purpose].",
                "mastery": "敢用",
            }
            add = {"task_id": "T-MINE-1", "status_updates": [], "new_items": [{"target": "task1", "data": seed_item}]}
            res_add = self.run_cmd(["batch-update", "--data", json.dumps(add, ensure_ascii=False)], env=env)
            self.assertEqual(res_add.returncode, 0, f"seed failed: {res_add.stderr}")

            # 1. 跨文类召回：以投诉信为文类检索，建议信资产必须出现并带 [跨文类复用] 标记
            res_mine = self.run_cmd(["query", "--mine", "--genre", "complaint", "--limit", "20"], env=env)
            self.assertEqual(res_mine.returncode, 0, f"query --mine failed: {res_mine.stderr}")
            self.assertIn("跨文类可复用", res_mine.stdout)
            self.assertIn("[跨文类复用]", res_mine.stdout)
            self.assertIn(seed_item["expression"], res_mine.stdout)

            # 2. 默认三栏检索行为不得被 --mine 改动
            res_default = self.run_cmd(["query", "--genre", "advice", "--limit", "5"], env=env)
            self.assertIn("【一、本题可用已掌握】", res_default.stdout)
            self.assertIn("【二、本题建议新学】", res_default.stdout)
            self.assertIn("【三、本题建议结构/模板】", res_default.stdout)

            # 3. 初稿命中判定
            draft = Path(temp_dir) / "draft.txt"
            draft.write_text(
                "Dear Sir or Madam,\n\n    Knowing that you are preparing for the contest, I am writing to confirm my support.\n",
                encoding="utf-8",
            )
            res_hit = self.run_cmd(["query", "--mine", "--genre", "complaint", "--match-file", str(draft), "--json"], env=env)
            self.assertEqual(res_hit.returncode, 0, f"query --mine --match-file failed: {res_hit.stderr}")
            data_hit = json.loads(res_hit.stdout)
            self.assertEqual(len(data_hit["hits"]), 1, f"expected 1 hit, got {data_hit['hits']}")
            self.assertIn("knowing that you are", data_hit["hits"][0]["evidence"].lower())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_33_check_essay_signature_and_possessive_rules(self):
        """P0-3/P0-4: 所有格不得误报缩写；署名句号 / 题干署名不符 / 重名 / 敬语失配必须报错。"""
        possessive_essay = (
            "Dear Sir or Madam,\n\n"
            "    The dictionary's screen has gone blank and the brand's service failed.\n\n"
            "Yours faithfully,\n"
            "Li Ming"
        )
        res = self.run_cmd(["check-essay", "--text", possessive_essay, "--json"])
        data = json.loads(res.stdout)
        self.assertEqual(data["contractions"], [], f"possessives must not be flagged: {data['contractions']}")

        # 题干法定署名不符（2012 英二为 Zhang Wei，题中签 Li Ming）+ 敬语配对
        essay_wrong_name = (
            "Dear Sir or Madam,\n\n"
            "    I am writing to lodge a formal complaint.\n\n"
            "Yours sincerely,\n"
            "Li Ming."
        )
        res2 = self.run_cmd(["check-essay", "--text", essay_wrong_name, "--year", "2012", "--exam-type", "2", "--json"])
        data2 = json.loads(res2.stdout)
        self.assertEqual(data2["expected_signoff"], "Zhang Wei")
        self.assertEqual(data2["detected_signature"], "Li Ming.")
        joined = " | ".join(data2["format_issues"])
        self.assertIn("署名误加句号", joined)
        self.assertIn("题干法定署名不一致", joined)
        self.assertIn("敬语与称呼不匹配", joined)

        # 收件人与署名重名
        essay_collision = (
            "Dear Li Ming,\n\n"
            "    I am writing to share some news.\n\n"
            "Best wishes,\n"
            "Li Ming"
        )
        res3 = self.run_cmd(["check-essay", "--text", essay_collision, "--json"])
        data3 = json.loads(res3.stdout)
        self.assertIn("收件人与署名重名", " | ".join(data3["format_issues"]))

        # 告示类：机构落款合规、个人署名报警
        notice_ok = "Notice\n\n    All students are welcome.\n\nThe Student Union"
        res4 = self.run_cmd(["check-essay", "--text", notice_ok, "--genre", "notice", "--json"])
        data4 = json.loads(res4.stdout)
        self.assertEqual([i for i in data4["format_issues"] if "告示" in i or "称呼" in i], [],
                         f"notice with institution signoff must be clean: {data4['format_issues']}")
        notice_bad = "Notice\n\n    All students are welcome.\n\nLi Ming"
        res5 = self.run_cmd(["check-essay", "--text", notice_bad, "--genre", "notice", "--json"])
        data5 = json.loads(res5.stdout)
        self.assertIn("落款应为发布机构", " | ".join(data5["format_issues"]))

    def test_34_mandated_signoff_lookup_chain(self):
        """P0-1 回归保护：题干法定署名链路（2010/2011/2012 英二 = Zhang Wei；其余 = Li Ming）。"""
        if str(SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPT_DIR))
        import kb_manager

        for year in ("2010", "2011", "2012"):
            signoff, rec = kb_manager.lookup_mandated_signoff(year, "2")
            self.assertIsNotNone(rec, f"{year} English II anchor missing")
            self.assertEqual(signoff, "Zhang Wei", f"{year} English II should mandate Zhang Wei, got {signoff}")

        for year in ("2019", "2021"):
            signoff, rec = kb_manager.lookup_mandated_signoff(year, "1")
            self.assertIsNotNone(rec, f"{year} English I anchor missing")
            self.assertEqual(signoff, "Li Ming", f"{year} English I should mandate Li Ming, got {signoff}")

    def test_settle_pipeline(self):
        """Test atomic settle command with batch, archive, maimemo (mock), and verify."""
        temp_dir = tempfile.mkdtemp(prefix="test_settle_")
        try:
            env = dict(self.env)
            if "KB_ROOT" in env:
                del env["KB_ROOT"]
            env["KAOYAN_USER_BRAIN"] = temp_dir
            self.run_cmd(["init", "--reset"], env=env)

            settle_payload = {
                "task_id": "T2012-E2-ADV",
                "genre": "complaint",
                "year": "2012",
                "exam_type": "English II",
                "title": "投诉网购电子词典（2012英二）",
                "archive": {
                    "content": "Dear Sir or Madam,\n\n    I am writing to lodge a formal complaint regarding the electronic dictionary that I purchased.\n\nYours faithfully,\nZhang Wei\n",
                    "metadata": {
                        "signature": "Zhang Wei",
                        "word_count": 110,
                        "points_coverage": "100%"
                    }
                },
                "batch": {
                    "status_updates": [],
                    "new_items": [
                        {
                            "target": "task1",
                            "data": {
                                "category": "functional_sentence",
                                "genre": "complaint",
                                "section": "opening",
                                "register": "neutral_formal",
                                "intent": "投诉信开篇定调",
                                "expression": "I am writing to lodge a formal complaint regarding [Product].",
                                "mastery": "敢用"
                            }
                        }
                    ]
                },
                "maimemo": {
                    "chapter": "2012英二小作文",
                    "words": [
                        {
                            "spelling": "express",
                            "type": "spelling_fix",
                            "misspelling": "expree",
                            "sentence": "I am writing to express my dissatisfaction.",
                            "translation": "我写信是为了表达不满。",
                            "usage_note": "考研高频动词",
                            "grammar_note": "不定式作目的状语"
                        }
                    ]
                }
            }

            with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8", suffix=".json") as f:
                json.dump(settle_payload, f, ensure_ascii=False)
                payload_file = f.name

            try:
                res = self.run_cmd(["settle", "--file", payload_file, "--mock"], env=env)
                self.assertEqual(res.returncode, 0, f"settle failed: {res.stderr}\nstdout: {res.stdout}")
                self.assertIn("外脑双仓入库完成", res.stdout)
                self.assertIn("范文归档与题目台账登记完成", res.stdout)
                self.assertIn("墨墨背单词专属词本同步成功", res.stdout)
                self.assertIn("知识库一致性校验通过", res.stdout)

                # Check archive file created
                md_files = [f for f in Path(temp_dir).rglob("*.md")]
                self.assertGreaterEqual(len(md_files), 1, f"No md files found in {temp_dir}")

                # Check tasks.jsonl
                tasks_files = [f for f in Path(temp_dir).rglob("tasks.jsonl")]
                self.assertGreaterEqual(len(tasks_files), 1, f"No tasks.jsonl found in {temp_dir}")
                found_task = False
                for tf in tasks_files:
                    with open(tf, "r", encoding="utf-8") as f:
                        if "T2012-E2-ADV" in f.read():
                            found_task = True
                            break
                self.assertTrue(found_task, "T2012-E2-ADV not recorded in tasks.jsonl")
            finally:
                if os.path.exists(payload_file):
                    os.remove(payload_file)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    # =====================================================================
    # Regression tests for the audit remediation (P0 data safety / P1 correctness)
    # =====================================================================

    BUILTIN_GLOBS = (
        "anchors/*.jsonl",
        "seeds/*.jsonl",
    )

    def builtin_fingerprint(self):
        """SHA256 of every read-only built-in asset; must never change."""
        fp = {}
        for pattern in self.BUILTIN_GLOBS:
            for f in sorted(KB_ROOT.glob(pattern)):
                fp[str(f.relative_to(KB_ROOT))] = hashlib.sha256(f.read_bytes()).hexdigest()
        return fp

    def test_36_builtin_base_is_read_only_under_every_write_path(self):
        """P0-1: no command may ever write user data into the shipped anchors/seeds."""
        import types
        sys.path.insert(0, str(SCRIPT_DIR))
        import kb_manager

        temp_dir = tempfile.mkdtemp(prefix="test_builtin_ro_")
        try:
            env = self.init_isolated_brain(temp_dir)
            before = self.builtin_fingerprint()
            self.assertTrue(before, "builtin fingerprint is empty; test is vacuous")

            # (a) write_store must refuse the built-in shared store outright
            paths = kb_manager.get_paths()
            with self.assertRaises(PermissionError):
                kb_manager.write_store(paths, "shared", [])
            with self.assertRaises(PermissionError):
                kb_manager.write_store(paths, "seed_shared", [])
            with self.assertRaises(PermissionError):
                kb_manager.write_store(paths, "seed_task1", [])

            # (b) promoting a built-in shared seed must land in the personal store
            r1 = self.run_cmd(["update-status", "--id", "M_LIB_001", "--status", "敢用"], env=env)
            self.assertEqual(r1.returncode, 0, r1.stderr)
            self.assertIn("已沉淀至个人共享仓", r1.stdout)

            # (c) new morphemes routed to shared must land in the personal store
            batch = {"task_id": "T-RO", "new_items": [{
                "target": "shared",
                "data": {"type": "morpheme", "text": "curb seat hoarding",
                         "meaning": "遏制占座", "source": "回归测试", "mastery": "学习中"},
            }]}
            r2 = self.run_cmd(["batch-update", "--data", json.dumps(batch, ensure_ascii=False)], env=env)
            self.assertEqual(r2.returncode, 0, r2.stderr)

            # (d) cleanup --apply must not touch the base either
            r3 = self.run_cmd(["cleanup", "--apply"], env=env)
            self.assertEqual(r3.returncode, 0, r3.stderr)

            after = self.builtin_fingerprint()
            self.assertEqual(before, after, "read-only built-in assets were mutated by a write path!")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            os.environ.pop("KB_BUILTIN_ROOT", None)
            os.environ.pop("KAOYAN_USER_BRAIN", None)

    def test_37_archive_overwrite_is_restorable_on_rollback(self):
        """P0-2: a pre-existing archive with the SAME filename must be restored byte-exactly."""
        import types
        sys.path.insert(0, str(SCRIPT_DIR))
        import kb_manager

        temp_dir = tempfile.mkdtemp(prefix="test_arch_rb_")
        saved_env = dict(os.environ)
        original_archive = kb_manager.cmd_archive
        try:
            env = self.init_isolated_brain(temp_dir)
            os.environ["KB_BUILTIN_ROOT"] = env["KB_BUILTIN_ROOT"]
            os.environ["KAOYAN_USER_BRAIN"] = env["KAOYAN_USER_BRAIN"]
            os.environ.pop("KB_ROOT", None)

            paths = kb_manager.get_paths()
            arch_dir = Path(paths["archives"])
            arch_dir.mkdir(parents=True, exist_ok=True)

            # Predict the exact filename the archiver will target (date + task + title)
            date_str = datetime.datetime.now().strftime("%Y%m%d")
            title = "Rollback Overwrite Probe"
            title_safe = kb_manager.re.sub(r'[\\/*?:"<>| \t\n]', "_", title)[:40]
            existing = arch_dir / f"{date_str}_2012_complaint_{title_safe}.md"
            existing.write_text("ORIGINAL ARCHIVE CONTENT THAT MUST SURVIVE", encoding="utf-8")

            payload = {
                "task_id": "T-RB2",
                "title": title,
                "genre": "complaint",
                "year": "2012",
                "exam_type": "2",
                "essay_content": "Dear Sir or Madam,\n\n    Body.\n\nYours faithfully,\nZhang Wei\n",
            }
            payload_file = Path(temp_dir) / "settle_rb2.json"
            payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            # Force a LOCAL failure after the archive step by rejecting the verify gate
            original_verify = kb_manager.verify_integrity
            kb_manager.verify_integrity = lambda paths, verbose=True: (True, 0)

            args = types.SimpleNamespace(
                file=str(payload_file), data=None, token=None, mock=True,
                dry_run=False, json=False, example=False,
            )
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    with self.assertRaises(SystemExit) as ctx:
                        kb_manager.cmd_settle(args)
                self.assertEqual(ctx.exception.code, 1)
            finally:
                kb_manager.verify_integrity = original_verify

            self.assertTrue(existing.exists(), "overwritten archive was deleted instead of restored")
            self.assertEqual(
                existing.read_text(encoding="utf-8"),
                "ORIGINAL ARCHIVE CONTENT THAT MUST SURVIVE",
                "pre-existing archive content was lost on rollback",
            )
            # And the new archive must not have been left behind
            self.assertEqual(len(list(Path(temp_dir).rglob("*.md"))), 1)
        finally:
            kb_manager.cmd_archive = original_archive
            os.environ.clear()
            os.environ.update(saved_env)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_38_settle_promotion_is_never_a_silent_noop(self):
        """P0-3: a reported promotion must actually be persisted (no counted-but-unwritten update)."""
        temp_dir = tempfile.mkdtemp(prefix="test_nonoop_")
        try:
            env = self.init_isolated_brain(temp_dir)
            user_shared = Path(temp_dir) / "user_brain" / "shared" / "morphemes.jsonl"
            before = user_shared.read_text(encoding="utf-8")

            # Promote a built-in shared seed id via settle's own batch section
            payload = {
                "task_id": "T-NONOOP",
                "genre": "advice",
                "year": "2011",
                "exam_type": "2",
                "essay_content": "Dear Li Ming,\n\n    Body.\n\nBest wishes,\nZhang Wei\n",
                "batch": {"status_updates": [
                    {"id": "M_LIB_001", "status": "敢用", "note": "回归：晋级必须落盘", "independent": True}
                ]},
            }
            payload_file = Path(temp_dir) / "settle_noop.json"
            payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            res = self.run_cmd(["settle", "--file", str(payload_file), "--mock"], env=env)
            self.assertEqual(res.returncode, 0, f"{res.stderr}\n{res.stdout}")

            after = user_shared.read_text(encoding="utf-8")
            self.assertNotEqual(before, after, "reported promotion wrote nothing (silent no-op)")
            records = [json.loads(l) for l in after.splitlines() if l.strip()]
            promoted = next((r for r in records if r.get("id") == "M_LIB_001"), None)
            self.assertIsNotNone(promoted, "promoted seed record missing from the personal shared warehouse")
            # independent=True 时脚本内建规则会把提议的"敢用"晋级为"稳定"（必须真实落盘）
            self.assertEqual(promoted.get("mastery"), "稳定")
            self.assertEqual(promoted.get("version"), 2, "version must be incremented on promotion")
            self.assertIn("history", promoted, "promoted record must carry a history block")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_39_read_commands_never_create_a_brain(self):
        """P1-5: read-only commands must not create the user brain on disk (PC stays clean)."""
        temp_dir = tempfile.mkdtemp(prefix="test_ro_probe_")
        try:
            target = Path(temp_dir) / "not_yet_created" / "写作外脑"
            self.assertFalse(target.exists())

            env = dict(os.environ)
            env.pop("KB_ROOT", None)
            env["KB_BUILTIN_ROOT"] = str(KB_ROOT)
            env["KAOYAN_USER_BRAIN"] = str(target)

            read_cmds = [
                ["status"],
                ["prompt", "--year", "2012", "--exam-type", "2"],
                ["anchor", "--genre", "advice", "--limit", "1"],
                ["query", "--genre", "advice", "--limit", "3"],
                ["cleanup"],
            ]
            for cmd in read_cmds:
                res = self.run_cmd(cmd, env=env)
                self.assertEqual(res.returncode, 0, f"{cmd} failed: {res.stderr}")
                self.assertFalse(target.exists(), f"read command {cmd} created the user brain at {target}")

            # verify legitimately reports a missing brain, but must still not create it
            res_v = self.run_cmd(["verify"], env=env)
            self.assertFalse(target.exists(), "verify created the user brain")
            self.assertIn("个人外脑尚未初始化", res_v.stdout + res_v.stderr)

            # ...while an explicit write command IS allowed to initialise (env = explicit opt-in)
            res_w = self.run_cmd(["init", "--reset"], env=env)
            self.assertEqual(res.returncode, 0, res_w.stderr)
            self.assertTrue((target / "user_brain" / "task1" / "expressions.jsonl").exists())
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            os.environ.pop("KB_BUILTIN_ROOT", None)
            os.environ.pop("KAOYAN_USER_BRAIN", None)

    def test_40_anchor_limit_returns_newest_real_exam(self):
        """P1-1: --limit 1 must return the newest real-exam anchor, not the first in file order."""
        res = self.run_cmd(["anchor", "--genre", "advice", "--limit", "1"])
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("2024 English II", res.stdout, f"expected newest advice anchor, got:\n{res.stdout}")
        self.assertNotIn("2021 English I", res.stdout)

        res2 = self.run_cmd(["anchor", "--genre", "reply_letter", "--limit", "1"])
        self.assertEqual(res2.returncode, 0, res2.stderr)
        self.assertIn("2025 English I", res2.stdout, f"expected newest reply_letter anchor, got:\n{res2.stdout}")

    def test_41_ambiguous_year_refuses_signature_verdict(self):
        """P1-3: --year without --exam-type must refuse to judge the signature, not guess a paper."""
        essay = ("Dear Sir or Madam,\n\n    I am writing to lodge a complaint.\n\n"
                 "Yours faithfully,\nLi Ming\n")
        ambiguous = self.run_cmd(["check-essay", "--text", essay, "--year", "2011"])
        self.assertEqual(ambiguous.returncode, 0, ambiguous.stderr)
        self.assertIn("已跳过署名核验", ambiguous.stdout)
        # 署名一行必须只给"未校验"，不得给出 PASS/FAIL 结论
        sig_lines = [l for l in ambiguous.stdout.splitlines() if "署名核验:" in l]
        self.assertEqual(len(sig_lines), 1, ambiguous.stdout)
        self.assertIn("未校验", sig_lines[0])
        self.assertNotIn("[FAIL]", sig_lines[0])
        self.assertNotIn("[PASS]", sig_lines[0])

        pinned = self.run_cmd(["check-essay", "--text", essay, "--year", "2012", "--exam-type", "2"])
        self.assertEqual(pinned.returncode, 0, pinned.stderr)
        self.assertIn("题干法定 'Zhang Wei'", pinned.stdout)
        self.assertIn("[FAIL]", pinned.stdout)

    def test_42_user_shared_schema_is_verified_like_task1(self):
        """P1-4: a corrupt personal shared warehouse must fail verify (parity with task1)."""
        import types
        sys.path.insert(0, str(SCRIPT_DIR))
        import kb_manager

        temp_dir = tempfile.mkdtemp(prefix="test_verify_parity_")
        saved_env = dict(os.environ)
        try:
            env = self.init_isolated_brain(temp_dir)
            os.environ["KB_BUILTIN_ROOT"] = env["KB_BUILTIN_ROOT"]
            os.environ["KAOYAN_USER_BRAIN"] = env["KAOYAN_USER_BRAIN"]
            os.environ.pop("KB_ROOT", None)

            user_shared = Path(temp_dir) / "user_brain" / "shared" / "morphemes.jsonl"
            bad = {"id": "M_LIB_001", "category": "not_a_category", "mastery": "随便",
                   "status": "weird", "verb_phrase": "x"}  # missing source + illegal enums
            user_shared.write_text(json.dumps(bad, ensure_ascii=False) + "\n", encoding="utf-8")

            buf = io.StringIO()
            with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
                has_error, _total = kb_manager.verify_integrity(kb_manager.get_paths(), verbose=True)
            report = buf.getvalue()
            self.assertTrue(has_error, "verify must fail on an invalid user_shared record")
            self.assertIn("非法 category", report)
            self.assertIn("非法 mastery", report)
            self.assertIn("非法 status", report)
            self.assertIn("缺少必填字段: source", report)
        finally:
            os.environ.clear()
            os.environ.update(saved_env)
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_43_legacy_flat_layout_is_still_readable(self):
        """P3: historical flat files must remain readable (no data loss on upgrade), but not written."""
        temp_dir = tempfile.mkdtemp(prefix="test_legacy_")
        try:
            env = self.isolated_env(temp_dir)
            ub = Path(temp_dir) / "user_brain"
            ub.mkdir(parents=True, exist_ok=True)

            legacy_rec = {
                "id": "T1_ADV_SEN_900", "category": "functional_sentence", "genre": "advice",
                "section": "opening", "expression": "I am writing to [action].",
                "intent": "存量扁平布局兼容", "source": "legacy", "mastery": "敢用",
            }
            (ub / "task1_expressions.jsonl").write_text(
                json.dumps(legacy_rec, ensure_ascii=False) + "\n", encoding="utf-8")

            res = self.run_cmd(["query", "--mine", "--json"], env=env)
            self.assertEqual(res.returncode, 0, f"{res.stderr}\n{res.stdout}")
            payload = json.loads(res.stdout)
            ids = [it["id"] for grp in ("hits", "same_genre", "cross_genre") for it in payload.get(grp, [])]
            self.assertIn("T1_ADV_SEN_900", ids, "legacy flat records must still be recalled by query --mine")

            # A write must go to the v2 path only, never resurrect the legacy file
            legacy_before = (ub / "task1_expressions.jsonl").read_text(encoding="utf-8")
            (ub / "task1").mkdir(parents=True, exist_ok=True)
            (ub / "task1" / "expressions.jsonl").write_text("", encoding="utf-8")
            res_w = self.run_cmd(["update-status", "--id", "T1_ADV_SEN_900", "--status", "稳定"], env=env)
            self.assertEqual(res_w.returncode, 0, res_w.stderr)
            self.assertEqual((ub / "task1_expressions.jsonl").read_text(encoding="utf-8"), legacy_before,
                             "legacy flat file must not be rewritten")
            v2_records = [json.loads(l) for l in (ub / "task1" / "expressions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertTrue(any(r.get("id") == "T1_ADV_SEN_900" and r.get("mastery") == "稳定" for r in v2_records),
                            "update must be persisted into the v2 warehouse")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_44_doctor_subcommand_diagnostics(self):
        """doctor subcommand: verifies diagnostics without token, and mock-based API probes with JSON output."""
        env_no_token = dict(os.environ)
        env_no_token.pop("MAIMEMO_SPELLING_TOKEN", None)
        env_no_token.pop("MAIMEMO_TOKEN", None)
        env_no_token["KB_BUILTIN_ROOT"] = str(KB_ROOT)

        # 1. Without token: passes with WARN on token, local KB checked
        res = self.run_cmd(["doctor", "--json"], env=env_no_token)
        self.assertEqual(res.returncode, 0, f"doctor without token should exit 0: {res.stderr}\n{res.stdout}")
        self.assertIn("未配置 MAIMEMO_SPELLING_TOKEN", res.stdout)
        json_start = res.stdout.index("{")
        data = json.loads(res.stdout[json_start:])
        self.assertTrue(data["local_kb"]["anchors_ok"])
        self.assertTrue(data["local_kb"]["seed_shared_ok"])
        self.assertTrue(data["local_kb"]["seed_task1_ok"])
        self.assertFalse(data["maimemo"]["configured"])
        self.assertTrue(data["ready"])

        # 2. With mock token
        res_mock = self.run_cmd(["doctor", "--token", "mock_tok_123456789", "--mock", "--json"], env=env_no_token)
        self.assertEqual(res_mock.returncode, 0, f"doctor with mock token failed: {res_mock.stderr}")
        json_start_mock = res_mock.stdout.index("{")
        data_mock = json.loads(res_mock.stdout[json_start_mock:])
        self.assertTrue(data_mock["maimemo"]["configured"])
        self.assertEqual(data_mock["maimemo"]["notepads"]["status"], "PASS")
        self.assertEqual(data_mock["maimemo"]["vocabulary"]["status"], "PASS")
        self.assertEqual(data_mock["maimemo"]["notes"]["status"], "PASS")
        self.assertEqual(data_mock["maimemo"]["phrases"]["status"], "PASS")
        self.assertEqual(data_mock["maimemo"]["study_review"]["status"], "PASS")

    def test_45_settle_recognizes_soft_success_and_relative_path_fallback(self):
        """settle command: accepts relative file path in cwd, and treats maimemo soft_success as exit 0."""
        temp_dir = tempfile.mkdtemp(prefix="test_settle_soft_")
        try:
            env = self.init_isolated_brain(temp_dir)
            payload = {
                "task_id": "T2013-E2-NOTICE",
                "title": "通知慈善义卖（2013英二）",
                "genre": "notice",
                "year": "2013",
                "exam_type": "2",
                "essay_content": (
                    "Notice\n\n    A charity sale will be held on campus.\n\n"
                    "                                        Postgraduates' Association\n"
                ),
                "batch": {"status_updates": [], "new_items": []},
                "maimemo": {
                    "chapter": "2013英二小作文",
                    "words": [
                        {
                            "spelling": "necessities",
                            "sentence": "Students are encouraged to donate daily necessities."
                        }
                    ]
                }
            }
            # Write relative file in temp_dir
            payload_file = Path(temp_dir) / "settle.json"
            payload_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            # 1. Test relative path fallback via run_cmd with cwd=temp_dir
            res = self.run_cmd(["settle", "--file", "settle.json", "--mock"], env=env, cwd=temp_dir)
            self.assertEqual(res.returncode, 0, f"settle with relative path failed: {res.stderr}\n{res.stdout}")
            self.assertIn("范文归档与题目台账登记完成", res.stdout)

            # Verify archive exists
            md_files = list(Path(temp_dir).rglob("*_notice_*.md"))
            self.assertEqual(len(md_files), 1, f"expected 1 notice archive, got {md_files}")

            # 2. In-process test: verify soft_success is recognized as exit 0 without errors
            import types
            import maimemo_sync
            import kb_manager

            orig_sync = maimemo_sync.sync_essay_vocabulary
            def mock_soft_sync(*args, **kwargs):
                return {
                    "status": "soft_success",
                    "message": "生词本与借壳助记已同步入库，专属例句因权限不足已安全跳过（软降级）",
                    "notepad_title": "我的考研作文",
                    "chapter": "2013英二小作文",
                    "notepad_action": "update",
                    "synced_words": ["necessities"],
                    "already_synced_words": [],
                    "skipped_words": [],
                    "phrases_created": 0,
                    "phrases_failed": 0,
                    "phrases_unauthorized": True,
                    "notes_created": 1,
                    "notes_failed": 0,
                    "highlight_missing": [],
                    "failure_details": [],
                    "study_advance": True,
                    "added_count": 1,
                    "remote_side_effects": {
                        "notepad_updated": True,
                        "review_pushed": True,
                        "idempotent_retry": True
                    }
                }

            maimemo_sync.sync_essay_vocabulary = mock_soft_sync
            saved_env = dict(os.environ)
            try:
                os.environ["KB_BUILTIN_ROOT"] = env["KB_BUILTIN_ROOT"]
                os.environ["KAOYAN_USER_BRAIN"] = env["KAOYAN_USER_BRAIN"]
                os.environ.pop("KB_ROOT", None)
                args = types.SimpleNamespace(
                    file=str(payload_file), data=None, token="mock_tok",
                    dry_run=False, mock=False, example=False, json=True
                )
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                    kb_manager.cmd_settle(args)
                out = buf.getvalue()
                self.assertIn("专属例句因 Token 权限跳过", out)
            finally:
                maimemo_sync.sync_essay_vocabulary = orig_sync
                os.environ.clear()
                os.environ.update(saved_env)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_46_maimemo_sync_nested_settle_json(self):
        """maimemo-sync command: natively accepts a full settle.json without manual payload extraction."""
        temp_dir = tempfile.mkdtemp(prefix="test_settle_sync_")
        try:
            settle_payload = {
                "task_id": "T2014-E2-ADV",
                "genre": "advice",
                "year": "2014",
                "exam_type": "English II",
                "title": "合租生活习惯（2014英二）",
                "essay_content": "Dear John,\n\n    I keep early hours.\n\n                                        Li Ming\n",
                "batch": {"status_updates": [], "new_items": []},
                "maimemo": {
                    "chapter": "2014英二小作文",
                    "words": [
                        {
                            "spelling": "brief",
                            "type": "advanced_vocab",
                            "sentence": "I would like to brief you about my living habits.",
                            "usage_note": "及物动词 brief sb. about sth.",
                            "grammar_note": "would like to brief 谓语"
                        }
                    ]
                }
            }
            settle_file = Path(temp_dir) / "settle.json"
            settle_file.write_text(json.dumps(settle_payload, ensure_ascii=False), encoding="utf-8")

            res = self.run_cmd(["maimemo-sync", "--file", str(settle_file), "--mock", "--json"])
            self.assertEqual(res.returncode, 0, f"maimemo-sync with settle.json failed: {res.stderr}\n{res.stdout}")
            data = json.loads(res.stdout)
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["chapter"], "2014英二小作文")
            self.assertEqual(data["synced_words"], ["brief"])
            self.assertEqual(data["notes_created"], 1)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()



