#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
maimemo_sync.py - MaiMemo (墨墨背单词) Sync Engine for Kaoyan Practical Writing

Tailored and self-contained specifically for kaoyan writing vocabulary retention:
  1. Resolves vocabulary IDs via POST /vocabulary/query
  2. Creates or updates the dedicated notepad 《我的考研作文》 with chapter '# [真题章节]'
  3. Creates example phrases with sentence context and exact character highlight ranges
  4. Generates deep "borrowed-shell" writing mnemonics (spelling correction + usage + syntax breakdown)
  5. Pushes words into today's immediate review stream (POST /study/add_words with advance: true)
"""

import os
import sys
import json
import time
import re
import argparse
import urllib.request
import urllib.error

# Force UTF-8 stdout/stderr on Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

MAIMEMO_BASE_URL = "https://open.maimemo.com/open/api/v1"
DEFAULT_NOTEPAD_TITLE = "我的考研作文"
DEFAULT_NOTEPAD_BRIEF = "考研英语小作文实战生词与错词集"

# 官方频控契约（references/maimemo_api.md）：20 次/10 秒、40 次/60 秒、2000 次/5 小时
RATE_LIMITS = ((20, 10.0), (40, 60.0), (2000, 5 * 3600.0))
MIN_CALL_GAP = 0.5  # 20 次/10 秒 ⇒ 平均 0.5 秒一次，留出安全余量


def find_word_highlight_ranges(sentence: str, spelling: str) -> list:
    """
    Calculate character offset [start, end) for target spelling in sentence.
    Handles case-insensitivity, common inflections. Returns [] when the target
    word is absent: 绝不回落高亮句首，避免给学生错误的"目标词位置"。
    """
    if not sentence or not spelling:
        return []

    clean_spelling = spelling.strip()

    # 1. Exact boundary match (case-insensitive)
    pattern = rf"\b{re.escape(clean_spelling)}\b"
    matches = list(re.finditer(pattern, sentence, re.IGNORECASE))
    if matches:
        m = matches[0]
        return [{"start": m.start(), "end": m.end()}]

    # 2. Inflection stem match (e.g. accommodate -> accommodating / accommodated / accommodates)
    stem = clean_spelling
    if len(clean_spelling) > 4:
        if clean_spelling.endswith("e"):
            stem = clean_spelling[:-1]
        elif clean_spelling.endswith(("ed", "es", "ly")):
            stem = clean_spelling[:-2]
        elif clean_spelling.endswith("ing"):
            stem = clean_spelling[:-3]

    inflection_pattern = rf"\b{re.escape(stem)}[a-zA-Z]*\b"
    matches = list(re.finditer(inflection_pattern, sentence, re.IGNORECASE))
    if matches:
        m = matches[0]
        return [{"start": m.start(), "end": m.end()}]

    # 3. Substring match fallback
    idx = sentence.lower().find(clean_spelling.lower())
    if idx != -1:
        return [{"start": idx, "end": idx + len(clean_spelling)}]

    # 4. 未命中：返回空列表，由调用方决定不带 highlight 建句或跳过
    return []


def update_notepad_content(existing_content: str, chapter_name: str, new_words: list) -> str:
    """
    Update notepad content with chapter and words.
    Avoids duplicate chapters or duplicate words within the same chapter.
    Preserves all existing notepad content and chapters.
    """
    clean_chapter = chapter_name.strip().lstrip("#").strip()
    chapter_header = f"# {clean_chapter}"
    words_to_add = [w.strip() for w in new_words if w.strip()]

    if not existing_content or not existing_content.strip():
        # Brand new notepad content
        lines = [chapter_header] + words_to_add
        return "\n".join(lines).strip()

    content = existing_content.strip()
    lines = content.split("\n")

    # Locate chapter if already exists
    chapter_idx = -1
    for i, line in enumerate(lines):
        line_clean = line.strip().lstrip("#").strip()
        if line.strip().startswith("#") and line_clean.lower() == clean_chapter.lower():
            chapter_idx = i
            break

    if chapter_idx == -1:
        # Chapter does not exist: append to bottom
        add_lines = ["", chapter_header] + words_to_add
        return (content + "\n" + "\n".join(add_lines)).strip()

    # Chapter exists: find end of current chapter (next '#' or end of content)
    next_chapter_idx = len(lines)
    for i in range(chapter_idx + 1, len(lines)):
        if lines[i].strip().startswith("#"):
            next_chapter_idx = i
            break

    # Collect existing words in this chapter
    existing_in_chapter = set()
    for i in range(chapter_idx + 1, next_chapter_idx):
        w = lines[i].strip()
        if w and not w.startswith("#"):
            existing_in_chapter.add(w.lower())

    # Add only non-duplicate words
    filtered_new = [w for w in words_to_add if w.lower() not in existing_in_chapter]
    if not filtered_new:
        return content  # Nothing new to add

    # Insert new words before next chapter or at end
    lines = lines[:next_chapter_idx] + filtered_new + lines[next_chapter_idx:]
    return "\n".join(lines).strip()


def format_mnemonic_note(word_data: dict) -> str:
    """
    Format 'borrowed-shell' writing mnemonic note.
    Includes spelling fix explanation if applicable, kaoyan writing usage, and syntax breakdown.
    """
    parts = []
    
    # 1. Spelling fix part
    is_spelling_fix = word_data.get("type") == "spelling_fix" or bool(word_data.get("misspelling"))
    if is_spelling_fix:
        mis = word_data.get("misspelling", "初稿拼写")
        correct = word_data.get("spelling", "")
        parts.append(f"【初稿纠偏】：初稿误拼为 {mis}，正确拼写为 {correct}（考场务必防范拼写扣分）！")

    # 2. Kaoyan writing usage part
    usage = word_data.get("usage_note", "").strip()
    if usage:
        parts.append(f"【考研写作用法】：{usage}")

    # 3. Sentence grammar / syntax breakdown part
    grammar = word_data.get("grammar_note", "").strip()
    if grammar:
        parts.append(f"【原句语法剖析】：{grammar}")

    if not parts:
        parts.append(f"【考研写作实战】：收录于考研小作文高分范文核心表达。")

    return "\n".join(parts)


class MaimemoClient:
    """
    Lightweight, self-contained MaiMemo API Client with zero third-party dependencies.
    """
    def __init__(self, token: str = None, base_url: str = MAIMEMO_BASE_URL, mock: bool = False, dry_run: bool = False):
        self.token = token if token is not None else os.environ.get("MAIMEMO_TOKEN", "")
        self.base_url = base_url.rstrip("/")
        self.mock = mock
        self.dry_run = dry_run
        self.last_req_time = 0.0
        self._call_times = []

    def _throttle(self):
        """滑动窗口限流：严格执行 20 次/10 秒、40 次/60 秒、2000 次/5 小时。"""
        now = time.time()
        five_hours = 5 * 3600.0
        self._call_times = [t for t in self._call_times if now - t < five_hours]
        for limit, window in RATE_LIMITS:
            while True:
                recent = [t for t in self._call_times if now - t < window]
                if len(recent) < limit:
                    break
                sleep_for = window - (now - min(recent)) + 0.05
                time.sleep(max(0.05, sleep_for))
                now = time.time()
        if self._call_times and now - self._call_times[-1] < MIN_CALL_GAP:
            time.sleep(MIN_CALL_GAP - (now - self._call_times[-1]))
            now = time.time()
        self._call_times.append(now)
        self.last_req_time = now

    def request(self, method: str, path: str, body: dict = None) -> dict:
        """Execute HTTP request against MaiMemo Open API"""
        if self.mock:
            return self._mock_response(method, path, body)

        if not self.token:
            raise ValueError(
                "MAIMEMO_TOKEN 未设置！请配置环境变量 MAIMEMO_TOKEN 或通过 --token 传入。\n"
                "获取方式：墨墨背单词 App → 设置 → 开放 API 或打开 https://open.maimemo.com/open/api/v1/tokens/openapi 复制 Token。"
            )

        if self.dry_run and method != "GET":
            return {"status": "dry_run_success", "mock": True}

        self._throttle()
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": "FreeKaoyanWritingCoach/1.0"
        }
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_bytes = resp.read()
                if not resp_bytes:
                    return {}
                return json.loads(resp_bytes.decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass
            
            # Rate limit backoff
            if e.code == 429:
                time.sleep(2.0)
                try:
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        return json.loads(resp.read().decode("utf-8"))
                except Exception:
                    pass
            
            raise RuntimeError(f"MaiMemo API 请求失败 [{e.code}]: {error_body or e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"MaiMemo API 网络连接失败: {e.reason}")

    @staticmethod
    def _unwrap_data(resp: dict) -> dict:
        """Unwrap 'data' payload from MaiMemo Open API response if present."""
        if isinstance(resp, dict) and "data" in resp and isinstance(resp["data"], dict):
            return resp["data"]
        return resp

    def _mock_response(self, method: str, path: str, body: dict = None) -> dict:
        """Provide deterministic mock responses for offline unit tests (aligned with real API data wrapping)"""
        if path == "/vocabulary/query":
            spellings = (body or {}).get("spellings", [])
            voc_list = [{"id": f"voc_mock_{w}", "spelling": w} for w in spellings]
            return {"success": True, "data": {"voc": voc_list}, "errors": []}
        elif path.startswith("/notepads") and method == "GET":
            if path == "/notepads?limit=50&offset=0":
                return {
                    "success": True,
                    "data": {
                        "notepads": [
                            {
                                "id": "np_mock_1",
                                "title": DEFAULT_NOTEPAD_TITLE,
                                "brief": DEFAULT_NOTEPAD_BRIEF,
                                "tags": ["考研"],
                                "status": "PUBLISHED"
                            }
                        ]
                    },
                    "errors": []
                }
            else:
                return {
                    "success": True,
                    "data": {
                        "notepad": {
                            "id": "np_mock_1",
                            "title": DEFAULT_NOTEPAD_TITLE,
                            "brief": DEFAULT_NOTEPAD_BRIEF,
                            "tags": ["考研"],
                            "content": "# 2010英一小作文\nsuggest\nrecommend",
                            "status": "PUBLISHED"
                        }
                    },
                    "errors": []
                }
        elif path == "/notepads" and method == "POST":
            return {"success": True, "data": {"id": "np_mock_new", "notepad": {"id": "np_mock_new", **(body.get("notepad", {}))}}, "errors": []}
        elif path.startswith("/notepads/") and method == "POST":
            np_id = path.split("/")[-1]
            return {"success": True, "data": {"id": np_id, "notepad": {"id": np_id, **(body.get("notepad", {}))}}, "errors": []}
        elif path == "/phrases" and method == "POST":
            return {"success": True, "data": {"id": "ph_mock_1", "phrase": {"id": "ph_mock_1", **(body.get("phrase", {}))}}, "errors": []}
        elif path == "/notes" and method == "POST":
            return {"success": True, "data": {"id": "nt_mock_1", "note": {"id": "nt_mock_1", **(body.get("note", {}))}}, "errors": []}
        elif path == "/study/add_words" and method == "POST":
            words = (body or {}).get("words", [])
            return {"success": True, "data": {"added_count": len(words)}, "errors": []}
        return {"success": True, "data": {}, "errors": []}

    def query_vocabulary_ids(self, spellings: list) -> dict:
        """Batch query voc_id for a list of spellings. Returns {spelling.lower(): voc_id}."""
        if not spellings:
            return {}
        clean_spellings = list({s.strip() for s in spellings if s.strip()})
        resp = self.request("POST", "/vocabulary/query", {"spellings": clean_spellings})
        data = self._unwrap_data(resp)
        voc_items = data.get("voc", [])
        return {item["spelling"].lower(): item["id"] for item in voc_items if "spelling" in item and "id" in item}

    def sync_notepad(self, title: str, chapter: str, words: list) -> dict:
        """Create or update chapter in notepad 《我的考研作文》."""
        resp = self.request("GET", "/notepads?limit=50&offset=0")
        data = self._unwrap_data(resp)
        notepads = data.get("notepads", [])
        
        target_np = None
        for np in notepads:
            if np.get("title") == title and np.get("status") != "DELETED":
                target_np = np
                break

        if not target_np:
            # Create new notepad
            content = update_notepad_content("", chapter, words)
            create_body = {
                "notepad": {
                    "title": title,
                    "brief": DEFAULT_NOTEPAD_BRIEF,
                    "content": content,
                    "tags": ["考研"],
                    "status": "PUBLISHED"
                }
            }
            res = self.request("POST", "/notepads", create_body)
            res_data = self._unwrap_data(res)
            return {"action": "created", "notepad": res_data.get("notepad", res_data)}
        else:
            # Update existing notepad
            np_id = target_np["id"]
            detail = self.request("GET", f"/notepads/{np_id}")
            detail_data = self._unwrap_data(detail)
            existing_content = detail_data.get("notepad", {}).get("content", "") or detail_data.get("content", "")
            updated_content = update_notepad_content(existing_content, chapter, words)
            update_body = {
                "notepad": {
                    "title": target_np.get("title", title),
                    "brief": target_np.get("brief", DEFAULT_NOTEPAD_BRIEF),
                    "content": updated_content,
                    "tags": target_np.get("tags", ["考研"]),
                    "status": "PUBLISHED"
                }
            }
            res = self.request("POST", f"/notepads/{np_id}", update_body)
            res_data = self._unwrap_data(res)
            return {"action": "updated", "notepad": res_data.get("notepad", res_data)}

    def create_example_phrase(self, voc_id: str, sentence: str, translation: str, chapter: str, spelling: str) -> dict:
        """Create custom example phrase with target word highlighted (no highlight when absent)."""
        highlight = find_word_highlight_ranges(sentence, spelling)
        origin_str = f"{chapter}实战" if chapter else "考研作文实战"
        phrase_body = {
            "voc_id": voc_id,
            "phrase": sentence,
            "interpretation": translation or "考研作文实战例句",
            "tags": ["考研"],
            "origin": origin_str,
        }
        if highlight:
            phrase_body["highlight"] = highlight
        return self.request("POST", "/phrases", {"phrase": phrase_body})

    def create_mnemonic_note(self, voc_id: str, note_text: str) -> dict:
        """Create mnemonic note with note_type: '语法'."""
        body = {
            "note": {
                "voc_id": voc_id,
                "note_type": "语法",
                "note": note_text
            }
        }
        return self.request("POST", "/notes", body)

    def add_to_today_review(self, voc_ids: list, advance: bool = True) -> dict:
        """Add words to study plan and advance to immediate review."""
        if not voc_ids:
            return {"added_count": 0}
        body = {
            "words": [{"id": vid} for vid in voc_ids],
            "advance": advance
        }
        resp = self.request("POST", "/study/add_words", body)
        data = self._unwrap_data(resp)
        return data if isinstance(data, dict) else {"added_count": len(voc_ids)}


def sync_essay_vocabulary(payload: dict, token: str = None, mock: bool = False, dry_run: bool = False) -> dict:
    """
    Main orchestration function to sync kaoyan essay vocabulary into MaiMemo App.
    """
    chapter = payload.get("chapter", "考研小作文实战").strip()
    words = payload.get("words", [])
    if not words:
        return {"status": "skipped", "message": "待同步生词列表为空，已跳过。"}

    # 0. 载荷内去重：同一 spelling 只同步一次，避免重复建例句/助记
    seen_spellings = set()
    unique_words = []
    for w in words:
        sp = str(w.get("spelling", "")).strip().lower()
        if not sp or sp in seen_spellings:
            continue
        seen_spellings.add(sp)
        unique_words.append(w)
    words = unique_words

    client = MaimemoClient(token=token, mock=mock, dry_run=dry_run)

    # 1. Resolve vocabulary IDs in batch
    spellings = [w.get("spelling", "").strip() for w in words if w.get("spelling")]
    voc_map = client.query_vocabulary_ids(spellings)

    matched_words = []
    skipped_words = []
    for w in words:
        spelling = w.get("spelling", "").strip()
        vid = voc_map.get(spelling.lower())
        if vid:
            matched_words.append({**w, "voc_id": vid})
        else:
            skipped_words.append(spelling)

    if not matched_words:
        return {
            "status": "partial_failed",
            "message": f"所选单词均未能匹配到墨墨官方词库 ID：{', '.join(skipped_words)}",
            "skipped_words": skipped_words
        }

    # 2. Update cloud notepad 《我的考研作文》
    valid_spellings = [w["spelling"] for w in matched_words]
    np_res = client.sync_notepad(DEFAULT_NOTEPAD_TITLE, chapter, valid_spellings)

    # 3. Create example phrases & 4. Create mnemonic notes
    phrase_count = 0
    note_count = 0
    phrase_failures = []
    note_failures = []
    highlight_missing = []
    for w in matched_words:
        vid = w["voc_id"]
        spelling = w["spelling"]
        sentence = w.get("sentence", "")
        translation = w.get("translation", "")

        # 3. Phrase creation
        if sentence:
            if not find_word_highlight_ranges(sentence, spelling):
                highlight_missing.append(spelling)
            try:
                client.create_example_phrase(vid, sentence, translation, chapter, spelling)
                phrase_count += 1
            except Exception as e:
                phrase_failures.append(f"{spelling}: {e}")

        # 4. Note creation
        note_text = format_mnemonic_note(w)
        try:
            client.create_mnemonic_note(vid, note_text)
            note_count += 1
        except Exception as e:
            note_failures.append(f"{spelling}: {e}")

    # 5. Push words to study plan and immediate review
    vids = [w["voc_id"] for w in matched_words]
    study_res = client.add_to_today_review(vids, advance=True)

    # 6. 部分失败显式化：绝不把"0 条例句"包装成 success
    expected_phrases = len([w for w in matched_words if w.get("sentence")])
    status = "success"
    message = ""
    if phrase_failures and phrase_count == 0 and expected_phrases > 0:
        status = "partial_failed"
        message = f"例句创建全部失败（{len(phrase_failures)} 条）：{'; '.join(phrase_failures[:3])}"
    elif phrase_failures or note_failures:
        message = (f"部分例句/助记创建失败：例句失败 {len(phrase_failures)} 条，"
                   f"助记失败 {len(note_failures)} 条")
        status = "partial_failed"

    return {
        "status": status,
        "message": message,
        "notepad_title": DEFAULT_NOTEPAD_TITLE,
        "chapter": chapter,
        "notepad_action": (np_res or {}).get("action"),
        "synced_words": [w["spelling"] for w in matched_words],
        "skipped_words": skipped_words,
        "phrases_created": phrase_count,
        "phrases_failed": len(phrase_failures),
        "notes_created": note_count,
        "notes_failed": len(note_failures),
        "highlight_missing": highlight_missing,
        "failure_details": (phrase_failures + note_failures)[:5],
        "study_advance": True,
        "added_count": study_res.get("added_count", len(vids))
    }


def main():
    parser = argparse.ArgumentParser(description="MaiMemo Sync Engine for Kaoyan Practical Writing")
    parser.add_argument("--file", type=str, default=None, help="Path to JSON payload file")
    parser.add_argument("--token", type=str, default=None, help="MaiMemo API token")
    parser.add_argument("--dry-run", action="store_true", help="Dry run without modifying remote MaiMemo data")
    parser.add_argument("--mock", action="store_true", help="Mock API responses for offline tests")
    parser.add_argument("--example", action="store_true", help="Print payload template and exit")
    parser.add_argument("--json", action="store_true", help="Output result as pure JSON")

    args = parser.parse_args()

    if args.example:
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
        parser.error("必须通过 --file 指定 JSON 载荷文件路径，或使用 --example 查看样例")

    with open(args.file, "r", encoding="utf-8") as f:
        payload = json.load(f)

    try:
        res = sync_essay_vocabulary(payload, token=args.token, mock=args.mock, dry_run=args.dry_run)
        if res.get("status") in ("partial_failed", "error"):
            if args.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(f"[ERROR] 墨墨同步失败: {res.get('message')}", file=sys.stderr)
                if res.get("skipped_words"):
                    print(f"未匹配跳过: {', '.join(res.get('skipped_words', []))}", file=sys.stderr)
            sys.exit(1)
        elif res.get("status") == "skipped":
            if args.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(f"[INFO] {res.get('message')}")
            return
        elif args.json:
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
        if args.json:
            print(json.dumps({"status": "error", "message": err_msg}, ensure_ascii=False))
        else:
            print(f"同步失败: {err_msg}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
