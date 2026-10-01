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
import copy
import argparse
import datetime
import re
from pathlib import Path

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

EXAM_TYPE_ALIASES = {
    "1": "English I", "英一": "English I", "英语一": "English I", "考研英语一": "English I",
    "eng1": "English I", "english1": "English I", "english 1": "English I",
    "english i": "English I", "i": "English I",
    "2": "English II", "英二": "English II", "英语二": "English II", "考研英语二": "English II",
    "eng2": "English II", "english2": "English II", "english 2": "English II",
    "english ii": "English II", "ii": "English II",
}

def normalize_exam_type(exam_type, default: str = "考研小作文") -> str:
    """归一化试卷类型，统一归档 / 台账 / 词本章节取值（English I / English II）。

    仅收敛明确的英一/英二写法，其余原样保留（例如自拟题、考研英语、英二模拟卷等）。
    """
    if exam_type is None:
        return default
    raw = str(exam_type).strip()
    if not raw:
        return default
    return EXAM_TYPE_ALIASES.get(raw.lower(), raw)

def _anchor_sort_key(rec: dict):
    """锚点排序键：真题优先，年份降序（非真题/N-A 年份排最后）。"""
    year = str(rec.get("year", "") or "")
    return (
        1 if rec.get("is_real_exam", True) else 0,
        int(year) if year.isdigit() else -1,
    )


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

VALID_CATEGORIES = {"word", "phrase", "sentence", "functional_sentence", "template", "structure", "morpheme"}
VALID_STATUSES = {"active", "dormant", "retired"}
VALID_REGISTERS = {"informal_peer", "neutral_formal", "formal_authority", "public_notice"}
VALID_SECTIONS = {"opening", "body", "closing", "format", "any"}

def test_writable_dir(target_path_str: str) -> bool:
    """真实探测目录可写性（支持创建临时父目录并执行写入测试）

    注意：本函数会真实建目录，仅供 init / --reset 等显式创建流程使用。
    路径探测阶段必须改用 exists_writable_dir，避免"探测即建库"的副作用。
    """
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

def exists_writable_dir(target_path_str: str) -> bool:
    """零副作用探测：只接受"已存在且可写"的目录，绝不创建任何路径。

    这是"PC 侧必须保持完全干净"的技术保障：外部外脑只在已真实存在时被采用，
    否则宁可回落到规范挂载路径等待显式 init，也不许凭空建库。
    """
    try:
        p = Path(target_path_str)
        return p.is_dir() and os.access(p, os.W_OK)
    except Exception:
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
    5. PC / 桌面系统用户文档目录（仅当该外脑目录已真实存在时才采用）

    硬约束：全部探测均为零副作用（不建目录、不写探测文件），且绝不回退到
    <skill>/knowledge_base —— 权威外脑在用户安卓设备上，PC 侧必须保持完全干净。
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
            if exists_writable_dir(cand):
                return Path(cand)

        # Open Minis 官方 workspace 降级
        minis_ws = "/var/minis/workspace/考研英语/写作外脑"
        if os.path.exists("/var/minis/workspace"):
            if exists_writable_dir(minis_ws):
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
            if exists_writable_dir(cand):
                return Path(cand)

    # 4. PC / 常规系统的用户文档目录
    #    严格零副作用：仅在用户已手工创建该外脑目录时才采用（不再探测即建库）。
    #    权威外脑在用户安卓设备上；PC 侧保持完全干净是硬约束。
    try:
        home = Path.home()
        pc_docs = home / "Documents" / "考研英语" / "写作外脑"
        if exists_writable_dir(str(pc_docs)):
            return pc_docs
    except Exception:
        pass

    # 5. 无任何已存在的外脑：返回规范挂载路径的纯值，不做任何创建。
    #    绝不回退到 <skill>/knowledge_base —— 那会让用户沉淀覆盖只读教研底座。
    return Path("/var/minis/mounts/Documents/考研英语/写作外脑")

def get_base_dir() -> Path:
    """兼容旧接口"""
    return get_builtin_base_dir()

def init_user_brain(user_brain_dir: Path = None, force_reset: bool = False) -> Path:
    """初始化或格式化用户外脑目录（白纸化纯净就绪，绝不拷贝出厂种子）"""
    if user_brain_dir is None:
        user_brain_dir = get_user_brain_dir()

    if user_brain_dir.name == "user_brain":
        ub_sub = user_brain_dir
    else:
        ub_sub = user_brain_dir / "user_brain"

    target_hist = ub_sub / "history.log"
    target_sess = ub_sub / "sessions"

    # 双仓结构（唯一权威表示）
    target_shared_dir = ub_sub / "shared"
    target_shared_morph = target_shared_dir / "morphemes.jsonl"

    target_t1_dir = ub_sub / "task1"
    target_t1_v2 = target_t1_dir / "expressions.jsonl"
    target_t1_tasks = target_t1_dir / "tasks.jsonl"

    # Archives target: 优先满意范文/task1
    if user_brain_dir.name == "写作外脑" or (user_brain_dir / "满意范文").exists() or not (ub_sub / "satisfaction_archives").exists():
        target_arch = user_brain_dir / "满意范文" / "task1"
    else:
        target_arch = ub_sub / "satisfaction_archives" / "task1"

    ub_sub.mkdir(parents=True, exist_ok=True)
    target_shared_dir.mkdir(parents=True, exist_ok=True)
    target_t1_dir.mkdir(parents=True, exist_ok=True)
    target_arch.mkdir(parents=True, exist_ok=True)
    target_sess.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. 纯净白纸初始化：shared morphemes 保持 0 记录
    if force_reset or not target_shared_morph.exists():
        with open(target_shared_morph, "w", encoding="utf-8") as f:
            pass

    # 2. 纯净白纸初始化：task1 expressions 保持 0 记录
    if force_reset or not target_t1_v2.exists():
        with open(target_t1_v2, "w", encoding="utf-8") as f:
            pass

    # 3. 题目台账（同一 task_id upsert）
    if force_reset or not target_t1_tasks.exists():
        with open(target_t1_tasks, "w", encoding="utf-8") as f:
            pass

    # 4. 审计流水日志
    if force_reset or not target_hist.exists():
        with open(target_hist, "a" if not force_reset and target_hist.exists() else "w", encoding="utf-8") as f:
            entry = {
                "ts": now_iso,
                "op": "init",
                "id": "SYS_INIT",
                "before": None,
                "after": "个人写作外脑已就绪（纯净白纸状态：0条条目）",
                "reason": "格式化重置并初始化纯净个人外脑" if force_reset else "初始化纯净个人外脑",
                "task_id": ""
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # 5. 标记外脑元数据
    meta_file = user_brain_dir / ".kb_meta.json"
    try:
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump({
                "initialized_at": now_iso,
                "version": "2.0.0",
                "storage_type": "external_mount" if "/mounts/" in str(user_brain_dir) else "local",
                "clean_factory": True,
                "decoupled_seeds": True
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return user_brain_dir

def get_paths(kb_dir: Path = None, base_kb_dir: Path = None, user_brain_dir: Path = None, ensure: bool = False) -> dict:
    """双根路由解析：只读教研底座资产 + 外部读写用户外脑

    ensure=False（默认）：纯解析，零副作用 —— 读命令（prompt/anchor/query/status/verify/check-essay）必须用此模式。
    ensure=True：写命令专用。外脑不存在时，仅当"位置被显式配置（环境变量）"或"该目录已真实存在"
                 才初始化；否则直接以非零码拒绝，绝不在用户机器上凭空建库（PC 侧保持完全干净的硬约束）。
    """
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
    if (user_brain_dir / "shared" / "morphemes.jsonl").exists() or (user_brain_dir / "task1" / "expressions.jsonl").exists():
        ub_sub = user_brain_dir
    elif (user_brain_dir / "user_brain").exists():
        ub_sub = user_brain_dir / "user_brain"
    elif user_brain_dir.name == "user_brain":
        ub_sub = user_brain_dir
    else:
        ub_sub = user_brain_dir / "user_brain"

    # 确定范文归档目录
    if (ub_sub / "task1" / "archive").exists():
        archives_dir = ub_sub / "task1" / "archive"
        archives_root = ub_sub / "task1"
    elif (user_brain_dir / "task1" / "archive").exists():
        archives_dir = user_brain_dir / "task1" / "archive"
        archives_root = user_brain_dir / "task1"
    elif (user_brain_dir / "满意范文" / "task1").exists():
        archives_dir = user_brain_dir / "满意范文" / "task1"
        archives_root = user_brain_dir / "满意范文"
    elif (ub_sub / "satisfaction_archives" / "task1").exists():
        archives_dir = ub_sub / "satisfaction_archives" / "task1"
        archives_root = ub_sub / "satisfaction_archives"
    elif (user_brain_dir / "satisfaction_archives" / "task1").exists():
        archives_dir = user_brain_dir / "satisfaction_archives" / "task1"
        archives_root = user_brain_dir / "satisfaction_archives"
    else:
        if (ub_sub / "task1").exists():
            archives_dir = ub_sub / "task1" / "archive"
            archives_root = ub_sub / "task1"
        elif user_brain_dir.name == "写作外脑" or (user_brain_dir / "满意范文").exists():
            archives_dir = user_brain_dir / "满意范文" / "task1"
            archives_root = user_brain_dir / "满意范文"
        else:
            archives_dir = ub_sub / "satisfaction_archives" / "task1"
            archives_root = ub_sub / "satisfaction_archives"

    # 统一以 v2 双仓布局为唯一写入表示；扁平单文件仅作只读兼容（历史外脑仍可见）
    t1_v2 = ub_sub / "task1" / "expressions.jsonl"
    t1_legacy = ub_sub / "task1_expressions.jsonl"
    tasks_v2 = ub_sub / "task1" / "tasks.jsonl"
    tasks_legacy = ub_sub / "tasks.jsonl"
    user_shared_path = ub_sub / "shared" / "morphemes.jsonl"

    # 注意：本函数默认绝不做任何写入或初始化。曾经在此隐式调用 init_user_brain，
    # 使 prompt/anchor/query/check-essay/status/verify 等纯读命令也会在用户机器上凭空建库。
    explicit_root = bool(
        os.environ.get("KAOYAN_WRITING_KB")
        or os.environ.get("KAOYAN_USER_BRAIN")
        or os.environ.get("KB_ROOT")
    )
    initialized = t1_v2.exists() or user_shared_path.exists()

    if ensure and not initialized:
        if explicit_root or exists_writable_dir(str(user_brain_dir)):
            init_user_brain(user_brain_dir, force_reset=False)
            initialized = True
        else:
            print(
                f"[ERROR] 个人外脑不存在且位置未经显式配置：{user_brain_dir}\n"
                f"        为避免在用户机器上凭空建库，已拒绝执行写操作。\n"
                f"        请先执行 `init` 显式初始化，或设置 KAOYAN_USER_BRAIN 指定外脑目录。",
                file=sys.stderr,
            )
            sys.exit(1)

    # 只读共享语素底座：唯一权威来源。
    # 原实现在此文件缺失时回退到 shared/scenario_morphemes.jsonl —— 那是同一批 ID
    # 的另一份 schema 副本（verb_phrase/history/... 用户字段），一旦被当成底座读取，
    # 会让"只读底座"混入用户态字段。该副本已删除，此处不再回退。
    seed_shared = base_kb_dir / "seeds" / "shared_morphemes.seed.jsonl"

    seed_t1 = base_kb_dir / "seeds" / "task1_expressions.seed.jsonl"
    if not seed_t1.exists():
        seed_t1 = base_kb_dir / "user_brain" / "task1_expressions.jsonl"

    return {
        "base_root": base_kb_dir,
        "user_root": user_brain_dir,
        "initialized": initialized,
        "user_root_explicit": explicit_root,
        # 只读教研底座（借调来源，严禁写入）
        "shared": seed_shared,
        "seed_shared": seed_shared,
        "seed_task1": seed_t1,
        "anchors": base_kb_dir / "anchors" / "task1_past_papers.jsonl",
        # 个人外脑写入目标（v2 规范路径）
        "task1": t1_v2,
        "user_task1": t1_v2,
        "tasks": tasks_v2,
        "user_task1_tasks": tasks_v2,
        "user_shared": user_shared_path,
        "history_log": ub_sub / "history.log",
        "kb_meta": user_brain_dir / ".kb_meta.json",
        "sessions": ub_sub / "sessions",
        "archives": archives_dir,
        "archives_root": archives_root,
        # 历史扁平布局：只读兼容，绝不再回写
        "task1_legacy": t1_legacy,
        "user_task1_legacy": t1_legacy,
        "tasks_legacy": tasks_legacy,
        "user_shared_legacy": ub_sub / "user_brain" / "shared" / "morphemes.jsonl"
        if (ub_sub / "user_brain" / "shared" / "morphemes.jsonl").exists()
        else ub_sub / "shared_morphemes.jsonl",
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


def is_builtin_path(target, paths: dict) -> bool:
    """判定目标是否落在只读教研底座内（anchors / seeds / 出厂语料）。

    教研底座是随包发布的静态资产，任何用户沉淀写入都会污染发布内容
    （历史上曾因此在个人外脑中堆出 55 条"出厂僵尸条目"，需要事后专门剥离），故一律拒绝。
    """
    if target is None:
        return False
    try:
        base = Path(paths.get("base_root") or "").resolve()
        return Path(target).resolve().is_relative_to(base)
    except Exception:
        return False


def write_store(paths: dict, key: str, records: list):
    """用户外脑唯一写入入口：拒绝写入只读教研底座。"""
    target = paths.get(key)
    if target is None:
        raise KeyError(f"未知的外脑仓库键: {key}")
    if is_builtin_path(target, paths):
        raise PermissionError(
            f"拒绝写入只读教研底座（{key} -> {target}）；用户沉淀必须落在个人外脑仓。"
        )
    write_jsonl(target, records)
    return target


def read_store(paths: dict, key: str) -> list:
    """读取用户仓：优先 v2 规范路径，兼容历史扁平单文件（只读，不再回写）。"""
    primary = paths.get(key)
    records = read_jsonl(primary) if primary else []
    if records:
        return records
    legacy = paths.get(f"{key}_legacy")
    if legacy and Path(legacy).exists():
        return read_jsonl(legacy)
    return records


def new_history(**overrides) -> dict:
    """统一的 history 骨架，避免多处字面量漂移。"""
    hist = {
        "recommended_count": 0,
        "used_count": 0,
        "last_used": None,
        "used_in_tasks": [],
        "independent_use_count": 0,
        "error_use_count": 0,
        "consecutive_recommended_no_use": 0,
        "user_notes": "",
    }
    hist.update(overrides)
    return hist

def is_id_match(id1: str, id2: str) -> bool:
    if not id1 or not id2:
        return False
    id1_s = str(id1).strip()
    id2_s = str(id2).strip()
    if id1_s == id2_s:
        return True
    s1 = re.sub(r'_(SEN|TMP|STR)_', '_', id1_s)
    s2 = re.sub(r'_(SEN|TMP|STR)_', '_', id2_s)
    return s1 == s2

def save_user_task1(paths: dict, records: list):
    """写入个人小作文专属仓（v2 唯一规范路径）。

    历史实现会同时回写扁平单文件，导致同一数据两份表示静默分叉；
    现统一走 v2，扁平文件降级为只读兼容（read_store）。
    """
    return write_store(paths, "user_task1", records)


def save_user_shared(paths: dict, records: list):
    """写入个人共享语素仓（v2 唯一规范路径），底座种子永远只读。"""
    return write_store(paths, "user_shared", records)

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
    cat = item.get("category") or item.get("type") or "functional_sentence"
    if cat not in VALID_CATEGORIES:
        return False, f"Invalid category: {cat}. Must be one of {sorted(list(VALID_CATEGORIES))}"

    # 1. Reusability: must contain slots or be template/structure
    if cat in ("functional_sentence", "sentence"):
        expr = item.get("text") or item.get("expression", "")
        if not re.search(r"\[.*?\]", expr) and not item.get("slots"):
            return False, "Not reusable: functional_sentence/sentence expression lacks slots [x] or variable placeholders."
    elif cat in ("template", "structure"):
        pass
    elif cat in ("word", "phrase", "morpheme"):
        if not item.get("verb_phrase") and not item.get("term") and not item.get("pattern") and not item.get("text"):
            if item.get("expression"):
                item["verb_phrase"] = item["expression"]
            else:
                return False, "Word/phrase missing head term, verb_phrase or expression."
        if not item.get("verb_phrase") and item.get("text"):
            item["verb_phrase"] = item["text"]

    # 2. Source and intent required
    if not item.get("source"):
        return False, "Missing required field: source"
    if not item.get("intent") and not item.get("intent_cn") and not item.get("meaning"):
        return False, "Missing required field: intent/intent_cn"

    # 3. Exam band check
    band = str(item.get("exam_band", "大纲内")).strip()
    if band in ("考纲核心", "大纲词汇", "核心词汇", "大纲", "core"):
        band = "大纲内"
        item["exam_band"] = "大纲内"
    if band not in ("大纲内", "超纲"):
        return False, f"Invalid exam_band: {band}. Must be '大纲内' or '超纲'"

    return True, "OK"

SALUTATION_RE = re.compile(r'^(dear\b|to\b|notice\b|announcement\b)', re.IGNORECASE)
SIGNOFF_PATTERNS = (
    r'^(best\s+wishes|kind\s+regards|best\s+regards|warmest\s+regards|yours\s+sincerely|sincerely\s+yours|yours\s+faithfully|yours\s+truly|sincerely|regards|warm\s+regards|yours)[,\.]?$',
    r'^(li\s+ming|zhang\s+wei|wang\s+hua)[,\.]?$',
    r'^(the\s+student\s+union|postgraduate\s+association)[,\.]?$',
)


def split_essay_body(content: str, strip_markdown_tail: bool = False) -> tuple:
    """切分作文为 (称呼行 | None, 正文段落列表, 敬语与署名行列表)。

    check-essay 与 archive 共用同一套切分规则。历史实现各自维护了一份完全相同的
    signoff 正则表，任何一侧调整都会让"词数"在预检与归档两处对不上。
    """
    text = content or ""
    if strip_markdown_tail:
        text = re.split(r'\n(?=#{1,3}\s|---|===)', text)[0]
    text = text.strip()
    raw_lines = [l.strip() for l in text.splitlines() if l.strip()]

    salutation = None
    if raw_lines and SALUTATION_RE.match(raw_lines[0]):
        salutation = raw_lines[0]
        candidate_lines = raw_lines[1:]
    else:
        candidate_lines = raw_lines[:]

    signoff = []
    while candidate_lines:
        last = candidate_lines[-1]
        if any(re.match(p, last, re.IGNORECASE) for p in SIGNOFF_PATTERNS):
            signoff.insert(0, candidate_lines.pop())
        else:
            break

    return salutation, candidate_lines, signoff


def cmd_anchor(args):
    paths = get_paths()
    anchors = read_jsonl(paths["anchors"])

    genre_target = normalize_genre(args.genre) if args.genre else None
    year_target = str(args.year).strip() if args.year else None
    exam_target_norm = normalize_exam_filter(getattr(args, "exam_type", None))

    if not genre_target and not year_target and not exam_target_norm:
        print("[ERROR] 请至少指定 --genre、--year 或 --exam-type 参数之一。", file=sys.stderr)
        return

    matches = filter_anchors(anchors, args.genre, args.year, getattr(args, "exam_type", None))

    if not matches:
        print(f"[ANCHOR] 未检索到匹配的官方真题范文 (genre={genre_target}, year={year_target})。")
        return

    # 统一排序：真题优先 + 年份降序。
    # 修复：原实现直接按 JSONL 文件顺序截断，却打印"已按最新年份展示"，
    # 导致 `anchor --genre advice --limit 1` 返回 2021 英一而拿不到 2024 英二。
    matches.sort(key=_anchor_sort_key, reverse=True)

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
        # source_file 指向创作期语料（docs/…），不随本包分发，打印原始路径会误导为可读文件
        if source_file and source_file != "N/A":
            print(f"• 真题出处: 创作期语料库 (authoring-side corpus)")

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
    """从 Directions 题干中提取官方指定署名。

    仅当题干明文给出替代署名时才返回该署名；题干未给出署名要求时，返回带括号的
    显式提示，绝不把"默认值"伪装成官方指定署名，以免与内置范文落款产生冲突。
    """
    if not prompt:
        return "未指定（题干缺失，需人工确认）"
    m = re.search(r'Use\s+["“]([^"”]+)["”]\s+instead', prompt, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m2 = re.search(r'sign\s+your\s+name\s+as\s+["“]([^"”]+)["”]', prompt, re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    if re.search(r'Do not\s+(?:use|sign)[^.]*?name', prompt, re.IGNORECASE):
        return "未指定（题干仅要求不得署真实姓名，通知/纪要类请署机构或职务名）"
    return "未指定（题干未给出署名要求，需人工确认）"

def lookup_mandated_signoff(year, exam_type, genre: str = None):
    """按年份/卷别（可带文类）从内置真题标尺查取题干法定署名。

    返回 (署名, 命中记录)。未命中返回 (None, None)；题干未给出具体署名时
    签名字段为 "未指定（...）" 形式的提示串，调用方需自行判别。
    """
    if not year and not exam_type:
        return None, None
    try:
        paths = get_paths()
        anchors = read_jsonl(paths["anchors"])
    except Exception:
        return None, None

    year_target = str(year).strip() if year else None
    exam_norm = normalize_exam_type(exam_type, default="") if exam_type else ""
    genre_target = normalize_genre(genre) if genre else None

    fallback = None
    for rec in anchors:
        if year_target and str(rec.get("year", "")) != year_target:
            continue
        if exam_norm and str(rec.get("exam_type", "")).strip().lower() != exam_norm.lower():
            continue
        if genre_target:
            if normalize_genre(rec.get("genre", "")) != genre_target:
                if fallback is None:
                    fallback = rec
                continue
        return extract_mandated_signoff(rec.get("prompt", "")), rec
    if fallback is not None:
        return extract_mandated_signoff(fallback.get("prompt", "")), fallback
    return None, None

def normalize_exam_filter(exam_type) -> str:
    """把用户/LLM 传入的卷别写法归一为锚点比对用的内部小写形式。

    统一复用 EXAM_TYPE_ALIASES，避免 anchor / prompt 各自维护一份重复的别名表。
    """
    if not exam_type:
        return ""
    raw = str(exam_type).strip().lower()
    mapped = EXAM_TYPE_ALIASES.get(raw)
    return mapped.lower() if mapped else raw


def filter_anchors(anchors: list, genre=None, year=None, exam_type=None) -> list:
    """按文类/年份/卷别过滤锚点；文类无硬命中时回退到题干与语域剖析的文本检索。

    安全约束：回退检索绝不检索 official_model，避免范文正文成为过滤依据。
    """
    genre_target = normalize_genre(genre) if genre else None
    year_target = str(year).strip() if year else None
    exam_target = normalize_exam_filter(exam_type)

    matches = []
    for item in anchors:
        item_genre = str(item.get("genre", "")).lower()
        item_year = str(item.get("year", ""))
        item_exam = str(item.get("exam_type", "")).lower()
        if genre_target and genre_target != item_genre and genre_target not in item_genre:
            continue
        if year_target and year_target != item_year:
            continue
        if exam_target:
            if exam_target in ("english i", "english ii"):
                if exam_target != item_exam:
                    continue
            elif exam_target not in item_exam:
                continue
        matches.append(item)

    if not matches and genre_target:
        for item in anchors:
            text = (
                f"{item.get('prompt', '')} {item.get('register_analysis', '')} "
                f"{' '.join(item.get('tags', []))}"
            ).lower()
            if genre_target in text:
                matches.append(item)
    return matches


def cmd_prompt(args):
    """
    专门为阶段 0/1（审题、零碎句诊断、三栏清单、基础版批改与偏题拦截）设计的题干调取接口。
    核心安全机制：数据投影（Projection），物理剔除官方范文与高能句式骨架，彻底杜绝阶段 1 上下文污染。
    """
    paths = get_paths()
    anchors = read_jsonl(paths["anchors"])

    genre_target = normalize_genre(args.genre) if args.genre else None
    year_target = str(args.year).strip() if args.year else None
    exam_target_norm = normalize_exam_filter(getattr(args, "exam_type", None))

    if not genre_target and not year_target and not exam_target_norm:
        print("[ERROR] 请至少指定 --year、--exam-type 或 --genre 参数之一。", file=sys.stderr)
        return

    matches = filter_anchors(anchors, args.genre, args.year, getattr(args, "exam_type", None))

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

def _expression_core_words(text: str) -> list:
    """把表达/句式骨架（含 [slot] 占位符）归一化为可匹配的实词序列。"""
    core = re.sub(r"\[[^\]]*\]", " ", text or "")
    core = re.sub(r"[^A-Za-z\s]", " ", core)
    return [w for w in core.lower().split() if w]


def _draft_normalized(draft: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z\s]", " ", draft or "").lower()).strip()


def _match_draft(core_words: list, draft_norm: str) -> str:
    """返回命中的片段描述；未命中返回空串。以 4 词/5 词/3 词连续片段做证据匹配。"""
    if not core_words or not draft_norm:
        return ""
    n = len(core_words)
    for span in (4, 5, 3):
        if n < span:
            continue
        for i in range(0, n - span + 1):
            frag = " ".join(core_words[i:i + span])
            if frag in draft_norm:
                return frag
    return ""


def _query_mine(args, paths: dict):
    """个人外脑全量检索（跨文类召回）：为阶段 1【外脑连接】与「我的外脑里有什么」提供事实依据。

    与默认三栏检索不同，本模式不做 genre / scenario 过滤，仅按「同文类优先 + 掌握度」分层，
    并把非本篇章文类的资产显式标记为 [跨文类复用]，避免学生已有积累被文类过滤器吞掉。
    """
    genre_filter = normalize_genre(args.genre) if getattr(args, "genre", None) else None
    section_filter = (getattr(args, "section", None) or "").lower().strip()
    limit = max(1, int(getattr(args, "limit", 20) or 20))

    records = []
    # 经 read_store 读取，兼容历史扁平布局（存量外脑不丢数据）
    records += read_store(paths, "user_task1")
    records += read_store(paths, "user_shared")

    draft_norm = ""
    match_file = getattr(args, "match_file", None)
    if match_file:
        try:
            with open(Path(match_file).expanduser(), "r", encoding="utf-8") as f:
                draft_norm = _draft_normalized(f.read())
        except Exception as e:
            print(f"[ERROR] 无法读取 --match-file: {e}", file=sys.stderr)
            sys.exit(1)

    same_genre, cross_genre, hits = [], [], []
    for rec in records:
        if rec.get("status") == "retired" or rec.get("exam_band") == "超纲":
            continue
        item_genre = normalize_genre(rec.get("genre", ""))
        if section_filter and section_filter not in ("all", "any"):
            item_sec = (rec.get("section") or "any").lower()
            if item_sec not in (section_filter, "any"):
                continue
        is_same = bool(genre_filter and item_genre == genre_filter) or item_genre in ("general", "common", "all", "shared", "")
        entry = {
            "id": rec.get("id", "N/A"),
            "mastery": rec.get("mastery", "未接触"),
            "genre": item_genre or "general",
            "section": rec.get("section", "body"),
            "category": rec.get("category") or rec.get("type") or "",
            "expression": rec.get("text") or rec.get("expression") or rec.get("verb_phrase") or "",
            "intent": rec.get("meaning") or rec.get("intent_cn") or rec.get("intent", ""),
            "cross_genre": not is_same,
        }
        if draft_norm:
            frag = _match_draft(_expression_core_words(entry["expression"]), draft_norm)
            if frag:
                entry["evidence"] = frag
                hits.append(entry)
                continue
        (same_genre if is_same else cross_genre).append(entry)

    rank = lambda e: MASTERY_RANK.get(e["mastery"], 1)
    hits.sort(key=rank, reverse=True)
    same_genre.sort(key=rank, reverse=True)
    cross_genre.sort(key=rank, reverse=True)

    selected = (hits + same_genre + cross_genre)[:limit]

    if getattr(args, "json", False):
        print(json.dumps({
            "hits": hits, "same_genre": same_genre, "cross_genre": cross_genre,
            "total_assets": len(records),
        }, ensure_ascii=False, indent=2))
        return

    print(f"=== 个人外脑全量检索 (跨文类召回) | 资产总数 {len(records)} 条 | 文类基准: {genre_filter or '未指定'} ===")
    if not records:
        print("  (个人外脑暂无任何资产，本篇无法复用；请在阶段 3 完成首次沉淀)")
        return
    if not selected:
        print("  (未检索到匹配条目)")
        return

    def dump(group_title, items):
        if not items:
            return
        print(f"\n{group_title}")
        for it in items:
            tag = " [跨文类复用]" if it["cross_genre"] else ""
            ev = f" | 命中片段: `{it['evidence']}`" if it.get("evidence") else ""
            print(f"  • [{it['id']}]{tag} 【{it['mastery']}】 {it['intent']}")
            print(f"    骨架: `{it['expression']}` | 文类: {it['genre']} | 段位: {it['section']}{ev}")

    dump("【一、初稿已实际命中】(建议在【外脑连接】中原样引用)", hits)
    dump("【二、同文类可复用】", same_genre)
    dump("【三、跨文类可复用】(他类信体积累的通用骨架，投诉/建议/道歉等可迁移)", cross_genre)
    if not hits:
        print("\n【提示】初稿未命中任何个人外脑资产，请如实说明，并从上面第二/三组中推荐 1~2 条建议激活项。")


def cmd_query(args):
    paths = get_paths()

    target_type = args.type.lower()
    genre_filter = normalize_genre(args.genre) if args.genre else None
    scenario_filter = args.scenario.lower().strip() if args.scenario else None
    status_filter = args.status.strip() if args.status else None
    section_filter = args.section.lower().strip() if getattr(args, "section", None) else None

    # 个人外脑全量检索模式（阶段 1【外脑连接】/「我的外脑里有什么」专用）
    if getattr(args, "mine", False):
        return _query_mine(args, paths)

    # Determine allowed scenarios for genre
    allowed_scenarios = set()
    if genre_filter and genre_filter in GENRE_TO_SCENARIOS:
        allowed_scenarios = set(GENRE_TO_SCENARIOS[genre_filter])

    limit = args.limit

    # =========================================================================
    # Tier 1: 个人外脑优先检索 (Tier 1: Personal User Brain Assets)
    # =========================================================================
    user_results = []
    user_keys = set()
    user_ids = set()
    seen_result_ids = set()
    seen_result_keys = set()

    # 1.1 读取个人小作文专属表达仓
    user_t1_items = []
    if target_type in ("all", "task1"):
        user_t1_items = read_store(paths, "user_task1")
        for item in user_t1_items:
            iid = item.get("id", "")
            raw_key = item.get("text") or item.get("expression") or item.get("intent", "")
            k = normalize_key(raw_key) if raw_key else ""
            if iid:
                user_ids.add(iid)
            if k:
                user_keys.add(k)

            # 过滤 retired 与超纲
            if item.get("status") == "retired" or item.get("exam_band") == "超纲":
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
                text_to_search = f"{item.get('intent', '')} {item.get('intent_cn', '')} {item.get('expression', '')} {item.get('text', '')} {item.get('verb_phrase', '')} {item.get('scenario', '')} {' '.join(item.get('tags', []))}".lower()
                if scenario_filter not in text_to_search:
                    continue

            if iid and iid in seen_result_ids:
                continue
            if k and k in seen_result_keys:
                continue
            if iid:
                seen_result_ids.add(iid)
            if k:
                seen_result_keys.add(k)

            # 外脑资产权重加成 (大幅优先于底座种子)
            score = 10.0
            if item_genre == genre_filter:
                score += 3.0
            score += MASTERY_RANK.get(item.get("mastery", "未接触"), 1)
            hist = item.get("history", {})
            if isinstance(hist, dict) and hist.get("error_use_count", 0) > 0:
                score -= 2.0
            if item.get("status") == "dormant":
                score -= 1.5

            item["_score"] = score
            item["source_tier"] = "user_brain"
            item["is_borrowed"] = False
            user_results.append(item)

    # 1.2 读取个人共享场景语素仓
    user_shared_items = []
    if target_type in ("all", "shared"):
        if paths["user_shared"].exists():
            user_shared_items = read_store(paths, "user_shared")
        for item in user_shared_items:
            iid = item.get("id", "")
            raw_key = item.get("text") or item.get("verb_phrase") or item.get("expression") or item.get("meaning", "")
            k = normalize_key(raw_key) if raw_key else ""
            if iid:
                user_ids.add(iid)
            if k:
                user_keys.add(k)

            if item.get("status") == "retired" or item.get("exam_band") == "超纲":
                continue

            item_scenario = str(item.get("scenario", "")).strip()
            if scenario_filter:
                text_to_search = f"{item_scenario} {item.get('meaning', '')} {item.get('intent_cn', '')} {item.get('verb_phrase', '')} {item.get('text', '')}".lower()
                if scenario_filter not in text_to_search:
                    continue
            elif genre_filter:
                if allowed_scenarios and item_scenario not in allowed_scenarios:
                    continue

            if status_filter and item.get("mastery") != status_filter:
                continue

            if section_filter and section_filter not in ("body", "any"):
                continue

            if iid and iid in seen_result_ids:
                continue
            if k and k in seen_result_keys:
                continue
            if iid:
                seen_result_ids.add(iid)
            if k:
                seen_result_keys.add(k)

            score = 10.0
            if allowed_scenarios and item_scenario in allowed_scenarios:
                score += 2.5
            score += MASTERY_RANK.get(item.get("mastery", "未接触"), 1)
            hist = item.get("history", {})
            if isinstance(hist, dict) and hist.get("error_use_count", 0) > 0:
                score -= 2.0
            if item.get("status") == "dormant":
                score -= 1.5

            item["_score"] = score
            item["source_tier"] = "user_brain"
            item["is_borrowed"] = False
            user_results.append(item)

    # 1.3 个人外脑三栏分类
    ub_mastered = []
    ub_to_learn = []
    ub_templates = []

    for item in user_results:
        m = item.get("mastery", "未接触")
        cat = item.get("category") or item.get("type") or ""
        caution = item.get("caution", False)
        if cat in ("template", "structure"):
            ub_templates.append(item)
        elif m in ("稳定", "敢用") and not caution:
            ub_mastered.append(item)
        else:
            ub_to_learn.append(item)

    ub_mastered.sort(key=lambda x: x.get("_score", 0), reverse=True)
    ub_to_learn.sort(key=lambda x: x.get("_score", 0), reverse=True)
    ub_templates.sort(key=lambda x: x.get("_score", 0), reverse=True)

    # 1.4 从个人外脑按配额提取
    pick_m = ub_mastered[:min(2, limit)]
    user_pick_t = ub_templates[:min(1, max(0, limit - len(pick_m)))]
    rem_for_learn = max(0, limit - len(pick_m) - len(user_pick_t))
    user_pick_l = ub_to_learn[:min(2, rem_for_learn)]

    # =========================================================================
    # Tier 2: 系统底座仅作缺额兜底借调 (Tier 2: System Base Borrowing on Deficit)
    # =========================================================================
    sys_pick_t = []
    sys_pick_l = []

    # 2.1 结构/模板缺额借调：当且仅当个人外脑在该文类下未积累任何模板/结构时借调
    target_templates_quota = min(1, max(0, limit - len(pick_m)))
    deficit_t = target_templates_quota - len(user_pick_t)
    if deficit_t > 0 and target_type in ("all", "task1"):
        seed_t1_items = read_jsonl(paths["seed_task1"])
        candidate_t = []
        for s_item in seed_t1_items:
            cat = s_item.get("category") or s_item.get("type") or ""
            if cat not in ("template", "structure"):
                continue
            item_genre = normalize_genre(s_item.get("genre", ""))
            if genre_filter and genre_filter != item_genre and item_genre not in ("general", "common", "all", "shared"):
                continue

            raw_k = normalize_key(s_item.get("text") or s_item.get("expression") or s_item.get("intent", ""))
            if raw_k in user_keys or s_item.get("id") in user_ids or s_item.get("id") in seen_result_ids:
                continue

            score = 1.0
            if item_genre == genre_filter:
                score += 3.0
            s_item["_score"] = score
            candidate_t.append(s_item)

        candidate_t.sort(key=lambda x: x.get("_score", 0), reverse=True)
        for t_item in candidate_t[:deficit_t]:
            t_item["source_tier"] = "system_seeds"
            t_item["is_borrowed"] = True
            sys_pick_t.append(t_item)

    pick_t = user_pick_t + sys_pick_t

    # 2.2 新学语素缺额借调：当且仅当个人外脑在新学语素上未凑满配额时借调
    rem_quota_l = max(0, limit - len(pick_m) - len(pick_t))
    target_l_quota = min(2, rem_quota_l)
    deficit_l = max(0, target_l_quota - len(user_pick_l))

    if deficit_l > 0:
        candidate_l = []

        # (a) 从共享场景语素底座检索
        if target_type in ("all", "shared"):
            seed_shared_items = read_jsonl(paths["seed_shared"])
            for s_item in seed_shared_items:
                if s_item.get("status") == "retired" or s_item.get("exam_band") == "超纲":
                    continue
                item_sc = str(s_item.get("scenario", "")).strip()
                if scenario_filter:
                    text_s = f"{item_sc} {s_item.get('meaning', '')} {s_item.get('intent_cn', '')} {s_item.get('verb_phrase', '')} {s_item.get('text', '')}".lower()
                    if scenario_filter not in text_s:
                        continue
                elif genre_filter:
                    if allowed_scenarios and item_sc not in allowed_scenarios:
                        continue

                raw_k = normalize_key(s_item.get("text") or s_item.get("verb_phrase") or s_item.get("meaning", ""))
                if raw_k in user_keys or s_item.get("id") in user_ids or s_item.get("id") in seen_result_ids:
                    continue

                score = 1.0
                if allowed_scenarios and item_sc in allowed_scenarios:
                    score += 2.5
                s_item["_score"] = score
                candidate_l.append(s_item)

        # (b) 从小作文功能句底座检索（若共享语素不足）
        if target_type in ("all", "task1"):
            seed_t1_items = read_jsonl(paths["seed_task1"])
            for s_item in seed_t1_items:
                cat = s_item.get("category") or s_item.get("type") or ""
                if cat in ("template", "structure"):
                    continue
                item_genre = normalize_genre(s_item.get("genre", ""))
                if genre_filter and genre_filter != item_genre and item_genre not in ("general", "common", "all", "shared"):
                    continue

                raw_k = normalize_key(s_item.get("text") or s_item.get("expression") or s_item.get("intent", ""))
                if raw_k in user_keys or s_item.get("id") in user_ids or s_item.get("id") in seen_result_ids:
                    continue

                score = 1.0
                if item_genre == genre_filter:
                    score += 2.0
                s_item["_score"] = score
                candidate_l.append(s_item)

        candidate_l.sort(key=lambda x: x.get("_score", 0), reverse=True)
        for l_item in candidate_l[:deficit_l]:
            l_item["source_tier"] = "system_seeds"
            l_item["is_borrowed"] = True
            sys_pick_l.append(l_item)

    pick_l = user_pick_l + sys_pick_l

    # 合并最终三栏条目
    all_picked = pick_m + pick_l + pick_t

    if args.json:
        all_picked.sort(key=lambda x: x.get("_score", 0), reverse=True)
        print(json.dumps(all_picked[:args.limit], ensure_ascii=False, indent=2))
        return

    if not all_picked:
        print(f"[KB] 未检索到匹配的条目 (genre={genre_filter}, scenario={scenario_filter}, status={status_filter})。")
        return

    def print_item(i, item):
        item_id = item.get("id", "N/A")
        mastery = item.get("mastery", "未接触")
        m_note = f"（{item.get('mastery_note')}）" if item.get("mastery_note") else ""
        cat = item.get("type") or item.get("category", "")
        reg = item.get("register", "neutral_formal")
        sec = item.get("section", "body")
        c_note = f" (注意: {item.get('caution_note')})" if item.get("caution_note") else ""
        borrowed_tag = " [系统借调]" if item.get("is_borrowed") else ""

        if cat == "functional_sentence":
            intent = item.get("meaning") or item.get("intent", "")
            expr = item.get("text") or item.get("expression", "")
            slots = item.get("slots", {})
            slots_desc = " | ".join([f"{k}: {v}" for k, v in slots.items()]) if slots else "无"
            print(f"  {i}. [{item_id}]{borrowed_tag} 【{mastery}{m_note}】 {intent}{c_note}")
            print(f"     表达骨架: `{expr}`")
            if slots:
                print(f"     槽位指引: {slots_desc}")
            print(f"     段位/语域: 段位: {sec} | 语域: {reg}")
        elif cat in ("phrase", "morpheme") or "verb_phrase" in item or item_id.startswith("M_"):
            scenario = item.get("scenario", "")
            intent_cn = item.get("meaning") or item.get("intent_cn", item.get("intent", ""))
            phrase = item.get("text") or item.get("verb_phrase") or item.get("expression", "")
            colloc_list = item.get("collocations") or item.get("typical_collocations", [])
            collocations = ", ".join(colloc_list) if isinstance(colloc_list, list) else str(colloc_list)
            print(f"  {i}. [{item_id}]{borrowed_tag} 【{mastery}{m_note}】 语素 ({scenario}): {intent_cn}{c_note}")
            print(f"     动宾短语: `{phrase}`")
            if collocations:
                print(f"     典型搭配: {collocations}")
            print(f"     段位/语域: 段位: {sec} | 语域: {reg}")
        elif cat == "template":
            intent = item.get("meaning") or item.get("intent", "")
            budget = item.get("word_budget", "100-110")
            print(f"  {i}. [{item_id}]{borrowed_tag} 【{mastery}】 篇章模板: {intent} (建议词数: {budget})")
            blocks = item.get("blocks", [])
            if blocks:
                preview = " / ".join([b.strip().replace('\n', ' ') for b in blocks[:3]])
                print(f"     骨架预览: `{preview}`")
        elif cat == "structure":
            intent = item.get("meaning") or item.get("intent", "")
            plan = item.get("section_plan", [])
            plan_desc = " ➔ ".join([f"{p.get('section')}({p.get('sentences')}句/{p.get('words')}词)" for p in plan]) if plan else ""
            print(f"  {i}. [{item_id}]{borrowed_tag} 【{mastery}】 篇章结构: {intent}")
            if plan_desc:
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
        cat = item.get("category") or item.get("type") or "functional_sentence"
        
        prefix = f"T1_{code}_"
        if cat == "template":
            prefix = f"T1_{code}_TMP_"
        elif cat == "structure":
            prefix = f"T1_{code}_STR_"
        elif cat in ("functional_sentence", "sentence"):
            prefix = f"T1_{code}_SEN_"

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
    paths = get_paths(ensure=True)
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
            item["history"] = new_history()

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
        if target == "task1":
            save_user_task1(paths, current_records)
        else:
            save_user_shared(paths, current_records)
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

    paths = get_paths(ensure=True)

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

    # 结构化执行结果：供 settle 判定真实成功/失败，杜绝"静默无操作却报成功"
    result = {
        "status_updates_applied": 0,
        "status_updates_unmatched": [],
        "status_updates_invalid": [],
        "new_items_added": [],
        "new_items_rejected": [],
        "new_items_skipped": [],
    }

    # 1. Process status updates
    if status_updates:
        task1_records = read_store(paths, "user_task1")
        user_shared_records = read_store(paths, "user_shared")
        # 只读借调来源：出厂底座（绝不可写）
        seed_shared_records = read_jsonl(paths["seed_shared"]) if paths["seed_shared"].exists() else []
        seed_t1_records = read_jsonl(paths["seed_task1"]) if paths["seed_task1"].exists() else []
        task1_touched = False
        shared_touched = False
        updated_count = 0

        for upd in status_updates:
            t_id = upd.get("id", "").strip()
            proposed_st = upd.get("status", "").strip()
            note = upd.get("note", "")
            is_independent = upd.get("independent", False)
            is_error = upd.get("error", False)

            if not t_id or proposed_st not in MASTERY_RANK:
                result["status_updates_invalid"].append(t_id or "<empty-id>")
                print(f"  [INVALID] 状态更新条目非法（id='{t_id}', status='{proposed_st}'），已忽略")
                continue

            found = False

            def apply_status_rec(rec, display_id):
                old_st = rec.get("mastery", "未接触")
                hist = rec.setdefault("history", new_history())

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

                log_history(paths, "update_status", display_id, old_st, actual_st, note, task_id)
                if actual_st != proposed_st:
                    print(f"  [STATUS] [{display_id}] {old_st} ➔ {actual_st}（提议 '{proposed_st}' 被晋级/纠偏规则改写，独立={is_independent}，批注={note}）")
                else:
                    print(f"  [STATUS] [{display_id}] {old_st} ➔ {actual_st} (独立={is_independent}, 批注={note})")
                result["status_updates_applied"] += 1

            # Check user task1 first
            for rec in task1_records:
                if is_id_match(rec.get("id"), t_id):
                    apply_status_rec(rec, t_id)
                    found = True
                    task1_touched = True
                    updated_count += 1
                    break

            # If not in task1, check user shared
            if not found and user_shared_records:
                for rec in user_shared_records:
                    if is_id_match(rec.get("id"), t_id):
                        apply_status_rec(rec, t_id)
                        found = True
                        shared_touched = True
                        updated_count += 1
                        break

            # If not found in user brain, check seed task1 (promote to user task1)
            if not found and seed_t1_records:
                for seed_rec in seed_t1_records:
                    if is_id_match(seed_rec.get("id"), t_id):
                        rec_copy = copy.deepcopy(seed_rec)
                        apply_status_rec(rec_copy, t_id)
                        task1_records.append(rec_copy)
                        found = True
                        task1_touched = True
                        updated_count += 1
                        break

            # If not found, check seed shared (promote into the personal shared warehouse)
            # 修复：原实现在 is_shared_writable 为真时直接 pass，而 rec_copy 是浅拷贝，
            # 导致嵌套 history 被改动、顶层 mastery 丢失，还被写回底座并汇报成功。
            if not found and seed_shared_records:
                for seed_rec in seed_shared_records:
                    if is_id_match(seed_rec.get("id"), t_id):
                        rec_copy = copy.deepcopy(seed_rec)
                        apply_status_rec(rec_copy, t_id)
                        user_shared_records.append(rec_copy)
                        found = True
                        shared_touched = True
                        updated_count += 1
                        break

            if not found:
                result["status_updates_unmatched"].append(t_id)
                print(f"  [MISS] 未在任何仓（个人 task1 / 个人 shared / 出厂底座）中定位到条目: {t_id}，掌握度未变更")

        # 只写真正被改动过的用户仓；底座永不写入
        if task1_touched:
            save_user_task1(paths, task1_records)
        if shared_touched:
            save_user_shared(paths, user_shared_records)
        result["status_updates_written"] = updated_count
        print(f"[OK] 已成功更新 {updated_count} 条条目的掌握度状态。")
        if result["status_updates_unmatched"]:
            print(f"[WARN] 有 {len(result['status_updates_unmatched'])} 条状态更新未命中: {', '.join(result['status_updates_unmatched'])}")

    # 2. Process new items
    if new_items:
        task1_records = read_store(paths, "user_task1")
        # 用户共享仓为累加基；出厂底座只用于防重比对，绝不作为写入目标
        user_shared_records = read_store(paths, "user_shared")
        seed_shared_records = read_jsonl(paths["shared"]) if paths["shared"].exists() else []
        added_task1 = 0
        added_shared = 0

        existing_keys = {
            r.get("dedup_key")
            for r in task1_records + user_shared_records + seed_shared_records
            if "dedup_key" in r
        }

        for item_wrapper in new_items:
            target = item_wrapper.get("target", "task1").lower()
            item = item_wrapper.get("data", item_wrapper)

            if not item.get("source"):
                item["source"] = f"{task_id} 实战沉淀" if task_id else "实战沉淀"

            ok, reason = check_admission_rules(item)
            if not ok:
                result["new_items_rejected"].append({"reason": reason, "intent": item.get("intent", item.get("intent_cn", ""))})
                print(f"  [REJECT] 准入失败: {reason} | {item.get('intent', item.get('intent_cn', ''))}")
                continue

            raw_key = item.get("expression") or item.get("verb_phrase") or item.get("intent") or ""
            key = normalize_key(raw_key)
            item["dedup_key"] = key

            if key and key in existing_keys:
                result["new_items_skipped"].append(key)
                print(f"  [SKIP] 条目已存在，跳过: {key}")
                continue

            cat = item.get("category") or item.get("type") or ""
            iid = str(item.get("id", ""))
            is_morph = (target == "shared" or iid.startswith("M_") or item.get("type") == "morpheme" or (cat in ["phrase", "word"] and not item.get("slots")))
            if is_morph:
                target = "shared"
            else:
                target = "task1"

            can_write_shared = paths["user_shared"].parent.exists()
            if not can_write_shared and target == "shared":
                # 用户共享仓不可用时降级到 task1，而不是回写只读底座
                print("  [WARN] 个人共享语素仓不可写，本条已改录至小作文专属仓 (task1)")
                target = "task1"

            if not item.get("id"):
                item["id"] = generate_item_id(target, item, task1_records if target == "task1" else user_shared_records)

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
            if not item.get("source"):
                item["source"] = f"{task_id} 实战沉淀" if task_id else "实战沉淀"

            used_in = [task_id] if task_id else []
            if "history" not in item or not isinstance(item["history"], dict):
                item["history"] = new_history(
                    used_count=1, last_used=now_iso, used_in_tasks=used_in,
                    user_notes="阶段3沉淀入库",
                )

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
                result["new_items_added"].append({"id": item["id"], "target": "task1"})
                print(f"  [NEW] 追加至 task1: [{item['id']}] {item.get('intent', '')} ({item.get('mastery', '')})")
            else:
                user_shared_records.append(item)
                added_shared += 1
                existing_keys.add(key)
                log_history(paths, "batch_append", item["id"], None, item, "Batch new morpheme", task_id)
                result["new_items_added"].append({"id": item["id"], "target": "shared"})
                print(f"  [NEW] 追加至 shared: [{item['id']}] {item.get('intent_cn', item.get('meaning', item.get('intent', '')))} ({item.get('mastery', '')})")

        if added_task1 > 0:
            save_user_task1(paths, task1_records)
        if added_shared > 0:
            save_user_shared(paths, user_shared_records)
        print(f"[OK] 批量录入完成：追加 task1 条目 {added_task1} 条，shared 条目 {added_shared} 条。")

    result["synced_task1"] = len([i for i in result["new_items_added"] if i.get("target") == "task1"])
    result["synced_shared"] = len([i for i in result["new_items_added"] if i.get("target") == "shared"])
    return result

def cmd_update_status(args):
    paths = get_paths(ensure=True)
    target_id = args.id.strip()
    new_status = args.status.strip()

    if new_status not in MASTERY_RANK:
        print(f"[ERROR] 无效状态: '{new_status}'。必须为: {list(MASTERY_RANK.keys())}", file=sys.stderr)
        sys.exit(1)

    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    task1_records = read_store(paths, "user_task1")
    user_shared_records = read_store(paths, "user_shared")
    # 只读借调来源：出厂底座（绝不可写）
    seed_shared_records = read_jsonl(paths["shared"]) if paths["shared"].exists() else []
    seed_t1_records = read_jsonl(paths["seed_task1"]) if paths["seed_task1"].exists() else []

    def apply(rec):
        old_status = rec.get("mastery", "未接触")
        rec["mastery"] = new_status
        rec["version"] = rec.get("version", 1) + 1
        hist = rec.setdefault("history", new_history())
        hist["last_used"] = now_iso
        if args.increment_used:
            hist["used_count"] = hist.get("used_count", 0) + 1
        if args.increment_recommended:
            hist["recommended_count"] = hist.get("recommended_count", 0) + 1
        if args.note:
            prev_notes = hist.get("user_notes", "")
            hist["user_notes"] = f"{prev_notes}; [{now_iso}] {args.note}".strip("; ")
        log_history(paths, "update_status", target_id, old_status, new_status, args.note or "", "")
        return old_status

    # 1. 个人小作文专属仓
    for rec in task1_records:
        if is_id_match(rec.get("id"), target_id):
            old_status = apply(rec)
            save_user_task1(paths, task1_records)
            print(f"[OK] 成功更新条目 [{target_id}]: 状态 {old_status} -> {new_status} (来源: {paths['task1'].name})")
            return

    # 2. 个人共享语素仓
    for rec in user_shared_records:
        if is_id_match(rec.get("id"), target_id):
            old_status = apply(rec)
            save_user_shared(paths, user_shared_records)
            print(f"[OK] 成功更新共享条目 [{target_id}]: 状态 {old_status} -> {new_status} (来源: {paths['user_shared'].name})")
            return

    # 3. 底座共享语素借调转正 -> 落入个人共享仓
    for seed_rec in seed_shared_records:
        if is_id_match(seed_rec.get("id"), target_id):
            rec_copy = copy.deepcopy(seed_rec)
            old_status = apply(rec_copy)
            user_shared_records.append(rec_copy)
            save_user_shared(paths, user_shared_records)
            print(f"[OK] 成功从底座借调转正条目 [{target_id}]: 状态 {old_status} -> {new_status} (已沉淀至个人共享仓: {paths['user_shared'].name})")
            return

    # 4. 底座小作文句式借调转正 -> 落入个人专属仓
    for seed_rec in seed_t1_records:
        if is_id_match(seed_rec.get("id"), target_id):
            rec_copy = copy.deepcopy(seed_rec)
            old_status = apply(rec_copy)
            task1_records.append(rec_copy)
            save_user_task1(paths, task1_records)
            print(f"[OK] 成功从底座借调转正条目 [{target_id}]: 状态 {old_status} -> {new_status} (已沉淀至用户专属仓: {paths['task1'].name})")
            return

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

    paths = get_paths(ensure=True)
    archives_dir = paths["archives"]
    archives_dir.mkdir(parents=True, exist_ok=True)

    title = args.title.strip()
    genre = normalize_genre(args.genre) if args.genre else "general"
    task_id = getattr(args, "task_id", None) or f"T{datetime.datetime.now().strftime('%Y%m%d%H%M')}"
    exam_type = normalize_exam_type(getattr(args, "exam_type", None))

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
        # 与 check-essay 共用同一套切分规则，保证预检词数与归档词数一致
        _sal, archive_body_lines, _signoff = split_essay_body(content, strip_markdown_tail=True)
        if archive_body_lines:
            metadata["word_count"] = sum(len(p.split()) for p in archive_body_lines)

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
    # 台账按 task_id upsert：同一任务重复归档只保留最新一行，且同一文件绝不重复写入
    ledger_targets = []
    seen_ledger = set()
    for cand in (paths["tasks"], paths.get("user_task1_tasks")):
        if not cand:
            continue
        # 双仓布局下 paths["tasks"] 与 paths["user_task1_tasks"] 可能指向同一文件，必须先按真实路径去重
        if not cand.parent.exists():
            continue
        rp = cand.resolve()
        if rp in seen_ledger:
            continue
        seen_ledger.add(rp)
        ledger_targets.append(cand)

    allow_duplicate = bool(getattr(args, "force", False))
    for ledger in ledger_targets:
        if allow_duplicate:
            with open(ledger, "a", encoding="utf-8") as f:
                f.write(json.dumps(task_entry, ensure_ascii=False) + "\n")
        else:
            kept = [r for r in read_jsonl(ledger) if r.get("task_id") != task_id]
            kept.append(task_entry)
            write_jsonl(ledger, kept)

    ledger_desc = ", ".join(str(p) for p in ledger_targets) if ledger_targets else "无可用台账"
    print(f"[OK] 范文已成功归档至: {target_file}")
    print(f"[OK] 题目台账已同步至: {ledger_desc}")
    return target_file

def cmd_session(args):
    paths = get_paths(ensure=True)
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
    # 试运行只读；只有 --apply 才允许触发外脑初始化与写入
    paths = get_paths(ensure=bool(getattr(args, "apply", False)))
    print("=== 开始知识库体检与定期清理评估 ===")

    # 只体检个人外脑两仓；出厂底座是静态教研资产，不参与个人休眠/退役评估
    task1_records = read_store(paths, "user_task1")
    user_shared_records = read_store(paths, "user_shared")

    dormant_candidates = []
    retired_candidates = []

    for rec in task1_records + user_shared_records:
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
        for rec in task1_records + user_shared_records:
            if rec.get("id") in retired_candidates:
                rec["status"] = "retired"
                updated += 1
            elif rec.get("id") in dormant_candidates and rec.get("status") == "active":
                rec["status"] = "dormant"
                updated += 1
        # 两仓均走统一写入入口，杜绝"只写一份表示"导致的双仓分叉
        save_user_task1(paths, task1_records)
        save_user_shared(paths, user_shared_records)
        print(f"[OK] 已应用清理策略，状态流转 {updated} 条。")
    else:
        print("[INFO] 本次为试运行，添加 --apply 可实际执行软删除与降权。")

def verify_integrity(paths: dict, verbose: bool = True) -> tuple[bool, int]:
    """严格校验教研底座与个人外脑。

    返回 (has_error, user_total)；user_total 只统计"个人外脑实战资产"，
    教研底座（锚点 + 出厂种子）单独汇报，避免把只读底座算成外脑成果。
    """
    if verbose:
        print(f"=== 开始严格校验知识库 ===\n• 教研底座: {paths['base_root']}\n• 用户外脑: {paths['user_root']}")

    has_error = False
    builtin_total = 0
    user_total = 0

    # 1. Verify anchors/task1_past_papers.jsonl
    anc_error = False
    anc_path = paths["anchors"]
    if not anc_path.exists():
        if verbose:
            print(f"[FAIL] {anc_path.name} 文件不存在！", file=sys.stderr)
        has_error = True
        anc_error = True
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
                    if verbose:
                        print(f"[FAIL] {anc_path.name}:{l_num} JSON格式解析错误: {e}", file=sys.stderr)
                    has_error = True
                    anc_error = True

        for l_num, rec in anc_records:
            r_id = rec.get("id")
            if not r_id or r_id in seen_ids:
                if verbose:
                    print(f"[FAIL] {anc_path.name}:{l_num} ID缺失或重复: {r_id}", file=sys.stderr)
                has_error = True
                anc_error = True
            seen_ids.add(r_id)

            for req_field in ("genre", "relationship", "register", "prompt", "official_model", "register_analysis"):
                if not rec.get(req_field):
                    if verbose:
                        print(f"[FAIL] {anc_path.name}:{l_num} [{r_id}] 缺少必填字段: {req_field}", file=sys.stderr)
                    has_error = True
                    anc_error = True

            # 署名链路防回退：真题题干必须给出替代署名指令或"不得使用真实姓名"约束
            if rec.get("is_real_exam", True):
                pr = rec.get("prompt", "") or ""
                has_directive = bool(
                    re.search(r'Use\s+["“][^"”]+["”]\s+instead', pr, re.IGNORECASE)
                    or re.search(r'sign\s+your\s+name\s+as\s+["“][^"”]+["”]', pr, re.IGNORECASE)
                    or re.search(r'Do not\s+(?:use|sign)[^.]*?name', pr, re.IGNORECASE)
                )
                if not has_directive:
                    if verbose:
                        print(f"[FAIL] {anc_path.name}:{l_num} [{r_id}] 真题题干缺少署名指令（署名链路将回退为默认 Li Ming）", file=sys.stderr)
                    has_error = True
                    anc_error = True

        if verbose:
            print(f"[{'WARN' if anc_error else 'PASS'}] anchors ({anc_path.name}): 校验完成，有效记录 {len(anc_records)} 条。")
        builtin_total += len(anc_records)


    # 2. Verify shared scenario morphemes (system base seeds)
    sh_error = False
    sh_path = paths["shared"]
    if not sh_path.exists():
        if verbose:
            print(f"[FAIL] {sh_path.name} 文件不存在！", file=sys.stderr)
        has_error = True
        sh_error = True
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
                    if verbose:
                        print(f"[FAIL] {sh_path.name}:{l_num} JSON格式解析错误: {e}", file=sys.stderr)
                    has_error = True

        for l_num, rec in sh_records:
            r_id = rec.get("id")
            if not r_id:
                if verbose:
                    print(f"[FAIL] {sh_path.name}:{l_num} 缺少必填字段: id", file=sys.stderr)
                has_error = True
                sh_error = True
            elif r_id in seen_ids:
                if verbose:
                    print(f"[FAIL] {sh_path.name}:{l_num} ID重复: {r_id}", file=sys.stderr)
                has_error = True
                sh_error = True
            else:
                seen_ids.add(r_id)

            if not rec.get("scenario"):
                if verbose:
                    print(f"[FAIL] {sh_path.name}:{l_num} [{r_id}] 缺少必填字段: scenario", file=sys.stderr)
                has_error = True
                sh_error = True
            if not rec.get("verb_phrase") and not rec.get("text"):
                if verbose:
                    print(f"[FAIL] {sh_path.name}:{l_num} [{r_id}] 缺少必填字段: verb_phrase/text", file=sys.stderr)
                has_error = True
                sh_error = True

        if verbose:
            print(f"[{'WARN' if sh_error else 'PASS'}] shared ({sh_path.name}): 校验完成，有效记录 {len(sh_records)} 条。")
        builtin_total += len(sh_records)

    # 3. Verify the personal task1 warehouse (allows 0 records for clean slate)
    #    同时校验 v2 规范路径与历史扁平文件，兼顾存量外脑
    t1_check_paths = []
    seen_check_paths = set()
    for cand in [paths.get("user_task1"), paths.get("task1"), paths.get("task1_legacy")]:
        if cand and cand.exists():
            rp = cand.resolve()
            if rp not in seen_check_paths:
                t1_check_paths.append(cand)
                seen_check_paths.add(rp)

    if not t1_check_paths:
        if verbose:
            if not paths.get("initialized"):
                print(f"[FAIL] 个人外脑尚未初始化（{paths['user_root']} 下无任何仓文件）。"
                      f"请先执行 `init`，或设置 KAOYAN_USER_BRAIN 指向已有外脑。", file=sys.stderr)
            else:
                print(f"[FAIL] task1 文件不存在！", file=sys.stderr)
        has_error = True
    else:
        for t1_path in t1_check_paths:
            t1_error = False
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
                        if verbose:
                            print(f"[FAIL] {t1_path.name}:{l_num} JSON格式解析错误: {e}", file=sys.stderr)
                        has_error = True
                        t1_error = True

            for l_num, rec in t1_records:
                r_id = rec.get("id")
                if not r_id:
                    if verbose:
                        print(f"[FAIL] {t1_path.name}:{l_num} 缺少必填字段: id", file=sys.stderr)
                    has_error = True
                    t1_error = True
                elif r_id in seen_ids:
                    if verbose:
                        print(f"[FAIL] {t1_path.name}:{l_num} ID重复: {r_id}", file=sys.stderr)
                    has_error = True
                    t1_error = True
                else:
                    seen_ids.add(r_id)

                cat = rec.get("category") or rec.get("type")
                if cat not in VALID_CATEGORIES:
                    if verbose:
                        print(f"[FAIL] {t1_path.name}:{l_num} [{r_id}] 非法 category: {cat}", file=sys.stderr)
                    has_error = True
                    t1_error = True

                m = rec.get("mastery")
                if m not in MASTERY_RANK:
                    if verbose:
                        print(f"[FAIL] {t1_path.name}:{l_num} [{r_id}] 非法 mastery: {m}", file=sys.stderr)
                    has_error = True
                    t1_error = True

                st = rec.get("status", "active")
                if st not in VALID_STATUSES:
                    if verbose:
                        print(f"[FAIL] {t1_path.name}:{l_num} [{r_id}] 非法 status: {st}", file=sys.stderr)
                    has_error = True
                    t1_error = True

                if not rec.get("source"):
                    if verbose:
                        print(f"[FAIL] {t1_path.name}:{l_num} [{r_id}] 缺少必填字段: source", file=sys.stderr)
                    has_error = True
                    t1_error = True

            status_tag = 'WARN' if t1_error else 'PASS'
            if verbose:
                if len(t1_records) == 0:
                    print(f"[{status_tag}] task1 ({t1_path.name}): 校验完成，纯净白纸就绪 (有效实战积累 0 条)。")
                else:
                    print(f"[{status_tag}] task1 ({t1_path.name}): 校验完成，有效记录 {len(t1_records)} 条。")
            user_total += len(t1_records)

    # 4. Verify user_shared morphemes (allows 0 records)
    if paths["user_shared"].exists():
        # 与 task1 完全对等的严格校验（修复：原实现只做 read_jsonl 解析，
        # 导致共享仓的 ID 重复 / 非法 category / 非法 mastery / 非法 status / 缺 source 全部漏检，
        # 而 settle 又用本函数的返回值作为"本地链路成功"的门禁）
        u_sh_error = False
        u_sh_records = []
        with open(paths["user_shared"], "r", encoding="utf-8") as f:
            for l_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    u_sh_records.append((l_num, json.loads(line)))
                except json.JSONDecodeError as e:
                    if verbose:
                        print(f"[FAIL] {paths['user_shared'].name}:{l_num} JSON格式解析错误: {e}", file=sys.stderr)
                    has_error = True
                    u_sh_error = True

        u_sh_seen = set()
        for l_num, rec in u_sh_records:
            r_id = rec.get("id")
            if not r_id:
                if verbose:
                    print(f"[FAIL] {paths['user_shared'].name}:{l_num} 缺少必填字段: id", file=sys.stderr)
                has_error = True
                u_sh_error = True
            elif r_id in u_sh_seen:
                if verbose:
                    print(f"[FAIL] {paths['user_shared'].name}:{l_num} ID重复: {r_id}", file=sys.stderr)
                has_error = True
                u_sh_error = True
            else:
                u_sh_seen.add(r_id)

            u_cat = rec.get("category") or rec.get("type")
            if u_cat not in VALID_CATEGORIES:
                if verbose:
                    print(f"[FAIL] {paths['user_shared'].name}:{l_num} [{r_id}] 非法 category: {u_cat}", file=sys.stderr)
                has_error = True
                u_sh_error = True

            u_m = rec.get("mastery")
            if u_m not in MASTERY_RANK:
                if verbose:
                    print(f"[FAIL] {paths['user_shared'].name}:{l_num} [{r_id}] 非法 mastery: {u_m}", file=sys.stderr)
                has_error = True
                u_sh_error = True

            u_st = rec.get("status", "active")
            if u_st not in VALID_STATUSES:
                if verbose:
                    print(f"[FAIL] {paths['user_shared'].name}:{l_num} [{r_id}] 非法 status: {u_st}", file=sys.stderr)
                has_error = True
                u_sh_error = True

            if not rec.get("source"):
                if verbose:
                    print(f"[FAIL] {paths['user_shared'].name}:{l_num} [{r_id}] 缺少必填字段: source", file=sys.stderr)
                has_error = True
                u_sh_error = True

        if verbose:
            tag = 'WARN' if u_sh_error else 'PASS'
            if len(u_sh_records) == 0:
                print(f"[{tag}] user_shared ({paths['user_shared'].name}): 校验完成，纯净白纸就绪 (有效实战语素 0 条)。")
            else:
                print(f"[{tag}] user_shared ({paths['user_shared'].name}): 校验完成，有效实战语素 {len(u_sh_records)} 条。")
        user_total += len(u_sh_records)

    # 5. Verify satisfaction archives
    arch_dir = paths["archives"]
    if arch_dir.exists():
        md_files = list(arch_dir.glob("*.md"))
        if verbose:
            print(f"[PASS] archives ({arch_dir.parent.name}/{arch_dir.name}): 包含 {len(md_files)} 篇满意归档作文。")

    if verbose:
        print(f"[INFO] 只读教研底座资产 {builtin_total} 条（锚点 + 出厂种子，不计入个人外脑积累）")

    return has_error, user_total


def cmd_verify(args):
    paths = get_paths()
    has_error, user_total = verify_integrity(paths, verbose=True)
    if has_error:
        print(f"\n[FAIL] 知识库验证失败！请修复以上列出的错误。", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"\n=== 验证通过！个人外脑有效条目: {user_total} 条（不含只读教研底座） ===")
        sys.exit(0)

def ambiguous_year_exams(year: str) -> list:
    """同年存在多个卷别（英一/英二）时返回卷别列表。

    仅给 --year 而不给 --exam-type 时，同年两条记录任取其一会让署名校验产生
    假 PASS / 假 FAIL，因此调用方应据此拒绝判定而不是猜。
    """
    if not year:
        return []
    try:
        anchors = read_jsonl(get_paths()["anchors"])
    except Exception:
        return []
    exams = sorted({
        str(r.get("exam_type", "")).strip()
        for r in anchors
        if str(r.get("year", "")).strip() == str(year).strip()
    } - {""})
    return exams if len(exams) > 1 else []


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

    salutation, body_paragraphs, signoff = split_essay_body(content)
    if not salutation and not body_paragraphs and not signoff:
        print("[ERROR] 未检测到有效文本内容。", file=sys.stderr)
        sys.exit(1)

    # Word counts
    p_counts = [len(p.split()) for p in body_paragraphs]
    body_total = sum(p_counts)
    total_words = len(content.split())

    # Ratios
    ratios = [round(c / body_total * 10, 1) if body_total > 0 else 0 for c in p_counts]
    ratio_str = " : ".join(str(r) for r in ratios) if ratios else "无"

    # Contraction check (P0-4 修正：显式契约，绝不把名词所有格误判为口语缩写)
    contraction_pattern = re.compile(r"\b([A-Za-z]+)['\u2019]([A-Za-z]+)\b")
    s_form_contractions = {
        "i", "you", "he", "she", "it", "we", "they", "that", "there", "here",
        "what", "who", "let", "this", "how", "where", "when", "why", "one",
        "everybody", "somebody", "nobody", "anybody", "something", "nothing",
    }
    contractions_found = []
    for line_no, line in enumerate(content.splitlines(), 1):
        for m in contraction_pattern.finditer(line):
            stem = m.group(1).lower()
            tail = m.group(2).lower()
            if tail == "s":
                # 仅「代词/指示词 + 's」属缩写；dictionary's / parents' 等所有格一律不判为缩写
                if stem not in s_form_contractions:
                    continue
            elif tail not in ("t", "re", "ve", "ll", "d", "m"):
                continue
            contractions_found.append((line_no, m.group(0)))

    # Exclamation check
    exclamation_count = content.count("!")

    # Format checks
    format_issues = []
    salutation_head = bool(salutation and re.match(r'^(dear\b|to\b)', salutation, re.IGNORECASE))
    notice_title = bool(salutation and re.match(r'^(notice|announcement)\b', salutation, re.IGNORECASE))
    if salutation_head:
        if salutation.endswith(":") or salutation.endswith("："):
            format_issues.append(f"称呼误用冒号（'{salutation}'），考研公文一律使用英文半角逗号")
        elif salutation.endswith("，"):
            format_issues.append(f"称呼误用中文全角逗号（'{salutation}'），必须使用英文半角逗号")
        elif not salutation.endswith(","):
            format_issues.append(f"称呼末尾缺少英文逗号（'{salutation}'）")

    signoff_phrase_line = None
    for s_line in signoff:
        if re.match(r'^(best\s+wishes|kind\s+regards|best\s+regards|warmest\s+regards|yours\s+sincerely|sincerely\s+yours|yours\s+faithfully)', s_line, re.IGNORECASE):
            if signoff_phrase_line is None:
                signoff_phrase_line = s_line
            if not s_line.endswith(","):
                format_issues.append(f"结语敬语缺少英文逗号（'{s_line}'）")

    # 署名核验（P0-3）：题干法定署名 / 句号 / 与收件人重名 / 敬语配对 / 告示机构落款
    detected_signature = None
    for s_line in reversed(signoff):
        if not re.match(
            r'^(best\s+wishes|kind\s+regards|best\s+regards|warmest\s+regards|yours\s+sincerely|'
            r'sincerely\s+yours|yours\s+faithfully|yours\s+truly|sincerely|regards|warm\s+regards|yours)[,\.]?$',
            s_line, re.IGNORECASE
        ):
            detected_signature = s_line
            break

    addressee = None
    if salutation:
        m_addr = re.match(r'^dear\s+(.+?)\s*[,:：]?\s*$', salutation, re.IGNORECASE)
        if m_addr:
            addressee = m_addr.group(1).strip().strip(",:：").strip()
    addressee_is_unknown = bool(
        addressee and re.match(r'^(sir|madam|sir\s+or\s+madam|madam\s+or\s+sir|dear\s+sir|dear\s+madam)', addressee, re.IGNORECASE)
    )

    expected_signoff = None
    signoff_note = ""
    if getattr(args, "signoff", None):
        expected_signoff = str(args.signoff).strip()
    elif getattr(args, "year", None) or getattr(args, "exam_type", None):
        multi = ambiguous_year_exams(getattr(args, "year", None)) if not getattr(args, "exam_type", None) else []
        if multi:
            # 拒绝在卷别不确定时校验署名，避免拿英一的 Li Ming 去判英二作文
            signoff_note = (
                f"该年份含 {' / '.join(multi)} 多份卷别，未指定 --exam-type 无法确定题干法定署名，"
                f"已跳过署名核验（请补充 --exam-type）"
            )
        else:
            looked, matched_rec = lookup_mandated_signoff(
                getattr(args, "year", None), getattr(args, "exam_type", None), getattr(args, "genre", None)
            )
            if looked and not str(looked).startswith("未指定"):
                expected_signoff = looked
            elif looked:
                signoff_note = looked
            else:
                signoff_note = "未在真题标尺中定位到该年份/卷别的题干，无法校验法定署名"

    if detected_signature:
        if detected_signature.endswith("."):
            format_issues.append(f"署名误加句号（'{detected_signature}'），署名严禁加句号")
        if expected_signoff and detected_signature.strip().rstrip(".,").lower() != expected_signoff.lower():
            format_issues.append(
                f"落款署名与题干法定署名不一致（本篇为 '{detected_signature.strip()}'，题干法定为 '{expected_signoff}'）"
            )
        if addressee and not addressee_is_unknown:
            if detected_signature.strip().rstrip(".,").lower() == addressee.lower():
                format_issues.append(
                    f"收件人与署名重名（称呼 '{salutation}' 与落款 '{detected_signature.strip()}' 同名），严禁收件人与署名重名"
                )

    if signoff_phrase_line and addressee and not notice_title:
        phrase_text = signoff_phrase_line.strip().rstrip(",.").lower()
        is_faithfully = phrase_text.startswith("yours faithfully")
        is_sincerely_family = phrase_text.startswith(("yours sincerely", "sincerely yours", "yours truly", "sincerely"))
        has_complimentary = phrase_text.startswith(("yours", "sincerely", "best", "kind", "warm"))
        if addressee_is_unknown and has_complimentary and not is_faithfully:
            format_issues.append(
                f"敬语与称呼不匹配：不知收件人姓名（'{salutation}'）应使用 'Yours faithfully,'，当前为 '{signoff_phrase_line}'"
            )
        elif (not addressee_is_unknown) and is_faithfully:
            format_issues.append(
                f"敬语与称呼不匹配：已知收件人姓名（'{salutation}'）应使用 'Yours sincerely,'，当前为 '{signoff_phrase_line}'"
            )

    genre_norm = normalize_genre(getattr(args, "genre", "") or "")
    is_notice = genre_norm == "notice" or notice_title
    if is_notice:
        if salutation_head:
            format_issues.append(f"告示/通知类严禁使用称呼（'{salutation}'）")
        if detected_signature and not re.match(
            r'^(the\s+|recorder\b|postgraduate|student\s+union|organizing|department|office)', detected_signature, re.IGNORECASE
        ):
            format_issues.append(f"告示/通知类落款应为发布机构（当前为个人署名 '{detected_signature}'）")

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
            "format_issues": format_issues,
            "salutation": salutation,
            "detected_signature": detected_signature,
            "expected_signoff": expected_signoff,
            "signoff_note": signoff_note,
        }
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    print("==================== 作文格式与硬红线预检报告 (机器可判 4 项) ====================")
    print("• 覆盖范围: ① 正文词数 ② 格式与署名 ③ 口语缩写 ④ 感叹号")
    print("• 不在本工具判据内（须由私教人工判断）: 超纲词 / 采分点覆盖 / 无中生有")
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

    sig_desc = detected_signature.strip() if detected_signature else "未检出"
    if expected_signoff:
        sig_check = f"题干法定 '{expected_signoff}' | [{'PASS' if not any('署名' in i for i in format_issues) else 'FAIL'}]"
    elif signoff_note:
        sig_check = f"未校验（{signoff_note}）"
    else:
        sig_check = "未校验（未提供 --year/--exam-type/--signoff）"
    print(f"• 署名核验: 本篇 '{sig_desc}' | {sig_check}")

    print("======================================================================")

def cmd_init(args):
    force_reset = getattr(args, "reset", False)
    target_dir = None
    if getattr(args, "dir", None):
        target_dir = Path(args.dir).expanduser().resolve()
    user_root = init_user_brain(user_brain_dir=target_dir, force_reset=force_reset)
    paths = get_paths(user_brain_dir=user_root)
    print("==================== 考研小作文写作外脑初始化报告 ====================")
    print(f"• 教研底座目录 (只读储备): {paths['base_root']}")
    print(f"• 个人外脑目录 (专属实战): {paths['user_root']}")
    print(f"• 执行动作: {'【格式化重置】纯净白纸初始化 (0记录白纸就绪)' if force_reset else '【安全初始化】纯净白纸探测'}")

    user_morph_count = len(read_store(paths, "user_shared"))
    user_t1_count = len(read_store(paths, "user_task1"))
    seed_t1_count = len(read_jsonl(paths["seed_task1"])) if paths["seed_task1"].exists() else 0
    seed_sh_count = len(read_jsonl(paths["seed_shared"])) if paths["seed_shared"].exists() else 0
    anc_count = len(read_jsonl(paths["anchors"])) if paths["anchors"].exists() else 0

    if user_t1_count == 0 and user_morph_count == 0:
        print("• 个人外脑状态: 【100% 纯净白纸】(0 条出厂僵尸条目，只有实战确认表达才配入库)")
    else:
        print(f"• 个人专属仓 (task1/expressions.jsonl): {user_t1_count} 条 (实战确认)")
        print(f"• 共享语素仓 (shared/morphemes.jsonl): {user_morph_count} 条 (实战确认)")

    print(f"• 教研底座种子 (seeds): 包含 {seed_t1_count} 条小作文表达 + {seed_sh_count} 条共享语素 (只读底座，仅作缺额兜底借调)")
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
    explicit_hint = paths.get("user_root_explicit")
    print(f"• 外脑存储类型: {storage_type}")
    print(f"• 外脑就绪状态: {'已初始化' if paths.get('initialized') else '未初始化（写命令将按需创建；纯读命令不会创建任何目录）'}")
    if not explicit_hint and not paths.get("initialized"):
        print("• 提示: 权威外脑在你的安卓设备上；PC 侧保持完全干净。如确需在 PC 落盘，"
              "请先执行 `init` 或设置 KAOYAN_USER_BRAIN。")

    # 1. 教研底座只读储备
    seed_t1_records = read_jsonl(paths["seed_task1"]) if paths["seed_task1"].exists() else []
    seed_sh_records = read_jsonl(paths["seed_shared"]) if paths["seed_shared"].exists() else []
    anc_records = read_jsonl(paths["anchors"]) if paths["anchors"].exists() else []
    print(f"\n【一、教研底座 (只读储备，仅作缺额借调)】:")
    anc_real = [r for r in anc_records if r.get("is_real_exam", True)]
    anc_years = sorted({int(r["year"]) for r in anc_records if str(r.get("year", "")).isdigit()})
    year_span = f"{anc_years[0]}-{anc_years[-1]}" if anc_years else "无"
    exam_kinds = sorted({str(r.get("exam_type", "")) for r in anc_real} - {"", "N/A"})
    print(f"• 历年真题标尺库: {len(anc_records)} 篇 (真题 {len(anc_real)} 篇，覆盖 {year_span}；"
          f"卷别: {' / '.join(exam_kinds) if exam_kinds else '无'}；含 {len(anc_records) - len(anc_real)} 条非真题题型参考)")
    print(f"• 出厂专属表达种子: {len(seed_t1_records)} 条 (小作文功能句与篇章模板)")
    print(f"• 出厂场景语素种子: {len(seed_sh_records)} 条 (7大核心高频场景共享素材)")

    # 2. 个人外脑专属资产
    user_morph_records = read_store(paths, "user_shared")
    user_t1_records = read_store(paths, "user_task1")
    tasks = read_jsonl(paths["tasks"])
    arch_files = list(paths["archives"].glob("*.md")) if paths["archives"].exists() else []

    print(f"\n【二、个人外脑资产 (实战确认与专属积累)】:")
    total_user_items = len(user_morph_records) + len(user_t1_records)
    if total_user_items == 0:
        print("• 个人词句外脑总数: 0 条 (【100% 纯净白纸】已就绪，坐等实战表达沉淀)")
    else:
        print(f"• 个人词句外脑总数: {total_user_items} 条 (实战资产)")
    print(f"  - 个人共享语素仓 (shared): {len(user_morph_records)} 条 (大小作文通用素材)")
    print(f"  - 个人小作文专属仓 (task1): {len(user_t1_records)} 条 (功能句、结构与模板)")

    mastery_counts = {"稳定": 0, "敢用": 0, "学习中": 0, "未接触": 0}
    for r in user_morph_records + user_t1_records:
        m = r.get("mastery", "未接触")
        mastery_counts[m] = mastery_counts.get(m, 0) + 1
    print(f"  - 个人掌握度分布: 稳定={mastery_counts['稳定']} | 敢用={mastery_counts['敢用']} | 学习中={mastery_counts['学习中']} | 未接触={mastery_counts['未接触']}")
    print(f"  - 满意范文归档: {len(arch_files)} 篇 | 演练台账: {len(tasks)} 次")

    # 3. 文类私有化与去系统化进展
    print(f"\n【三、十大文类私有化进度 (去系统化看板)】:")
    genre_labels = [
        ("advice", "建议信"),
        ("recommendation", "推荐信"),
        ("complaint", "投诉信"),
        ("apology", "道歉信"),
        ("invitation", "邀请信"),
        ("gratitude", "感谢信"),
        ("application", "申请信"),
        ("notice", "通知告示"),
        ("minutes", "纪要备忘"),
        ("reply_letter", "回复信")
    ]
    for g_code, g_name in genre_labels:
        g_items = [it for it in user_t1_records if normalize_genre(it.get("genre")) == g_code]
        cnt = len(g_items)
        if cnt >= 5:
            status_desc = f"【已自给自足】(外脑 {cnt} 条 >= 5，底座 0 借调，100% 个人化)"
        elif cnt > 0:
            status_desc = f"【借调过渡中】(外脑已有 {cnt} 条，不足配额由底座借调补齐)"
        else:
            status_desc = f"【纯净待演练】(外脑 0 条，写前由底座借调支持)"
        print(f"  • [{g_name.ljust(4, '　')}]: {status_desc}")

    meta_file = paths["user_root"] / ".kb_meta.json"
    if meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
                print(f"\n• 外脑初始化时间: {meta.get('initialized_at', '未知')}")
        except Exception:
            pass
def cmd_maimemo_sync(args):
    """Sync essay vocabulary to MaiMemo (墨墨背单词)"""
    try:
        from maimemo_sync import sync_essay_vocabulary
    except ImportError:
        script_dir = Path(__file__).resolve().parent
        if str(script_dir) not in sys.path:
            sys.path.insert(0, str(script_dir))
        from maimemo_sync import sync_essay_vocabulary

    if getattr(args, "example", False):
        example_payload = {
            "chapter": "2011英二小作文",
            "task_id": "T2011-E2-ADV",
            "words": [
                {
                    "spelling": "accommodate",
                    "type": "spelling_fix",
                    "misspelling": "acommodate",
                    "sentence": "The library is expected to prolong opening hours to accommodate students.",
                    "translation": "图书馆预计将延长开放时间以方便/容纳学生。",
                    "usage_note": "考研高频动词，常接 students / needs，表示‘迎合、容纳、迁就’，写作中可完美替换普通的 meet 或 help。",
                    "grammar_note": "主干为 The library is expected to prolong opening hours；不定式短语 to accommodate students 作后置目的状语，有力承载举措价值。"
                },
                {
                    "spelling": "prolong",
                    "type": "advanced_vocab",
                    "sentence": "The library is expected to prolong opening hours to accommodate students.",
                    "translation": "图书馆预计将延长开放时间以方便/容纳学生。",
                    "usage_note": "写作及阅读高频动词，及物动词常搭 opening hours / service，比 lengthen 或 extend 更加严谨书面。",
                    "grammar_note": "在 be expected to 结构中充当动词不定式核心动词，形成动宾结构 prolong opening hours。"
                }
            ]
        }
        print(json.dumps(example_payload, indent=2, ensure_ascii=False))
        return

    if not args.file:
        print("错误: 必须通过 --file 指定 JSON 载荷文件路径，或使用 --example 查看样例", file=sys.stderr)
        sys.exit(1)

    with open(args.file, "r", encoding="utf-8") as f:
        payload = json.load(f)

    try:
        res = sync_essay_vocabulary(payload, token=args.token, mock=args.mock, dry_run=args.dry_run)
        if res.get("status") in ("partial_failed", "error"):
            err_msg = res.get("message", "所选单词未能匹配或同步失败")
            if getattr(args, "json", False):
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(f"[ERROR] 墨墨同步失败: {err_msg}", file=sys.stderr)
                if res.get("skipped_words"):
                    print(f"未匹配跳过: {', '.join(res.get('skipped_words', []))}", file=sys.stderr)
            sys.exit(1)
        elif res.get("status") == "skipped":
            if getattr(args, "json", False):
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(f"[INFO] {res.get('message')}")
            return
        elif getattr(args, "json", False):
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(f"=== 墨墨背单词同步完成 ===")
            print(f"专属词本: {res.get('notepad_title')}")
            print(f"章节: # {res.get('chapter')}")
            print(f"同步生词: {', '.join(res.get('synced_words', []))}")
            if res.get('skipped_words'):
                print(f"未匹配跳过: {', '.join(res.get('skipped_words', []))}")
            print(f"例句沉淀数: {res.get('phrases_created')}")
            print(f"借壳助记数: {res.get('notes_created')}")
            if res.get("highlight_missing"):
                print(f"[WARN] 以下词未在例句中找到目标词，已按无高亮建句: {', '.join(res['highlight_missing'])}", file=sys.stderr)
            print(f"今日复习流: 已推入 (advance=True)")
    except Exception as e:
        err_msg = str(e)
        if getattr(args, "json", False):
            print(json.dumps({"status": "error", "message": err_msg}, ensure_ascii=False))
        else:
            print(f"同步失败: {err_msg}", file=sys.stderr)
        sys.exit(1)

SETTLE_SNAPSHOT_KEYS = (
    "user_task1",
    "user_shared",
    "tasks",
    "history_log",
    "kb_meta",
    # 历史扁平布局：虽已不再回写，但旧外脑上仍可能存在，写入型命令的兼容读取路径会触及
    "task1_legacy",
    "user_task1_legacy",
    "tasks_legacy",
    "user_shared_legacy",
)


def _load_settle_payload(raw_data: str) -> dict:
    """解析并归一化结算载荷。

    同时兼容 SKILL.md 文档化的顶层 `essay_content` 与 CLI 示例的 `archive.content`，
    避免文档与实现不一致导致"静默跳过归档却报成功"。
    """
    spec = json.loads(raw_data)
    if not isinstance(spec, dict):
        raise ValueError("结算载荷必须是 JSON 对象")
    archive = spec.get("archive")
    if not isinstance(archive, dict):
        archive = {}
    if not str(archive.get("content", "") or "").strip():
        for key in ("essay_content", "essay", "content"):
            candidate = spec.get(key)
            if candidate and str(candidate).strip():
                archive["content"] = str(candidate)
                break
    if archive:
        spec["archive"] = archive
    return spec


def _settle_snapshot_files(paths: dict) -> list:
    """结算前快照本地可写资产，用于失败回滚。

    覆盖范围必须等于"结算可能触碰的全部本地文件"，否则回滚会留下半更新状态：
    两个用户仓、题目台账、审计日志、外脑元数据、会话目录、以及历史扁平布局文件。
    归档另由 _settle_snapshot_archives 逐字节快照（同名覆盖也需可还原）。
    """
    snapshot = []
    seen = set()
    for key in SETTLE_SNAPSHOT_KEYS:
        target = paths.get(key)
        if not target:
            continue
        resolved = Path(target).resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            data = resolved.read_bytes() if resolved.exists() else None
        except Exception:
            data = None
        snapshot.append((resolved, data))

    # 会话目录：记录结算前已存在的文件名清单，回滚时删除新增文件
    sessions_dir = paths.get("sessions")
    if sessions_dir:
        sd = Path(sessions_dir)
        if sd.is_dir():
            for f in sorted(sd.rglob("*")):
                if f.is_file():
                    rp = f.resolve()
                    if rp in seen:
                        continue
                    seen.add(rp)
                    try:
                        snapshot.append((rp, rp.read_bytes()))
                    except Exception:
                        snapshot.append((rp, None))
    return snapshot


def _settle_snapshot_archives(archives_dir) -> dict:
    """快照归档目录下所有 .md 的字节内容，使"同名文件被就地覆盖"也可回滚。"""
    snap = {}
    if not archives_dir:
        return snap
    ad = Path(archives_dir)
    if not ad.is_dir():
        return snap
    for f in ad.glob("*.md"):
        try:
            snap[f.name] = f.read_bytes()
        except Exception:
            snap[f.name] = None
    return snap


def _settle_restore_files(snapshot: list, archives_dir=None, archive_snapshot=None):
    """把本地资产还原到快照状态；归档按字节还原并删除新增文件。"""
    for target, data in snapshot:
        try:
            if data is None:
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        except Exception:
            pass
    if archives_dir is not None and archive_snapshot is not None:
        try:
            ad = Path(archives_dir)
            if ad.is_dir():
                for f in ad.glob("*.md"):
                    if f.name not in archive_snapshot:
                        f.unlink()
                for name, data in archive_snapshot.items():
                    if data is None:
                        continue
                    target = ad / name
                    if not target.exists() or target.read_bytes() != data:
                        target.write_bytes(data)
        except Exception:
            pass


class _SettleLock:
    """结算互斥锁：避免并发 settle 对同一 JSONL 整文件读改写互相覆盖。

    以 O_CREAT|O_EXCL 抢占锁文件；超时即放弃并提示，绝不静默并行写入。
    """

    def __init__(self, lock_path, timeout: float = 20.0):
        self.lock_path = Path(lock_path)
        self.timeout = timeout
        self.acquired = False

    def __enter__(self):
        import time as _time
        deadline = _time.time() + self.timeout
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("utf-8"))
                os.close(fd)
                self.acquired = True
                return self
            except FileExistsError:
                if _time.time() >= deadline:
                    raise TimeoutError(
                        f"另一结算进程正在运行（锁文件: {self.lock_path}）。"
                        f"请等待其结束，或确认无进程后手工删除该锁文件。"
                    )
                _time.sleep(0.3)

    def __exit__(self, exc_type, exc, tb):
        if self.acquired:
            try:
                self.lock_path.unlink()
            except Exception:
                pass
        return False


def _settle_preflight(spec: dict, paths: dict, task_id: str):
    """结算前置校验：任何一项不通过都不得开始写入，杜绝"半写入 + 假成功"。"""
    errors, warnings = [], []

    batch = spec.get("batch")
    if batch is not None and not isinstance(batch, dict):
        errors.append("batch 段必须是 JSON 对象")
        batch = None

    archive = spec.get("archive") or {}
    if not str(archive.get("content", "") or "").strip():
        errors.append("缺少终版范文正文：请在载荷顶层提供 essay_content，或提供 archive.content")

    if isinstance(batch, dict):
        known_ids = []
        for key in ("user_task1", "user_shared", "seed_task1", "shared"):
            candidate = paths.get(key)
            if candidate and Path(candidate).exists():
                for rec in read_jsonl(candidate):
                    if rec.get("id"):
                        known_ids.append(str(rec["id"]).strip())
        for upd in batch.get("status_updates", []) or []:
            uid = str(upd.get("id", "")).strip()
            if not uid:
                errors.append("status_updates 中存在缺少 id 的条目")
                continue
            if not any(is_id_match(known, uid) for known in known_ids):
                errors.append(f"status_updates 指定的条目不存在，无法晋级: {uid}")
            if str(upd.get("status", "")).strip() not in MASTERY_RANK:
                errors.append(f"status_updates 中 '{uid}' 的 status 非法: {upd.get('status')}")
        for wrapper in batch.get("new_items", []) or []:
            item = wrapper.get("data", wrapper) if isinstance(wrapper, dict) else {}
            probe = dict(item)
            if not probe.get("source"):
                probe["source"] = f"{task_id} 实战沉淀" if task_id else "实战沉淀"
            ok, reason = check_admission_rules(probe)
            if not ok:
                errors.append(f"new_items 未通过准入规则: {reason} | {item.get('intent', item.get('intent_cn', ''))}")

    maimemo = spec.get("maimemo")
    if maimemo is not None and not isinstance(maimemo, dict):
        errors.append("maimemo 段必须是 JSON 对象")
    elif isinstance(maimemo, dict) and maimemo.get("words"):
        missing_spelling = [w.get("sentence", "") for w in maimemo["words"] if not str(w.get("spelling", "")).strip()]
        if missing_spelling:
            errors.append(f"maimemo.words 中有 {len(missing_spelling)} 张词卡缺少 spelling 字段")
        no_sentence = [w.get("spelling") for w in maimemo["words"] if not str(w.get("sentence", "")).strip()]
        if no_sentence:
            warnings.append(f"以下词卡缺少例句，将不生成专属例句: {', '.join(str(x) for x in no_sentence)}")

    return errors, warnings


def cmd_settle(args):
    """结算入口：持有互斥锁，并保证任何未预期异常都整体回滚本地资产。

    历史缺陷：只有 cmd_batch_update / cmd_archive 抛出的 SystemExit 被捕获，
    其它异常（I/O、编码、verify 内部错误、Ctrl-C）会带着已落盘数据直接冒泡，零回滚。
    """
    state = {"snapshot": None, "archives_dir": None, "archive_snapshot": None, "lock": None}
    try:
        _settle_impl(args, state)
    except SystemExit:
        raise
    except BaseException as e:
        if state["snapshot"] is not None:
            try:
                _settle_restore_files(state["snapshot"], state["archives_dir"], state["archive_snapshot"])
            except Exception:
                pass
            print(f"\n[FAIL] 结算过程发生未预期异常，已整体回滚本地资产: {e}", file=sys.stderr)
        else:
            print(f"\n[FAIL] 结算过程发生未预期异常（尚未快照，无需回滚）: {e}", file=sys.stderr)
        raise
    finally:
        lock = state.get("lock")
        if lock is not None:
            lock.__exit__(None, None, None)


def _settle_impl(args, state):
    """一键原子结算的实际实现。"""
    if getattr(args, "example", False):
        example_payload = {
            "task_id": "T2012-E2-ADV",
            "genre": "complaint",
            "year": "2012",
            "exam_type": "English II",
            "title": "投诉网购电子词典（2012英二）",
            # 顶层 essay_content 为文档化主形态；archive.content 亦被兼容
            "essay_content": "Dear Sir or Madam,\n\n    I am writing to lodge a formal complaint regarding the electronic dictionary that I purchased from your online store on September 20th.\n\n                                        Yours faithfully,\n                                        Zhang Wei\n",
            "archive": {
                "metadata": {
                    "signature": "Zhang Wei",
                    "word_count": 117,
                    "points_coverage": "100%",
                    "advanced_patterns": ["Having done", "which-clause", "be justified in doing"]
                }
            },
            "batch": {
                "status_updates": [
                    {
                        "id": "T1_ADV_SEN_001",
                        "status": "敢用",
                        "note": "跨文类复用验证（ID 必须取自 query --mine 的真实输出）",
                        "independent": True
                    }
                ],
                "new_items": [
                    {
                        "target": "shared",
                        "data": {
                            "category": "phrase",
                            "genre": "complaint",
                            "section": "body",
                            "register": "neutral_formal",
                            "intent": "提供建设性的解决方案（售后交涉、回复信、建议信通用的举措承重表达）",
                            "verb_phrase": "offer a constructive solution",
                            "expression": "offer a constructive solution",
                            "mastery": "学习中"
                        }
                    },
                    {
                        "target": "task1",
                        "data": {
                            "category": "functional_sentence",
                            "genre": "complaint",
                            "section": "opening",
                            "register": "neutral_formal",
                            "intent": "投诉信开篇定调：一句话交代投诉意图、商品、购买渠道与购买时间四要素",
                            "expression": "I am writing to lodge a formal complaint regarding [Product] that I purchased from [Place] on [Date].",
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
                        "sentence": "I am writing to express my dissatisfaction with the electronic dictionary.",
                        "translation": "我写信是为了表达我对电子词典的不满。",
                        "usage_note": "考研高频动词，表表达情感或立场",
                        "grammar_note": "不定式作目的状语"
                    }
                ]
            }
        }
        print(json.dumps(example_payload, indent=2, ensure_ascii=False))
        return

    raw_data = getattr(args, "data", None)
    if not raw_data and getattr(args, "file", None):
        with open(args.file, "r", encoding="utf-8") as f:
            raw_data = f.read()
    elif not raw_data:
        raw_data = sys.stdin.read()

    if not raw_data or not raw_data.strip():
        print("错误: 必须通过 --file 指定 JSON 载荷文件路径，或使用 --data / stdin，或使用 --example 查看样例", file=sys.stderr)
        sys.exit(1)

    try:
        settle_spec = _load_settle_payload(raw_data)
    except json.JSONDecodeError as e:
        print(f"[ERROR] 结算载荷 JSON 格式错误: {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    paths = get_paths(ensure=True)

    # 互斥锁：避免并发结算对同一 JSONL 整文件读改写互相覆盖
    lock = _SettleLock(Path(paths["user_root"]) / "settle.lock")
    try:
        lock.__enter__()
    except TimeoutError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(2)
    state["lock"] = lock

    task_id = settle_spec.get("task_id", "") or f"T{datetime.datetime.now().strftime('%Y%m%d%H%M')}"
    genre = normalize_genre(settle_spec.get("genre", "general"))
    year = str(settle_spec.get("year", datetime.datetime.now().year))
    exam_type = normalize_exam_type(settle_spec.get("exam_type"), default="考研小作文")
    title = settle_spec.get("title", f"{year} {exam_type} 满分范文")

    settle_report = {
        "status": "success",
        "task_id": task_id,
        "batch": None,
        "archive": None,
        "maimemo": None,
        "verify": None,
        "errors": [],
        "warnings": [],
    }

    print("==================== 考研英语小作文 · 阶段3一键沉淀结算 ====================")
    print(f"• 任务编号: {task_id} | 题目标题: {title} ({year} · {exam_type} · {genre})")

    import types

    # 0. 前置校验（不通过则零写入直接退出）
    preflight_errors, preflight_warnings = _settle_preflight(settle_spec, paths, task_id)
    for w in preflight_warnings:
        print(f"  [WARN] {w}", file=sys.stderr)
    settle_report["warnings"] = preflight_warnings
    if preflight_errors:
        print("\n--- [步骤 0/4] 结算前置校验 ---")
        for item in preflight_errors:
            print(f"  ✗ {item}", file=sys.stderr)
        settle_report["status"] = "invalid"
        settle_report["errors"] = preflight_errors
        print("\n==================== 结算总结卡片 ====================")
        print("[FAIL] 前置校验未通过，本次未做任何写入，请修正载荷后重试。", file=sys.stderr)
        if getattr(args, "json", False):
            print(json.dumps(settle_report, ensure_ascii=False, indent=2))
        sys.exit(2)

    snapshot = _settle_snapshot_files(paths)
    archives_dir = paths.get("archives")
    archive_snapshot = _settle_snapshot_archives(archives_dir)
    # 登记到外层包装器：此后任何未预期异常都会触发逐字节回滚
    state["snapshot"] = snapshot
    state["archives_dir"] = archives_dir
    state["archive_snapshot"] = archive_snapshot

    local_failures = []
    remote_failures = []

    def _rollback_and_exit(code: int, failures: list, label: str):
        _settle_restore_files(snapshot, archives_dir, archive_snapshot)
        settle_report["status"] = "error"
        settle_report["errors"] = failures
        print(f"\n[FAIL] {label}，已整体回滚（个人外脑 / 双仓 / 台账 / history.log / 元数据 / 归档均恢复原状）:",
              file=sys.stderr)
        for item in failures:
            print(f"  ✗ {item}", file=sys.stderr)
        print("======================================================")
        if getattr(args, "json", False):
            print(json.dumps(settle_report, ensure_ascii=False, indent=2))
        sys.exit(code)

    # 1. Batch update
    batch_spec = settle_spec.get("batch")
    if batch_spec:
        batch_args = types.SimpleNamespace(
            data=json.dumps(batch_spec, ensure_ascii=False),
            file=None,
            task_id=task_id,
            example=False
        )
        print("\n--- [步骤 1/4] 执行外脑双仓入库 (batch-update) ---")
        try:
            batch_result = cmd_batch_update(batch_args) or {}
        except SystemExit as e:
            batch_result = {"error": f"batch-update exited with code {e.code}"}
        except Exception as e:
            batch_result = {"error": f"batch-update 执行异常: {e}"}
        settle_report["batch"] = batch_result
        if batch_result.get("error"):
            local_failures.append(batch_result["error"])
        if batch_result.get("status_updates_unmatched"):
            local_failures.append(f"掌握度晋级未命中条目: {', '.join(batch_result['status_updates_unmatched'])}")
        if batch_result.get("status_updates_invalid"):
            local_failures.append(f"掌握度晋级载荷非法: {', '.join(batch_result['status_updates_invalid'])}")
        if batch_result.get("new_items_rejected"):
            local_failures.append(f"新条目被准入规则拒绝 {len(batch_result['new_items_rejected'])} 条")
    else:
        print("\n--- [步骤 1/4] 外脑双仓入库: 载荷未提供 batch 段，已跳过 ---")
        settle_report["batch"] = {"status": "skipped", "message": "no batch section"}

    # 2. Archive
    archive_spec = settle_spec.get("archive")
    if archive_spec and str(archive_spec.get("content", "") or "").strip():
        arch_content = str(archive_spec.get("content")).strip()
        arch_meta = archive_spec.get("metadata", {}) or {}
        arch_args = types.SimpleNamespace(
            title=title,
            genre=genre,
            year=year,
            exam_type=exam_type,
            task_id=task_id,
            content=arch_content,
            file=None,
            metadata=json.dumps(arch_meta, ensure_ascii=False) if arch_meta else None,
            metadata_file=None,
            example=False,
            force=False,
        )
        print("\n--- [步骤 2/4] 执行范文与台账归档 (archive) ---")
        try:
            archived_path = cmd_archive(arch_args)
            settle_report["archive"] = {
                "status": "success",
                "path": str(archived_path),
                "title": title,
                "genre": genre,
                "year": year,
                "exam_type": exam_type,
                "word_count": arch_meta.get("word_count"),
            }
        except SystemExit as e:
            local_failures.append(f"范文归档失败 (archive exited with code {e.code})")
            settle_report["archive"] = {"status": "error", "message": f"archive exited with code {e.code}"}
        except Exception as e:
            local_failures.append(f"范文归档异常: {e}")
            settle_report["archive"] = {"status": "error", "message": str(e)}
    else:
        print("\n--- [步骤 2/4] 范文归档: 载荷缺少归档正文，已跳过 ---")
        settle_report["archive"] = {"status": "skipped", "message": "no archive content"}

    # 3. MaiMemo Sync
    memo_spec = settle_spec.get("maimemo")
    if memo_spec and memo_spec.get("words"):
        print("\n--- [步骤 3/4] 执行墨墨背单词专属词本同步 (maimemo-sync) ---")
        try:
            try:
                from maimemo_sync import sync_essay_vocabulary
            except ImportError:
                script_dir = Path(__file__).resolve().parent
                if str(script_dir) not in sys.path:
                    sys.path.insert(0, str(script_dir))
                from maimemo_sync import sync_essay_vocabulary

            memo_payload = {
                "chapter": memo_spec.get("chapter", f"{year}{exam_type}小作文"),
                "task_id": task_id,
                "words": memo_spec.get("words", [])
            }
            token = getattr(args, "token", None) or os.environ.get("MAIMEMO_TOKEN")
            is_mock = getattr(args, "mock", False)
            is_dry_run = getattr(args, "dry_run", False)

            if not token and not is_mock and not is_dry_run:
                print("  [WARN] 未检测到 MAIMEMO_TOKEN 环境变量，已跳过墨墨背单词自动同步。", file=sys.stderr)
                settle_report["maimemo"] = {"status": "skipped", "message": "MAIMEMO_TOKEN not set"}
            else:
                res = sync_essay_vocabulary(memo_payload, token=token, mock=is_mock, dry_run=is_dry_run)
                settle_report["maimemo"] = res
                if res.get("status") == "success":
                    print(f"  [OK] 专属词本: 《{res.get('notepad_title')}》 ➔ 章节 # {res.get('chapter')}")
                    print(f"  [OK] 同步生词: {', '.join(res.get('synced_words', []))}")
                    print(f"  [OK] 专属例句沉淀数: {res.get('phrases_created')} 条 | 借壳助记数: {res.get('notes_created')} 条")
                    print("  [OK] 今日复习流: 已直接注入 (advance=True)")
                    if res.get("skipped_words"):
                        print(f"  [WARN] 未匹配跳过词: {', '.join(res.get('skipped_words'))}", file=sys.stderr)
                else:
                    remote_failures.append(f"墨墨同步未成功（status={res.get('status')}）: {res.get('message')}")
                    print(f"  [FAIL] 墨墨同步失败: {res.get('message')}", file=sys.stderr)
                    if res.get("skipped_words"):
                        print(f"  [FAIL] 未匹配跳过词: {', '.join(res.get('skipped_words'))}", file=sys.stderr)
        except Exception as e:
            print(f"  [FAIL] 墨墨同步执行发生异常: {e}", file=sys.stderr)
            settle_report["maimemo"] = {"status": "error", "message": str(e)}
            remote_failures.append(f"墨墨同步异常: {e}")
    else:
        print("\n--- [步骤 3/4] 墨墨背单词专属词本同步: 未配置或生词列表为空，已跳过 ---")
        settle_report["maimemo"] = {"status": "skipped", "message": "No words provided"}

    # 4. Verify integrity
    print("\n--- [步骤 4/4] 校验知识库外脑一致性 (verify) ---")
    try:
        has_error, user_total = verify_integrity(paths, verbose=True)
    except Exception as e:
        has_error, user_total = True, 0
        local_failures.append(f"一致性校验执行异常: {e}")
    settle_report["verify"] = {
        "passed": not has_error,
        "user_total_entries": user_total
    }
    if has_error:
        local_failures.append("结算后知识库一致性校验未通过")

    print("\n==================== 结算总结卡片 ====================")

    # 本地写入链路失败 -> 整体回滚，保证"要么全成功，要么零变化"
    if local_failures:
        _rollback_and_exit(1, local_failures, "本地沉淀链路失败")

    print("✔ 外脑双仓入库完成")
    print("✔ 范文归档与题目台账登记完成")
    memo_status = (settle_report["maimemo"] or {}).get("status")
    if memo_status == "success":
        print("✔ 墨墨背单词专属词本同步成功 (已注入今日复习流)")
    elif memo_status == "skipped":
        print(f"○ 墨墨背单词同步跳过 ({(settle_report['maimemo'] or {}).get('message')})")
    else:
        print("✗ 墨墨背单词同步未完成（本地沉淀已保留）")
    print(f"✔ 知识库一致性校验通过 (个人外脑有效条目: {user_total} 条，不含只读教研底座)")
    print("======================================================")

    if remote_failures:
        # 远端同步失败不回滚本地成果，但必须以非零退出码与显式 ✗ 告知，杜绝假成功
        settle_report["status"] = "partial"
        settle_report["errors"] = remote_failures
        for item in remote_failures:
            print(f"  ✗ {item}", file=sys.stderr)
        print("  [提示] 本地知识库与归档已落盘，仅墨墨词本同步未完成；可修正后用 `maimemo-sync` 单独重试。", file=sys.stderr)
        if getattr(args, "json", False):
            print(json.dumps(settle_report, ensure_ascii=False, indent=2))
        sys.exit(1)

    if getattr(args, "json", False):
        print(json.dumps(settle_report, ensure_ascii=False, indent=2))

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
    p_query.add_argument("--mine", action="store_true", help="个人外脑全量检索（跨文类召回，阶段1【外脑连接】专用）")
    p_query.add_argument("--match-file", type=str, default=None, help="与 --mine 搭配：传入初稿文件，返回已被初稿命中的外脑资产")
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
    p_arch.add_argument("--force", action="store_true", help="Allow duplicate ledger rows (default: upsert by task_id)")
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
    p_check.add_argument("--genre", type=str, default=None, help="Essay genre (optional; helps pin the mandated signature lookup)")
    p_check.add_argument("--year", type=str, default=None, help="Exam year: look up the mandated signature from anchors for verification")
    p_check.add_argument("--exam-type", type=str, default=None, help="Exam type (1/2/英一/英二/English I/English II) for signature verification")
    p_check.add_argument("--signoff", type=str, default=None, help="Expected signature name (overrides --year/--exam-type lookup)")
    p_check.add_argument("--json", action="store_true", help="Output as JSON")

    # verify
    subparsers.add_parser("verify", help="Verify syntax and integrity of JSONL databases")

    # maimemo-sync
    p_memo = subparsers.add_parser("maimemo-sync", help="Sync essay vocabulary to MaiMemo (墨墨背单词)")
    p_memo.add_argument("--file", type=str, default=None, help="Path to JSON payload file")
    p_memo.add_argument("--token", type=str, default=None, help="MaiMemo API token")
    p_memo.add_argument("--dry-run", action="store_true", help="Dry run without modifying remote MaiMemo data")
    p_memo.add_argument("--mock", action="store_true", help="Mock API responses for offline tests")
    p_memo.add_argument("--example", action="store_true", help="Print payload template and exit")
    p_memo.add_argument("--json", action="store_true", help="Output result as pure JSON")

    # settle
    p_settle = subparsers.add_parser("settle", help="Atomic settlement: batch update KB, archive essay, sync MaiMemo, verify integrity")
    p_settle.add_argument("--file", type=str, default=None, help="Path to settle JSON file")
    p_settle.add_argument("--data", type=str, default=None, help="Raw JSON string for settlement")
    p_settle.add_argument("--token", type=str, default=None, help="MaiMemo API token")
    p_settle.add_argument("--dry-run", action="store_true", help="Dry run without modifying external remote APIs")
    p_settle.add_argument("--mock", action="store_true", help="Mock API responses for offline tests")
    p_settle.add_argument("--example", action="store_true", help="Print sample settle JSON and exit")
    p_settle.add_argument("--json", action="store_true", help="Output result as pure JSON")

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
    elif args.command == "maimemo-sync":
        cmd_maimemo_sync(args)
    elif args.command == "settle":
        cmd_settle(args)

if __name__ == "__main__":
    main()
