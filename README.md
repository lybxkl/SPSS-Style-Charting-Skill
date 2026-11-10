# SPSS-Style-Charting-Skill

通用实证研究流水线：把 PDF、Word、Excel、CSV、文本、网页、访谈稿、图片等资料，整理成可审计的数据集、统计模型、SPSS 风格图表和论文成稿。

这个仓库提供一个可复用的 Agent Skill：`empirical-research-pipeline`。它不限定学科、语言或文件格式；中文裁判文书只是“文本编码”的一个可选示例，问卷、访谈、新闻、政策文件、实验记录、开放数据和数据库导出同样适用。

> **数据隐私**：本仓库只包含方法、脚本和模板，不包含任何真实资料、编码数据、SPSS 数据、论文成稿或个人信息。文档和配置中的样本量、文件名、路径、变量值均为虚构占位，不对应任何真实数据。

## 功能

- **多格式资料审计**：逐文件建立状态机，区分 `valid / metadata / hidden / unsupported / quarantined / zero_byte / corrupt / encrypted / textless / image_only / media / unreadable`，并对账“原始文件 → 可读 → 唯一样本 → 分析样本”；单个文件读不出不会让整次扫描崩溃，会记 `unreadable` 并在末行汇总。
- **内容去重**：MD5 分组，`--content-dedupe` 另按正文归一化指纹分组（同一判决的不同导出版本）；先生成计划，`--apply` 移动到 `_duplicates/` 并写 `move_log.csv`，`--undo` 可回滚，不删除原件。
- **通用编码工作表**：从 PDF、DOCX、ODT、PPTX、HTML、TXT/MD/RTF 等抽取全文、标题、年份和关键词证据句；默认 `generic`，`--profile legal` 才抽取法院/案号/省份/案由。被审计/去重排除的文件逐条落 `skipped_documents.csv`，样本漏斗写 `sample_flow.csv`。
- **字段抽取（一行一个观测）**：`--extract profiles/<x>.json` 把材料取成结构化字段，产出 `dataset.csv`（每字段带 `<字段>_src` 来源列）、`evidence.jsonl`（带可回验的字符偏移）、`run.json`（profile 哈希 + 每字段命中/缺失数）。**领域写在 JSON 里**：换一份 profile 就换领域，`scripts/extract_lib.py` 里没有任何学科词。缺失一律落 `na` 短语，`False`/`0` 与"没提到"分开。规范见 `references/09-field-extraction.md`。
- **表格数据质量**：行/列、主键、缺失、分类编码、异常值、日期范围；CSV/Excel 直接进入统计流程，不混入文本编码。
- **SPSS 数据**：输出 CSV/JSONL；生成 `.sps` 读入语法、变量标签、值标签、`MISSING VALUES` 与 `VARIABLE LEVEL`（NA 不再与 0 混同），并自动把“是/否、有/无、支持/不支持”等二值文本 `RECODE` 为 `*_num`。
- **自动统计筛查**：描述统计、组间检验、相关、单变量 OLS/Logit；多分类自变量自动哑变量化，完全分离/不可估计模型写入跳过清单。`--spec` 提供**多变量模型入口**（logit/ols、聚类稳健、HC0/HC1/HC3、显式参照组、空单元分离检测），输出可直接喂图表的 `coef_<id>.csv`。
- **十六种经典方法**：`scripts/methods_pack.py` 按 `methods.json` 一次跑完教材里那 16 种方法（描述统计、PCA、相关、ANOVA、卡方、SEM、判别、时序、因子、聚类、回归、T 检验、中介、卡诺、信度、效度），另加非参数检验族与二元 Logistic 两节。**每个方法先自检前置条件**（两组才做 t、0/1 才做 Logit、KMO≥0.6 才做因子、n>参数数才做回归…），不满足就 `skipped` 并指出替代方法，绝不硬算；产出 `methods_report.md`（含可直接改写的报告句式）、`methods_manifest.csv`、每法一张 600 dpi 配图。SEM 因为没有引擎而**明确拒绝**，不给假模型。用法与判据见 `references/11-methods-catalog.md`。
- **全景图表包**：默认覆盖 A 数据质量、B 单变量、C 双变量、D 多变量、E 时间、F 模型诊断、G 附录，实测 15–44 张（`--max-charts` 默认上限 60，0 = 不限；`--only`/`--sections` 只跑需要的）；含 PCA、Ward 聚类、MDS、对应分析、控制图、ROC/PR/校准/混淆矩阵/Lift、Kaplan–Meier 等。
- **出版级输出**：15 cm 版心、宋体 + Times New Roman、600 dpi PNG、矢量 PDF、LZW 无损 TIFF（默认三格式；`--no-tiff` 可关）。log 轴次刻度标注已关闭，不再出现 `4×10⁻¹` 混排。
- **多面板正文图**：`scripts/paper_figures.py --paper paper.json` 按 GridSpec 组装 (a)(b)(c)，支持 `bar/bar_with_ci/stacked_bar/line/scatter/hist/pie/forest`，返回每格实际厘米与**实测最小字号**，产出 `FigureN.*` + 与图包同构的 manifest；森林图直接吃 `coef_all.csv`。
- **Word → PDF 高清回填**：定位 Word 导出 PDF 中被压缩的图，替换回 600 dpi 原图，回填后清理页面内容树（`clean_contents` + `garbage=4`）以免旧的低分辨率副本残留在成品里，并按版面尺寸校验有效 dpi。
- **成稿组装**：`scripts/assemble_manuscript.py --spec manuscript.json` 直接产出 `.docx`——三线表（1.5/0.75/1.5 pt、无竖线）、行不跨页、表头重复、图按正文栏宽嵌入、图题与图同页、中西文字体分别设置、首行缩进按字符、页脚页码；表格与图**引用 CSV/PNG 而非手抄数值**，同时写出本文档实际印出的每个 N（`manuscript_numbers.csv`）与回填用的 `figure_map.json`。取不到的占位符直接报错，不会印出半个 `N=`。
- **终检**：核对样本流程、N、图注、图表清单、PDF/图片的**有效 dpi**（不是像素宽）、**最小字号**（按实际安置宽度折算）、**分类色灰度/色盲可分性**；`chart_manifest.csv` 支持图号唯一性、N 合理性（允许 `3111→2713` 这类区间与 `n_scope`）和相对路径检查；有 error 退出码 2。
- **数字溯源**：`scripts/verify_numbers.py` 查表内合计、表图同值、正文每个 `N=/OR=/p<` 能否找回表、图号连续且被引用、样本 N 跨表一致、漏斗单调不增；产物 `number_issues.csv` + `number_trace.csv`。
- **可测试**：`tests/` 下 378 个 `unittest` 用例，全部使用运行时生成的最小 fixture，不依赖网络、真实资料或 SPSS/Word。

## 支持的资料

| 资料 | 原生处理 | 说明 |
|---|---|---|
| PDF | 文字层、页数、字符数、图片数、加密状态 | 扫描件先 OCR |
| DOCX / ODT / PPTX | 段落、表格、幻灯片文字 | `.doc/.ppt` 先转换 |
| XLSX / XLSM | 工作表、单元格文本 | `.xls` 先转换；建议安装 `openpyxl` |
| CSV / TSV / JSON / JSONL | 字段、行数、编码、缺失 | 走统计流程，不进入逐份文本编码 |
| TXT / MD / HTML / XML / YAML / RTF | 纯文本抽取；HTML 去标签 | 网页脚本/样式会被去掉 |
| 图片 | 文件清单、尺寸/页数 | 先 OCR；本 skill 不自带 OCR |
| 音频/视频 | 文件清单 | 先转写/抽帧；本 skill 不自带 ASR |
| 压缩包、旧版 Office、未知格式 | 文件清单 | 先解压/转换；审计会标 `unsupported` |

“任何资料”不等于“任何二进制都能直接解析”：所有文件都会进入审计和样本对账，不能直接读的格式会明确标记并给出转换路径。

## 目录

```text
SPSS-Style-Charting-Skill/
├── README.md
├── CHANGELOG.md                            # 版本变更记录
├── requirements.txt
├── .gitignore
├── dist/
│   └── empirical-research-pipeline.skill   # 可直接导入的打包版（含 sha256 校验文件）
├── docs/
│   └── ISSUES-FIXED.md                     # 审计发现的缺陷索引与修复状态
├── tests/                                  # unittest 用例，fixture 运行时生成
│   ├── _helpers.py
│   ├── test_audit_layer.py
│   ├── test_coding_layer.py
│   ├── test_extract_lib.py
│   ├── test_stats_charts.py
│   ├── test_chart_pack.py
│   ├── test_methods_pack.py
│   ├── test_figures_paper.py
│   ├── test_verify_numbers.py
│   ├── test_output_layer.py
│   ├── test_docs_contract.py
│   └── test_assemble_manuscript.py
├── tools/
│   └── build_skill.py                      # 可复现打包 + --check
└── empirical-research-pipeline/
    ├── SKILL.md
    ├── assets/                             # 配置、codebook、图注、示例图表规格模板
    ├── profiles/                           # 字段抽取 profile 示例（裁判文书 / 访谈）与词表
    ├── references/                         # 01–10：审计、编码、字段抽取、SPSS、制图、排稿、QA、跨脚本契约
    ├── scripts/                            # 可执行流水线（13 个）
    └── evals/                              # 行为测试提示词（不随 skill 打包）
```

## 测试

```bash
# 全部
python -m unittest discover -s tests -p "test_*.py" -v

# 只跑某一层
python -m unittest discover -s tests -p "test_output_layer*.py" -v
```

用例不需要网络、真实资料、SPSS 或 Word；`export_pdf_hires.py` 的用例在检测不到 Word COM 时自动 skip。

## 环境要求

- Python 3.9+
- 审计/文本抽取：`PyMuPDF`、`pandas`、`numpy`
- 统计：`scipy`、`statsmodels`
- 图表：`matplotlib`、`Pillow`
- Excel：`openpyxl`（建议；未安装时会尝试直接解析 XLSX XML）
- Word → PDF 回填：Windows + Microsoft Word + `pywin32`
- SPSS 语法：由 SPSS 打开运行
- 可选：`lifelines`（Cox 模型；Kaplan–Meier 图本身不依赖它）

```bash
pip install -r requirements.txt
```

## 安装

### 方式一：复制目录

Qoder / 通用 Agent Skills：

```bash
mkdir -p ~/.agents/skills
cp -r empirical-research-pipeline ~/.agents/skills/
```

Claude Code：

```bash
mkdir -p ~/.claude/skills
cp -r empirical-research-pipeline ~/.claude/skills/
```

Windows PowerShell：

```powershell
Copy-Item -Recurse .\empirical-research-pipeline "$HOME\.agents\skills\"
```

### 方式二：导入 `.skill`

在支持 Skill 导入的客户端中选择 `dist/empirical-research-pipeline.skill`；也可以把 `.skill` 当作 zip 解压后放入上述 skills 目录。

## 快速开始

以下命令在 `empirical-research-pipeline/` 目录下执行；把 `资料目录`、`data/analysis.csv` 换成本项目的实际路径。

```bash
# 1. 多格式资料审计（先审计，再编码/建模）
#    --content-dedupe 额外按正文指纹找“同一文书的不同导出版本”
python scripts/audit_corpus.py --root "资料目录" --out-dir output/audit --min-chars 100 --content-dedupe

# 2. 去重计划；确认后加 --apply 移动到 _duplicates/（写 move_log.csv，可用 --undo 回滚）
python scripts/dedupe_corpus.py --audit output/audit/corpus_files.csv --root "资料目录" --out-dir output/audit
python scripts/dedupe_corpus.py --audit output/audit/corpus_files.csv --root "资料目录" --out-dir output/audit --apply

# 3. 生成通用编码工作表（访谈/报告/网页/文档）
python scripts/make_coding_sheet.py --root "资料目录" --out output/coding --keywords assets/coding-keywords.json

#    如资料是中国裁判文书，可加：
#    --profile legal --doc-type judgment
#    被 --audit/--dedupe-plan 排除的文件会逐条写进 output/coding/skipped_documents.csv
#    只读文件时不必带 --audit；要沿审计/去重结论走漏斗时必须带（否则被排除的文件会重新进表）

# 3b. 字段抽取：换一份 profile 就换领域（示例：裁判文书 / 访谈）
python scripts/make_coding_sheet.py --root "资料目录" --out output/coding \
  --profile legal --doc-type all --extract profiles/legal-judgment.json
#    产出 dataset.csv（一行一个观测，每字段带 _src）、evidence.jsonl（可回验偏移）、run.json
#    和 missing_by_source.csv（每个字段的缺失按 not_found/negated/redacted/na_phrase/unparsed 分开计数）

# 4. 人工/LLM 按 codebook 编码，形成 data/analysis.csv 和 data/coded.jsonl
#    编码规则、证据句、信度检验见 references/02-coding-protocol.md
#    注意：信度检验（Cohen's κ）是人工协议，本 skill 没有脚本代做

# 5. 表格数据：生成 SPSS 读入语法与 SAV
python scripts/csv_to_spss_syntax.py --csv data/analysis.csv --out-sps syntax/import.sps --sav-out data/analysis.sav
#    本 skill 不调用 SPSS：用 SPSS 打开 syntax/import.sps 运行（或用 R/Stata 直接读 data/analysis.csv）

# 6. 自动统计筛查
python scripts/auto_stats.py --data data/analysis.csv --config assets/chart_config.example.json --out output/analysis_pack

#    多变量主模型：先在 spec 里显式写清因变量、预测变量与参照组，再估计
python scripts/auto_stats.py --data data/analysis.csv --spec model_spec.json \
  --out output/models --separation drop --vif --roc

# 6b. 十六种经典方法一次跑完（前置条件不满足就 skipped 并给替代，不硬算）
python scripts/methods_pack.py --list
python scripts/methods_pack.py --data data/analysis.csv --config methods.json \
  --out output/methods --methods all
#    只跑部分：--methods m04,m05 或 --only m14；方法说明见 references/11-methods-catalog.md

# 7. 生成全景图表包（PNG + PDF + TIFF 三格式；试跑可加 --no-tiff 提速约 30%）
python scripts/auto_chart_pack.py --data data/analysis.csv --config assets/chart_config.example.json --out output/chart_pack
#    只跑部分图：--only F01,F02 或 --sections A,B；先看清单：--list-charts

# 7b. 排正文主图：多面板 + 面板字母 + 图注 N 自动替换
python scripts/paper_figures.py --paper paper.json --out output/figures
#    示例：--paper assets/paper_figures.example.json（合成数据，3 图 0 error）
#    n 写数字或 "auto"：写 "auto" 时必须同时给 --data，否则报错而不是猜

# 7c. 组装 Word 成稿：表格/图引用文件，不手抄数字；顺带写出 numbers.csv 与 figure_map.json
python scripts/assemble_manuscript.py --spec manuscript.json --out output/manuscript.docx
#    {key} 取不到值会退出码 2 并告诉你是哪个键；图默认按正文栏宽（A4-3.17cm=14.66cm）放置

# 7d. Word → PDF，再回填 600 dpi 原图（依赖 Windows + Word）
python scripts/export_pdf_hires.py --docx output/manuscript.docx \
  --out-pdf output/manuscript.pdf --figure-map output/figure_map.json

# 8. 终检（docx/pdf 为成稿；尚未排稿时可先只用 --data/--figures/--manifest）
#    有 error 退出码 2；--min-dpi 600 按版面折算有效 dpi（15 cm 宽 = 3543 px）
#    --min-fontsize 7.2 按实际安置宽度查字号；灰度/色盲检查默认开
#    路径指到"图"那一层，不是它爹：
#      --figures  → 图表包的 output/chart_pack/figures/（内含 *.png/*.pdf），或排稿图的 output/figures/
#      --manifest → output/chart_pack/chart_manifest.csv 或 output/figures/paper_figures_manifest.csv
#    指到父目录 chart_pack/ 会找不到图片（脚本会报 "no image files" 并退出码 2）。
python scripts/qa_outputs.py --docx output/manuscript.docx --pdf output/manuscript.pdf \
  --figures output/chart_pack/figures --data data/analysis.csv \
  --audit output/audit/corpus_files.csv \
  --manifest output/chart_pack/chart_manifest.csv --min-dpi 600 --min-fontsize 7.2

# 9. 数字溯源：正文每个 N/OR/p 能不能找回表
#    --tables            放表格 CSV 的目录（每张表一个 *.csv，首行表头；模型表用 coef_*.csv / fit.csv）
#    --figures-manifest  图的 manifest（paper_figures_manifest.csv 或 chart_manifest.csv，二选一给一份即可）
#    --sample-flow       漏斗文件；由 make_coding_sheet.py 写在它自己的 --out 下（output/coding/sample_flow.csv），
#                        不是 output/tables/
python scripts/verify_numbers.py --out output/verify --tables output/tables \
  --figures-manifest output/figures/paper_figures_manifest.csv \
  --docx output/manuscript.docx --sample-flow output/coding/sample_flow.csv
```

## 配置

`assets/chart_config.example.json` 是列角色模板：`treatment`、`outcome`、`group`、`time`、`region`、`trial`、`filter_query`、`variable_labels`、`value_labels`、`term_labels`，以及双比例哑铃图所需的 `dumbbell`（两个 0/1 列）。示例列名和值标签均为虚构占位，使用时按自己的 codebook 替换。

文本结果是“是/否”时，用 `outcome_map` 明确正类；不要依赖脚本猜方向。多分类自变量会以 `变量_水平` 进入单变量模型，参照组为省略的水平；**用 `--spec` 跑多变量模型时参照组必须显式声明**（写成 `C(变量, Treatment('水平'))` 或在 spec 的 `ref` 里给出），未声明会直接退出码 2 并列出可选水平——脚本不替你猜参照组。

## 图表覆盖

| 组 | 内容 |
|---|---|
| A 数据质量 | 缺失率、样本类别/年份/地区构成、二元变量发生率 |
| B 单变量 | 结果分布、Q-Q、处理构成（条形/环形）、数值分布、类别构成 |
| C 双变量 | 类别×结果、阶段×结果、交叉热图/堆叠、地区/审级差异、相关热图、散点拟合、气泡图 |
| D 多变量 | 提琴/箱线、散点矩阵、哑铃图、PCA 碎石/双标图/载荷、Ward 树状图、经典 MDS |
| E 时间 | 结果率/均值趋势、3σ 控制图、样本量、阶段构成堆叠柱/面积 |
| F 模型诊断 | 森林图、ROC、PR、校准、预测分布、混淆矩阵、十分位 Lift、Kaplan–Meier |
| G 附录 | 对应分析、Pareto |

图数不是越少越“精炼”：正文放主图，诊断、异质性和稳健性图放附录；每张图先在 `chart_manifest.csv` 里写清“回答什么问题”，没有问题就不画。

## 文档

- `SKILL.md`：完整流程、阶段闸门、脚本清单、常见翻车点
- `references/01-corpus-audit.md`：文件状态机、多格式处理、三层去重、表格数据质量
- `references/02-coding-protocol.md`：codebook、证据句、有序层级、问卷/量表、信度
- `references/03-analysis-spss.md`：模型设定、SPSS 语法、结果表、诊断
- `references/04-figures-publication.md`：物理规格、颜色语义、导出检查
- `references/05-manuscript-assembly.md`：Word 排版、图表同页、PDF 回填
- `references/06-qa-checklist.md`：交付前 A–G 清单
- `references/07-chart-atlas.md`：SPSS 高级图形对照与选图策略
- `references/08-analysis-expansion.md`：主模型之外的扩展分析与记录方式
- `references/10-contracts.md`：跨脚本契约（主键 `rel_path`、`sample_flow.csv`、manifest 的 N 与 `n_scope`、缺失值语义、`<字段>_src`、证据句偏移、图与 PDF 规格、退出码）
- `docs/ISSUES-FIXED.md`：逐条审计缺陷索引与修复/未修复状态
- `CHANGELOG.md`：变更记录

## 说明

- 本 skill 面向实证研究，不替代研究设计、人工编码判断或因果识别。
- 样本 N、模型 N、图注 N 必须同源；去重、改 codebook、换筛选条件后要重跑模型和图表。
- 资料中“提到某种情况”不等于“实际发生了某种结果”，结论使用“关联/对应/更可能”，不写因果。
- 公开资料存在选择偏差、未记载不等于未发生、编码单位差异等限制，需在论文中说明。
- 语料通常是**按关键词检索来的目的性抽样**，不是全样本；若某个关键词近乎全覆盖（例如按“生态修复”检索到的案件里 99% 提到“修复”），必须在方法部分写清抽样框，不能把占比当成总体发生率。
- 脚本之间对列名、N、缺失值的约定以 `references/10-contracts.md` 为准；出现不一致时先查契约，不要在单个脚本里就地打补丁。



