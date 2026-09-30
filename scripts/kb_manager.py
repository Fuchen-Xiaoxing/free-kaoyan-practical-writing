#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kb_manager.py - Knowledge Base Manager for Kaoyan Practical Writing (Section A)

Core Capabilities:
  1. anchor: Query official past paper anchor briefs (register analysis, vocabulary benchmark, extractable skeleton).
             Official model text is internal-only by default and omitted unless --full is explicitly specified.
  2. query: 3-tier retrieval (hard filter + relevance scoring + strict quota <= 5, "宁缺毋滥") for pre-writing清单.
  3. append: Admission-controlled append with 4 hard rules, normalized deduplication, and stable ID generation.
  4. update-status / batch-update: Evidence-based mastery lifecycle (未接触 -> 学习中 -> 敢用 -> 稳定),
                                  cross-task independent use tracking, error handling, and history.log versioning.
  5. archive: Satisfaction essay archival in archives/task1/ with absorbed items and tasks.jsonl sync.
  6. session: Multi-round session tracking (basic_versions with diffs, advanced_versions).
  7. cleanup: Periodic soft-delete / dormancy recommendations based on recommendation history.
  8. verify: Strict validation (syntax, required fields, ID uniqueness, enums, references).
"""

import sys
import os
import json
import argparse
import datetime
import re
from pathlib import Path
import shutil

# Force UTF-8 stdout/stderr on Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Explicit Genre Code Map for stable ID generation
GENRE_CODE_MAP = {
    "advice": "ADV",
    "recommendation": "REC",
    "complaint": "COM",
    "apology": "APO",
    "invitation": "INV",
    "gratitude": "GRA",
    "application": "APP",
    "notice": "NOT",
    "minutes": "MIN",
    "reply_letter": "REP",
    "general": "GEN"
}

SCENARIO_CODE_MAP = {
    "图书馆与学习环境": "LIB",
    "校园文体、学术讲座与国际研讨会": "ACT",
    "志愿服务与校园公益": "VOL",
    "消费者维权与售后": "CON",
    "餐饮卫生与食品安全": "FOOD",
    "求职实习与学术引荐": "JOB",
    "文化交流与文旅推荐": "CUL"
}

# Genre aliases for robust user/LLM input normalization
GENRE_ALIASES = {
    "suggestion": "advice",
    "advise": "advice",
    "recommend": "recommendation",
    "invite": "invitation",
    "apologize": "apology",
    "complain": "complaint",
    "apply": "application",
    "thank": "gratitude",
    "thanks": "gratitude",
    "announcement": "notice",
    "meeting_minutes": "minutes",
    "memo": "minutes"
}

def normalize_genre(genre: str) -> str:
    if not genre:
        return ""
    g = str(genre).lower().strip()
    return GENRE_ALIASES.get(g, g)

# Scenario relevance mapping for genres to eliminate cross-scenario noise
GENRE_TO_SCENARIOS = {
    "invitation": ["校园文体、学术讲座与国际研讨会", "文化交流与文旅推荐", "志愿服务与校园公益"],
    "advice": ["图书馆与学习环境", "餐饮卫生与食品安全", "校园文体、学术讲座与国际研讨会"],
    "recommendation": ["文化交流与文旅推荐", "求职实习与学术引荐", "校园文体、学术讲座与国际研讨会"],
    "complaint": ["消费者维权与售后", "餐饮卫生与食品安全"],
    "apology": ["校园文体、学术讲座与国际研讨会", "求职实习与学术引荐"],
    "gratitude": ["文化交流与文旅推荐", "志愿服务与校园公益", "求职实习与学术引荐"],
    "application": ["求职实习与学术引荐", "志愿服务与校园公益"],
    "notice": ["校园文体、学术讲座与国际研讨会", "志愿服务与校园公益", "图书馆与学习环境"],
    "minutes": ["校园文体、学术讲座与国际研讨会", "志愿服务与校园公益"],
    "reply_letter": ["文化交流与文旅推荐", "校园文体、学术讲座与国际研讨会", "求职实习与学术引荐"]
}

MASTERY_RANK = {
    "稳定": 4,
    "敢用": 3,
    "学习中": 2,
    "未接触": 1
}

VALID_CATEGORIES = {"word", "phrase", "sentence", "functional_sentence", "template", "structure"}
VALID_STATUSES = {"active", "dormant", "retired"}
VALID_REGISTERS = {"informal_peer", "neutral_formal", "formal_authority", "public_notice"}
VALID_SECTIONS = {"opening", "body", "closing", "format", "any"}

def test_writable_dir(target_path_str: str) -> bool:
    """真实探测目录可写性（支持创建临时父目录并执行写入测试）"""
    try:
        p = Path(target_path_str)
        if p.exists() and os.access(p, os.W_OK):
            return True
        parent = p
        while parent and not parent.exists() and parent != parent.parent:
            parent = parent.parent
        # 避免在根目录（如 / 或 D:\）下直接滥建未知顶层目录，要求已存在父级至少有1级非根路径
        if parent and parent.exists() and len(parent.parts) > 1:
            p.mkdir(parents=True, exist_ok=True)
            test_file = p / ".perm_test"
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("1")
            test_file.unlink(missing_ok=True)
            return True
    except Exception:
        pass
    return False

def get_builtin_base_dir() -> Path:
    """定位 Skill 内置的静态教研底座资产（anchors, shared 及出厂种子模板）"""
    if "KB_BUILTIN_ROOT" in os.environ:
        p = Path(os.environ["KB_BUILTIN_ROOT"])
        if p.exists():
            return p

    # 1. 优先使用环境变量 KB_ROOT（保持单测兼容）
    if "KB_ROOT" in os.environ:
        kb_env = Path(os.environ["KB_ROOT"])
        if kb_env.exists():
            return kb_env

    # 2. 脚本所在目录相对定位 (free-kaoyan-practical-writing/knowledge_base)
    script_dir = Path(__file__).resolve().parent
    skill_kb = script_dir.parent / "knowledge_base"
    if skill_kb.exists():
        return skill_kb

    # 3. 宿主上级目录定位
    repo_kb = script_dir.parent.parent / "knowledge_base"
    if repo_kb.exists():
        return repo_kb

    # 4. OpenMinis 默认安装路径
    minis_skill_kb = Path("/var/minis/skills/free-kaoyan-practical-writing/knowledge_base")
    if minis_skill_kb.exists():
        return minis_skill_kb

    return skill_kb

def get_user_brain_dir() -> Path:
    """
    智能解析用户外脑安全持久化存储路径，彻底与 Skill 目录解耦：
    1. 环境变量优先：KAOYAN_WRITING_KB 或 KAOYAN_USER_BRAIN 或 KB_ROOT
    2. Open Minis 外部挂载 Documents 优先（/var/minis/mounts/Documents/考研英语/写作外脑）
    3. Android 手机公共文档目录原生探测（/storage/emulated/0/Documents/考研英语/写作外脑）
    4. Open Minis 沙盒持久工作区降级（/var/minis/workspace/考研英语/写作外脑）
    5. PC / 桌面系统用户文档目录（~/Documents/考研英语/写作外脑）
    6. 本地开发/单测环境兜底
    """
    # 1. 显式环境变量优先
    env_path = os.environ.get("KAOYAN_WRITING_KB") or os.environ.get("KAOYAN_USER_BRAIN") or os.environ.get("KB_ROOT")
    if env_path:
        return Path(env_path).expanduser().resolve()

    # 2. Open Minis 外部挂载目录与持久区优先（仅在 OpenMinis 环境生效）
    if os.path.exists("/var/minis"):
        minis_mount_candidates = [
            "/var/minis/mounts/Documents/考研英语/写作外脑",
            "/var/minis/mounts/documents/考研英语/写作外脑",
            "/var/minis/mounts/Documents/写作外脑",
            "/var/minis/mounts/documents/写作外脑",
        ]
        if os.path.isdir("/var/minis/mounts"):
            try:
                for entry in os.listdir("/var/minis/mounts"):
                    sub = os.path.join("/var/minis/mounts", entry)
                    if os.path.isdir(sub) and entry.lower() in ["documents", "document", "docs"]:
                        cand = os.path.join(sub, "考研英语", "写作外脑")
                        if cand not in minis_mount_candidates:
                            minis_mount_candidates.insert(0, cand)
            except Exception:
                pass

        for cand in minis_mount_candidates:
            if test_writable_dir(cand):
                return Path(cand)

        # Open Minis 官方 workspace 降级
        minis_ws = "/var/minis/workspace/考研英语/写作外脑"
        if os.path.exists("/var/minis/workspace"):
            if test_writable_dir(minis_ws):
                return Path(minis_ws)

    # 3. Android 原生公共存储路径探测
    if os.path.exists("/storage/emulated/0") or os.path.exists("/sdcard"):
        android_candidates = [
            "/storage/emulated/0/Documents/考研英语/写作外脑",
            "/sdcard/Documents/考研英语/写作外脑",
            "/storage/emulated/0/Download/考研英语/写作外脑",
            "/sdcard/Download/考研英语/写作外脑",
        ]
        for cand in android_candidates:
            if test_writable_dir(cand):
                return Path(cand)

    # 4. PC / 常规系统（Windows / macOS / Linux）用户文档目录
    try:
        home = Path.home()
        pc_docs = home / "Documents" / "考研英语" / "写作外脑"
        if (home / "Documents").exists():
            if test_writable_dir(str(pc_docs)):
                return pc_docs
    except Exception:
        pass

    # 6. 本地开发/单测环境兜底
    script_dir = Path(__file__).resolve().parent
    local_kb = script_dir.parent / "knowledge_base"
    return local_kb

def get_base_dir() -> Path:
    """兼容旧接口"""
    return get_builtin_base_dir()

def init_user_brain(user_brain_dir: Path = None, force_reset: bool = False) -> Path:
    """初始化或格式化用户外脑目录（自动播种出厂种子与旧数据迁移）"""
    if user_brain_dir is None:
        user_brain_dir = get_user_brain_dir()

    base_dir = get_builtin_base_dir()
    seed_t1 = base_dir / "user_brain" / "task1_expressions.jsonl"

    if user_brain_dir.name == "user_brain":
        ub_sub = user_brain_dir
    else:
        ub_sub = user_brain_dir / "user_brain"

    target_t1 = ub_sub / "task1_expressions.jsonl"
    target_tasks = ub_sub / "tasks.jsonl"
    target_hist = ub_sub / "history.log"
    target_sess = ub_sub / "sessions"

    # Archives target: 优先满意范文/task1
    if user_brain_dir.name == "写作外脑" or (user_brain_dir / "满意范文").exists() or not (ub_sub / "satisfaction_archives").exists():
        target_arch = user_brain_dir / "满意范文" / "task1"
    else:
        target_arch = ub_sub / "satisfaction_archives" / "task1"

    ub_sub.mkdir(parents=True, exist_ok=True)
    target_arch.mkdir(parents=True, exist_ok=True)
    target_sess.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if force_reset or not target_t1.exists() or target_t1.stat().st_size == 0:
        if not force_reset:
            # 尝试向上跨级自愈迁移：检测 workspace 中是否有遗留的学习数据
            legacy_candidates = [
                Path("/var/minis/workspace/考研英语/写作外脑/user_brain/task1_expressions.jsonl"),
            ]
            migrated = False
            for leg in legacy_candidates:
                if leg.exists() and leg.resolve() != target_t1.resolve() and leg.stat().st_size > 0:
                    try:
                        leg_items = read_jsonl(leg)
                        has_progress = any(it.get("mastery") != "未接触" or it.get("version", 1) > 1 for it in leg_items)
                        if has_progress:
                            write_jsonl(target_t1, leg_items)
                            leg_tasks = leg.parent / "tasks.jsonl"
                            if leg_tasks.exists():
                                shutil.copy2(leg_tasks, target_tasks)
                            print(f"[MIGRATE] 检测到历史有效学习数据，已自动迁移至外部外脑: {user_brain_dir}")
                            migrated = True
                            break
                    except Exception:
                        pass
            if migrated:
                return user_brain_dir

        # 播种纯净出厂种子
        if seed_t1.exists() and seed_t1.resolve() != target_t1.resolve():
            shutil.copy2(seed_t1, target_t1)
        elif not target_t1.exists():
            target_t1.touch()

        if force_reset or not target_tasks.exists():
            with open(target_tasks, "w", encoding="utf-8") as f:
                pass

        if force_reset or not target_hist.exists():
            with open(target_hist, "w", encoding="utf-8") as f:
                entry = {
                    "ts": now_iso,
                    "op": "init",
                    "id": "SYS_INIT",
                    "before": None,
                    "after": "出厂纯净写作外脑种子就绪",
                    "reason": "格式化重置并初始化考研小作文出厂外脑" if force_reset else "初始化考研小作文出厂外脑",
                    "task_id": ""
                }
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # 标记外脑元数据
        meta_file = user_brain_dir / ".kb_meta.json"
        try:
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump({
                    "initialized_at": now_iso,
                    "version": "1.0.0",
                    "storage_type": "external_mount" if "/mounts/" in str(user_brain_dir) else "local",
                    "clean_factory": True
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return user_brain_dir

def get_paths(kb_dir: Path = None, base_kb_dir: Path = None, user_brain_dir: Path = None) -> dict:
    """双根路由解析：只读教研底座资产 + 外部读写用户外脑"""
    if kb_dir is not None:
        if base_kb_dir is None:
            base_kb_dir = kb_dir
        if user_brain_dir is None:
            user_brain_dir = kb_dir

    if base_kb_dir is None:
        base_kb_dir = get_builtin_base_dir()
    if user_brain_dir is None:
        user_brain_dir = get_user_brain_dir()

    # 确定 user_brain 子目录
    if user_brain_dir.name == "user_brain":
        ub_sub = user_brain_dir
    else:
        ub_sub = user_brain_dir / "user_brain"

    # 确定范文归档目录
    if (user_brain_dir / "满意范文" / "task1").exists():
        archives_dir = user_brain_dir / "满意范文" / "task1"
        archives_root = user_brain_dir / "满意范文"
    elif (ub_sub / "satisfaction_archives" / "task1").exists():
        archives_dir = ub_sub / "satisfaction_archives" / "task1"
        archives_root = ub_sub / "satisfaction_archives"
    elif (user_brain_dir / "satisfaction_archives" / "task1").exists():
        archives_dir = user_brain_dir / "satisfaction_archives" / "task1"
        archives_root = user_brain_dir / "satisfaction_archives"
    else:
        if user_brain_dir.name == "写作外脑" or (user_brain_dir / "满意范文").exists():
            archives_dir = user_brain_dir / "满意范文" / "task1"
            archives_root = user_brain_dir / "满意范文"
        else:
            archives_dir = ub_sub / "satisfaction_archives" / "task1"
            archives_root = ub_sub / "satisfaction_archives"

    t1_file = ub_sub / "task1_expressions.jsonl"
    # 若外脑未初始化且处于挂载/持久目录，自动触发静默播种
    if not t1_file.exists() and user_brain_dir != base_kb_dir:
        init_user_brain(user_brain_dir, force_reset=False)

    return {
        "base_root": base_kb_dir,
        "user_root": user_brain_dir,
        "task1": t1_file,
        "shared": base_kb_dir / "shared" / "scenario_morphemes.jsonl",
        "anchors": base_kb_dir / "anchors" / "task1_past_papers.jsonl",
        "archives": archives_dir,
        "archives_root": archives_root,
        "tasks": ub_sub / "tasks.jsonl",
        "history_log": ub_sub / "history.log",
        "sessions": ub_sub / "sessions"
    }


def read_jsonl(file_path: Path, strict: bool = False):
    if not file_path.exists():
        return []
    records = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                err_msg = f"[ERROR] Failed to parse JSON at {file_path}:{line_num}: {e}"
                if strict:
                    raise ValueError(err_msg)
                print(err_msg, file=sys.stderr)
    return records

def write_jsonl(file_path: Path, records: list):
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_suffix(".tmp")
    with open(temp_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    temp_path.replace(file_path)

def log_history(paths: dict, op: str, item_id: str, before: any, after: any, reason: str = "", task_id: str = ""):
    hist_file = paths["history_log"]
    hist_file.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "op": op,
        "id": item_id,
        "before": before,
        "after": after,
        "reason": reason,
        "task_id": task_id
    }
    with open(hist_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def normalize_key(text: str) -> str:
    cleaned = re.sub(r"\[.*?\]", "[X]", text)
    cleaned = re.sub(r"[^\w\s\[\]]", " ", cleaned.lower())
    return re.sub(r"\s+", " ", cleaned).strip()

def check_admission_rules(item: dict) -> tuple[bool, str]:
    cat = item.get("category", "functional_sentence")
    if cat not in VALID_CATEGORIES:
        return False, f"Invalid category: {cat}. Must be one of {sorted(list(VALID_CATEGORIES))}"

    # 1. Reusability: must contain slots or be template/structure
    if cat in ("functional_sentence", "sentence"):
        expr = item.get("expression", "")
        if not re.search(r"\[.*?\]", expr) and not item.get("slots"):
            return False, "Not reusable: functional_sentence/sentence expression lacks slots [x] or variable placeholders."
    elif cat in ("template", "structure"):
        pass
    elif cat in ("word", "phrase"):
        if not item.get("verb_phrase") and not item.get("term") and not item.get("pattern"):
            if item.get("expression"):
                item["verb_phrase"] = item["expression"]
            else:
                return False, "Word/phrase missing head term, verb_phrase or expression."

    # 2. Source and intent required
    if not item.get("source"):
        return False, "Missing required field: source"
    if not item.get("intent") and not item.get("intent_cn"):
        return False, "Missing required field: intent/intent_cn"

    # 3. Exam band check
    band = str(item.get("exam_band", "大纲内")).strip()
    if band in ("考纲核心", "大纲词汇", "核心词汇", "大纲", "core"):
        band = "大纲内"
        item["exam_band"] = "大纲内"
    if band not in ("大纲内", "超纲"):
        return False, f"Invalid exam_band: {band}. Must be '大纲内' or '超纲'"

    return True, "OK"

def cmd_anchor(args):
    paths = get_paths()
    anchors = read_jsonl(paths["anchors"])

    genre_target = normalize_genre(args.genre) if args.genre else None
    year_target = str(args.year).strip() if args.year else None
    exam_target = str(args.exam_type).strip().lower() if getattr(args, "exam_type", None) else None

    if exam_target:
        if exam_target in ("1", "英一", "eng1", "english1", "english 1", "english i"):
            exam_target_norm = "english i"
        elif exam_target in ("2", "英二", "eng2", "english2", "english 2", "english ii"):
            exam_target_norm = "english ii"
        else:
            exam_target_norm = exam_target
    else:
        exam_target_norm = None

    if not genre_target and not year_target and not exam_target_norm:
        print("[ERROR] 请至少指定 --genre、--year 或 --exam-type 参数之一。", file=sys.stderr)
        return

    matches = []
    for item in anchors:
        item_genre = str(item.get("genre", "")).lower()
        item_year = str(item.get("year", ""))
        item_exam = str(item.get("exam_type", "")).lower()
        if genre_target:
            if genre_target != item_genre and genre_target not in item_genre:
                continue
        if year_target:
            if year_target != item_year:
                continue
        if exam_target_norm:
            if exam_target_norm in ("english i", "english ii"):
                if exam_target_norm != item_exam:
                    continue
            elif exam_target_norm not in item_exam:
                continue
        matches.append(item)

    if not matches and genre_target:
        # Fallback: search prompt, register_analysis, tags only (NEVER search official_model!)
        for item in anchors:
            text = f"{item.get('prompt', '')} {item.get('register_analysis', '')} {' '.join(item.get('tags', []))}".lower()
            if genre_target in text:
                matches.append(item)

    if not matches:
        print(f"[ANCHOR] 未检索到匹配的官方真题范文 (genre={genre_target}, year={year_target})。")
        return

    # Limit truncation if explicitly specified
    total_matched = len(matches)
    truncated = False
    limit_arg = getattr(args, "limit", None)
    if limit_arg is not None and str(limit_arg).lower() != "all":
        try:
            lim = max(1, int(limit_arg))
            if total_matched > lim:
                matches = matches[:lim]
                truncated = True
        except ValueError:
            pass

    if args.json:
        out_matches = []
        for m in matches:
            m_copy = dict(m)
            if not args.full:
                m_copy["official_model"] = "[OMITTED: run with --full to view full model text]"
                if "model_advanced" in m_copy:
                    m_copy["model_advanced"] = "[OMITTED]"
                if "model_perfect" in m_copy:
                    m_copy["model_perfect"] = "[OMITTED]"
                if "official_models" in m_copy:
                    m_copy["official_models"] = "[OMITTED]"
            out_matches.append(m_copy)
        print(json.dumps(out_matches if len(out_matches) > 1 else out_matches[0], ensure_ascii=False, indent=2))
        return

    print(f"=== 官方真题范文与语域基准标尺 (共 {len(matches)} 篇) ===")
    if truncated:
        print(f"• [提示] 已按最新年份展示前 {len(matches)} 篇真题标尺（共匹配到 {total_matched} 篇）。如需查阅更多可指定 --limit {total_matched} 或 --limit all。")
    for idx, anchor in enumerate(matches, 1):
        year = anchor.get("year", "N/A")
        exam = anchor.get("exam_type", "N/A")
        genre = anchor.get("genre", "N/A")
        is_real = anchor.get("is_real_exam", True)
        real_ref = anchor.get("real_exam_ref", "N/A")
        source_file = anchor.get("source_file", "N/A")
        rel = anchor.get("relationship", "未标注")
        reg = anchor.get("register", "neutral_formal")
        prompt = anchor.get("prompt", "")
        model = anchor.get("official_model", "")
        analysis = anchor.get("register_analysis", anchor.get("analysis", ""))
        vocab = anchor.get("vocabulary_benchmark", "")
        extracts = anchor.get("extractable_expressions", [])

        real_tag = f"真题 ({real_ref})" if is_real else "大纲模拟 (非真题，仅作题型参考)"

        print(f"\n--- 【范文锚点 #{idx}】 {year} {exam} · {genre} [{real_tag}] ---")
        print(f"• 受众权责关系: {rel} | 语域档位: {reg}")
        print(f"• 试题要求 (Prompt):\n  {prompt}")
        print(f"\n• 语域与语气深度剖析:\n  {analysis}")
        if vocab:
            print(f"• 句法与考纲词汇标尺:\n  {vocab}")
        if extracts:
            print(f"• 推荐抽取的高价值核心骨架:")
            for e in extracts:
                print(f"  - {e}")
        has_dual = bool(anchor.get("model_perfect") or (anchor.get("official_models") and len(anchor.get("official_models")) > 1))
        if has_dual:
            print("• 范文架构: 双范文支持（含【版本一 · 高级范文】与【版本二 · 满分习作】）")
        print(f"• 真题出处文件: {source_file}")

        # P0-2: Leak protection: Only display official model if --full is requested
        if args.full:
            m_ver = getattr(args, "model_version", "all")
            if m_ver == "1" and anchor.get("model_advanced"):
                print(f"\n• 官方高分范文 (Official Model · 版本一 高级范文):\n{anchor.get('model_advanced')}")
            elif m_ver == "2" and anchor.get("model_perfect"):
                print(f"\n• 官方高分范文 (Official Model · 版本二 满分习作):\n{anchor.get('model_perfect')}")
            else:
                print(f"\n• 官方高分范文 (Official Model):\n{model}")
        else:
            print(f"\n• [提示] 官方范文正文默认不展示（作为 AI 内部语域标尺）。如需查验全文请添加 --full 参数。")

def extract_mandated_signoff(prompt: str) -> str:
    """从 Directions 题干中提取官方指定署名，未指定时默认为 Li Ming"""
    if not prompt:
        return "Li Ming (默认)"
    m = re.search(r'Use\s+["“]([^"”]+)["”]\s+instead', prompt, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m2 = re.search(r'sign\s+your\s+name\s+as\s+["“]([^"”]+)["”]', prompt, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return "Li Ming (默认)"

def cmd_prompt(args):
    """
    专门为阶段 0/1（审题、零碎句诊断、三栏清单、基础版批改与偏题拦截）设计的题干调取接口。
    核心安全机制：数据投影（Projection），物理剔除官方范文与高能句式骨架，彻底杜绝阶段 1 上下文污染。
    """
    paths = get_paths()
    anchors = read_jsonl(paths["anchors"])

    genre_target = normalize_genre(args.genre) if args.genre else None
    year_target = str(args.year).strip() if args.year else None
    exam_target = str(args.exam_type).strip().lower() if getattr(args, "exam_type", None) else None

    if exam_target:
        if exam_target in ("1", "英一", "eng1", "english1", "english 1", "english i"):
            exam_target_norm = "english i"
        elif exam_target in ("2", "英二", "eng2", "english2", "english 2", "english ii"):
            exam_target_norm = "english ii"
        else:
            exam_target_norm = exam_target
    else:
        exam_target_norm = None

    if not genre_target and not year_target and not exam_target_norm:
        print("[ERROR] 请至少指定 --year、--exam-type 或 --genre 参数之一。", file=sys.stderr)
        return

    matches = []
    for item in anchors:
        item_genre = str(item.get("genre", "")).lower()
        item_year = str(item.get("year", ""))
        item_exam = str(item.get("exam_type", "")).lower()
        if genre_target:
            if genre_target != item_genre and genre_target not in item_genre:
                continue
        if year_target:
            if year_target != item_year:
                continue
        if exam_target_norm:
            if exam_target_norm in ("english i", "english ii"):
                if exam_target_norm != item_exam:
                    continue
            elif exam_target_norm not in item_exam:
                continue
        matches.append(item)

    if not matches and genre_target:
        for item in anchors:
            text = f"{item.get('prompt', '')} {item.get('register_analysis', '')} {' '.join(item.get('tags', []))}".lower()
            if genre_target in text:
                matches.append(item)

    if not matches:
        print(f"[PROMPT] 未检索到匹配的官方真题题干 (genre={genre_target}, year={year_target}, exam_type={exam_target_norm})。")
        return

    # 数据投影：只保留题干、要点、语域、指定落款，物理删除所有范文和抽取骨架
    projected = []
    for m in matches:
        clean = {
            "id": m.get("id"),
            "year": m.get("year"),
            "exam_type": m.get("exam_type"),
            "genre": m.get("genre"),
            "relationship": m.get("relationship", "未标注"),
            "register": m.get("register", "neutral_formal"),
            "prompt": m.get("prompt", ""),
            "key_points": m.get("key_points", []),
            "register_analysis": m.get("register_analysis", ""),
            "mandated_signoff": extract_mandated_signoff(m.get("prompt", "")),
            "source_file": m.get("source_file", "")
        }
        projected.append(clean)

    if args.json:
        print(json.dumps(projected if len(projected) > 1 else projected[0], ensure_ascii=False, indent=2))
        return

    if len(projected) > 1:
        print(f"=== 官方真题题干与审题标尺 (共检索到 {len(projected)} 篇，存在卷别分支) ===")
        print("• [注意] 检测到当年存在英一/英二双卷。若未指明卷别，请直接追问学员确认！\n")
        for idx, p in enumerate(projected, 1):
            print(f"--- 【卷别选项 #{idx}】 {p['year']} {p['exam_type']} · {p['genre']} ---")
            print(f"• 官方指定署名: {p['mandated_signoff']}")
            print(f"• 试题要求 (Prompt):\n  {p['prompt']}")
            print(f"• 核心采分点 (Key Points): {', '.join(p['key_points'])}")
            print(f"• 语域档位: {p['register']} ({p['relationship']})\n")
    else:
        p = projected[0]
        print(f"=== 官方真题要求与审题基准标尺: {p['year']} {p['exam_type']} · {p['genre']} ===")
        print(f"• 受众权责关系: {p['relationship']} | 语域档位: {p['register']}")
        print(f"• 【官方指定署名】: {p['mandated_signoff']}")
        print(f"• 试题要求 (Directions):\n{p['prompt']}")
        print("• 核心采分要点 (Key Points):")
        for kp in p['key_points']:
            print(f"  - {kp}")
        print(f"• 语域与语气深度剖析:\n  {p['register_analysis']}")
        print("\n*(本命令已对官方范文执行物理级隔离，输出中 100% 零范文泄露)*")

def cmd_query(args):
    paths = get_paths()
    results = []

    target_type = args.type.lower()
    genre_filter = normalize_genre(args.genre) if args.genre else None
    scenario_filter = args.scenario.lower().strip() if args.scenario else None
    status_filter = args.status.strip() if args.status else None
    section_filter = args.section.lower().strip() if getattr(args, "section", None) else None

    # Determine allowed scenarios for genre
    allowed_scenarios = set()
    if genre_filter and genre_filter in GENRE_TO_SCENARIOS:
        allowed_scenarios = set(GENRE_TO_SCENARIOS[genre_filter])

    task1_ids = set()
    # 1. Load task1 expressions
    if target_type in ("all", "task1"):
        task1_items = read_jsonl(paths["task1"])
        for item in task1_items:
            if "id" in item:
                task1_ids.add(item["id"])
            # Hard filter: status
            if item.get("status") == "retired":
                continue
            # Hard filter: exam_band
            if item.get("exam_band") == "超纲":
                continue

            item_genre = normalize_genre(item.get("genre", ""))
            if genre_filter:
                if genre_filter != item_genre and item_genre not in ("general", "common", "all", "shared"):
                    continue

            if status_filter and item.get("mastery") != status_filter:
                continue

            if section_filter and section_filter != "any":
                item_sec = item.get("section", "any")
                if item_sec not in (section_filter, "any"):
                    continue

            if scenario_filter:
                text_to_search = f"{item.get('intent', '')} {item.get('intent_cn', '')} {item.get('expression', '')} {item.get('verb_phrase', '')} {item.get('scenario', '')} {' '.join(item.get('tags', []))}".lower()
                if scenario_filter not in text_to_search:
                    continue

            # Calculate relevance score
            score = 1.0
            if item_genre == genre_filter:
                score += 3.0
            score += MASTERY_RANK.get(item.get("mastery", "未接触"), 1)
            hist = item.get("history", {})
            if hist.get("error_use_count", 0) > 0:
                score -= 2.0
            if item.get("status") == "dormant":
                score -= 1.5

            item["_score"] = score
            results.append(item)

    # 2. Load shared scenario morphemes
    if target_type in ("all", "shared"):
        shared_items = read_jsonl(paths["shared"])
        for item in shared_items:
            if item.get("id") in task1_ids:
                continue
            if item.get("status") == "retired":
                continue
            if item.get("exam_band") == "超纲":
                continue

            item_scenario = str(item.get("scenario", "")).strip()

            # P0-3 & D03: Strict scenario relevance filtering
            if scenario_filter:
                text_to_search = f"{item_scenario} {item.get('intent_cn', '')} {item.get('verb_phrase', '')}".lower()
                if scenario_filter not in text_to_search:
                    continue
            elif genre_filter:
                # If genre is given, morpheme MUST belong to allowed scenarios!
                if allowed_scenarios and item_scenario not in allowed_scenarios:
                    continue

            if status_filter and item.get("mastery") != status_filter:
                continue

            if section_filter and section_filter not in ("body", "any"):
                continue

            score = 1.0
            if allowed_scenarios and item_scenario in allowed_scenarios:
                score += 2.5
            score += MASTERY_RANK.get(item.get("mastery", "未接触"), 1)
            hist = item.get("history", {})
            if hist.get("error_use_count", 0) > 0:
                score -= 2.0
            if item.get("status") == "dormant":
                score -= 1.5

            item["_score"] = score
            results.append(item)

    if args.json:
        results.sort(key=lambda x: x.get("_score", 0), reverse=True)
        print(json.dumps(results[:args.limit], ensure_ascii=False, indent=2))
        return

    if not results:
        print(f"[KB] 未检索到匹配的条目 (genre={genre_filter}, scenario={scenario_filter}, status={status_filter})。")
        return

    # Structured 3-column grouping
    # Group 1: 本题可用已掌握 (mastery in 稳定, 敢用)
    # Group 2: 本题建议新学 (mastery in 学习中, 未接触)
    # Group 3: 本题建议结构/模板 (category in template, structure)
    mastered = []
    to_learn = []
    templates = []

    for item in results:
        m = item.get("mastery", "未接触")
        cat = item.get("category", "")
        if cat in ("template", "structure"):
            templates.append(item)
        elif m in ("稳定", "敢用"):
            mastered.append(item)
        else:
            to_learn.append(item)

    # Sort each group by score
    mastered.sort(key=lambda x: x.get("_score", 0), reverse=True)
    to_learn.sort(key=lambda x: x.get("_score", 0), reverse=True)
    templates.sort(key=lambda x: x.get("_score", 0), reverse=True)

    limit = args.limit
    # Strict Quota: mastered <= 2, to_learn <= 2, templates <= 1, total <= limit
    pick_m = mastered[:min(2, limit)]
    pick_t = templates[:min(1, max(0, limit - len(pick_m)))]
    rem = max(0, limit - len(pick_m) - len(pick_t))
    pick_l = to_learn[:min(2, rem)]

    # Total picked (P3-1: limit is upper bound, do not force-pad irrelevant items)
    all_picked = pick_m + pick_l + pick_t

    def print_item(i, item):
        item_id = item.get("id", "N/A")
        mastery = item.get("mastery", "未接触")
        m_note = f"（{item.get('mastery_note')}）" if item.get("mastery_note") else ""
        cat = item.get("category", "")
        reg = item.get("register", "neutral_formal")
        sec = item.get("section", "body")

        if cat == "functional_sentence":
            intent = item.get("intent", "")
            expr = item.get("expression", "")
            slots = item.get("slots", {})
            slots_desc = " | ".join([f"{k}: {v}" for k, v in slots.items()]) if slots else "无"
            print(f"  {i}. [{item_id}] 【{mastery}{m_note}】 {intent}")
            print(f"     表达骨架: `{expr}`")
            if slots:
                print(f"     槽位指引: {slots_desc}")
            print(f"     段位/语域: 段位: {sec} | 语域: {reg}")
        elif cat == "phrase" or "verb_phrase" in item:
            scenario = item.get("scenario", "")
            intent_cn = item.get("intent_cn", item.get("intent", ""))
            phrase = item.get("verb_phrase", "")
            collocations = ", ".join(item.get("typical_collocations", []))
            print(f"  {i}. [{item_id}] 【{mastery}{m_note}】 语素 ({scenario}): {intent_cn}")
            print(f"     动宾短语: `{phrase}`")
            if collocations:
                print(f"     典型搭配: {collocations}")
            print(f"     段位/语域: 段位: {sec} | 语域: {reg}")
        elif cat == "template":
            intent = item.get("intent", "")
            budget = item.get("word_budget", "100-110")
            print(f"  {i}. [{item_id}] 【{mastery}】 篇章模板: {intent} (建议词数: {budget})")
            blocks = item.get("blocks", [])
            if blocks:
                preview = " / ".join([b.strip().replace('\n', ' ') for b in blocks[:3]])
                print(f"     骨架预览: `{preview}`")
        elif cat == "structure":
            intent = item.get("intent", "")
            plan = item.get("section_plan", [])
            plan_desc = " ➔ ".join([f"{p.get('section')}({p.get('sentences')}句/{p.get('words')}词)" for p in plan])
            print(f"  {i}. [{item_id}] 【{mastery}】 篇章结构: {intent}")
            print(f"     段落规划: {plan_desc}")

    print(f"=== 写作前知识库检索清单 (共 {len(all_picked)} 条，上限 {limit} 条，宁缺毋滥) ===\n")

    cnt = 1
    print("【一、本题可用已掌握】(唤醒个人知识库沉睡记忆，优先复用):")
    if pick_m:
        for it in pick_m:
            print_item(cnt, it)
            cnt += 1
    else:
        print("  (暂无已掌握条目，本次写作可学习新表达后沉淀入库)")
    print()

    print("【二、本题建议新学】(针对次段核心举措的外刊级高阶动词承重短语):")
    if pick_l:
        for it in pick_l:
            print_item(cnt, it)
            cnt += 1
    else:
        print("  (本题无需新学表达)")
    print()

    print("【三、本题建议结构/模板】(契合本题文类与受众权责的段落骨架):")
    if pick_t:
        for it in pick_t:
            print_item(cnt, it)
            cnt += 1
    else:
        print("  (参见文类标准 2-6-2 黄金视觉结构)")
    print()

def generate_item_id(target: str, item: dict, existing_records: list) -> str:
    if target == "task1":
        g = item.get("genre", "general").lower()
        code = GENRE_CODE_MAP.get(g, "GEN")
        cat = item.get("category", "functional_sentence")
        
        prefix = f"T1_{code}_"
        if cat == "template":
            prefix = f"T1_{code}_TMP_"
        elif cat == "structure":
            prefix = f"T1_{code}_STR_"

        max_seq = 0
        for r in existing_records:
            cid = r.get("id", "")
            if cid.startswith(prefix):
                m = re.search(r"(\d+)$", cid)
                if m:
                    max_seq = max(max_seq, int(m.group(1)))
        return f"{prefix}{max_seq + 1:03d}"
    else:
        sc = item.get("scenario", "")
        code = SCENARIO_CODE_MAP.get(sc, "SCENE")
        prefix = f"M_{code}_"
        max_seq = 0
        for r in existing_records:
            cid = r.get("id", "")
            if cid.startswith(prefix):
                m = re.search(r"(\d+)$", cid)
                if m:
                    max_seq = max(max_seq, int(m.group(1)))
        return f"{prefix}{max_seq + 1:03d}"

def cmd_append(args):
    paths = get_paths()
    target = args.target.lower()

    if target not in ("task1", "shared"):
        print("[ERROR] --target must be 'task1' or 'shared'.", file=sys.stderr)
        sys.exit(1)

    data_str = args.data
    if not data_str and args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            data_str = f.read()
    elif not data_str:
        data_str = sys.stdin.read()

    if not data_str.strip():
        print("[ERROR] No data provided to append.", file=sys.stderr)
        sys.exit(1)

    try:
        new_data = json.loads(data_str)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON data: {e}", file=sys.stderr)
        sys.exit(1)

    items_to_add = new_data if isinstance(new_data, list) else [new_data]
    target_path = paths[target]
    if target == "shared" and not target_path.resolve().is_relative_to(paths["user_root"].resolve()):
        target = "task1"
        target_path = paths["task1"]
    current_records = read_jsonl(target_path)

    existing_ids = {r.get("id") for r in current_records if "id" in r}
    existing_keys = {r.get("dedup_key") for r in current_records if "dedup_key" in r}

    added_count = 0
    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for item in items_to_add:
        # P1-5: Check admission rules
        ok, reason = check_admission_rules(item)
        if not ok:
            print(f"[REJECT] 条目准入校验未通过: {reason} | item={item.get('intent', item.get('intent_cn', ''))}")
            continue

        raw_key = item.get("expression") or item.get("verb_phrase") or item.get("intent") or ""
        key = normalize_key(raw_key)
        item["dedup_key"] = key

        # Deduplication
        if key and key in existing_keys:
            print(f"[SKIP] 条目已存在，跳过防重: {key}")
            continue

        # ID generation
        if not item.get("id"):
            item["id"] = generate_item_id(target, item, current_records)

        if "mastery" not in item:
            item["mastery"] = "未接触"
        if "mastery_note" not in item:
            item["mastery_note"] = ""
        if "version" not in item:
            item["version"] = 1
        if "status" not in item:
            item["status"] = "active"
        if "section" not in item:
            item["section"] = "body"
        if "register" not in item:
            item["register"] = "neutral_formal"
        if "exam_band" not in item:
            item["exam_band"] = "大纲内"

        if "history" not in item or not isinstance(item["history"], dict):
            item["history"] = {
                "recommended_count": 0,
                "used_count": 0,
                "last_used": None,
                "used_in_tasks": [],
                "independent_use_count": 0,
                "error_use_count": 0,
                "consecutive_recommended_no_use": 0,
                "user_notes": ""
            }

        if "status_evidence" not in item:
            item["status_evidence"] = {"last_promotion_reason": "", "last_evidence_task_id": ""}

        current_records.append(item)
        existing_ids.add(item["id"])
        if key:
            existing_keys.add(key)
        added_count += 1

        log_history(paths, "append", item["id"], None, item, "New item admission", getattr(args, "task_id", "") or "")
        print(f"[ADDED] 成功录入: [{item['id']}] {item.get('intent', item.get('intent_cn', ''))}")

    if added_count > 0:
        write_jsonl(target_path, current_records)
        print(f"[OK] 成功追加 {added_count} 条条目至 {target_path.name}。")
    else:
        print("[INFO] 未有新条目写入。")

def cmd_batch_update(args):
    if getattr(args, "example", False):
        example_spec = {
            "task_id": "T2011-E2-ADV",
            "status_updates": [
                {
                    "id": "T1_ADV_001",
                    "status": "敢用",
                    "note": "本篇实战用对",
                    "independent": True
                }
            ],
            "new_items": [
                {
                    "target": "task1",
                    "data": {
                        "category": "phrase",
                        "genre": "advice",
                        "section": "body",
                        "register": "neutral_formal",
                        "intent": "提前接触、初步了解某领域（替代 learn about 的平铺表达）",
                        "verb_phrase": "gain exposure to [field]",
                        "expression": "gain exposure to [field]",
                        "pattern": "it is never too early to gain exposure to [field]",
                        "slots": {
                            "[field]": "要提前接触的领域（专业/职场/文化等）"
                        },
                        "source": "2011英二建议信实战·高级版升华",
                        "tags": ["建议信", "动词承重"],
                        "exam_band": "大纲内",
                        "mastery": "学习中",
                        "mastery_note": ""
                    }
                },
                {
                    "target": "task1",
                    "data": {
                        "category": "functional_sentence",
                        "genre": "advice",
                        "section": "body",
                        "register": "neutral_formal",
                        "intent": "双重否定式强调：推动对方尽早采取行动并给出收益",
                        "expression": "It is never too early to [action], which will undoubtedly help you [benefit].",
                        "slots": {
                            "[action]": "尽早该做的动作（动词短语）",
                            "[benefit]": "预期益处（动词短语）"
                        },
                        "source": "2011英二建议信实战·高级版升华",
                        "tags": ["建议信", "功能句"],
                        "exam_band": "大纲内",
                        "mastery": "学习中"
                    }
                }
            ]
        }
        print(json.dumps(example_spec, ensure_ascii=False, indent=2))
        return

    paths = get_paths()

    raw_data = args.data
    if not raw_data and args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            raw_data = f.read()
    elif not raw_data:
        raw_data = sys.stdin.read()

    if not raw_data.strip():
        print("[ERROR] No batch data provided.", file=sys.stderr)
        sys.exit(1)

    try:
        batch_spec = json.loads(raw_data)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON for batch-update: {e}", file=sys.stderr)
        sys.exit(1)

    task_id = getattr(args, "task_id", "") or batch_spec.get("task_id", "")
    status_updates = batch_spec.get("status_updates", [])
    new_items = batch_spec.get("new_items", [])

    print(f"=== 开始批量更新知识库外脑 (待更新状态: {len(status_updates)} 条, 待录入新条目: {len(new_items)} 条, task_id='{task_id}') ===")

    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Process status updates
    if status_updates:
        task1_records = read_jsonl(paths["task1"])
        shared_records = read_jsonl(paths["shared"])
        is_shared_writable = paths["shared"].resolve().is_relative_to(paths["user_root"].resolve())
        updated_count = 0

        for upd in status_updates:
            t_id = upd.get("id", "").strip()
            proposed_st = upd.get("status", "").strip()
            note = upd.get("note", "")
            is_independent = upd.get("independent", False)
            is_error = upd.get("error", False)

            if not t_id or proposed_st not in MASTERY_RANK:
                continue

            found = False
            # Check task1 first
            for rec in task1_records:
                if rec.get("id") == t_id:
                    old_st = rec.get("mastery", "未接触")
                    hist = rec.setdefault("history", {
                        "recommended_count": 0, "used_count": 0, "last_used": None,
                        "used_in_tasks": [], "independent_use_count": 0, "error_use_count": 0,
                        "consecutive_recommended_no_use": 0, "user_notes": ""
                    })

                    used_tasks = set(hist.get("used_in_tasks", []))
                    if task_id:
                        used_tasks.add(task_id)
                        hist["used_in_tasks"] = sorted(list(used_tasks))

                    hist["last_used"] = now_iso
                    hist["used_count"] = hist.get("used_count", 0) + 1

                    # P1-2: Mastery evidence model
                    actual_st = proposed_st
                    if is_error or "瑕疵" in note or "用错" in note:
                        hist["error_use_count"] = hist.get("error_use_count", 0) + 1
                        actual_st = "敢用"
                        rec["mastery_note"] = "需注意"
                    elif is_independent:
                        hist["independent_use_count"] = hist.get("independent_use_count", 0) + 1
                        if len(used_tasks) >= 2 or hist["independent_use_count"] >= 1:
                            actual_st = "稳定"
                            rec["mastery_note"] = ""
                        else:
                            actual_st = "敢用"
                    else:
                        if actual_st == "稳定":
                            actual_st = "敢用"

                    rec["mastery"] = actual_st
                    rec["version"] = rec.get("version", 1) + 1

                    evidence = rec.setdefault("status_evidence", {})
                    evidence["last_promotion_reason"] = f"{actual_st}: {note}"
                    evidence["last_evidence_task_id"] = task_id

                    if note:
                        prev = hist.get("user_notes", "")
                        hist["user_notes"] = f"{prev}; [{now_iso}] {note}".strip("; ")

                    log_history(paths, "update_status", t_id, old_st, actual_st, note, task_id)
                    print(f"  [STATUS] [{t_id}] {old_st} ➔ {actual_st} (独立={is_independent}, 批注={note})")
                    found = True
                    updated_count += 1
                    break

            # If not in task1, check shared
            if not found:
                for rec in shared_records:
                    if rec.get("id") == t_id:
                        old_st = rec.get("mastery", "未接触")
                        hist = rec.setdefault("history", {
                            "recommended_count": 0, "used_count": 0, "last_used": None,
                            "used_in_tasks": [], "independent_use_count": 0, "error_use_count": 0,
                            "consecutive_recommended_no_use": 0, "user_notes": ""
                        })

                        used_tasks = set(hist.get("used_in_tasks", []))
                        if task_id:
                            used_tasks.add(task_id)
                            hist["used_in_tasks"] = sorted(list(used_tasks))

                        hist["last_used"] = now_iso
                        hist["used_count"] = hist.get("used_count", 0) + 1

                        actual_st = proposed_st
                        if is_error or "瑕疵" in note or "用错" in note:
                            hist["error_use_count"] = hist.get("error_use_count", 0) + 1
                            actual_st = "敢用"
                            rec["mastery_note"] = "需注意"
                        elif is_independent:
                            hist["independent_use_count"] = hist.get("independent_use_count", 0) + 1
                            if len(used_tasks) >= 2 or hist["independent_use_count"] >= 1:
                                actual_st = "稳定"
                                rec["mastery_note"] = ""
                            else:
                                actual_st = "敢用"
                        else:
                            if actual_st == "稳定":
                                actual_st = "敢用"

                        rec["mastery"] = actual_st
                        rec["version"] = rec.get("version", 1) + 1

                        evidence = rec.setdefault("status_evidence", {})
                        evidence["last_promotion_reason"] = f"{actual_st}: {note}"
                        evidence["last_evidence_task_id"] = task_id

                        if note:
                            prev = hist.get("user_notes", "")
                            hist["user_notes"] = f"{prev}; [{now_iso}] {note}".strip("; ")

                        log_history(paths, "update_status", t_id, old_st, actual_st, note, task_id)
                        print(f"  [STATUS] [{t_id}] {old_st} ➔ {actual_st} (独立={is_independent}, 批注={note})")
                        if not is_shared_writable:
                            # Promote into task1 expressions to protect read-only base
                            task1_records.append(rec)
                        found = True
                        updated_count += 1
                        break

        write_jsonl(paths["task1"], task1_records)
        if is_shared_writable:
            write_jsonl(paths["shared"], shared_records)
        print(f"[OK] 已成功更新 {updated_count} 条条目的掌握度状态。")

    # 2. Process new items
    if new_items:
        task1_records = read_jsonl(paths["task1"])
        shared_records = read_jsonl(paths["shared"])
        is_shared_writable = paths["shared"].resolve().is_relative_to(paths["user_root"].resolve())
        added_task1 = 0
        added_shared = 0

        existing_keys = {r.get("dedup_key") for r in task1_records + shared_records if "dedup_key" in r}

        for item_wrapper in new_items:
            target = item_wrapper.get("target", "task1").lower()
            item = item_wrapper.get("data", item_wrapper)

            ok, reason = check_admission_rules(item)
            if not ok:
                print(f"  [REJECT] 准入失败: {reason} | {item.get('intent', item.get('intent_cn', ''))}")
                continue

            raw_key = item.get("expression") or item.get("verb_phrase") or item.get("intent") or ""
            key = normalize_key(raw_key)
            item["dedup_key"] = key

            if key and key in existing_keys:
                print(f"  [SKIP] 条目已存在，跳过: {key}")
                continue

            if not is_shared_writable and target == "shared":
                target = "task1"

            if not item.get("id"):
                item["id"] = generate_item_id(target, item, task1_records if target == "task1" else shared_records)

            if "mastery" not in item:
                item["mastery"] = "学习中"
            if "mastery_note" not in item:
                item["mastery_note"] = ""
            if "version" not in item:
                item["version"] = 1
            if "status" not in item:
                item["status"] = "active"
            if "section" not in item:
                item["section"] = "body"
            if "register" not in item:
                item["register"] = "neutral_formal"
            if "exam_band" not in item:
                item["exam_band"] = "大纲内"
            if "genre" in item:
                item["genre"] = normalize_genre(item["genre"])

            used_in = [task_id] if task_id else []
            if "history" not in item or not isinstance(item["history"], dict):
                item["history"] = {
                    "recommended_count": 0, "used_count": 1, "last_used": now_iso,
                    "used_in_tasks": used_in, "independent_use_count": 0, "error_use_count": 0,
                    "consecutive_recommended_no_use": 0, "user_notes": "阶段3沉淀入库"
                }

            if "status_evidence" not in item:
                item["status_evidence"] = {
                    "last_promotion_reason": "阶段3用户确认入库",
                    "last_evidence_task_id": task_id
                }

            if target == "task1":
                task1_records.append(item)
                added_task1 += 1
                existing_keys.add(key)
                log_history(paths, "batch_append", item["id"], None, item, "Batch new item", task_id)
                print(f"  [NEW] 追加至 task1: [{item['id']}] {item.get('intent', '')} ({item.get('mastery', '')})")
            else:
                shared_records.append(item)
                added_shared += 1
                existing_keys.add(key)
                log_history(paths, "batch_append", item["id"], None, item, "Batch new morpheme", task_id)
                print(f"  [NEW] 追加至 shared: [{item['id']}] {item.get('intent_cn', '')} ({item.get('mastery', '')})")

        if added_task1 > 0:
            write_jsonl(paths["task1"], task1_records)
        if added_shared > 0 and is_shared_writable:
            write_jsonl(paths["shared"], shared_records)
        print(f"[OK] 批量录入完成：追加 task1 条目 {added_task1} 条，shared 条目 {added_shared} 条。")

def cmd_update_status(args):
    paths = get_paths()
    target_id = args.id.strip()
    new_status = args.status.strip()

    if new_status not in MASTERY_RANK:
        print(f"[ERROR] 无效状态: '{new_status}'。必须为: {list(MASTERY_RANK.keys())}", file=sys.stderr)
        sys.exit(1)

    updated = False
    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    task1_records = read_jsonl(paths["task1"])
    shared_records = read_jsonl(paths["shared"])
    is_shared_writable = paths["shared"].resolve().is_relative_to(paths["user_root"].resolve())

    # Check task1 first
    for rec in task1_records:
        if rec.get("id") == target_id:
            old_status = rec.get("mastery", "未接触")
            rec["mastery"] = new_status
            rec["version"] = rec.get("version", 1) + 1
            hist = rec.setdefault("history", {
                "recommended_count": 0, "used_count": 0, "last_used": None,
                "used_in_tasks": [], "independent_use_count": 0, "error_use_count": 0,
                "consecutive_recommended_no_use": 0, "user_notes": ""
            })
            hist["last_used"] = now_iso
            if args.increment_used:
                hist["used_count"] = hist.get("used_count", 0) + 1
            if args.increment_recommended:
                hist["recommended_count"] = hist.get("recommended_count", 0) + 1
            if args.note:
                prev_notes = hist.get("user_notes", "")
                hist["user_notes"] = f"{prev_notes}; [{now_iso}] {args.note}".strip("; ")

            log_history(paths, "update_status", target_id, old_status, new_status, args.note or "", "")
            write_jsonl(paths["task1"], task1_records)
            print(f"[OK] 成功更新条目 [{target_id}]: 状态 {old_status} -> {new_status} (来源: {paths['task1'].name})")
            updated = True
            break

    # If not found in task1, check shared
    if not updated:
        for rec in shared_records:
            if rec.get("id") == target_id:
                old_status = rec.get("mastery", "未接触")
                rec["mastery"] = new_status
                rec["version"] = rec.get("version", 1) + 1
                hist = rec.setdefault("history", {
                    "recommended_count": 0, "used_count": 0, "last_used": None,
                    "used_in_tasks": [], "independent_use_count": 0, "error_use_count": 0,
                    "consecutive_recommended_no_use": 0, "user_notes": ""
                })
                hist["last_used"] = now_iso
                if args.increment_used:
                    hist["used_count"] = hist.get("used_count", 0) + 1
                if args.increment_recommended:
                    hist["recommended_count"] = hist.get("recommended_count", 0) + 1
                if args.note:
                    prev_notes = hist.get("user_notes", "")
                    hist["user_notes"] = f"{prev_notes}; [{now_iso}] {args.note}".strip("; ")

                log_history(paths, "update_status", target_id, old_status, new_status, args.note or "", "")
                if is_shared_writable:
                    write_jsonl(paths["shared"], shared_records)
                    print(f"[OK] 成功更新条目 [{target_id}]: 状态 {old_status} -> {new_status} (来源: {paths['shared'].name})")
                else:
                    task1_records.append(rec)
                    write_jsonl(paths["task1"], task1_records)
                    print(f"[OK] 成功提升并更新条目 [{target_id}]: 状态 {old_status} -> {new_status} (已同步保存至用户外脑: {paths['task1'].name})")
                updated = True
                break

    if not updated:
        print(f"[ERROR] 未找到 ID 为 '{target_id}' 的条目。", file=sys.stderr)
        sys.exit(1)

def cmd_archive(args):
    if getattr(args, "example", False):
        print("""# 范文归档命令使用示例：
python3 scripts/kb_manager.py archive \\
  --title "2011英二建议信·祝贺cousin Li Ming考入大学并给出入学前准备建议" \\
  --genre "advice" \\
  --year "2011" \\
  --exam-type "英二" \\
  --task-id "T2011-E2-ADV" \\
  --file /tmp/archive.md \\
  --metadata '{"absorbed_items": ["T1_ADV_005 gain exposure to", "T1_ADV_006 navigate path"]}'

# 说明：若 --metadata 中省略 word_count，系统将自动基于 /tmp/archive.md 的正文计算词数。""")
        return

    paths = get_paths()
    archives_dir = paths["archives"]
    archives_dir.mkdir(parents=True, exist_ok=True)

    title = args.title.strip()
    genre = normalize_genre(args.genre) if args.genre else "general"
    task_id = getattr(args, "task_id", None) or f"T{datetime.datetime.now().strftime('%Y%m%d%H%M')}"
    exam_type = getattr(args, "exam_type", None) or "考研小作文"

    # Year handling: default to exam year if given, else current year
    year = args.year.strip() if args.year else str(datetime.datetime.now().year)

    content = args.content
    if not content and args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            content = f.read()
    elif not content:
        content = sys.stdin.read()

    if not content.strip():
        print("[ERROR] Archive content cannot be empty.", file=sys.stderr)
        sys.exit(1)

    metadata = {}
    if getattr(args, "metadata_file", None):
        try:
            with open(args.metadata_file, "r", encoding="utf-8") as mf:
                metadata = json.load(mf)
        except Exception as e:
            print(f"[WARN] Failed to load metadata from file: {e}", file=sys.stderr)
    elif args.metadata:
        try:
            metadata = json.loads(args.metadata)
        except Exception:
            pass

    date_str = datetime.datetime.now().strftime("%Y%m%d")
    title_safe = re.sub(r'[\\/*?:"<>| \t\n]', "_", title)[:40]
    filename = f"{date_str}_{year}_{genre}_{title_safe}.md"
    target_file = archives_dir / filename

    absorbed_items = metadata.get("absorbed_items", [])

    if "word_count" not in metadata:
        # Extract body essay text before any markdown headers or dividing rules
        essay_chunk = re.split(r'\n(?=#{1,3}\s|---|===)', content)[0].strip()
        raw_lines = [l.strip() for l in essay_chunk.splitlines() if l.strip()]
        if raw_lines:
            candidate_lines = raw_lines[1:] if re.match(r'^(dear\b|to\b|notice\b|announcement\b)', raw_lines[0], re.I) else raw_lines[:]
            signoff_patterns = [
                r'^(best\s+wishes|kind\s+regards|best\s+regards|warmest\s+regards|yours\s+sincerely|sincerely\s+yours|yours\s+faithfully|yours\s+truly|sincerely|regards|warm\s+regards|yours)[,\.]?$',
                r'^(li\s+ming|zhang\s+wei|wang\s+hua)[,\.]?$',
                r'^(the\s+student\s+union|postgraduate\s+association)[,\.]?$'
            ]
            while candidate_lines and any(re.match(p, candidate_lines[-1], re.I) for p in signoff_patterns):
                candidate_lines.pop()
            metadata["word_count"] = sum(len(p.split()) for p in candidate_lines)

    doc_lines = [
        f"# 考研英语小作文满意范文归档",
        "",
        f"- **题目**：{title}",
        f"- **任务编号**：{task_id}",
        f"- **试卷类型**：{exam_type}",
        f"- **年份**：{year}",
        f"- **文类**：{genre}",
        f"- **归档时间**：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]

    if "word_count" in metadata:
        doc_lines.append(f"- **字数统计**：{metadata['word_count']} 词")

    if absorbed_items and isinstance(absorbed_items, list):
        doc_lines.append("")
        doc_lines.append("## 本篇吸收沉淀的知识点")
        for item_info in absorbed_items:
            doc_lines.append(f"- {item_info}")

    doc_lines.append("")
    doc_lines.append("---")
    doc_lines.append("")
    doc_lines.append("## 终版高分范文")
    doc_lines.append("")
    doc_lines.append(content.strip())
    doc_lines.append("")

    with open(target_file, "w", encoding="utf-8") as f:
        f.write("\n".join(doc_lines))

    # P1-1: Record in tasks.jsonl
    tasks_file = paths["tasks"]
    tasks_file.parent.mkdir(parents=True, exist_ok=True)
    task_entry = {
        "task_id": task_id,
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "exam_type": exam_type,
        "year": year,
        "genre": genre,
        "prompt": title,
        "status": "已归档",
        "archived_path": str(target_file).replace("\\", "/"),
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    with open(tasks_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(task_entry, ensure_ascii=False) + "\n")

    print(f"[OK] 范文已成功归档至: {target_file}")
    print(f"[OK] 题目台账已同步至: {tasks_file}")

def cmd_session(args):
    paths = get_paths()
    sessions_dir = paths["sessions"]
    sessions_dir.mkdir(parents=True, exist_ok=True)

    task_id = args.task_id.strip()
    session_file = sessions_dir / f"{task_id}.json"

    session_data = {
        "task_id": task_id,
        "exam_type": getattr(args, "exam_type", "考研英语"),
        "year": getattr(args, "year", ""),
        "genre": getattr(args, "genre", ""),
        "phase": args.phase,
        "basic_versions": [],
        "advanced_versions": [],
        "events": []
    }
    if session_file.exists():
        try:
            with open(session_file, "r", encoding="utf-8") as f:
                session_data = json.load(f)
        except Exception:
            pass

    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = args.content or ""
    diff = args.diff or []

    if args.phase == "basic":
        v_num = len(session_data.get("basic_versions", [])) + 1
        session_data["basic_versions"].append({
            "v": v_num,
            "content": content,
            "diff_from_prev": diff,
            "ts": now_iso
        })
    elif args.phase == "advanced":
        v_num = len(session_data.get("advanced_versions", [])) + 1
        session_data["advanced_versions"].append({
            "v": v_num,
            "content": content,
            "diff_from_prev": diff,
            "ts": now_iso
        })

    session_data["events"].append({
        "ts": now_iso,
        "type": f"{args.phase}_update",
        "note": args.note or ""
    })

    with open(session_file, "w", encoding="utf-8") as f:
        json.dump(session_data, f, ensure_ascii=False, indent=2)

    print(f"[OK] 会话记录已更新: {session_file}")

def cmd_cleanup(args):
    paths = get_paths()
    print("=== 开始知识库体检与定期清理评估 ===")

    task1_records = read_jsonl(paths["task1"])
    shared_records = read_jsonl(paths["shared"])
    is_shared_writable = paths["shared"].resolve().is_relative_to(paths["user_root"].resolve())

    dormant_candidates = []
    retired_candidates = []

    for rec in task1_records + shared_records:
        r_id = rec.get("id")
        hist = rec.get("history", {})
        rec_count = hist.get("recommended_count", 0)
        used_count = hist.get("used_count", 0)
        consec_no_use = hist.get("consecutive_recommended_no_use", 0)
        status = rec.get("status", "active")

        if status == "active" and consec_no_use >= 3 and used_count == 0:
            dormant_candidates.append(r_id)
        if status in ("active", "dormant") and consec_no_use >= 6 and used_count == 0:
            retired_candidates.append(r_id)

    print(f"• 建议转为休眠 (dormant) 条目: {len(dormant_candidates)} 条")
    for cid in dormant_candidates[:5]:
        print(f"  - {cid}")
    print(f"• 建议软删除退役 (retired) 条目: {len(retired_candidates)} 条")
    for cid in retired_candidates[:5]:
        print(f"  - {cid}")

    if args.apply:
        updated = 0
        for rec in task1_records + shared_records:
            if rec.get("id") in retired_candidates:
                rec["status"] = "retired"
                updated += 1
            elif rec.get("id") in dormant_candidates and rec.get("status") == "active":
                rec["status"] = "dormant"
                updated += 1
        write_jsonl(paths["task1"], task1_records)
        if is_shared_writable:
            write_jsonl(paths["shared"], shared_records)
        print(f"[OK] 已应用清理策略，状态流转 {updated} 条。")
    else:
        print("[INFO] 本次为试运行，添加 --apply 可实际执行软删除与降权。")

def cmd_verify(args):
    paths = get_paths()
    print(f"=== 开始严格校验知识库 ===\n• 教研底座: {paths['base_root']}\n• 用户外脑: {paths['user_root']}")

    has_error = False
    total_valid = 0

    # 1. Verify task1_expressions.jsonl
    t1_path = paths["task1"]
    if not t1_path.exists():
        print(f"[FAIL] {t1_path.name} 文件不存在！", file=sys.stderr)
        has_error = True
    else:
        seen_ids = set()
        t1_records = []
        with open(t1_path, "r", encoding="utf-8") as f:
            for l_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    t1_records.append((l_num, json.loads(line)))
                except json.JSONDecodeError as e:
                    print(f"[FAIL] {t1_path.name}:{l_num} JSON格式解析错误: {e}", file=sys.stderr)
                    has_error = True

        for l_num, rec in t1_records:
            r_id = rec.get("id")
            if not r_id:
                print(f"[FAIL] {t1_path.name}:{l_num} 缺少必填字段: id", file=sys.stderr)
                has_error = True
            elif r_id in seen_ids:
                print(f"[FAIL] {t1_path.name}:{l_num} ID重复: {r_id}", file=sys.stderr)
                has_error = True
            else:
                seen_ids.add(r_id)

            cat = rec.get("category")
            if cat not in VALID_CATEGORIES:
                print(f"[FAIL] {t1_path.name}:{l_num} [{r_id}] 非法 category: {cat}", file=sys.stderr)
                has_error = True

            m = rec.get("mastery")
            if m not in MASTERY_RANK:
                print(f"[FAIL] {t1_path.name}:{l_num} [{r_id}] 非法 mastery: {m}", file=sys.stderr)
                has_error = True

            st = rec.get("status", "active")
            if st not in VALID_STATUSES:
                print(f"[FAIL] {t1_path.name}:{l_num} [{r_id}] 非法 status: {st}", file=sys.stderr)
                has_error = True

            if not rec.get("source"):
                print(f"[FAIL] {t1_path.name}:{l_num} [{r_id}] 缺少必填字段: source", file=sys.stderr)
                has_error = True

        print(f"[{'PASS' if not has_error else 'WARN'}] task1 ({t1_path.name}): 校验完成，有效记录 {len(t1_records)} 条。")
        total_valid += len(t1_records)

    # 2. Verify shared/scenario_morphemes.jsonl
    sh_path = paths["shared"]
    if not sh_path.exists():
        print(f"[FAIL] {sh_path.name} 文件不存在！", file=sys.stderr)
        has_error = True
    else:
        seen_ids = set()
        sh_records = []
        with open(sh_path, "r", encoding="utf-8") as f:
            for l_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    sh_records.append((l_num, json.loads(line)))
                except json.JSONDecodeError as e:
                    print(f"[FAIL] {sh_path.name}:{l_num} JSON格式解析错误: {e}", file=sys.stderr)
                    has_error = True

        for l_num, rec in sh_records:
            r_id = rec.get("id")
            if not r_id:
                print(f"[FAIL] {sh_path.name}:{l_num} 缺少必填字段: id", file=sys.stderr)
                has_error = True
            elif r_id in seen_ids:
                print(f"[FAIL] {sh_path.name}:{l_num} ID重复: {r_id}", file=sys.stderr)
                has_error = True
            else:
                seen_ids.add(r_id)

            if not rec.get("scenario"):
                print(f"[FAIL] {sh_path.name}:{l_num} [{r_id}] 缺少必填字段: scenario", file=sys.stderr)
                has_error = True
            if not rec.get("verb_phrase"):
                print(f"[FAIL] {sh_path.name}:{l_num} [{r_id}] 缺少必填字段: verb_phrase", file=sys.stderr)
                has_error = True

        print(f"[{'PASS' if not has_error else 'WARN'}] shared ({sh_path.name}): 校验完成，有效记录 {len(sh_records)} 条。")
        total_valid += len(sh_records)

    # 3. Verify anchors/task1_past_papers.jsonl
    anc_path = paths["anchors"]
    if not anc_path.exists():
        print(f"[FAIL] {anc_path.name} 文件不存在！", file=sys.stderr)
        has_error = True
    else:
        seen_ids = set()
        anc_records = []
        with open(anc_path, "r", encoding="utf-8") as f:
            for l_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    anc_records.append((l_num, json.loads(line)))
                except json.JSONDecodeError as e:
                    print(f"[FAIL] {anc_path.name}:{l_num} JSON格式解析错误: {e}", file=sys.stderr)
                    has_error = True

        for l_num, rec in anc_records:
            r_id = rec.get("id")
            if not r_id or r_id in seen_ids:
                print(f"[FAIL] {anc_path.name}:{l_num} ID缺失或重复: {r_id}", file=sys.stderr)
                has_error = True
            seen_ids.add(r_id)

            for req_field in ("genre", "relationship", "register", "prompt", "official_model", "register_analysis"):
                if not rec.get(req_field):
                    print(f"[FAIL] {anc_path.name}:{l_num} [{r_id}] 缺少必填字段: {req_field}", file=sys.stderr)
                    has_error = True

        print(f"[{'PASS' if not has_error else 'WARN'}] anchors ({anc_path.name}): 校验完成，有效记录 {len(anc_records)} 条。")
        total_valid += len(anc_records)

    # 4. Verify satisfaction archives
    arch_dir = paths["archives"]
    if arch_dir.exists():
        md_files = list(arch_dir.glob("*.md"))
        print(f"[PASS] archives ({arch_dir.parent.name}/{arch_dir.name}): 包含 {len(md_files)} 篇满意归档作文。")

    if has_error:
        print(f"\n[FAIL] 知识库验证失败！请修复以上列出的错误。", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"\n=== 验证通过！共计有效条目: {total_valid} 条 ===")
        sys.exit(0)

def cmd_check_essay(args):
    content = None
    if getattr(args, "file", None):
        fpath = Path(args.file).expanduser().resolve()
        if not fpath.exists():
            print(f"[ERROR] 指定的文件不存在: {args.file}", file=sys.stderr)
            sys.exit(1)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
    elif getattr(args, "text", None):
        content = args.text
    else:
        content = sys.stdin.read()

    if not content or not content.strip():
        print("[ERROR] 作文内容不能为空。", file=sys.stderr)
        sys.exit(1)

    raw_lines = [l.strip() for l in content.strip().splitlines() if l.strip()]
    if not raw_lines:
        print("[ERROR] 未检测到有效文本内容。", file=sys.stderr)
        sys.exit(1)

    salutation = None
    signoff = []

    # Salutation detector
    first_line = raw_lines[0]
    if re.match(r'^(dear\b|to\b|notice\b|announcement\b)', first_line, re.IGNORECASE):
        salutation = first_line
        candidate_lines = raw_lines[1:]
    else:
        candidate_lines = raw_lines[:]

    # Signoff detector (from the bottom)
    signoff_patterns = [
        r'^(best\s+wishes|kind\s+regards|best\s+regards|warmest\s+regards|yours\s+sincerely|sincerely\s+yours|yours\s+faithfully|yours\s+truly|sincerely|regards|warm\s+regards|yours)[,\.]?$',
        r'^(li\s+ming|zhang\s+wei|wang\s+hua)[,\.]?$',
        r'^(the\s+student\s+union|postgraduate\s+association)[,\.]?$'
    ]

    while candidate_lines:
        last = candidate_lines[-1]
        is_signoff = False
        for pat in signoff_patterns:
            if re.match(pat, last, re.IGNORECASE):
                is_signoff = True
                break
        if is_signoff:
            signoff.insert(0, candidate_lines.pop())
        else:
            break

    body_paragraphs = candidate_lines

    # Word counts
    p_counts = [len(p.split()) for p in body_paragraphs]
    body_total = sum(p_counts)
    total_words = len(content.split())

    # Ratios
    ratios = [round(c / body_total * 10, 1) if body_total > 0 else 0 for c in p_counts]
    ratio_str = " : ".join(str(r) for r in ratios) if ratios else "无"

    # Contraction check
    contraction_pattern = re.compile(
        r"\b([a-zA-Z]+'([a-zA-Z]{1,2}))\b",
        re.IGNORECASE
    )
    contractions_found = []
    for line_no, line in enumerate(content.splitlines(), 1):
        for m in contraction_pattern.finditer(line):
            contractions_found.append((line_no, m.group(0)))

    # Exclamation check
    exclamation_count = content.count("!")

    # Format checks
    format_issues = []
    if salutation:
        if salutation.endswith(":") or salutation.endswith("："):
            format_issues.append(f"称呼误用冒号（'{salutation}'），考研公文一律使用英文半角逗号")
        elif salutation.endswith("，"):
            format_issues.append(f"称呼误用中文全角逗号（'{salutation}'），必须使用英文半角逗号")
        elif not salutation.endswith(","):
            format_issues.append(f"称呼末尾缺少英文逗号（'{salutation}'）")

    for s_line in signoff:
        if re.match(r'^(best\s+wishes|kind\s+regards|best\s+regards|warmest\s+regards|yours\s+sincerely|sincerely\s+yours|yours\s+faithfully)', s_line, re.IGNORECASE):
            if not s_line.endswith(","):
                format_issues.append(f"结语敬语缺少英文逗号（'{s_line}'）")
        if re.match(r'^(li\s+ming)', s_line, re.IGNORECASE):
            if s_line.endswith("."):
                format_issues.append(f"署名误加句号（'{s_line}'），署名严禁加句号")

    # Word count safety assessment
    wc_status = "PASS"
    if 100 <= body_total <= 120:
        wc_desc = f"【严格通过】正文 {body_total} 词，处于 100~120 词黄金满分安全区间"
    elif body_total < 100:
        wc_status = "WARN"
        wc_desc = f"【偏少风险】正文 {body_total} 词（不足 100 词），建议适度丰富次段支撑细节"
    elif body_total <= 130:
        wc_status = "WARN"
        wc_desc = f"【偏多微险】正文 {body_total} 词（略超 120 词），建议执行减法精炼"
    else:
        wc_status = "FAIL"
        wc_desc = f"【严重超标】正文 {body_total} 词（已超出 120 词安全线），务必执行减法得分律替换精简"

    p_detail = " | ".join(f"P{i+1}: {c} 词" for i, c in enumerate(p_counts))

    if args.json:
        res = {
            "paragraph_counts": p_counts,
            "body_total": body_total,
            "total_words": total_words,
            "ratios": ratios,
            "word_count_status": wc_status,
            "contractions": contractions_found,
            "exclamations": exclamation_count,
            "format_issues": format_issues
        }
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    print("==================== 作文质量与 7 项硬指标预检报告 ====================")
    print(f"• 正文分段词数: {p_detail if p_detail else '未分段'}")
    print(f"• 正文总词数: {body_total} 词 (全篇含称呼落款: {total_words} 词)")
    print(f"• 词数安全判定: {wc_desc}")
    print(f"• 视觉比例诊断: {ratio_str} (基准参考: 2-6-2 黄金视觉律)")

    if contractions_found:
        items_str = ", ".join(f"L{ln}: '{w}'" for ln, w in contractions_found)
        print(f"• 口语缩写扫描: [FAIL] 发现 {len(contractions_found)} 处口语缩写 ({items_str})，公文严禁缩写！")
    else:
        print("• 口语缩写扫描: [PASS] 0 处口语缩写（严格通过）")

    if exclamation_count > 0:
        print(f"• 感叹号扫描: [FAIL] 发现 {exclamation_count} 处感叹号，考研公文严禁感叹号！")
    else:
        print("• 感叹号扫描: [PASS] 0 处感叹号（严格通过）")

    if format_issues:
        print(f"• 格式与标点扫描: [FAIL] 发现 {len(format_issues)} 处格式瑕疵:")
        for iss in format_issues:
            print(f"  - {iss}")
    else:
        print("• 格式与标点扫描: [PASS] 称呼逗号、结尾敬语与署名规范全部合规")

    print("======================================================================")

def cmd_init(args):
    force_reset = getattr(args, "reset", False)
    target_dir = None
    if getattr(args, "dir", None):
        target_dir = Path(args.dir).expanduser().resolve()
    user_root = init_user_brain(user_brain_dir=target_dir, force_reset=force_reset)
    paths = get_paths(user_brain_dir=user_root)
    print("==================== 考研小作文写作外脑初始化报告 ====================")
    print(f"• 教研底座目录 (只读): {paths['base_root']}")
    print(f"• 用户外脑目录 (读写): {paths['user_root']}")
    print(f"• 执行动作: {'【格式化重置】出厂纯净播种' if force_reset else '【安全初始化】就绪探测'}")
    t1_count = len(read_jsonl(paths["task1"]))
    sh_count = len(read_jsonl(paths["shared"]))
    anc_count = len(read_jsonl(paths["anchors"]))
    print(f"• 表达库 (task1_expressions.jsonl): {t1_count} 条 (就绪)")
    print(f"• 场景语素库 (scenario_morphemes.jsonl): {sh_count} 条 (只读底座)")
    print(f"• 历年真题标尺库 (task1_past_papers.jsonl): {anc_count} 篇 (只读底座)")
    print(f"• 范文归档目录: {paths['archives']}")
    print(f"• 题目台账路径: {paths['tasks']}")
    print(f"• 外脑健康状态: [PASS] 状态正常，已与 Skill 目录完全解耦并安全持久化！")
    print("======================================================================")

def cmd_status(args):
    paths = get_paths()
    print("==================== 考研英语小作文系统运行状态 ====================")
    print(f"• 教研底座路径: {paths['base_root']}")
    print(f"• 用户外脑路径: {paths['user_root']}")
    user_root_str = str(paths['user_root']).replace("\\", "/")
    if "/mounts/" in user_root_str:
        storage_type = "OpenMinis 外部挂载存储 (/var/minis/mounts/Documents/...)"
    elif "/storage/emulated" in user_root_str or "/sdcard" in user_root_str:
        storage_type = "Android 原生公共文档存储 (/storage/emulated/0/Documents/...)"
    elif "/workspace" in user_root_str:
        storage_type = "OpenMinis 沙盒持久工作区 (/var/minis/workspace/...)"
    elif "Documents" in user_root_str:
        storage_type = "PC / 宿主机用户文档目录 (Documents/...)"
    else:
        storage_type = "本地开发/单测环境兜底存储"
    print(f"• 外脑存储类型: {storage_type}")

    t1_records = read_jsonl(paths["task1"])
    sh_records = read_jsonl(paths["shared"])
    anc_records = read_jsonl(paths["anchors"])

    mastery_counts = {"稳定": 0, "敢用": 0, "学习中": 0, "未接触": 0}
    for r in t1_records:
        m = r.get("mastery", "未接触")
        mastery_counts[m] = mastery_counts.get(m, 0) + 1

    print(f"• 个人词句外脑总数: {len(t1_records)} 条")
    print(f"  - 掌握度分布: 稳定={mastery_counts['稳定']} | 敢用={mastery_counts['敢用']} | 学习中={mastery_counts['学习中']} | 未接触={mastery_counts['未接触']}")
    print(f"• 场景语素底座: {len(sh_records)} 条")
    print(f"• 历年真题标尺: {len(anc_records)} 篇 (英一 2005-2025 全量双范文原生支持)")

    tasks = read_jsonl(paths["tasks"])
    arch_files = list(paths["archives"].glob("*.md")) if paths["archives"].exists() else []
    print(f"• 满意范文归档: {len(arch_files)} 篇")
    print(f"• 练习台账记录: {len(tasks)} 条")

    meta_file = paths["user_root"] / ".kb_meta.json"
    if meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
                print(f"• 外脑初始化时间: {meta.get('initialized_at', '未知')}")
        except Exception:
            pass
    print("======================================================================")

def main():
    parser = argparse.ArgumentParser(description="Kaoyan Writing KB Manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Initialize or reset external user brain")
    p_init.add_argument("--reset", action="store_true", help="Force format and reset user brain to clean factory seed")
    p_init.add_argument("--dir", type=str, default=None, help="Explicit target directory for user brain")

    # status
    subparsers.add_parser("status", help="Show system status and knowledge base routing")

    # query
    p_query = subparsers.add_parser("query", help="Query expressions/morphemes")
    p_query.add_argument("--genre", type=str, default=None, help="Essay genre (e.g. advice, reply_letter, notice)")
    p_query.add_argument("--scenario", type=str, default=None, help="Scenario keyword")
    p_query.add_argument("--status", type=str, default=None, help="Filter by mastery status")
    p_query.add_argument("--section", type=str, default=None, help="Filter by section (opening, body, closing)")
    p_query.add_argument("--limit", type=int, default=5, help="Max items to return (default: 5)")
    p_query.add_argument("--type", type=str, default="all", choices=["all", "task1", "shared"], help="Knowledge domain")
    p_query.add_argument("--json", action="store_true", help="Output as JSON")

    # append
    p_append = subparsers.add_parser("append", help="Append new entries to KB")
    p_append.add_argument("--target", type=str, required=True, choices=["task1", "shared"], help="Target store")
    p_append.add_argument("--data", type=str, default=None, help="JSON string of entry or list of entries")
    p_append.add_argument("--file", type=str, default=None, help="Path to JSON file")
    p_append.add_argument("--task-id", type=str, default=None, help="Current task ID")

    # update-status
    p_upd = subparsers.add_parser("update-status", help="Update entry mastery status")
    p_upd.add_argument("--id", type=str, required=True, help="Entry ID (e.g. T1_ADV_001)")
    p_upd.add_argument("--status", type=str, required=True, choices=["未接触", "学习中", "敢用", "稳定"], help="New mastery status")
    p_upd.add_argument("--note", type=str, default=None, help="User note")
    p_upd.add_argument("--increment-used", action="store_true", help="Increment used count")
    p_upd.add_argument("--increment-recommended", action="store_true", help="Increment recommended count")

    # anchor
    p_anchor = subparsers.add_parser("anchor", help="Query official past paper model essay anchor")
    p_anchor.add_argument("--genre", type=str, default=None, help="Genre (e.g. advice, reply_letter, invitation)")
    p_anchor.add_argument("--year", type=str, default=None, help="Exam year (optional)")
    p_anchor.add_argument("--exam-type", type=str, default=None, help="Filter by exam type ('English I', 'English II', '英一', '英二')")
    p_anchor.add_argument("--limit", type=str, default=None, help="Max number of anchors to return (default: 1 when querying by genre, or 'all')")
    p_anchor.add_argument("--full", action="store_true", help="Include full official model essay text (internal use only)")
    p_anchor.add_argument("--model-version", choices=["all", "1", "2"], default="all", help="Select model version for exams supporting dual models (1: 高级范文, 2: 满分习作, all: 完整展示)")
    p_anchor.add_argument("--json", action="store_true", help="Output as JSON")

    # prompt
    p_prompt = subparsers.add_parser(
        "prompt",
        help="Query official past paper prompt, directions, key points and rubrics (strictly omits model essays)"
    )
    p_prompt.add_argument("--genre", type=str, default=None, help="Genre (e.g. advice, reply_letter, invitation)")
    p_prompt.add_argument("--year", type=str, default=None, help="Exam year (optional)")
    p_prompt.add_argument("--exam-type", type=str, default=None, help="Filter by exam type ('1', '2', '英一', '英二', 'English I', 'English II')")
    p_prompt.add_argument("--json", action="store_true", help="Output as JSON")

    # batch-update
    batch_epilog = """
JSON Payload Schema for batch-update:
{
  "task_id": "T2011-E2-ADV",
  "status_updates": [
    {"id": "T1_ADV_001", "status": "学习中|敢用|稳定", "note": "...", "independent": true}
  ],
  "new_items": [
    {
      "target": "task1",
      "data": {
        "category": "phrase|functional_sentence|structure|template|word",
        "genre": "advice|...",
        "section": "opening|body|closing",
        "register": "neutral_formal|informal_peer",
        "intent": "中文功能意图",
        "verb_phrase": "核心动宾短语 (phrase 必填或由 expression 回退)",
        "expression": "表达文本或骨架",
        "slots": {"[slot]": "说明"},
        "source": "出处说明",
        "exam_band": "大纲内",
        "mastery": "学习中|敢用|稳定"
      }
    }
  ]
}
Run 'python3 scripts/kb_manager.py batch-update --example' to print a complete ready-to-use template.
"""
    p_batch = subparsers.add_parser(
        "batch-update",
        help="Batch update statuses and append new entries",
        epilog=batch_epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p_batch.add_argument("--data", type=str, default=None, help="JSON string for batch update")
    p_batch.add_argument("--file", type=str, default=None, help="JSON file path for batch update")
    p_batch.add_argument("--task-id", type=str, default=None, help="Current task ID")
    p_batch.add_argument("--example", action="store_true", help="Print complete example JSON payload and exit")

    # archive
    arch_epilog = """
Archive Metadata Schema (--metadata JSON string or --metadata-file):
{
  "word_count": 109,  # Optional: automatically computed from essay body if omitted!
  "absorbed_items": [
    "T1_ADV_005 gain exposure to [field]",
    "T1_ADV_006 navigate one's career path"
  ]
}
Run 'python3 scripts/kb_manager.py archive --example' to print an example command.
"""
    p_arch = subparsers.add_parser(
        "archive",
        help="Archive 10/10 model essay as markdown",
        epilog=arch_epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p_arch.add_argument("--title", type=str, default=None, help="Essay title/prompt description")
    p_arch.add_argument("--genre", type=str, default="general", help="Genre name")
    p_arch.add_argument("--year", type=str, default=None, help="Exam year")
    p_arch.add_argument("--task-id", type=str, default=None, help="Task ID")
    p_arch.add_argument("--exam-type", type=str, default="考研英语", help="Exam type (e.g. 英一, 英二)")
    p_arch.add_argument("--content", type=str, default=None, help="Markdown content")
    p_arch.add_argument("--file", type=str, default=None, help="File containing markdown content")
    p_arch.add_argument("--metadata", type=str, default=None, help="JSON string with metadata")
    p_arch.add_argument("--metadata-file", type=str, default=None, help="File containing JSON metadata")
    p_arch.add_argument("--example", action="store_true", help="Print archive command usage example and exit")

    # session
    p_sess = subparsers.add_parser("session", help="Record session version progression")
    p_sess.add_argument("--task-id", type=str, required=True, help="Task ID")
    p_sess.add_argument("--phase", type=str, required=True, choices=["basic", "advanced"], help="Writing phase")
    p_sess.add_argument("--content", type=str, default="", help="Draft content")
    p_sess.add_argument("--diff", nargs="*", default=[], help="Differences from previous version")
    p_sess.add_argument("--note", type=str, default="", help="Event note")

    # cleanup
    p_clean = subparsers.add_parser("cleanup", help="Evaluate items for dormancy or retirement")
    p_clean.add_argument("--apply", action="store_true", help="Apply cleanup recommendations")

    # check-essay
    p_check = subparsers.add_parser("check-essay", help="Quick check essay word count, 2-6-2 ratio and 7 hard indicators")
    p_check.add_argument("--text", type=str, default=None, help="Essay text content")
    p_check.add_argument("--file", type=str, default=None, help="File containing essay text")
    p_check.add_argument("--genre", type=str, default="letter", help="Essay genre (default: letter)")
    p_check.add_argument("--json", action="store_true", help="Output as JSON")

    # verify
    subparsers.add_parser("verify", help="Verify syntax and integrity of JSONL databases")

    args = parser.parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "query":
        cmd_query(args)
    elif args.command == "prompt":
        cmd_prompt(args)
    elif args.command == "anchor":
        cmd_anchor(args)
    elif args.command == "append":
        cmd_append(args)
    elif args.command == "batch-update":
        cmd_batch_update(args)
    elif args.command == "update-status":
        cmd_update_status(args)
    elif args.command == "archive":
        cmd_archive(args)
    elif args.command == "session":
        cmd_session(args)
    elif args.command == "cleanup":
        cmd_cleanup(args)
    elif args.command == "check-essay":
        cmd_check_essay(args)
    elif args.command == "verify":
        cmd_verify(args)

if __name__ == "__main__":
    main()
