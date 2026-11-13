# 抽取层契约（`--extract` / `profiles/`）

本文件是 `extract_lib.py`、`profiles/*.json` 与 `make_coding_sheet.py --extract` 的唯一权威定义。实现、测试、审计都以本文件为准；实现与本文件冲突时，先改本文件再说。

**一句话**：领域知识写进 JSON，通用原语写进 Python。增一个领域 = 写一个 JSON，不改代码。

版本：v2（2026-11-10）。v1 → v2 的变更列在 §7，凡与 v1 冲突以 v2 为准。

---

## 0. 为什么需要这一层

第二轮审计的领域无关性检验测到：不给词典时，任何领域的 `coding_sheet` 都只有 `year` 与一个其实是文件扩展名的 `doc_type` 有值，其余全空，且退出码 0。给 12 个词就 100% 有值。

结论不是"词典不够好"，而是**缺"字段"这一层概念**：`signal_hits` 记的是"这句话提到了某个词"，而研究要问的是"这份材料的 X 等于几"。两者之间缺一次取值。

---

## 1. 通用原语

全部是纯函数，无 I/O，无全局状态，可单测。`extract_lib.py` 公开导出。

| # | 签名 | 语义 | 必须处理的形态 |
|---|---|---|---|
| 1 | `num(s) -> int \| None` | 取第一个数值 | `1358` `1,358` `1 358`（空格千分位）`二〇二一` `十五万` `九千` `1.2万` `零点五` |
| 2 | `quantity(s, unit_table=None, want=None) -> (float, str) \| None` | 数值 + 单位，归一到标准单位 | `2000元` `2万元` `三千元` `1.5小时` `四十分钟` `半小时` `0.5公顷` `9千元` |
| 3 | `date(s) -> "YYYY-MM-DD" \| None` | 日期归一；只有年月给 `YYYY-MM` | `2021年3月5日` `二〇二一年三月五日` `2021.03.05` `2021-3-5` `2021/03/05` `2021年3月` |
| 4 | `duration(s, unit="月") -> float \| None` | 时长归一；**相邻两段相加** | `二年九个月`→33 `三年`→36 `一年三个月十五天`→15.5 |
| 5 | `kv_block(text, labels, max_lines=40, sep="：:") -> (value, span, meta) \| None` | 表单式 `标签：值`；**标签可被拆成单字逐行** | 见 §1.1 |
| 6 | `section(text, start, end=None, after=None, last=True) -> (subtext, offset)` | 按标记切段；`start` 默认取**最后**一次出现 | `判决如下…如不服`、`二、访谈正文…三、访问员观察` |
| 7 | `items(text, style="auto") -> list[(idx, text, span)]` | 枚举项切分 | `一、二、` `（1）（2）` `1. 2.` `• •` |
| 8 | `window(text, span, before=80, after=120) -> dict` | 证据窗口：句子边界优先，200 字上限 | 任何片段都要能扩成可复核的整句 |
| 9 | `negate(text, span, within=12) -> bool` | 否定/限定作用域 | `不予` `没有` `并非` `禁止` `不得` `尚未` `驳回`；`没有不满意` 要判成"否定的是不满意"；`非法` `无偿` 不算否定 |
| 10 | `canon(hits, vocab) -> list[(canonical, raw, span)]` | 同义词归一到标准类，**最长匹配优先**，重叠取长 | `非法捕捞水产品罪` ⊃ `非法捕捞` |
| 11 | `count_unique(text, pattern) -> int` | 去重计数（同一实体多次出现算 1） | 被告人数、受访者提及的服务项 |
| 12 | `pattern(text, regex, group=0) / contains(text, needle)` | 两个平凡的取值 | 捕获组未参与时回落 `group(0)` |

### 1.1 `kv_block` 的三种形态（都必须支持）

```text
形态 A（单行）       访谈编号：IV-2024-017
形态 B（标签拆行）   案\n号：(2020)陕****刑初64 号
                    审\n理\n法\n院：****铁路运输****
形态 C（多标签同段） 受访者：李某  年龄：72  访谈日期：2024-05-06
```

规则：
- 标签匹配允许标签字符之间夹任意空白/换行（`案\s*号`）。
- 取冒号后**整行余量**，不跨行拼接（否则会把下一字段吃进来——这是第一轮最贵的 bug 之一）。本行为空时，允许取**下一非空行**（表单式排版）。
- 值被脱敏（`****`、`＊`、`×`）时返回原串并置 `redacted=True`。**默认不因脱敏而丢弃**（`redacted_is_na` 默认 `false`）：部分脱敏的值仍含年份与案由，整字段置 NA 会把可用信息一起扔掉。
- 找不到标签 → `None`（调用方落 `na` 短语，不落空串）。

### 1.2 `quantity` 的单位表

```json
{"元":   {"factor": 1,         "unit": "元",   "aliases": ["元", "块", "圆"]},
 "万元": {"factor": 10000,     "unit": "元",   "aliases": ["万元"]},
 "亿元": {"factor": 100000000, "unit": "元",   "aliases": ["亿元"]},
 "分钟": {"factor": 1,         "unit": "分钟", "aliases": ["分钟", "分"]},
 "小时": {"factor": 60,        "unit": "分钟", "aliases": ["小时", "钟头"]},
 "月":   {"factor": 1,         "unit": "月",   "aliases": ["个月", "月"]},
 "年":   {"factor": 12,        "unit": "月",   "aliases": ["年"]},
 "岁":   {"factor": 1,         "unit": "岁",   "aliases": ["岁", "周岁"]},
 "亩":   {"factor": 1,         "unit": "亩",   "aliases": ["亩"]},
 "公顷": {"factor": 15,        "unit": "亩",   "aliases": ["公顷"]},
 "天":   {"factor": 1,         "unit": "天",   "aliases": ["天", "日"]}}
```

未给 `unit_table` 时用 `DEFAULT_UNITS`（上表）。`factor` 只做乘法；返回值第二项是**标准单位**，不是原单位。

三条必须明确的判定：

1. **量级后缀只作用于阿拉伯数字**。`十五万` 是 150000；`九千` 是 9000；`1.2万` 是 12000。中文数字自带量级，再乘一次就错 4 个数量级。
2. **一个数只读一遍**。数值一律由同一条"从左到右、量级递减"的链式读取器解析（`1亿2000万` = 1.2e8，`3万5千` = 35000），`num` 与 `quantity` 共用它。此前 `quantity` 用另一套倒序规则，同一个 `1亿零5万` 在前者得 1e8、在后者得 50000 —— 两个解析器各自自洽、一起与文书不符，是最难发现的错法。
3. **别名自带的量级不得再乘一次**。`1200万元` 是 1.2e7：读数值时已把 `万元` 的 `万` 接进链里，`factor` 只用于 `元`/`分钟` 这类无量的单位。
4. **`零` 是连接词不是终止符**：`1亿零五万` = 1e8 + 5e4，`零` 之后允许再接中文数字组。
5. **最早出现的数值胜出**，别名长度只用于同一位置的并列裁决。按别名逐个扫描再返回第一个命中，会让远处的 `四十分钟` 击败紧贴锚点的 `半小时`。
6. **`半` 单独成数**：`半小时` → 30 分钟（0.5 × 60）。

### 1.3 `hint`（锚点）语义

数值类字段（`num`/`quantity`/`date`/`duration`）在整段里找数字必然抓错，所以按锚点定位：

- 锚点取值顺序：`hint` > `labels` > `label` > `start`。写了 `label: 受访者年龄` 的字段不必再重复一遍 `hint`。
- 锚点按"逐字可夹空白"匹配（同 §1.1 形态 B）。
- 窗口**先同行，再向后 160 字，最后向前 160 字**。同行优先是因为表头值不会跑到下一行：`受访者年龄：未记录` 的下一个数字是访谈日期，不是年龄。向后优先是因为数量通常紧跟名词（`修复费1250元`）；先向前会抓到上一条目的金额（在实际语料里常见是尚未退缴的违法所得）。
- 命中的数字若在窗口内出现多处，按 §1.2 第 5 条取最早。
- 锚点命中但带不出单位时（`受访者年龄：62`），允许回落到裸数值，`source="label"` 且 `unit_inferred=true`。
- **`date` 用锚点位置裁决远近**：`裁判日期：2021.03****` 与正文里一个完整的 `1988 年7 月11 日` 同时存在时，取离锚点近的那个；没有锚点则取文档中**最早出现**的日期（不是"最完整"的那个）。按完整度优先选日期，会静默错 30 多年。

### 1.4 缺失、零与"没提到"（NA 纪律）

| 情形 | 落盘 | `source` |
|---|---|---|
| 整段不存在（如没有"判决如下"） | NA 短语 | `none` |
| 段存在，`kv_block`/`pattern` 没命中 | NA 短语 | `none` |
| 段存在，`contains` 未命中 | `False` | `absent` |
| 段存在，`count_unique` 计数为 0 | `0` | `count` |
| 值本身是 NA 短语（`未提及` 等） | NA 短语 | 原来源 |
| 值落在否定域内（`尚未退缴…5000元`） | NA 短语（`na_negated` 可覆盖） | 原来源 + `negated=true` |
| 标签行写了 NA 短语，附近还有数字 | NA 短语；数字进候选并标 `rejected_by_na` | `na` |

数值/日期/时长字段的优先级是：**同行读数 > 标签行 NA 短语 > 跨行读数**。跨行读数落在 header 字段时会带 `cross_line_header` 并进入复审，不会静默当成事实。

**`False` 与 `0` 是有信息的取值，不是缺失。** 把"没投诉"写成 NA，等于扔掉了一次测量。

---

## 2. Profile 包（`profiles/<name>.json`）

```json
{
  "profile": "eldercare-interview",
  "version": "1.0",
  "description": "社区养老服务满意度访谈记录（示例夹具，不代表研究设计）",
  "sections": {
    "header": {"start": "访谈记录", "end": "访谈内容"},
    "qa":     {"start": ["访谈内容", "访谈正文"],
               "end": ["访问员观察", "记录人"]}
  },
  "fields": [
    {"name": "respondent_id", "label": "访谈编号", "func": "kv_block",
     "scope": "header", "type": "text", "na": ["未记录"],
     "labels": ["访谈编号", "编号"]},
    {"name": "wait_minutes", "func": "quantity", "scope": "qa",
     "unit": "分钟", "type": "numeric", "na": ["未提及", "不适用"],
     "hint": "等多久|等餐|等候|排队|等待"}
  ]
}
```

字段键：

| 键 | 必填 | 说明 |
|---|---|---|
| `name` | ✅ | 列名，`[a-z][a-z0-9_]*`，不得与保留列重名 |
| `func` | ✅ | 见 §1 的 12 个原语 |
| `type` | ✅ | `numeric` `categorical` `text` `date` `count` `bool` |
| `na` | ✅ | 缺失时写入的**短语**，字符串或字符串列表；空串不允许（无法区分"未提及/不适用"） |
| `na_negated` | | 被否定时的替代短语，缺省用 `na` |
| `na_redacted` | | 脱敏且 `redacted_is_na=true` 时的短语 |
| `scope` | | `full`（默认）/ `head` / 某个 `sections` 名 |
| `label` `labels` | | 人读名 / `kv_block` 候选标签；也是数值类字段的兜底锚点 |
| `hint` | | 数值类字段的锚点（§1.3） |
| `pattern` `group` | | `pattern`/`contains`/`count_unique` 用；`group` 默认 0 |
| `unit` `unit_table` | | 标准单位 / 覆盖单位表 |
| `vocab` | | `canon` 用；相对 profile 目录的 JSON 路径，或内联 `{"别名": "标准值"}` |
| `exclude` | | `canon`/`contains` 用：命中所在**行**匹配此正则时不计入（如访谈里的提问行 `^(问|Q)[：:]`——提问会重复受访者的词汇，不排除就会把每个访谈都判成"有投诉"） |
| `window` | | `[before, after]`，证据片段用，默认 `[80, 120]` |
| `negate` | | 数字：span 前 N 字内判否定，默认 12 |
| `drop_negated` | | 默认 `true`；`false` 时保留值并置 `negated=true` |
| `redacted_is_na` | | 默认 `false`（§1.1） |
| `max_items` | | `items`/`canon` 上限 |
| `fallback` | | 列表，逐项试；每项可写完整对象，也可只写原语名（如 `"pattern"`）表示复用本字段其余参数 |

**未知键直接报错。** 每个 `func` 只允许读它真会读的键（`kv_block` 不许带 `pattern`，`date` 不许带 `pattern`）。写错键名的字段原本会静默忽略那段配置——作者以为在按 `pattern` 抽取，实际什么也没发生。

`fallback` 合并后若缺该原语的必填参数（如只写 `"pattern"` 而本字段没有 `pattern`），**不报错、不假装跑过**：记 `fallback_skipped` 计数并跳过。

### 2.1 保留列（profile 不得占用）

`rel_path` `file` `doc_type` `title` `chars` `han_chars` `profile` `_row_id`

### 2.2 `sections`

- `start`/`end` 可为字符串或字符串列表；`last`（默认 `true`）取最后一次出现——页眉会重复标题，正文在后面。
- 可只给 `lines`（取前 N 行）而不给 `start`，用于表单式头部。
- `after`：先定位此标记，再在其后找 `start`。

---

## 3. 产物

### 3.1 `dataset.csv`（一行一个观测）

列顺序：`rel_path, file, doc_type, <field1>, <field1>_src, <field2>, <field2>_src, …`

- 值列：`numeric`/`count` 写数字（`""` 当缺失），整数不带 `.0`；其余写字符串。
- `<field>_src ∈ kv_block | label | vocab | pattern | contains | count | filename | absent | none | decision | decision:na`。
- 缺失一律写 `""`；为什么缺失看 `evidence.jsonl` 与 `run.json`。
- `doc_type` 是**文档类型**，不是文件格式。通用 profile 下写 `document`（`doc_type_src="default"`），不得回落到 `pdf`/`txt`。

### 3.2 `evidence.jsonl`（一行一个文档）

```json
{"_row_id": "00003", "rel_path": "a/b.pdf",
 "fields": {"wait_minutes": {"value": 30, "raw": "半小时", "span": [244, 246],
                             "source": "pattern", "na": null, "negated": false,
                             "fallback_used": 0, "truncated": false}},
 "evidence": ["wait_minutes=答：平均半小时左右，下雨天更久。@244-246"]}
```

- `evidence` 每条是 `<字段>=<片段>@<start>-<end>`，**一行一条**：片段里的换行压成空格（否则一条证据会把 JSONL 行撕成多条）。
- 判据是**包含**不是相等：`_collapse(text[start:end])` 必须出现在 `_collapse(片段)` 里。片段可以比 span 宽（`kv_block` 的片段是整行 `访谈编号：FY-2025-001`，span 只盖住值 `FY-2025-001`，因为读者需要看见标签才知道这个值是什么），但绝不能比 span 窄——窄了就等于片段和偏移各说各话。
- 片段 ≤200 字；`span` 与片段必须自洽——超长时**同时裁 span**，不只裁片段（只裁片段会让 `text[start:end]` 不再是片段的子串，这正是 1.7% 字段曾经不可回验的原因）。
- `evidence_line()` 与 `verify_evidence()` 是这对规则的唯一实现；测试与审计都调用它们，不得各写一份。
- 缺失字段：`{"value": null, "raw": null, "span": null, "source": "none", "na": "未提及"}`，且不产生 `evidence` 条目。

### 3.3 `run.json`

```json
{"profile": "eldercare-interview",
 "profile_path": "…/profiles/eldercare-interview.json",
 "profile_sha256": "…",
 "documents": 20, "errors": 0,
 "fields": {"respondent_id": {"hit": 20, "na": 0, "type": "text"}},
 "generated_by": "make_coding_sheet.py --extract"}
```

`profile_sha256` 覆盖 profile 文件字节——换 profile 必须能被发现。

### 3.4 `extraction_review.csv` / `extraction_candidates.jsonl`（复审层）

`--extract` 现在总是写这三件，不是可选项：

| 文件 | 内容 |
|---|---|
| `extraction_review.csv` | 一行一个文档×字段：`value, raw, source, span, na_hit, cross_line, needs_review, flags, alternatives, note` |
| `extraction_candidates.jsonl` | 每文档一份，保留每个候选的 `value/raw/span/source/note/same_line` |
| `decisions_todo.csv` | 只列 `needs_review=true` 的行，`target` 已拼成 `<rel_path>#<field>`，供模型写 decisions |

Flag 语义：

- `cross_line_header`：header 字段的值来自标签下一行。可能是拆分表头，也可能是偷了下一字段的值，必须看原文。
- `na_conflict`：标签行有 NA 短语，但附近还有数字。
- `multiple_values`：同一字段出现两个以上不同读数。
- `value_withheld`：当前值是空，但候选里还有非空读数。

`--require-review` 让任一 flag 变成退出码 2；模型写 `decisions.jsonl` 后用 `--decisions` 重跑。`value` 必须是候选之一（由 `check_decisions.py` 机器校验），`na` 不需要候选但要给原文 span。重跑后 `run.json.review` 记录 `fields / needs_review / decisions_applied / documents_excluded_by_decision`，复审计数随本次运行更新，不沿用旧值。

决策覆盖某个字段时，`evidence.jsonl` 里该字段的旧证据行会被移除，只留 `<field>=decision:<id>`，`span` 置空；被否决的读数仍保留在 `extraction_candidates.jsonl`，读者能看见“曾经抽到什么、为什么没采用”，但不会把它误当成最终证据。

---

## 4. 与既有产物的关系

- `--extract profile.json` 是**并列**入口，不替代 `--profile`/`--keywords`。同一趟运行里两者可同时给：`coding_sheet.*` 照旧产出，额外多出 `dataset.csv`/`evidence.jsonl`/`run.json`。
- `sample_flow.csv` 增加一行 `stage=抽取字段完成`，`n` = 写入 `dataset.csv` 的行数。
- `skipped_documents.csv` 不变。
- **文本在计算任何偏移之前统一换行**（`\r\n`/`\r` → `\n`）。证据偏移一律指向归一化后的文本；否则一份 CRLF 文件里每条偏移都会按行数偏移。

---

## 5. 验收标准

1. **已有领域（夹具 A，裁判文书）**：`case_no` ≥95%、`year` ≥98%、`judgment_date`/`cause` ≥95%；数值字段按**条件召回**计——只在原文确实提到该事项的文档里算分母，`fine_yuan`/`sentence_months`/`restore_amount` 均 ≥95%。用总体命中率惩罚"原文没写罚金"是错的口径。
2. **完全不同领域（夹具 B，访谈）**：8 个字段在 20 份合成语料上命中 ≥95%，且与生成器 `truth.json` 的**逐字段一致率 ≥95%**（`wait_minutes`/`satisfaction`/`services_mentioned`/`complaint_any`）。
3. **两条命令形状完全一致**：都是 `make_coding_sheet.py --root X --extract profiles/<x>.json`，产出同名三件套；`dataset.csv` 的列由 profile 决定，不由代码决定。
4. **无领域分支**：`extract_lib.py` 里不得出现任何学科词（由 `tests/test_extract_lib.py::LibraryIsDomainNeutralTest` 强制）。
5. **证据可回验**：每个字段至少 1 条证据，且 `verify_evidence(text, line)` 为真，覆盖率 100%。
6. **NA 可区分**：同一份语料里，"段不存在"、"段存在但没提到"、"提到但为否" 三类必须能分开（分别落 `source=none`、`none`、`absent`，`contains` 的 `False` 不等于 NA）。
7. **复审闭环**：每个 `needs_review=true` 的字段都能在 `decisions.jsonl` 找到同 target 的记录，且 `check_decisions.py` 0 error；否则交付闸门不通过。

---

## 6. 刻意不做

- **不做 OCR、不做表格抽取、不做多文档合并**（一份文档 = 一行）。
- **不内置任何领域 profile**：`profiles/legal-judgment.json` 与 `profiles/eldercare-interview.json` 是**示例**，同时兼作"两个领域跑同一条命令"的验收夹具；不代表工具的目标用户。
- **不做自动编码决策**：只抽字段，不判定"应不应判修复责任"。判定仍属研究者与 codebook。
- **不做跨字段推导**（如由罪名推案由类别）：那是 codebook 的事，写进 profile 会让 profile 变成隐藏的规则引擎。

---

## 7. v1 → v2 变更

1. `na` 可为字符串或字符串列表。
2. `fallback` 项可只写原语名；缺必填参数记 `fallback_skipped`、不抛异常。
3. 新增原语 `duration`（相邻两段相加；只取最后一段会把 33 个月读成 9）。
4. `hint` 语义成文：兜底顺序 `hint > labels > label > start`；先向后 160 字再向前。
5. `quantity` 改为"最早出现者胜出"；支持 `半`。
6. `contains` 在段存在但未命中时返回 `False`（`source=absent`），不再返回 NA；`count_unique` 的 `0` 是值。
7. `canon` 新增 `exclude`（跳过提问行等）。
8. `redacted_is_na` 默认 `false`（原为 `true`，会把脱敏案号整字段作废）。
9. 证据片段压成单行；`span` 与片段一律自洽；新增 `evidence_line()`/`verify_evidence()` 作为唯一实现。
10. 文本统一换行后再算偏移。
11. `doc_type` 不再回落到文件扩展名。
12. 验收第 1 条改为**条件召回**口径。
13. 数值类锚点先同行、再向后、再向前；标签行 NA 短语优先于跨行数字。
14. 每个字段带 `candidates/flags/needs_review`；`--require-review` 与 `--decisions` 形成复审闭环。
15. `canon` 过滤被更长命中包含的子串（`不满意` 不再同时算 `满意`）。
16. 孤立的「点/點」不再被读成数字 0。