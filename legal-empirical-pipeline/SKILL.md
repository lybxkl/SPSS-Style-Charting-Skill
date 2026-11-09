---
name: legal-empirical-pipeline
description: 将中文裁判文书/判决书 PDF（或其他法律文书语料）转化为可审计的实证数据集与论文成稿：先做语料完整性、文字层与重复副本审计，再按 codebook 编码、生成 CSV/SAV、跑 SPSS/Logistic 模型、制作 600 dpi 出版级图表，最后组装 Word/PDF 并做数字一致性质检。只要用户提到裁判文书批量整理、判决书编码、样本去重、SPSS 回归、实证论文图表、投稿排版，或要在既有编码数据上追加新 PDF，就使用本 skill。
compatibility: Python 3.9+；审计/图表需 PyMuPDF、pandas、numpy、matplotlib；自动统计需 scipy、statsmodels；Word→PDF 需 Windows + Microsoft Word + pywin32；SPSS 语法可由 SPSS 打开运行。
---

# 法律实证数据流水线

把“一堆判决书 PDF”变成“可复核的样本流程 + 可追溯的编码数据 + 可复现的模型 + 可投稿的图表与文稿”。本 skill 的重点不是替用户编造结论，而是保证每一步都能回答：**这份文书为什么在样本里、这个数字从哪来、这张表和这张图是否说的是同一件事。**

本仓库/包内的示例数字、文件名、路径与变量值均为虚构占位，不含任何真实案例 PDF、编码数据、SPSS 数据或论文成稿。

## 何时使用

- 用户给了一个装满裁判文书 PDF 的文件夹，要求统计案由、金额、处理阶段、结果类型等。
- 已有编码数据，需要追加新年度/新地区 PDF，或修正样本口径。
- 需要把编码结果做成 SPSS 数据、Logistic 回归、森林图、趋势图。
- 需要把实证部分写成 Word/PDF，且图、表、正文数字必须一致。
- 用户说“类似的数据还要再做一遍”，希望复用同一套流程。

## 六条硬规则

1. **先审计，再编码。** 没弄清文件数、可读文本数、重复数、排除原因之前，不要开始统计。
2. **按内容去重，不按文件名。** 同名不同文、同文不同名都很常见；至少用 MD5，再用案号/标题辅助复核。
3. **一行 = 一份文书，不是一名被告人。** 单位在项目开始时写死；多被告人文书整体编码，并在局限中说明。
4. **每个编码要有证据片段。** 文本没有记载就记 `NA/未记载`，不要默认记 0；否定表述、辩方建议、公诉建议不能当作裁判认定。
5. **描述样本 N ≠ 模型样本 N。** 每个模型单独报告 N 和筛选条件；正文、表、图、摘要必须用同一套口径。
6. **文本关联 ≠ 因果效应。** 写“关联/对应/更可能”，不写“导致/使得/证明有效”。

## 流程总览

```
0 范围界定 → 1 语料审计 → 2 编码协议 → 3 数据集 → 4 统计分析
                                      ↓
                         7 终检 ← 6 文稿组装 ← 5 出版级图表
```

每个阶段都有“闸门”。闸门不过，不进入下一阶段。

---

## 阶段 0：范围界定

先写一页 `scope.md`，至少包含：

- 检索库与检索式（如中国裁判文书网，关键词、案由、时间范围）。
- 文书类型：刑事一审/二审/再审；民事/行政是否纳入；裁定、执行、调解是否排除。
- 分析单位：文书 / 被告人 / 案件；多被告人、单位与个人如何处理。
- 时间口径：裁判年份还是立案年份；跨年案件归哪一年。
- 纳入/排除标准：字数下限、重复、无法读取、非刑事、年份缺失。
- 预期变量清单与每个变量的理论角色（因变量、核心自变量、控制变量、机制变量）。

**闸门**：能用一句话说清“原始文件 → 有效文书 → 在范围内文书 → 分析样本”的每一步会掉多少、为什么掉。

---

## 阶段 1：语料审计（必须先跑）

运行 `scripts/audit_corpus.py`：

```bash
python scripts/audit_corpus.py --root "语料目录" --out-dir "output/audit" --min-chars 100
```

它会输出：

| 文件 | 用途 |
|---|---|
| `corpus_audit.csv` | 每份文件的字节数、页数、文字数、图片数、MD5、错误 |
| `corpus_summary.json` | 机器可读的汇总 |
| `corpus_duplicates.csv` | 重复组、建议保留/移除 |
| `corpus_report.md` | 可直接贴进项目日志的中文报告 |

必须逐项处理：

- `._*`、`.DS_Store`：macOS 元数据，不是文书；计入“非文书文件”，不要计入样本。可读的 `._*.pdf` 会在 error 列标注，需人工确认。
- 隐藏文件/目录记为 `hidden`，扩展名不在 `--ext` 的文件记为 `unsupported`，`_duplicates` 等跳过目录记为 `quarantined`；三者都不进样本，但必须出现在总数和报告里，不能静默漏计。
- 0 字节、打不开、加密、无文字层：分别记录为 `zero_byte` / `corrupt` / `encrypted` / `image_only` / `textless`；无文字层要么 OCR，要么排除，不能默默当空文本。
- 顶层/年份分布只统计唯一样本（`valid` 且非副本）；不要把元数据、损坏文件或重复副本算进样本结构。
- 除 PDF 外，`--ext txt`/`md`/`csv` 可按纯文本审计；不支持的扩展名会进入 `unsupported`，避免把 docx 当 PDF 解析；`--ext` 本身写错会报错。
- 重复副本：按 MD5 分组；保留“文件名含案号/年份、路径更短、文本完整”的那一份，其余移动到 `_duplicates/`，不要直接删除。
- 文件名截断、尾随点、超长路径：Windows 下常见；用 Python 读取并在报告中记录，不要靠资源管理器手工数。已用 322 字符路径回归验证。
- 同名不同文、正文相同但 PDF 元数据不同（MD5 不同）：必须按案号/标题/正文抽样人工复核，不能只靠 MD5 自动去重。

然后运行 `scripts/dedupe_corpus.py` 生成去重计划：

```bash
python scripts/dedupe_corpus.py --audit "output/audit/corpus_audit.csv" --root "语料目录" --out-dir "output/audit" --apply
```

**闸门**：`sample_flow.md` 能对账：

```
原始文件数（含 .DS_Store/无扩展名文件）
- 元数据/隐藏文件
- 扩展名不在 --ext（unsupported）
- _duplicates 等隔离目录（quarantined）
- 0 字节/损坏/加密/无文字层
= 可读文书数
- 不在时间/类型范围
= 有效文书数
- 重复副本
= 唯一样本数（按 unique_valid_files）
- 关键变量缺失/无法编码
= 分析样本数
```

每个模型再有单独的 N，不要用一个 N 打天下。

---

## 阶段 2：编码协议

1. 先写 `assets/codebook-template.md` 的实例：每个变量都要有**定义、取值、判断规则、证据位置、反例**。
2. 用 `scripts/make_coding_sheet.py` 抽取全文和候选信号，生成编码工作表；它只提供证据片段，不替你做最终判断。默认跳过报告/案例汇编等非裁判文书，未读/过短/非文书全部写入 `skipped_documents.csv` 并给出原因；需要全部可读文件时加 `--doc-type all`。
   文书类型按“文件名 + 标题前 150 字 + 裁判结果段”判断，正文证据清单里的《扣押决定书》《行政处罚决定书》不会被当成文书类型。案号优先取文件名，其次取“本院/我院/本案”附近的案号；年份取自有案号年份，再取文件名/正文；省份从法院名推断。
3. 人工/LLM 编码时，每条记录至少保存 `*_ev` 证据句；没有证据句的编码视为未完成。
4. 抽 10%–15% 文书双人/双轮编码，报告一致率或 Cohen's κ；分歧先裁决再改 codebook。
5. codebook 冻结后再全量编码；后续改动要记录版本与影响范围。

**闸门**：随机抽 10 条，能从 `编码值 → 证据句 → 原文段落` 完整回溯；否则回到编码表修规则。

详见 `references/02-coding-protocol.md`。

---

## 阶段 3：数据集

推荐三件套：

- `data/coded.jsonl`：逐份文书编码明细 + 证据片段，便于回溯。
- `data/analysis.csv`：分析用宽表，一行一份文书。
- `data/analysis.sav`：SPSS 直接打开，带变量标签/值标签。

必须包含的标记列：

| 列 | 含义 |
|---|---|
| `in_scope` | 是否属于研究对象（时间、类型、地区） |
| `in_analysis` | 是否进入描述统计（排除无法编码/关键缺失） |
| `model1_sample` 等 | 每个模型单独的样本标记；不要用 `in_analysis` 代替 |
| `dup_group` | 重复组 ID；保留份为 0，副本为 1 |
| `exclusion_reason` | 排除原因，便于写样本流程 |

用 `scripts/csv_to_spss_syntax.py` 生成 `.sps`，避免手写 `GET DATA` 时列类型错位。CSV 里若是“是/否、有/无”等二值文本，脚本会自动追加 `RECODE ... ('是'=1) ('否'=0) INTO *_num`，Logistic 直接用数值列；不需要时加 `--no-recode`。

**闸门**：CSV 行数、JSONL 行数、SAV 行数、`sample_flow.md` 的唯一样本数四者能对上；每个模型 N 能从筛选条件重算。

---

## 阶段 4：统计分析与扩展

先写分析计划，再看结果。默认做“主分析 + 描述 + 双变量 + 多变量 + 诊断 + 异质性 + 稳健性”的组合，而不是只跑一个主模型。

先用自动筛查脚本把描述统计、组间检验、相关和单变量模型跑一遍：

```bash
python scripts/auto_stats.py --data data/analysis.csv   --config assets/chart_config.example.json --out output/analysis_pack
```

它输出 `descriptives.csv`、`group_tests.csv`、`binary_rates.csv`、`correlations.csv`、`univariate_models.csv`、`univariate_skipped.csv` 和 `analysis_pack.md`，用于发现值得进一步建模的变量；**最终模型仍按预设定规格在 SPSS 中估计**，不要用自动筛查的 p 值筛变量。

脚本会自动识别结果变量类型：

- 0/1 → 二元结果（Logistic/OR）。
- 连续数值 → 连续结果（OLS/均值+CI），多分类时组间检验用 Kruskal–Wallis。
- 多分类 → 分类结果，组间用卡方/Cramér’s V；多分类自变量会用哑变量进入单变量 OLS/Logit，并以 `变量_水平` 形式报告，不再静默漏掉。
- 多分类结果本身不做二分类 Logit；主模型应改用多项 Logit 或先合并类别，自动筛查不会硬套二分类。
- “是/否、有/无、支持/不支持”等常见文本标签会自动映射为 0/1；其他二值文本必须用配置项 `outcome_map` 指定正类。脚本不会猜正负方向。
- 完全分离、估计不稳定的单变量模型会写入 `univariate_skipped.csv`，不会给出一个虚假的巨大 OR。
- 结果列全缺失、过滤后 0 行、`filter_query` 拼错时直接报错退出，不生成空结果。

最少包含：

- 描述统计：每个层级的 N、占比、结果率、95% Wilson CI。
- 主模型：二元 Logistic，因变量定义、参照组、核心自变量、控制变量。
- 机制/调节模型：交互项、简单斜率或分组预测值。
- 稳健性：替换因变量、替换样本、加入/移除控制变量、去重前后。
- 诊断：多重共线性、完全分离、样本量不足的单元格、校准/区分度。
- 异质性：分类别/分地区/分审级/分年份。
- 能做的探索：PCA、对应分析、聚类、预测 ROC/校准；标注“探索性”。

报告表至少要有：系数/OR、95%CI、p、N、拟合指标、参照组说明。每个模型单独一行 N。

把做过的和跳过的分析写进 `analysis_manifest.md`（模板见 `references/08-analysis-expansion.md`），不要只报显著结果，也不要等用户追问“还能不能再看点什么”。

SPSS 语法模板与解释规范见 `references/03-analysis-spss.md`；扩展分析清单见 `references/08-analysis-expansion.md`。

**闸门**：任意一个 OR 都能从 `analysis.sps → 输出文件 → 表格` 三段追溯；`analysis_manifest.md` 能解释每个分析做/不做、样本多少；正文没有把“文本里写了某处理”写成“实际结果更有利”的因果结论。

---

## 阶段 5：出版级图表（默认做全景，不是只画 8 张）

先跑 `scripts/auto_chart_pack.py` 生成全景图表包，再从中挑正文主图、附录图和需要补画的模型图：

```bash
python scripts/auto_chart_pack.py \
  --data data/analysis.csv \
  --config assets/chart_config.example.json \
  --out output/chart_pack --tiff
```

连续/多分类结果不需要改脚本：结果变量会自动切换为“结果分布 + 分组均值/构成”图；文本结果同样可用 `outcome_map` 指定编码。`--coef` 支持 `metric`（OR/HR/RR/beta）与 `n` 列，森林图会按模型样本量写 N；`--pred` 支持 0/1 或“是/否”标签，常数预测/单一类别会跳过 ROC/PR/校准并写明原因。`term_labels` 可把 `lv3` 这类模型项名映射为“阶段3：已支付”。双比例哑铃图需在 config 里用 `dumbbell` 指定两个 0/1 列。有随访时间与事件列时，用 `--survival-time`、`--survival-event`（可加 `--survival-group`）生成 Kaplan–Meier 曲线；没有随访数据会在清单里写明跳过原因。

默认覆盖 7 组，常规约 40–55 张：二分类 37–45 张，带模型输入 45–50 张；连续/多分类结果 32–38 张。

- **A 数据质量**：缺失率、样本类别/年份/地区、二元变量发生率。
- **B 单变量**：结果分布（二分类/连续/多分类分别处理，连续结果加 Q-Q）、处理构成（条形+环形）、数值分布、类别构成。
- **C 双变量**：类别×结果、层级×结果、类别×层级热图/堆叠、地区/审级差异、相关热图、散点拟合、气泡图；连续结果用均值+95%CI（按层级顺序排列），多分类结果用组内构成堆叠图。
- **D 多变量**：提琴/箱线、散点矩阵、哑铃图、PCA 碎石/双标图/载荷热图、Ward 聚类树状图、经典 MDS。
- **E 时间**：结果率/均值趋势、3σ 控制图、样本量、层级构成堆叠柱/面积；多分类结果加结果类别构成趋势。
- **F 模型诊断**：森林图、ROC、校准、预测分布、混淆矩阵、PR 曲线、十分位 Lift（需 `--coef` / `--pred`）；Kaplan–Meier（需随访列）。
- **G 附录**：对应分析、Pareto。

出图策略：

- **每个主发现至少 2 张图**：主结果图 + 稳健性/诊断/异质性图。
- **正文 7–10 张，附录 20–50 张**；图数不设上限，别让用户反复追问。
- 每张图先写“回答什么问题”；没有问题就不画。
- 用 `references/07-chart-atlas.md` 选型，覆盖 SPSS 常用高级图形：簇状/堆叠/100% 堆叠条形、线/面积、直方图、箱线/提琴、误差条、散点/气泡、散点矩阵、Pareto、ROC、校准、Kaplan-Meier（有生存数据时）、碎石图、因子载荷、聚类树状图、对应分析、MDS、控制图等。
- 每张图写入 `chart_manifest.csv`：图号、问题、类型、变量、N、图注、文件路径。
- 颜色语义全稿统一：同一阶段/同一类别在每张图里用同一颜色。
- 图注写清 N、数据来源、模型设定、参照组；探索性图（PCA/CA/聚类）在图注标明“探索性”。

用 `scripts/pubfig.py` 统一风格：

```python
from pubfig import set_style, save_fig, wilson_ci, forest_plot
set_style()  # 15 cm 版心，宋体/Times New Roman，600 dpi
```

规范要点：

- 物理宽度 15 cm（A4 正文 15.4 cm 内），字号 7.2–8.5 pt。
- 中文宋体、西文 Times New Roman；PDF 字体嵌入（Type 42）。
- 图内不放标题；图题、图注在 Word 中排。
- 同时输出 PNG 600 dpi、矢量 PDF、LZW TIFF（`--tiff`）。
- 误差线注明 95% CI；森林图实心点=显著、空心点=不显著。
- 偏态连续变量用 log10 或 P99 截断，并在轴标签/图注注明。

**闸门**：`chart_manifest.csv` 中每张图都有问题、N、图注、文件；正文主图与附录图不重复；PDF 内嵌图宽度 ≥ 3000 px（15 cm 宽时约 600 dpi）；图注、图、正文引用三者齐全。

详见 `references/04-figures-publication.md` 和 `references/07-chart-atlas.md`。

---

## 阶段 6：文稿组装

Word 排版要求：

- 图、图题、图注设置为“与下段同页”，避免图题分页。
- 表格行禁止跨页断开，跨页重复表头。
- 表注在图/表下方；先给 N，再给显著性规则。
- 正文首次引用图/表时，编号与文件一致（图 1、表 1、附图 1）。
- 摘要、正文、表、图、附录的 N 和百分比全部同源；`chart_manifest.csv` 的 N 会回写图注，图注不再固定写全样本 N。

Word 导 PDF 时，Word 会把 600 dpi 图压到约 200 dpi。用 `scripts/export_pdf_hires.py` 导出后回填原图：

```bash
python scripts/export_pdf_hires.py --docx "成稿.docx" --out-pdf "成稿.pdf" --figure-map "figure_map.json"
```

**闸门**：PDF 页数、图数、图题数一致；每张图的内嵌宽度 ≥ 3000 px；表格没有断行/断表头。

详见 `references/05-manuscript-assembly.md`。

---

## 阶段 7：终检

运行：

```bash
python scripts/qa_outputs.py --docx "成稿.docx" --pdf "成稿.pdf" --figures "figures" --data "data/analysis.csv" --audit "output/audit/corpus_audit.csv" --manifest "output/chart_pack/chart_manifest.csv" --strict
```

再按 `references/06-qa-checklist.md` 人工过一遍。重点不是格式，而是：

- 样本流程每一档数字能对上。
- 重复副本已从分析样本移除，或明确报告未移除的影响。
- 正文每个 N 与对应表/图/模型一致。
- 图表与正文说的是同一个方向，没有“图上升、文说下降”。
- PDF 中的图注编号能识别“图1：”“图 1.”“Table 1:”等写法；低分辨率检查只看图幅足够大的图片，避免把 logo 误报；空 CSV 会直接报错。
- 理论赋分变量（如制度环境评分）在方法部分说明来源，不写成从文书直接测得。
- 结论使用“关联/对应”，不使用因果措辞。

---

## 脚本清单

以下命令假设当前目录是 skill 根目录；如果从项目目录运行，把 `scripts/` 换成 skill 的绝对路径。

| 脚本 | 作用 |
|---|---|
| `scripts/audit_corpus.py` | 扫描 PDF 目录：数量、文字层、页数、MD5、重复、损坏、年份分布 |
| `scripts/dedupe_corpus.py` | 基于审计结果生成去重计划；`--apply` 移动到 `_duplicates/` |
| `scripts/make_coding_sheet.py` | 抽取全文、案号、年份、案由候选与关键词证据句 |
| `scripts/csv_to_spss_syntax.py` | 由 CSV 表头生成 SPSS `GET DATA` 语法；清理非法/重复变量名并写变量标签 |
| `scripts/auto_stats.py` | 自动描述统计、组间检验、相关、单变量模型（多分类自变量哑变量化）、完全分离检查与 `analysis_pack.md` |
| `scripts/auto_chart_pack.py` | 按列角色自动生成约 40–55 张数据质量/分布/双变量/聚类/时间/模型诊断/生存图与 manifest |
| `scripts/pubfig.py` | 出版图统一风格、Wilson CI、森林图、热图、提琴、ROC/PR、PCA、MDS、聚类、KM、控制图等 30+ 图型 |
| `scripts/export_pdf_hires.py` | Word→PDF 并回填 600 dpi 原图 |
| `scripts/qa_outputs.py` | 检查 PDF 图分辨率（忽略 logo 等小图）、docx 图表数量、空数据、重复键、`chart_manifest.csv` 的 N/图注/路径与 N 提示 |

## 参考文档

| 文件 | 何时读 |
|---|---|
| `references/01-corpus-audit.md` | 开始审计、遇到重复/损坏/扫描件时 |
| `references/02-coding-protocol.md` | 设计变量、写 codebook、做信度检验时 |
| `references/03-analysis-spss.md` | 设定模型、写 SPSS 语法、解释 OR 时 |
| `references/04-figures-publication.md` | 画图、选颜色、导出投稿文件时 |
| `references/05-manuscript-assembly.md` | 排 Word、导 PDF、处理图注时 |
| `references/06-qa-checklist.md` | 投稿/交付前逐项检查时 |
| `references/07-chart-atlas.md` | 选图型、对应 SPSS 高级图形、确定图表数量时 |
| `references/08-analysis-expansion.md` | 主模型之外还要跑哪些分析、如何记录做/不做时 |

## 模板

- `assets/scope-template.md`：研究范围、纳入/排除标准、样本流程骨架。
- `assets/codebook-template.md`：变量编码手册骨架。
- `assets/figure-spec-template.md`：图注与制图规格表。
- `assets/figure_map.example.json`：Word→PDF 回填图的映射示例。
- `assets/delivery-checklist.md`：交付清单。
- `assets/coding-keywords.json`：可替换的关键词词典（通用占位示例，按课题替换）。
- `assets/chart_config.example.json`：列角色、标签、分析样本筛选（`filter_query`）示例。
- `assets/analysis-manifest-template.md`：主分析/扩展分析/跳过项清单。

## 最常见的翻车点

1. **把文件夹里的 PDF 数直接当样本量。** 必须先扣掉元数据、损坏、重复、范围外。
2. **只按文件名去重。** 同一文书常有“带案号/不带案号”“- 副本”“(2)”多个版本。
3. **描述统计 N 与模型 N 混用。** 模型有缺失值、层级筛选，N 一定更小。
4. **把“裁判文本提到某处理”当成“实际裁判结果”。** 这是文本关联，不是因果效应。
5. **Word 导出的 PDF 看着正常，图其实只有 200 dpi。** 必须回填并验证内嵌图像宽度。
6. **只画一张主结果图。** 分布、异质性、稳健性、诊断图都没画，用户只能反复追问；默认先跑全景图表包，再挑正文与附录。
7. **把证据清单里的《扣押决定书》《行政处罚决定书》当成文书类型。** 文书类型只看标题/文件名前 150 字与裁判结果段，不看正文引用。
8. **结果是“是/否”文本却直接当连续变量。** 用 `outcome_map` 明确正类，或在 CSV 里编码为 0/1；脚本不会猜正负方向。
9. **审计只数 PDF，静默漏掉 .DS_Store、无扩展名文件和 `_duplicates`。** 所有文件都要有状态，`total_files` 要能和资源管理器对账；不支持的扩展名记为 `unsupported`，隐藏文件记为 `hidden`，隔离副本记为 `quarantined`。
