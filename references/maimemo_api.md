# MaiMemo (墨墨背单词) Open API 裁剪规范与接口契约

本文档为考研英语小作文私教专用的墨墨背单词 Open API 裁剪规范。根据用户教学实战决议，**例句创建 (`POST /phrases`) 默认彻底停用**，仅聚焦与写作实战沉淀最核心的 4 项能力（生词解析、云词本维护、深度语法助记、加入今日复习），完全自包含于本 Skill 内部。

---

## 一、基础配置与认证

- **Base URL**: `https://open.maimemo.com/open/api/v1`
- **认证方式**: HTTP 请求头 `Authorization: Bearer $MAIMEMO_SPELLING_TOKEN`
- **账号隔离契约**:
  - 本 Skill（考研小作文）专职服务【背单词拼写】，绑定**拼写背单词账号**，使用环境变量 **`$MAIMEMO_SPELLING_TOKEN`**；
  - 考研英语阅读 Skill 保持独立，绑定**识记背单词账号**（只要求认识不要求拼写），使用环境变量 **`$MAIMEMO_TOKEN`**；
  - 两者 Token 与账号完全物理隔离，本 Skill 绝不回退读取 `$MAIMEMO_TOKEN`，杜绝串号污染。
- **Token 来源**:
  - 手机 App: 使用【拼写背单词专用账号】登录墨墨背单词 → 设置 → 开放 API
  - Web 端: 打开 `https://open.maimemo.com/open/api/v1/tokens/openapi` 登录该账号后复制 Token
- **Token 缺省处理**: 若未设置环境变量 `$MAIMEMO_SPELLING_TOKEN`，系统提示用户获取并配置，不阻断写作主流程。
- **频控限制 (Rate Limits)**:
  - 20 次 / 10 秒
  - 40 次 / 60 秒
  - 2000 次 / 5 小时
  *(注: 本 Skill 每次写作结算仅涉及 3~8 个生词，脚本内部已内置**滑动窗口限流器**，严格执行上述三档上限并保持平均 ≥0.5 秒/次的调用间隔，确保安全不超频；命中 429 后退避重试一次。)*
- **失败语义 (Failure Contract)**:
  - 返回 `status="success"` 才算真正同步成功；
  - 单词全部未匹配、或存在助记创建失败 → `status="partial_failed"`，并在 `message` / `failure_details` 中给出原因，命令以**非零退出码**终止；
  - **例句创建默认跳过**：`sync_phrases` 默认为 `False`，不发起 `/phrases` 请求，不尝试写例句，零 403 风险，`phrases_created: 0` 为标准正常表现；
  - 载荷内重复 `spelling` 自动去重；同一章节内已存在的单词不重复写入词本；
  - **跨次幂等**：以"该词是否已存在于目标章节"为已同步凭证。重复同步同一章节时，已存在的词记为 `already_synced_words`，**不重复创建助记**（`POST /notes` 每次调用都会新建对象，否则会在学生账号里堆出重复词卡）；仅补建缺失卡片，且只把本次新建的词推入复习流；
  - `remote_side_effects` 字段显式声明本次已发生的远端写入（词本更新 / 复习流推送），提醒"远端写入不可撤销"。

---

## 二、裁剪保留的 5 大核心端点

### 1. 单词查询与 voc_id 解析 (`POST /vocabulary/query`)
- **作用**: 批量将用户初稿纠正后的单词或高阶生词解析为墨墨内部唯一的 `voc_id`。
- **请求体**:
  ```json
  {
    "spellings": ["accommodate", "prolong"]
  }
  ```
- **响应体**:
  ```json
  {
    "data": {
      "voc": [
        {"id": "voc_12345", "spelling": "accommodate"},
        {"id": "voc_67890", "spelling": "prolong"}
      ]
    }
  }
  ```
- **异常处理**: 若生词拼写在墨墨官方词库中不存在，脚本记录该词并跳过后续例句/助记创建，保障整批任务稳定。

---

### 2. 云词本自动化维护 (`/notepads`)
- **专属词本名称**: 《我的考研作文》
- **词本标签**: `["考研"]`
- **章节命名规范**: `# [真题年份][卷别]小作文`（如 `# 2011英二小作文`，自拟题如 `# 自拟-图书馆服务小作文`）
- **操作逻辑**:
  1. `GET /notepads?limit=10&offset=0`：查询是否已有《我的考研作文》（墨墨 API 严格限制 `limit <= 10`，若大于 10 将直接抛 HTTP 400 错误；脚本内部使用 10 步进的分页循环扫描，最大检索 200 个云词本）；
  2. 若不存在，调用 `POST /notepads` 创建全新词本：
     ```json
     {
       "notepad": {
         "title": "我的考研作文",
         "brief": "考研英语小作文实战生词与错词集",
         "content": "# 2011英二小作文\naccommodate\nprolong",
         "tags": ["考研"],
         "status": "PUBLISHED"
       }
     }
     ```
  3. 若已存在，调用 `GET /notepads/{id}` 获取原内容，检查目标章节：
     - 若章节不存在：追加 `\n\n# 2011英二小作文\n` 及新词；
     - 若章节已存在：在该章节下方追加新词（已存在于该章节的单词自动去重，不重复添加）；
     - 调用 `POST /notepads/{id}` 更新内容。

---

### 3. 作文原句专属例句与字符高亮 (`POST /phrases`) [教学法默认停用 / DEPRECATED BY POLICY]
- **政策决议与背景**:
  - 用户明确指示：“**墨墨背单词不需要改例句了，不用每次都尝试了，只需要改助记即可。**”
  - 因此同步模块默认设置 `sync_phrases: bool = False`。同步流程完全跳过 `/phrases` 请求，彻底免除 403 权限受限风险与 API 额度浪费，无需任何权限降级等待。
  - 作文原句与其主干/修饰成分剖析已完整内嵌在“借壳”写作深度助记（`/notes`）中，在 App 内查看单词助记时即可全面复习原句。
- **底层兼容保留（Opt-in）**:
  - 仅当明确传入 `--sync-phrases` 参数或调用函数时显式设置 `sync_phrases=True` 时，才会激活例句写入。
  - 底层仍保留半开区间 `[start, end)` 字符高亮算法与 `highlight_missing` 缺失检测。
- **请求体（仅开启时有效）**:
  ```json
  {
    "phrase": {
      "voc_id": "voc_12345",
      "phrase": "The library is expected to prolong opening hours to accommodate students.",
      "interpretation": "图书馆预计将延长开放时间以方便/容纳学生。",
      "tags": ["考研"],
      "origin": "2011英二小作文实战",
      "highlight": [
        {"start": 52, "end": 63}
      ]
    }
  }
  ```

---

### 4. “借壳”写作深度助记 (`POST /notes`)
- **作用**: 点开助记卡片不是网上的搞笑段子，而是考研写作用法与原句语法拆解。
- **类型参数 (`note_type`)**: 统一固定为 `"语法"`。
- **助记内容规范**（纯文本三段式，禁用 Markdown 标题）:
  - **初稿拼错词**：`【初稿纠偏】：初稿误拼为 <错拼>，正确拼写为 <正拼>（考场务必防范拼写扣分）！` + `【考研写作用法】：词性、高频搭配、可替换的普通表达` + `【原句语法剖析】：作文原句的主干与修饰成分拆解`。
  - **范文高阶生词**：`【考研写作用法】：及物性与高频搭配，说明比某常见词更严谨书面` + `【原句语法剖析】：该词在范文原句中所充当的成分与形成的搭配`。
- **请求体**:
  ```json
  {
    "note": {
      "voc_id": "voc_12345",
      "note_type": "语法",
      "note": "..."
    }
  }
  ```

---

### 5. 立刻推入今日复习流 (`POST /study/add_words`)
- **作用**: 无视等级门槛，直接将本次沉淀的生词加入用户当天的复习队列，打开 App 即可立即刷到。
- **请求体**:
  ```json
  {
    "words": [
      {"id": "voc_12345"},
      {"id": "voc_67890"}
    ],
    "advance": true
  }
  ```
- **特性**: `"advance": true` 会同时触发提前复习（无需用户达到 10 级），当天复习队列立即可见。

---

## 三、结算数据载荷契约（`settle` 载荷内的 `maimemo` 段）

> **常规业务只走 `settle`**：阶段 3 用户确认后，把完整结算载荷写进工作区文件（推荐 `/var/minis/workspace/kaoyan/settle.json`，或当前目录 `settle.json`），由 `python3 kb_manager.py settle --file settle.json` 原子化提交，**严禁在 settle 前运行任何零散多余指令**。
>
> 独立载荷**仅供排错与单点重试**（例如仅墨墨同步因网络抖动中断）：
> - `maimemo-sync` 现已**原生支持自动解包嵌套 `settle.json`**：直接执行 `python3 kb_manager.py maimemo-sync --file settle.json` 即可（会自动提取其中的 `maimemo` 段和顶层 `task_id`，缺省自动降级为 `task_id="manual"`），**严禁额外编写脚本手动剥离 JSON 字段**！
> - 该独立入口全幂等，重复执行绝不产生重复词卡。

**载荷字段**（与 SKILL.md §四 的 `settle` 载荷 `maimemo` 段完全一致，完整示例见该处）：

- `chapter`：章节名，如 `2011英二小作文`；
- `words[]`：`spelling`（必填）、`type`（`spelling_fix` 或 `advanced_vocab`）、`misspelling`（纠偏卡必填）、`sentence`（作文原句）、`translation`、`usage_note`（考研写作用法）、`grammar_note`（原句语法剖析）。
