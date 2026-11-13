# 资料审计与去重

## 目标

在编码或建模前回答五个问题：

1. 文件夹里到底有多少份资料？
2. 哪些能读出文字/数据，哪些需要 OCR、转写、解压或转换？
3. 有多少份是同一内容的重复副本？
4. 每一份被排除的文件，原因是什么？
5. 如果是表格数据，字段类型、缺失、主键和异常值是否清楚？

审计不是“数文件”，而是建立**文件级状态机 + 数据级质量档案**。每份文件最终只能落在以下一类：

| 状态 | 含义 | 是否进入样本 |
|---|---|---|
| `valid` | 可打开、有足够文本/数据 | 是 |
| `metadata` | `._*`、`.DS_Store` 等系统文件 | 否 |
| `hidden` | 隐藏文件/隐藏目录中的文件 | 否，除非用户确认纳入 |
| `unsupported` | 未知格式、压缩包、旧版 Office、缺少解析器 | 否，先转换/解压/安装解析器 |
| `quarantined` | 位于 `_duplicates` 等 `--skip-dir` 目录 | 否，已隔离的副本 |
| `zero_byte` | 0 字节 | 否 |
| `corrupt` | 打不开、文件损坏 | 否 |
| `encrypted` | 有密码/权限限制，未提供密码 | 否，除非能解密 |
| `textless` | 有页面/单元格但文本不足 | 否，检查空文件或重新导出 |
| `image_only` | 图片/扫描件，无文字层 | OCR 后可用，否则排除 |
| `media` | 音频/视频 | 转写/抽帧后再用 |
| `unreadable` | 读取失败（权限、路径失效、文件被占用等） | 否，先修复再重跑 |

重复不是独立的 `status`：内容相同的文件仍是 `valid`，另用 `dup_group`/`dup_role` 标记 keeper/duplicate；`unique_valid_files` 已扣除副本（`--no-hash` 时无法判断副本，此时等于 `valid`）。单个文件读不出来时脚本只把该文件记为 `unreadable` 并继续，不会丢弃整次扫描结果。

## 先跑审计脚本

```bash
python scripts/audit_corpus.py \
  --root "资料目录" \
  --out-dir "output/audit" \
  --min-chars 100 \
  [--content-dedupe]
```

默认扫描所有支持的类型，不需要逐个写 `--ext`；`--list-ext` 可查看完整列表。支持：

- PDF、DOCX/DOCM、ODT、PPTX/PPTM、XLSX/XLSM、HTML、TXT/MD/RTF/XML、CSV/TSV/JSON/JSONL。
- 图片、音视频、压缩包、旧版 `.doc/.xls/.ppt` 会被清点并标记，不会静默漏掉。

`--ext` 只用于限制本次解析的范围；不写就解析所有支持格式。未支持格式会计入 `total_files` 并标为 `unsupported`，并给出转换提示。

`--min-chars` 比较的是**有效字符数**（`chars_effective`），不是原始字符数：纯页码行（`3/26`、`3／26`）和空白先被去掉，再去数可见字符。一页扫描件即使每页打印了页码，也不会因此通过门槛。`chars` 保留原始字符串长度，两个口径都写进 CSV；判断"文本够不够"用 `chars_effective`。

加密文件只有在**读不出任何正文**时才标为 `encrypted`，不会混进 `corrupt`；如果 PDF 带权限标记但仍能提取文字，则照常按文字量判定。`corpus_summary.json` 的 `by_top` / `by_year` 只统计唯一样本（`valid` 且不是副本），元数据、坏文件、隐藏文件、扩展名不符的文件、已隔离副本都不会虚增样本结构。

`--out-dir` 位于 `--root` 之内时会被自动跳过，第二次运行不会把上一次的 `corpus_files.csv` 等产出当资料再数一遍；当 `--out-dir` 就是 `--root` 本身时，按已知产物文件名（`corpus_files.csv`、`corpus_audit.csv`、`corpus_duplicates.csv`、`corpus_summary.json`、`corpus_report.md`）跳过，报告顶部会注明跳过的数量。

输出解释：

| 文件 | 关键列 |
|---|---|
| `corpus_files.csv` | `rel_path, relpath, top, name, ext, kind, bytes, pages, chars, chars_effective, images, encrypted, status, year_hint, md5, dup_group, dup_content_group, dup_role, dup_role_content, error, error_kind` |
| `corpus_duplicates.csv` | `group, md5, role, keeper_reason, top, file, rel_path, relpath, bytes, pages, chars, chars_effective` |
| `corpus_summary.json` | 总数、有效数、重复组、状态分布、扩展名分布、年份提示、`sampling_frame` |
| `corpus_report.md` | 可直接放进项目日志的中文摘要，顶部有「抽样框」一节 |

`corpus_audit.csv` 是 `corpus_files.csv` 的**旧名**：脚本仍会把同一张表写成这两个文件名，因为既有命令、`make_coding_sheet.py --audit` 与旧版文档都指向旧名；新写的命令请用 `corpus_files.csv`。两者内容逐字节一致，不存在版本差异。

两处契约细节：

- `rel_path` 与 `relpath` 取值相同、同时写出，前者是第一列；下游读取时优先 `rel_path`，其次 `relpath`。
- 所有 CSV 都是 UTF-8-SIG。用 Excel 打开正常；用 Python `csv` 读取时要 `encoding="utf-8-sig"`，否则第一列名会带 `\ufeff`。

## 多格式处理规则

- **PDF**：优先取文字层，按页按阅读顺序提取；单页损坏只会记为 `read:…` 错误并保留其余页的正文，只有整份文档没有一页可读时才记为 `corrupt`，`extract_text()` 也同样保留可读页、只有全部页不可读才报错。`chars_effective` 低且 `images` 高时记为 `image_only`，先 OCR。
- **DOCX/DOCM、ODT、PPTX/PPTM**：读段落/幻灯片文本；旧版 `.doc/.ppt` 用 Office 或 LibreOffice 转换。
- **XLSX/XLSM**：按工作表读取文本/单元格；建议安装 `openpyxl`，未安装时会尝试直接解析 XML。`.xls` 先另存为 `.xlsx`。
- **CSV/TSV/JSON**：属于表格/结构化数据，审计只统计字符与行；字段质量另做检查，编码工作表会跳过它们。
- **HTML**：去掉脚本、样式和标签后统计正文。
- **TXT/MD/RTF 等文本**：依次尝试 UTF-8-SIG、GB18030、Big5、UTF-16；全都失败才退回 Latin-1，此时 `encoding` 记为 `latin-1(fallback)`，`error` 写 `decoded as latin-1; mojibake likely`，不会假装解码成功。明显的二进制内容直接记 `corrupt`。单个文本文件超过 50 MB 记 `unsupported`，避免整次审计被一个大文件拖住。
- **加密的 Office 文件**：是 OLE/CFB 容器而不是 zip，记为 `encrypted`，不要提示"另存为 docx"。
- **图片**：`image_only`，需要 OCR；本 skill 不自带 OCR。
- **音频/视频**：`media`，需要转写或抽帧；本 skill 不自带 ASR。
- **压缩包/未知格式**：`unsupported`；先解压或转换成上述格式，再重跑审计。

## 重复检测：三层

第一层（字节级）由 `audit_corpus.py` 默认实现；第二层（内容级）由 `--content-dedupe` 实现；第三层（标题/近似）目前只能人工复核。

### 第一层：字节级（默认开启）

同一文件被下载/导出两次，MD5 完全相同。这是最可靠、最应优先清理的重复。

```text
MD5 相同 → 同一内容 → 保留一份
```

保留规则（按实现顺序，逐级比较；`keeper_score` 越小越优先）：

0. 状态为 `valid` 的副本优先于损坏/文本不足的副本。
1. 文件名含年份/稳定标识（如 `2024`、`[2021]`）优先。
2. 文件名无 `副本`、`复件`、`copy`、`_dup`、`(1)` 等痕迹优先。
3. 路径更短、目录层级更浅优先。
4. 有效文本更完整优先（`chars_effective >= 500` 视为完整）。
5. 字节更多优先；仍完全相同则保留排序第一份，并标记 `keeper_reason=tie_first`，需要人工裁决。

`corpus_duplicates.csv` 的 `keeper_reason` 记录该组按哪一级胜出（`valid_status` / `year_hint` / `no_copy_marker` / `shortest_path` / `text_completeness` / `largest_bytes` / `tie_first`）。`keeper_ties` 统计平局组数。

### 第二层：内容级（`--content-dedupe`，默认关闭）

对每个 `valid` 文件调用 `text_extract.extract_text()`，去掉空白与标点、统一小写/全半角（NFKC）后取 SHA-1，再分组写 `dup_content_group` / `dup_role_content`。它能抓到"同一文档的转码版、另排版、另存版本"这类字节不同但内容相同的副本。

开启后报告同时给出两组数字：

- 字节级重复组/多余副本；
- 内容级重复组/多余副本。

二者关系：**字节级只看字节，内容级在 `valid` 文件上按正文归并**。对能提取正文的文件，字节级相同必然内容相同，所以内容级不会漏掉这类重复；但内容级可能把多个字节组合并成一个内容组，也可能发现字节级没有的重复，两组数字口径不同、不能相减，应分别报告。内容级多出来的多余副本就是需要人工复核的转码/排版副本。内容级去重只改变报告与 CSV 标记，不会自动删除任何文件。

### 第三层：标题/近似内容级（人工）

去掉这些噪声后再比较：

- 日期前缀：`2021.04`、`2021年4月`、`2021.4.12`
- 编号前缀：`[2024-001]`
- 下载后缀：`_YYYYMMDD下载`、`- 副本`、`(1)`、`(2)`、`...`
- 同一标题的不同语言/缩写版本

标题相同但正文不同，可能是同主题的不同记录，**不能**直接去重；脚本不自动处理这一层。

## 去重脚本

先出计划，不直接删：

```bash
python scripts/dedupe_corpus.py \
  --audit "output/audit/corpus_files.csv" \
  --root "资料目录" \
  --out-dir "output/audit"
```

确认 `dedupe_plan.csv` 后，再执行移动：

```bash
python scripts/dedupe_corpus.py --audit ... --root ... --apply
```

安全机制：

- `--apply` 前逐组校验 keeper 仍在盘；缺失说明该副本可能就是唯一副本，整组跳过、不移动任何文件，并在 `move_log.csv` 记 `status=skipped`。
- 计划里带 `md5` 与 `exists` 列；应用前重新校验源文件 MD5，审计后文件被改过则跳过。
- 冻结的原始目录保持不动，按去重计划在分析中排除重复即可；需要 `--apply` 时，`--root` 指向工作副本目录，只把工作副本移到 `_duplicates/<原相对路径>`。`--copy` 改为复制；目标已存在时自动加 `__dup2` 等后缀，不覆盖。
- 每次应用都写 `move_log.csv`（`group,src,dest,action,status,reason`），dest 是实际落盘的绝对路径。用 `--undo output/audit/move_log.csv` 反做：`action=move` 的行搬回原位（原位已有文件记 `conflict` 拒绝覆盖）；`action=copy` 的行仅在 src 与 dest 的 MD5 仍一致时删除 dest，不一致记 `conflict` 并保留。输出 `undo: restored=…, removed=…, conflict=…, skipped=…`；有 conflict/skipped 或整份日志没有任何 move/copy 条目时返回 2。
- 有任何 `failed` 或 `skipped` 时脚本返回 2，不会把"部分失败"报成成功。计划文件名带时间戳另存一份，主 `dedupe_plan.csv` 始终是最新版本。

## 表格数据质量审计

如果 `data/` 里是 CSV/Excel/SPSS 数据，在编码/建模前逐项检查：

| 检查 | 做法 |
|---|---|
| 行/列 | 行数、列数、每列类型、唯一值数 |
| 主键 | ID 是否唯一、是否有重复行、是否有同一单位多条记录 |
| 缺失 | 每列缺失率；缺失是否与分组/年份相关 |
| 分类 | 取值拼写、空白、全半角、大小写、编码不一致 |
| 连续 | 范围、分位数、异常值、负数/零、单位一致性 |
| 日期 | 格式、范围、时区/年份口径 |
| 多选/量表 | 多选拆分、反向题、总分/维度、信度 |
| 编码 | UTF-8-SIG/GB18030、分隔符、小数分隔符、SPSS 变量名合法性 |

用 `scripts/csv_to_spss_syntax.py` 生成 `.sps` 后，先在 SPSS 里跑 `EXECUTE.` 核对变量数、行数、标签和 `*_num` 列，再建模。

## 样本流程模板

把这张表放进 `sample_flow.md`，后续所有 N 都从这里取：

| 步骤 | 数量 | 说明 |
|---|---:|---|
| 原始文件 | 2,500 | 含元数据/报告/坏文件 |
| 减：非资料文件 | 120 | `._*`、系统文件、说明文件 |
| 减：0 字节/损坏 | 0 | 无法读取 |
| 可读资料 | 2,380 | 文档 2,200 + 表格 180 |
| 减：范围外 | 180 | 不符合时间/类型/语言 |
| 减：重复副本 | 60 | 58 组字节级重复 |
| 唯一样本 | 2,140 | 可分析资料 |
| 减：无法编码/关键缺失 | 10 | 关键字段缺失、非目标类型 |
| 有效资料 | 2,130 | 进入描述统计前 |
| 减：未识别核心事实 | 50 | 例如未识别目标行为 |
| 分析样本 | 2,080 | 描述统计 N |
| 模型 1 样本 | 1,800 | 筛选 + 完整协变量 |
| 模型 2 样本 | 1,600 | 另一套筛选 |
| 模型 3 样本 | 1,700 | 交互模型 |

上表数字全部为虚构示例，不对应任何真实资料；每次项目必须按审计结果重算。

## 常见坑

- **文件名不是身份。** 同一内容可以有多个文件名，同一文件名也可以对应不同内容。
- **隐藏文件不只看点前缀。** Windows 的"隐藏"是文件属性，不是名字；审计同时检查文件及各级父目录的属性，非 Windows 平台跳过属性检查。
- **审计报告先写抽样框。** 根目录、扩展名限制、跳过目录、`--min-chars`、是否内容级去重，决定这份审计的适用范围；没有抽样框，N 无法复现。
- **`._*` 文件也会被 `find *.pdf` 数进去。** 它们通常 4 KB 左右，打不开，但不是 0 字节。
- **0 字节文件在资源管理器里可能显示为 0 KB，但仍占一个文件名。** 必须单独列。
- **路径超长/尾随点。** Windows 下 `os.walk` 能读到，但资源管理器可能打不开；以 Python 审计结果为准。
- **“重复”不等于“应删”。** 同主题不同记录正文不同，不能去重。
- **去重后要重跑所有模型。** 不能只改正文的 N，表格、图、OR/CI 都要重算。
- **把 `._*` 的年份算进年份分布。** 汇总只应统计 `valid` 资料。
- **把图片/扫描件当空文本。** 先 OCR，再判断是否纳入；否则会在样本流程里凭空少一截。
- **把 CSV 当文本编码。** 表格数据走 `auto_stats`/SPSS，不进入逐份文本编码。

## 审计报告必须写的三句话

1. 原始文件数、有效资料数、唯一样本数、分析样本数分别是多少。
2. 重复副本有多少组、多少份，分布在哪些目录/年份。
3. 被排除的文件分别是什么原因（元数据/损坏/加密/图片/媒体/格式不支持），是否有清单可查。
