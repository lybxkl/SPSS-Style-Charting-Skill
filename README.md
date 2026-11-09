# SPSS-Style-Charting-Skill

通用实证研究流水线：把 PDF、Word、Excel、CSV、文本、网页、访谈稿、图片等资料，整理成可审计的数据集、统计模型、SPSS 风格图表和论文成稿。

这个仓库提供一个可复用的 Agent Skill：`empirical-research-pipeline`。它不限定学科、语言或文件格式；中文裁判文书只是“文本编码”的一个可选示例，问卷、访谈、新闻、政策文件、实验记录、开放数据和数据库导出同样适用。

> **数据隐私**：本仓库只包含方法、脚本和模板，不包含任何真实资料、编码数据、SPSS 数据、论文成稿或个人信息。文档和配置中的样本量、文件名、路径、变量值均为虚构占位，不对应任何真实数据。

## 功能

- **多格式资料审计**：逐文件建立状态机，区分 `valid / metadata / hidden / unsupported / quarantined / zero_byte / corrupt / encrypted / textless / image_only / media`，并对账“原始文件 → 可读 → 唯一样本 → 分析样本”。
- **内容去重**：MD5 分组 + 稳定标识/标题辅助复核；先生成计划，`--apply` 移动到 `_duplicates/`，不删除原件。
- **通用编码工作表**：从 PDF、DOCX、ODT、PPTX、HTML、TXT/MD/RTF 等抽取全文、标题、年份和关键词证据句；默认 `generic`，`--profile legal` 才抽取法院/案号/省份/案由。
- **表格数据质量**：行/列、主键、缺失、分类编码、异常值、日期范围；CSV/Excel 直接进入统计流程，不混入文本编码。
- **SPSS 数据**：输出 CSV/JSONL；生成 `.sps` 读入语法、变量标签、值标签，并自动把“是/否、有/无、支持/不支持”等二值文本 `RECODE` 为 `*_num`。
- **自动统计筛查**：描述统计、组间检验、相关、单变量 OLS/Logit；多分类自变量自动哑变量化，完全分离/不可估计模型写入跳过清单。
- **全景图表包**：默认覆盖 A 数据质量、B 单变量、C 双变量、D 多变量、E 时间、F 模型诊断、G 附录，约 40–55 张；含 PCA、Ward 聚类、MDS、对应分析、控制图、ROC/PR/校准/混淆矩阵/Lift、Kaplan–Meier 等。
- **出版级输出**：15 cm 版心、宋体 + Times New Roman、600 dpi PNG、矢量 PDF、LZW TIFF。
- **Word → PDF 高清回填**：定位 Word 导出 PDF 中被压缩的图，替换回 600 dpi 原图，并检查内嵌图宽度。
- **终检**：核对样本流程、N、图注、图表清单、PDF 图分辨率；`chart_manifest.csv` 支持图号唯一性、N 合理性和文件路径检查。

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
├── requirements.txt
├── .gitignore
├── dist/
│   └── empirical-research-pipeline.skill   # 可直接导入的打包版
└── empirical-research-pipeline/
    ├── SKILL.md
    ├── assets/                             # 配置、codebook、图注、交付清单模板
    ├── references/                         # 审计、编码、SPSS、制图、排稿、QA 细则
    ├── scripts/                            # 可执行流水线
    └── evals/                              # 行为测试提示词
```

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
python scripts/audit_corpus.py --root "资料目录" --out-dir output/audit --min-chars 100

# 2. 去重计划；确认后加 --apply 移动到 _duplicates/
python scripts/dedupe_corpus.py --audit output/audit/corpus_audit.csv --root "资料目录" --out-dir output/audit

# 3. 生成通用编码工作表（访谈/报告/网页/文档）
python scripts/make_coding_sheet.py --root "资料目录" --out output/coding --keywords assets/coding-keywords.json

#    如资料是中国裁判文书，可加：
#    --profile legal --doc-type judgment

# 4. 人工/LLM 按 codebook 编码，形成 data/analysis.csv 和 data/coded.jsonl
#    编码规则、证据句、信度检验见 references/02-coding-protocol.md

# 5. 表格数据：生成 SPSS 读入语法与 SAV
python scripts/csv_to_spss_syntax.py --csv data/analysis.csv --out-sps syntax/import.sps --sav-out data/analysis.sav

# 6. 自动统计筛查
python scripts/auto_stats.py --data data/analysis.csv --config assets/chart_config.example.json --out output/analysis_pack

# 7. 生成全景图表包（PNG + PDF + TIFF）
python scripts/auto_chart_pack.py --data data/analysis.csv --config assets/chart_config.example.json --out output/chart_pack --tiff

# 8. 终检（docx/pdf 为成稿；尚未排稿时可先只用 --data/--figures/--manifest）
python scripts/qa_outputs.py --docx output/manuscript.docx --pdf output/manuscript.pdf \
  --figures output/chart_pack/figures --data data/analysis.csv \
  --audit output/audit/corpus_audit.csv \
  --manifest output/chart_pack/chart_manifest.csv --strict
```

## 配置

`assets/chart_config.example.json` 是列角色模板：`treatment`、`outcome`、`group`、`time`、`region`、`trial`、`filter_query`、`variable_labels`、`value_labels`、`term_labels`，以及双比例哑铃图所需的 `dumbbell`（两个 0/1 列）。示例列名和值标签均为虚构占位，使用时按自己的 codebook 替换。

文本结果是“是/否”时，用 `outcome_map` 明确正类；不要依赖脚本猜方向。多分类自变量会以 `变量_水平` 进入单变量模型，参照组为省略的水平。

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

## 说明

- 本 skill 面向实证研究，不替代研究设计、人工编码判断或因果识别。
- 样本 N、模型 N、图注 N 必须同源；去重、改 codebook、换筛选条件后要重跑模型和图表。
- 资料中“提到某种情况”不等于“实际发生了某种结果”，结论使用“关联/对应/更可能”，不写因果。
- 公开资料存在选择偏差、未记载不等于未发生、编码单位差异等限制，需在论文中说明。
