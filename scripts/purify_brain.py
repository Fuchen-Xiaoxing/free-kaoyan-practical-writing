#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
purify_brain.py - 写作外脑教研底座种子剥离与纯净化工具

功能：
  1. 彻底剥离用户个人外脑中混入的 55 条小作文出厂表达和 24 条共享场景语素底座种子（僵尸条目）；
  2. 精准保留用户在实战演练中真实学过、确认入库的实战资产（含 evidence_tasks 或非未接触掌握度）；
  3. 将新手或未实战外脑还原为 100% 干净白纸（0 条记录）；
  4. 支持单目录指定与全量扫描治理（--scan-all / --path / --dry-run）。
"""

import os
import sys
import json
import argparse
import datetime
from pathlib import Path
import shutil

# Ensure UTF-8 output
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
SEEDS_DIR = REPO_ROOT / "free-kaoyan-practical-writing" / "knowledge_base" / "seeds"
if not SEEDS_DIR.exists():
    SEEDS_DIR = REPO_ROOT / "knowledge_base" / "seeds"

def read_jsonl(path: Path):
    if not path.exists():
        return []
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass
    return records

def write_jsonl(path: Path, records: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

def is_real_practice_item(item: dict) -> bool:
    """判定条目是否为用户真实实战演练沉淀的资产（非出厂僵尸条目）"""
    # 1. 显式实战任务凭证
    evidence_tasks = item.get("evidence_tasks") or []
    if isinstance(evidence_tasks, str):
        evidence_tasks = [evidence_tasks]
    real_tasks = [t for t in evidence_tasks if t and not t.startswith("T-TEST")]
    if real_tasks:
        return True

    # 2. 来源中含有实战标记
    source = str(item.get("source", "")).lower()
    if "实战" in source or "升华" in source or "用户自选" in source or "初稿" in source or "纠偏" in source:
        return True

    # 3. 掌握度已被用户明确提升过（非出厂默认未接触）
    mastery = item.get("mastery", "未接触")
    if mastery in ("稳定", "敢用", "学习中"):
        # 排除完全未经使用的初始学习中状态且无实战凭证的条目
        hist = item.get("history", {})
        if isinstance(hist, dict) and hist.get("used_count", 0) > 0:
            return True
        if "实战" in source:
            return True

    return False

def purify_single_brain(brain_root: Path, dry_run: bool = False) -> dict:
    """净化单个外脑目录"""
    brain_root = brain_root.resolve()
    if not brain_root.exists():
        return {"status": "not_found", "path": str(brain_root)}

    # 探测 user_brain 子目录
    if (brain_root / "user_brain").exists() and (brain_root / "user_brain").is_dir():
        ub_dir = brain_root / "user_brain"
    elif brain_root.name == "user_brain":
        ub_dir = brain_root
    else:
        ub_dir = brain_root

    # 待检查文件清单
    files_to_check = {
        "shared": [
            ub_dir / "shared" / "morphemes.jsonl",
            brain_root / "shared" / "morphemes.jsonl"
        ],
        "task1": [
            ub_dir / "task1" / "expressions.jsonl",
            brain_root / "task1" / "expressions.jsonl",
            ub_dir / "task1_expressions.jsonl",
            brain_root / "task1_expressions.jsonl"
        ]
    }

    report = {
        "path": str(brain_root),
        "shared_before": 0,
        "shared_after": 0,
        "shared_purged": 0,
        "task1_before": 0,
        "task1_after": 0,
        "task1_purged": 0,
        "dry_run": dry_run
    }

    now_iso = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. 净化 shared 语素仓
    seen_shared_paths = set()
    for s_path in files_to_check["shared"]:
        if s_path.exists() and str(s_path) not in seen_shared_paths:
            seen_shared_paths.add(str(s_path))
            records = read_jsonl(s_path)
            report["shared_before"] += len(records)
            kept = [r for r in records if is_real_practice_item(r)]
            purged_count = len(records) - len(kept)
            report["shared_purged"] += purged_count
            report["shared_after"] += len(kept)

            if not dry_run:
                write_jsonl(s_path, kept)

    # 2. 净化 task1 表达仓
    seen_t1_paths = set()
    for t_path in files_to_check["task1"]:
        if t_path.exists() and str(t_path) not in seen_t1_paths:
            seen_t1_paths.add(str(t_path))
            records = read_jsonl(t_path)
            report["task1_before"] += len(records)
            kept = [r for r in records if is_real_practice_item(r)]
            purged_count = len(records) - len(kept)
            report["task1_purged"] += purged_count
            report["task1_after"] += len(kept)

            if not dry_run:
                write_jsonl(t_path, kept)

    # 3. 记录日志与元数据
    if not dry_run:
        hist_file = ub_dir / "history.log"
        if not hist_file.exists() and (brain_root / "history.log").exists():
            hist_file = brain_root / "history.log"
        
        if hist_file.parent.exists():
            entry = {
                "ts": now_iso,
                "op": "purify",
                "id": "SYS_PURIFY",
                "before": f"shared:{report['shared_before']}, task1:{report['task1_before']}",
                "after": f"shared:{report['shared_after']}, task1:{report['task1_after']}",
                "reason": f"彻底剥离教研底座种子，净化个人外脑（剔除 {report['shared_purged'] + report['task1_purged']} 条出厂僵尸条目，保留 {report['shared_after'] + report['task1_after']} 条实战确认条目）",
                "task_id": ""
            }
            with open(hist_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # 更新 .kb_meta.json
        meta_file = brain_root / ".kb_meta.json"
        if not meta_file.exists() and (ub_dir / ".kb_meta.json").exists():
            meta_file = ub_dir / ".kb_meta.json"
        try:
            meta = {}
            if meta_file.exists():
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            meta.update({
                "purified_at": now_iso,
                "decoupled_seeds": True,
                "clean_factory": True,
                "version": "2.0.0"
            })
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return report

def main():
    parser = argparse.ArgumentParser(description="写作外脑底座种子剥离与纯净化工具")
    parser.add_argument("--path", type=str, default=None, help="指定待净化的外脑目录路径")
    parser.add_argument("--scan-all", action="store_true", help="自动扫描并净化所有已知外脑存储路径")
    parser.add_argument("--dry-run", action="store_true", help="试运行预览，不实际修改文件")

    args = parser.parse_args()

    targets = []
    if args.path:
        targets.append(Path(args.path).expanduser().resolve())
    elif args.scan_all:
        home = Path.home()
        candidates = [
            home / "Documents" / "考研英语" / "写作外脑",
            REPO_ROOT / "_-78acc925" / "写作外脑",
            REPO_ROOT / "_-78acc925" / "写作外脑" / "写作外脑",
            REPO_ROOT / "free-kaoyan-practical-writing" / "knowledge_base" / "user_brain",
            REPO_ROOT / "knowledge_base" / "user_brain",
            Path("/var/minis/mounts/Documents/考研英语/写作外脑"),
            Path("/var/minis/workspace/考研英语/写作外脑")
        ]
        for c in candidates:
            if c.exists():
                targets.append(c)

    if not targets:
        print("[ERROR] 未指定外脑路径。请使用 --path <dir> 或 --scan-all 参数。", file=sys.stderr)
        sys.exit(1)

    print("==================== 写作外脑底座种子彻底剥离与净化 ====================")
    if args.dry_run:
        print("[提示] 当前为试运行模式 (--dry-run)，不实际写入文件。\n")

    for t in targets:
        rep = purify_single_brain(t, dry_run=args.dry_run)
        print(f"• 扫描目标: {rep['path']}")
        print(f"  - 共享场景语素仓 (shared): 原有 {rep['shared_before']} 条 ➔ 剔除僵尸种子 {rep['shared_purged']} 条 ➔ 保留实战 {rep['shared_after']} 条")
        print(f"  - 小作文专属表达仓 (task1): 原有 {rep['task1_before']} 条 ➔ 剔除僵尸种子 {rep['task1_purged']} 条 ➔ 保留实战 {rep['task1_after']} 条")
        total_kept = rep['shared_after'] + rep['task1_after']
        if total_kept == 0:
            print(f"  ➔ 状态: 【100% 纯净白纸】(0 记录已就绪，坐等实战表达沉淀)")
        else:
            print(f"  ➔ 状态: 【高精纯实战外脑】(成功脱壳剥离，保留 {total_kept} 条真实演练条目)")
        print()

    print("=============================== 净化完成 ===============================")

if __name__ == "__main__":
    main()
