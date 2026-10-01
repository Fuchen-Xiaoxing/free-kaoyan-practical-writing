# MaiMemo (墨墨背单词) Open API 裁剪规范与接口契约

本文档为考研英语小作文私教专用的墨墨背单词 Open API 裁剪规范。仅保留与写作实战沉淀直接相关的 5 项核心能力，完全自包含于本 Skill 内部。

---

## 一、基础配置与认证

- **Base URL**: `https://open.maimemo.com/open/api/v1`
- **认证方式**: HTTP 请求头 `Authorization: Bearer $MAIMEMO_TOKEN`
- **Token 来源**:
  - 手机 App: 墨墨背单词 → 设置 → 开放 API
  - Web 端: 打开 `https://open.maimemo.com/open/api/v1/tokens/openapi` 登录后复制 Token
- **Token 缺省处理**: 若未设置环境变量 `$MAIMEMO_TOKEN`，系统提示用户获取并配置，不阻断写作主流程。
- **频控限制 (Rate Limits)**:
  - 20 次 / 10 秒
  - 40 次 / 60 秒
  - 2000 次 / 5 小时
  *(注: 本 Skill 每次写作结算仅涉及 3~8 个生词，脚本内部统一内置 0.25 秒微限流保护，确保安全不超频)*

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
    "voc": [
      {"id": "voc_12345", "spelling": "accommodate"},
      {"id": "voc_67890", "spelling": "prolong"}
    ]
  }
  ```
- **异常处理**: 若生词拼写在墨墨官方词库中不存在，脚本记录该词并跳过后续例句/助记创建，保障整批任务稳定。

---

### 2. 云词本自动化维护 (`/notepads`)
- **专属词本名称**: 《我的考研作文》
- **词本标签**: `["考研"]`
- **章节命名规范**: `# [真题年份][卷别]小作文`（如 `# 2011英二小作文`，自拟题如 `# 自拟-图书馆服务小作文`）
- **操作逻辑**:
  1. `GET /notepads?limit=50&offset=0`：查询是否已有《我的考研作文》；
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

### 3. 作文原句专属例句与字符高亮 (`POST /phrases`)
- **作用**: 将本次作文中的原句收录为该单词在墨墨中的例句，并精准高亮该单词。
- **高亮算法契约 (`highlight: PhraseHighlightRange[]`)**:
  - 半开区间 `[start, end)`（0-indexed 字符索引）。
  - 脚本自动定位单词在例句中的起始与结束字符位置（兼容大小写形式与常见词尾屈折）。
- **请求体**:
  ```json
  {
    "phrase": {
      "voc_id": "voc_12345",
      "phrase": "The library is expected to prolong opening hours to accommodate students.",
      "interpretation": "图书馆预计将延长开放时间以方便/容纳学生。",
      "tags": ["考研"],
      "origin": "2011英二小作文实战",
      "highlight": [
        {"start": 51, "end": 62}
      ]
    }
  }
  ```

---

### 4. “借壳”写作深度助记 (`POST /notes`)
- **作用**: 点开助记卡片不是网上的搞笑段子，而是考研写作用法与原句语法拆解。
- **类型参数 (`note_type`)**: 统一固定为 `"语法"`。
- **助记内容规范**:
  - **初稿拼错词**:
    ```
    【初稿纠偏】：初稿误拼为 acommodate，正确拼写为 accommodate（考场务必防范拼写扣分）！
    【考研写作用法】：考研高频动词，常接 students / needs，表示“迎合、容纳、迁就”，写作中可完美替换普通的 meet 或 help。
    【原句语法剖析】：主干为 The library is expected to prolong opening hours；不定式短语 to accommodate students 作后置目的状语，有力承载举措价值。
    ```
  - **范文高阶生词**:
    ```
    【考研写作用法】：写作及阅读高频动词，及物动词常搭 opening hours / service / life，比 lengthen 或 extend 更加严谨书面。
    【原句语法剖析】：在 be expected to 结构中充当动词不定式核心动词，形成动宾结构 prolong opening hours。
    ```
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

## 三、结算数据载荷契约 (`/tmp/maimemo_sync.json`)

私教在阶段 3 用户确认同步后，输出如下规范 JSON 文件并执行同步脚本：

```json
{
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
```
