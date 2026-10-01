# 考研英语小作文：文体排版格式规范、评分细则与避坑死线 (Format & Rubrics Guide)

> **溯源出处与上游资产**：
> - 格式排版母本：《考研小作文微观语料库_模块功能句与场景语素》（第一篇：三大公文体例格式规范与排版红线）
> - 评分细则母本：《考研小作文特点与写作方法论》（第二部分：评卷标尺与得分点）

---

## 一、10 分满分制采分机制与权重分布

教育部大纲评分标准将考研小作文（Section A，应用文，正文 100~120 词）划分为三大采分支柱：

| 采分维度                | 分值   | 核心考查指标                             |
| :---------------------- | :----: | :--------------------------------------- |
| 1. 格式与排版规范       | 2 分   | 称呼、正文缩进、落款位置与标点规范       |
| 2. 内容要点完整度(5W1H) | 4 分   | 题干所有 Bullet Points 完整回应与具象展开 |
| 3. 语言准确与语域得体度 | 4 分   | 语法时态、正式公文语域（无缩写、无感叹号） |

> [!WARNING]
> 阅卷执行严格的**“格式扣分在前”与“踩点给分”**：称呼用冒号、署名自创或加句号直接扣 1~2 分格式基准分；漏次要要点扣 1 分、漏核心大要点扣 2 分；口语缩写（`don't` / `can't`）每处扣减语言分；语域错位（对同侪用过度老派外交辞令或用 `Yours sincerely,`）扣得体度分。

---

## 二、四大法定文体排版视觉规范与模版

### 1. 书信与电子邮件（Letter & Email）

```text
Dear Professor Wang,

    I am Li Ming, a postgraduate student from the History Department. I am writing this
letter with the purpose of presenting some constructive recommendations regarding our
library's digital database accessibility.
    First and foremost, it would be a sound policy to prolong opening hours during final
exam intervals. Furthermore, the administration is kindly expected to upgrade the erratic
campus Wi-Fi infrastructure.
    I sincerely hope that these humble proposals will be taken into favorable consideration.

                                                    Yours sincerely,
                                                    Li Ming
```

#### 视觉生死线：
1. **称呼（顶格写）**：
   - **靠左顶格书写，首字母大写，末尾必须加逗号（不要用冒号 `:`）**；
   - **称呼与结尾敬语三大固定对应法则（黄金契约）**：
     - **① 知道姓名** ➔ `Dear Mr. Smith,` / `Dear Professor Wang,` ➔ 结尾敬语固定搭配 `Yours sincerely,`（称呼严禁加 `the`，如 `Dear Curator,`）；
     - **② 不知道姓名** ➔ `Dear Sir or Madam,` ➔ 结尾敬语固定搭配 `Yours faithfully,`（*严禁写斜杠 `Dear Sir/Madam`，严禁写复数 `Dear Sirs`*）；
     - **③ 朋友私人书信（如邀请信、感谢信、致同学好友）** ➔ 称呼可以直接用 `Dear XXX,`（如 `Dear John,` / `Dear Li Hua,` / `Dear Friends,`），结尾敬语可以用 `Best wishes,` 或 `Kind regards,`（亦可用 `Best regards,`）。
2. **正文（首行缩进）**：
   - **一般分为三段（目的、细节、收尾）**；
   - **每一段的第一行都要向内缩进 4 个英文字母（大约相当于两个汉字的位置）**；
   - **段落与段落之间【坚决不空行】**（缩进式排版铁律；节省宝贵卷面行数）。
3. **结尾敬语（靠右写）**：
   - **单独占一行，整体靠右对齐（或者与下方的署名右对齐），首字母大写，末尾加逗号（`,`）**；
   - **搭配必须遵守上述三大固定对应法则，严禁跨档混用**（朋友私人信坚决严禁 `Yours sincerely,`，过于官僚会扣得体度分）。
4. **署名（靠右写）**：
   - **在结尾敬语的下一行，同样靠右对齐，首字母大写**；
   - **署名一律以题干 Directions 为准（`prompt` 命令输出的【官方指定署名】）**：题干明文给出替代署名时必须使用该署名，不得写本人真实姓名，也不得自创 `Peter` 等名字；
   - **真题实例（已核校内置标尺）**：`2010 / 2011 / 2012 英二` 为 `Zhang Wei`；`2010 英一通知` 为 `Postgraduates' Association`；其余绝大多数年份为 `Li Ming`；通知/告示类统一署机构；
   - 题干确实未给出任何署名要求时，才统一使用 `Li Ming`；
   - **署名末尾【坚决禁止加句号】**（如写成 `Li Ming.` / `Zhang Wei.` 属于严重标点硬伤扣分）；
   - 严禁收件人与署名重名（如 `Dear Li Ming,` 却落款 `Li Ming`）；
   - 机器校验：`check-essay --file ... --year <年份> --exam-type <卷别>` 会直接报出"题干法定署名不一致 / 署名误加句号 / 收件人与署名重名 / 敬语与称呼不匹配"。

---

### 2. 告示 / 通知（Notice / Announcement）

```text
                                Notice
                                                          May 10th, 2025

    With the purpose of ensuring the resounding success of the forthcoming International
Cultural Festival, we are presently recruiting 20 dedicated student volunteers across campus.
    Since the event revolves around cross-cultural interactions, qualified candidates are
expected to demonstrate proficient spoken English. Furthermore, applicants with proven
experience in photography or digital editing will enjoy definitive priority.
    Those who are interested are warmly encouraged to submit their application forms to
volunteer@university.edu.cn prior to May 18th.

                                            The Postgraduate Association
```

#### 视觉生死线：
1. **标题居中**：第一行居中书写 `Notice` 或 `Announcement`（全部大写 `NOTICE` / `ANNOUNCEMENT` 亦可）；
2. **日期位置（写在标题下一行的右侧）**：**必须写在标题下一行的右侧**，靠右书写标准英文日期（如 `May 10th, 2025`）；严禁使用纯阿拉伯数字（如 `2025.05.10` 会被阅卷判为暗号作弊）；
3. **称呼**：**告示文体【坚决没有称呼】**（严禁写 `Dear all` / `Dear students` / `Dear Friends`）；
4. **正文**：首行缩进 4 字符，段间不空行；
5. **落款**：右下角署名发布机构（如 `The Postgraduate Association` / `The Organizing Committee`），**告示结尾严禁署名 Li Ming**。

---

### 3. 会议纪要（Meeting Minutes）

```text
                            Meeting Minutes

Date: May 12th, 2025
Place: Room 204, Student Center
Present: Chen Hao, Zhao Lei, and 6 team members
Absent: Liu Tao (due to internship interview)
Subject: Preparations for the Campus Charity Bazaar

    The meeting commenced at 3:00 p.m. with Chen Hao presiding over the discussion. The
core resolutions reached are summarized as follows.
    Firstly, regarding venue allocation, it was agreed that the central playground will
be designated as the primary bazaar area. Secondly, in terms of publicity, Zhao Lei was
assigned to launch social media campaigns within three days.
    The meeting adjourned at 4:30 p.m. with all agendas concluded.

                                                    Recorder: Chen Hao
```

#### 视觉生死线：
1. **标题居中**：首行居中书写 `Meeting Minutes`；
2. **前五行顶格要素头（关键采分点）**：
   - `Date:` 英文日期；
   - `Place:` 具体地点；
   - `Present:` 出席人员；
   - `Absent:` 缺席人员及合理事由（如 `due to illness` / `on business trip`）；
   - `Subject:` 会议议题（实词首字母大写）；
3. **正文两段式**：第一段交待开启时间与主持人，第二段结构化汇报核心决议与分工；
4. **落款**：右下角注明记录人，如 `Recorder: Chen Hao`（记录人姓名沿用示例人名，**不要与考试法定署名占位符 `Li Ming`/`Zhang Wei` 混用**，以免与题干署名要求冲突）。

---

### 4. 备忘录（Memorandum / Memo）

```text
                              MEMORANDUM

To: All Department Staff
From: Chen Hao, Project Coordinator
Date: October 15th, 2025
Subject: Adjustments to Office Recycling Guidelines

    With an eye to promoting green sustainability, please be informed that our office
waste recycling protocols have been updated effective from next Monday.
    Firstly, all confidential paper documents must be placed into designated blue bins.
Secondly, disposable plastic containers are strictly prohibited in meeting rooms.
    Your proactive compliance with these updated procedures will be highly appreciated.
```

---

## 三、四大防作弊与正式公文生死红线

1. **日期防作弊红线**：
   - **严禁使用纯阿拉伯数字简写**（如 `2025.12.24` 或 `12/24/2025` 会被考研阅卷系统判定为“考生作弊暗号代码”，直接零分或扣除 3 分）；
   - 必须使用英文月份全拼或标准缩写：`May 10th, 2025` / `October 20, 2025`；
   - **书信与电子邮件正文默认可聪明地省略日期**（考纲评分并不强制要求书信写日期，不写立省出错风险）。
2. **零缩写铁律（Formal Register）**：
   - 严禁任何形式的日常口语缩写：
     - [禁用] `don't` ➔ [规范] `do not`
     - [禁用] `can't` ➔ [规范] `cannot`
     - [禁用] `I'd / I'm` ➔ [规范] `I would / I am`
     - [禁用] `won't` ➔ [规范] `will not`
     - [禁用] `it's` ➔ [规范] `it is`
3. **零感叹号铁律**：
   - 考研公文考查理性、客观、专业的事务沟通，**全篇严禁出现感叹号（`!`）**，一律使用句号（`.`）。
4. **合法署名**：
   - **以题干法定署名为准**（用 `prompt` 命令确认，如 2012 英二为 `Zhang Wei`，未指定时才用 `Li Ming`）；
   - 坚决不能加句号，严禁写成 `Liming`、`LiMing`、`Li-Ming`，严禁与收件人重名。

---

## 四、内容拓展边界与防写偏红线（严防画蛇添足与无中生有）

在考研英语小作文（正文 100~120 词）阅卷中，“切题”与“紧凑”是内容分（4 分）的生命线。展开时必须严格遵循以下边界：

1. **允许的 5W1H 具象展开（合规得分点）**：
   - **时间与地点**：如线上会议的平台（`via Zoom`）、具体时间（`at 7:00 p.m. this Friday`）；
   - **核心议题与宗旨**：如 `cross-cultural academic exchange`，用具体动词说明目的；
   - **角色期望与分工**：如 `serve as a guest speaker to share your insights`。
2. **严禁无中生有的画蛇添足（扣分重灾区）**：
   - **严禁虚构未提及的附件/日程/技术参数**：题干未提示任何附件或具体技术参数时，坚决不要套写附件说明（如 `Enclosed is...`）或编造具体参数编号，阅卷人会判定为生硬套用公文模板、脱离题干；
   - **严禁脱离受众身份生搬硬套**：收信人为同班同窗时，严禁使用陈旧僵化的公文外交套话，应使用自然得体的现代同侪书信表达；
   - **严禁过度假设与节外生枝**：不要额外编造与题干毫无关系的冗长背景故事，严格以 2-6-2 黄金结构推进。

---

## 五、高分范文 7 项硬指标

> **私教交付频次铁律**：在高级版输出中，**仅在首次输出终版定制范文时随文附带完整 7 项硬指标自查表**。在后续的多轮微调刷新中，**严禁重复输出完整表格**，只输出本次微调有改动/受影响的那一项指标（如词数变化对比），其余项注明维持通过即可。

1. **正文词数**：100~120 词；
2. **格式硬伤数**：= 0（称呼靠左顶格首字母大写逗号、正文三段首行缩进 4 字符段间不空行、结尾敬语与署名靠右对齐、落款逗号、署名无句号；告示居中无称呼、日期写在标题下一行的右侧、落款机构；纪要五要素头齐备）；
3. **口语缩写数**：= 0（0 个 don't/can't/I'm）；
4. **感叹号数**：= 0（全篇 0 个 !）；
5. **超纲词数**：= 0（紧扣考纲核心动词短语）；
6. **采分点覆盖率**：= 100%（逐条覆盖题干 Bullet Points）；
7. **无中生有数**：= 0（**初稿事实继承 N 处；标尺细节延展 M 处，逐条列明来源**；零虚构未提示的技术参数/附件/日程）。
