# SPSS-Style-Charting-Skill

将混合研究资料整理成可追溯的数据集，由 Agent 选择数学与统计模型，产出论文级图集、分析报告和 DOCX。

本仓库交付可复用的 Agent Skill：[`empirical-research-pipeline`](empirical-research-pipeline/SKILL.md)。名称保留了早期“SPSS 风格制图”的来源；实际范围已覆盖资料发现、审计、抽取、数据整合、逐格复核、模型补数、分析、制图、文稿与终检。

> 仓库只包含工具、规范和明确标注的合成示例，不含真实研究资料。示例数字、字段、路径和哈希占位符不能作为真实证据使用。

## 目标与原则

- **尽可能全面**：数据集数量和原生形态不封顶。按材料发现个人、事件、题项、长表、面板、配对、层级、节点/边、矩阵等形式，用户可以继续补充。
- **由 Agent 选模型和实现**：内置方法是工具库，模型族、规格、语言和引擎开放。逐一评估所有有合理数据联系的候选，保留不显著、失败、不适用和暂不可估计项目。
- **缺数回材料找**：现成 CSV 缺列不能直接结束。查正文、工作表、脚注、附件，必要时换解析器、转换、OCR 或转写；取得真实值后重整合、重新复核和重算。
- **每格有来处**：观测值保留原始文件 SHA256、精确位置与原值；派生值指向输入单元格并独立复算。键、空值、编码和标记列同样覆盖。
- **整合后再核对一遍**：机器检查通过只是 prepared。Agent 或人工必须逐格重新阅读原材料及上下文，完成版本绑定的复核，才能进入 final。
- **原件冻结**：原始目录与项目产出分开；按去重计划排除重复，需要隔离时只操作工作副本。模型运行保护整个原始目录，包括未参与分析和被排除的文件。

**可追溯不等于语义必然正确。** 哈希、数值匹配和复核声明不能证明模型真的理解了实体、时间、单位、否定、指代或研究设计。必须实际执行复读、方法诊断和结果审查；不得批量伪造“已核对”，也不能声称有限工具已经证明所有可能的数据集和模型都被穷尽。

完整契约见 [全资料发现、开放模型与逐格复核](empirical-research-pipeline/references/12-exhaustive-research.md)。

## 工作流程

```mermaid
flowchart LR
    A[冻结原始资料] --> B[全文件审计与数据发现]
    B --> C[多个数据集与各自 codebook]
    C --> D[逐格来源与派生复算]
    D --> E[prepare]
    E --> F[整合后实际逐格复读]
    F --> G[final 版本校验]
    G --> H[开放模型清单与前置诊断]
    H -->|缺字段或设计信息| B
    H --> I[自选引擎执行与运行回执]
    I --> J[全图集、结果表、分析报告与 DOCX]
    J --> K[资料与模型覆盖、数字溯源、版面终检]
```

这是一套 **Agent 主导、脚本检查事实** 的工作方式。脚本不会自动发明研究问题、选择全部合适模型或写出可靠理论论证；Agent 根据当前资料生成和维护配置、代码、证据与报告。

## 安装与环境

### 导入技能

支持 `.skill` 导入的客户端可导入 [打包文件](dist/empirical-research-pipeline.skill)。它是普通 ZIP，目录根为 `empirical-research-pipeline/`。也可以将该目录完整复制到客户端的技能目录；具体发现路径由客户端决定，例如支持 `.agents/skills` 的环境：

```powershell
New-Item -ItemType Directory -Force "$HOME/.agents/skills" | Out-Null
Copy-Item -LiteralPath ./empirical-research-pipeline -Destination "$HOME/.agents/skills/" -Recurse
```

更新现有安装前保留本地定制；本仓库更新与用户机器上的已安装副本是两件事。项目数据和输出应放在独立研究目录中。

### Python 依赖

```powershell
python -m pip install -r requirements.txt
```

| 环节 | 依赖与条件 |
|---|---|
| 基础执行 | Python 3.9+；Windows 终端建议设置 `$env:PYTHONUTF8 = '1'` |
| 统计与数据 | pandas、NumPy、SciPy、statsmodels |
| 图表 | matplotlib、Pillow；需要包含实际文字的中文字体，默认优先宋体，西文字体 Times New Roman |
| PDF | PyMuPDF |
| XLSX 单元格校验 | openpyxl；审计层有 XML 回退，不代表全部 Excel 分析无需 openpyxl |
| Word 组装 | python-docx；生成 DOCX 不需要安装 Word |
| Word → PDF | 当前导出实现需要 Windows、Microsoft Word、pywin32 |
| SPSS | 生成 `.sps` 不需要 SPSS；生成 SAV 需另外在 SPSS 中执行该语法 |
| 扩展模型 | Agent 按方法选择 R、Julia、SPSS/Stata 或专用 Python 引擎，记录依赖版本、种子和规格 |

原件保护会在项目 `.research-source-backups/` 中保留按内容哈希复用的恢复副本，并尝试执行期只读保护和改动检测/恢复。这会占用本地磁盘，包含原始资料，应采用与原件相同的访问控制。它用于防止可信分析代码的意外改写，**不是运行恶意代码的沙箱**。

## 资料支持范围

| 资料 | 内置能力 | 需要另行完成的工作 |
|---|---|---|
| PDF | 文字层、逐页检查、文字定位、图片与加密检查 | 扫描件 OCR；部分页损坏要修复/恢复，不能默默当全文完整 |
| DOCX / DOCM | 正文、表格文本、页眉页脚、脚注尾注、批注文字 | 图片、嵌入对象、修订语义等仍需专门读取与上下文判断 |
| ODT / PPTX / PPTM | 文档文字；幻灯片及讲者备注文字 | 图中数值、嵌入工作簿和其他非文字对象按需要额外提取 |
| XLSX / XLSM | 文件/工作表审计、精确工作表单元格定位 | 转为分析数据；公式格需独立复算，不能仅信可能过期的缓存 |
| CSV / TSV | 编码读取、严格行列检查、原始行/列定位 | 分析入口主要读取 CSV；非 CSV 表格先做可追溯转换 |
| JSON / JSONL | 指针/记录定位、重复键检查 | 按实际嵌套结构生成审计视图；高精度数值须保留精度 |
| TXT / MD / HTML / XML / YAML / RTF | 文本抽取与字符位置；HTML 去除脚本/样式 | 网页存档不等于自动联网采集；RTF、表格和正文结构要复核 |
| 图片、音视频 | 文件清单与状态 | 外部 OCR、转写或逐图读取；技能不自带 OCR/ASR 引擎 |
| 压缩包、旧版 Office、未知格式 | 纳入清单并记录不可直接解析的原因 | 解压、转换、专用读取；恢复产物继续保留到原件的映射 |

文件审计证明“看见并检查了哪些文件”，不自动证明“所有字段、表格和附件均已完整抽取”。原生数据可以是任何形态；CSV 审计视图是验证接口，不能为了符合接口而丢字段、丢关系或强行变成唯一宽表。

## 使用方式

### 交给 Agent 的任务示例

> 使用 empirical-research-pipeline，读取本项目 materials/ 的全部资料，尽可能发现和整合有用数据集。按实际单位定义主键与关联，保留原生文件、codebook 和全格证据。数据整合后逐格回原材料重新核对。为每个数据集广泛提出合理数学/统计模型，逐项检查条件，缺数时继续回正文、表格和附件补取。自行选择或编写实现，交付完整图集、结果表、分析报告、最终 DOCX、复现代码与所有校验记录；不显著、失败和无法估计的项目也保留说明。

### 推荐项目结构

```text
research-project/
  materials/                    # 冻结原件，不放产出
  research_registry.json        # 数据集、来源覆盖和模型清单入口
  data/                         # 任意数量原生数据/CSV审计视图/codebook/证据/逐格复核
  analysis/                     # Agent选择或编写的实现、模型规格、环境版本
  output/
    audit/                      # 原始清单、重复组、样本流程
    data_verification/          # prepare快照、待复核任务、final报告
    model_plan.jsonl            # 开放候选及每个缺口的实际回查
    source_coverage.jsonl        # 每份原件的使用/排除/恢复情况
    discovery_report.md         # 数据发现与未利用项说明
    models/                     # 各模型实际输出、诊断、样本键、执行回执
    figures/                    # PNG/PDF/TIFF及图表清单
    tables/                     # 可直接组稿的CSV表格
    manuscript.docx
    research_gate.json
    qa_report.json
```

### 命令链路

以下在**独立研究项目目录**运行；先把 `$SkillRoot` 设为实际技能路径。JSON、代码和台账由 Agent 按当前资料生成，示例命令不代替这些工作。

```powershell
$SkillRoot = 'F:/path/to/empirical-research-pipeline'
$env:PYTHONUTF8 = '1'

# 1. 全文件审计；阈值按材料选择，短表格不应按长文阈值误排除
python "$SkillRoot/scripts/audit_corpus.py" --root materials --out-dir output/audit --content-dedupe
python "$SkillRoot/scripts/dedupe_corpus.py" --root materials --audit output/audit/corpus_files.csv --out-dir output/audit

# 2. 可选的文档抽取入口。审计/去重结论要真正传给下游
python "$SkillRoot/scripts/make_coding_sheet.py" --root materials --out output/coding --audit output/audit/corpus_files.csv --extract "$SkillRoot/profiles/eldercare-interview.json" --require-review
```

抽取 profile 只是示例，必须按当前 codebook 改写；表格数据走结构化处理。对歧义写实际 `decisions.jsonl`，经 `check_decisions.py` 检查后重跑抽取。`--require-review` 只针对抽取歧义，**不能替代下面的全格复核**。

Agent 完成全资料发现、数据集、各自 codebook、provenance、来源覆盖与模型清单后，再执行：

```powershell
# 3. 对每一格重新打开原件、核对位置/raw，并独立复算派生值
python "$SkillRoot/scripts/verify_dataset.py" --registry research_registry.json --root . --out output/data_verification --stage prepare

# 此处必须真实逐格复读原材料及上下文，再将完成的逐项记录写入各数据集review文件。
# prepare只生成pending模板，不能用循环代替复读或伪造verified。

python "$SkillRoot/scripts/verify_dataset.py" --registry research_registry.json --root . --out output/data_verification --stage final --snapshot output/data_verification/verification_snapshot.json

# 4. Agent自选模型实现；执行前会重验final，之后绑定代码/全部原件/输入/输出
python "$SkillRoot/scripts/run_model.py" --id M1 --root . --registry research_registry.json --verification output/data_verification/dataset_verification.json --input data/analysis.csv --code analysis/M1.py --code analysis/M1_spec.json --output output/models/M1/coefficients.csv --output output/models/M1/diagnostics.json --output output/models/M1/sample.csv --receipt output/models/M1/run.json -- python analysis/M1.py

# 5. 检查全来源处置、全部数据集/模型、缺数回查、样本键与运行版本
python "$SkillRoot/scripts/research_gate.py" --registry research_registry.json --root . --verification output/data_verification/dataset_verification.json --out output/research_gate.json
```

需要非内置来源定位或独立计算时，提供显式可信 `--adapter name=path.py`，prepare、final、run_model、research_gate 使用一致的适配器。适配器代码也参与版本绑定。原始资料中的命令和代码不会被当作执行授权。

### 统计和图表工具

内置工具可以直接调用，也可作为 `run_model.py` 的实际命令。正式交付应保留对应回执、诊断与实际样本键；单独跑一个工具的退出码不能替代完整研究闸门。

```powershell
python "$SkillRoot/scripts/auto_stats.py" --data data/analysis.csv --config analysis/chart_config.json --out output/screen
python "$SkillRoot/scripts/auto_stats.py" --data data/analysis.csv --spec analysis/model_spec.json --out output/models --separation error --vif --roc
python "$SkillRoot/scripts/methods_pack.py" --list
python "$SkillRoot/scripts/methods_pack.py" --data data/analysis.csv --config analysis/methods.json --out output/methods --methods all
python "$SkillRoot/scripts/auto_chart_pack.py" --data data/analysis.csv --config analysis/chart_config.json --out output/chart_pack
python "$SkillRoot/scripts/paper_figures.py" --paper analysis/paper.json --out output/figures
```

- `auto_stats` 的多变量入口内置 OLS 与二元 Logistic；分类参照组必须显式声明。`--separation error` 避免未经选择便剔除/合并模型样本；需要 drop/merge 时明确记录依据。
- 数值型的年龄、剂量与地区编码不能仅靠唯一值数决定测量类型。用 `outcome_type`、`variable_types` 或显式 numeric/categorical/binary 列表声明 codebook 类型。
- `methods_pack` 有 18 个目录编号，SEM 编号明确不执行；其余包括描述、差异/非参数、相关、OLS/Logit、PCA、主成分提取的 EFA、信度/结构效度、聚类、LDA、有限 ARIMA、中介与 Kano。它不是所有模型的边界。
- EFA 使用完整案例上的同一相关矩阵、N 和诊断；“效度”入口是结构探索，不替代内容效度、CFA 或因果识别。
- ARIMA 内置搜索为 `(p,d,0)`，需要正确时间顺序和规则间隔；更复杂时序、SEM、多项/有序回归、Cox、层级/空间/网络/优化等由 Agent 选择专用实现。
- `max-predictors`、`max-models`、`max-charts` 默认 0=不限。正数预算、only/sections、top-N、展示抽样是显式分批或版面策略，最终需对照开放清单补全。
- 自动 PCA 默认完整案例、不插补/截尾。显式插补或截尾必须标注并做相应敏感性分析，不能混作原始观测。
- 图表默认 600 dpi PNG、矢量 PDF、LZW TIFF。正文/附录/全图集张数由发现决定，复杂结果按实际纸幅采用同图分面，密集标签默认倾斜，不自动分页。

### DOCX、PDF 和终检

```powershell
python "$SkillRoot/scripts/assemble_manuscript.py" --spec analysis/manuscript.json --numbers output/numbers.csv --out output/manuscript.docx
python "$SkillRoot/scripts/export_pdf_hires.py" --docx output/manuscript.docx --out-pdf output/manuscript.pdf --figure-map output/figure_map.json
python "$SkillRoot/scripts/verify_numbers.py" --out output/number_verification --tables output/tables --figures-manifest output/figures/paper_figures_manifest.csv --docx output/manuscript.docx --sample-flow output/coding/sample_flow.csv --fail-on-warn
python "$SkillRoot/scripts/qa_outputs.py" --docx output/manuscript.docx --pdf output/manuscript.pdf --figures output/figures --manifest output/figures/paper_figures_manifest.csv --min-dpi 600 --min-fontsize 7.2 --colorblind --out output/qa_report.json
python "$SkillRoot/scripts/review_pack.py" --research-gate output/research_gate.json --verify output/number_verification/number_issues.csv --qa output/qa_report.json --out output/review_pack.md
```

- 组稿器接受已写好的段落和文件引用，生成三线表、重复表头、同页图题与分别设置的中西文字体。它不会自行产生研究论证；表格引用 CSV，段落中的 `{key}` 引用真实数字，空值/未知键或损坏表格报错。
- Word 导出可能压缩图片；回填后按实际图幅检查**横向和纵向**有效 dpi。像素宽不代表分辨率，合法窄图不需要硬凑 3000 px。
- 字号必须按 DOCX 中每张图的实际宽高折算。严格字号检查需要可对应的原始 PNG 与同名矢量 PDF；仅看原图或位图元数据不能证明缩小后的字仍可读。
- 类别多/名称长时保留同一张图，横轴标签按实测倾斜 45°，必要时 60°/75° 并增加底部留白；不自动分页、不截断类别或文字、不缩小字号。实在超出目标纸幅时明确报错，调整图幅/纸幅或同图分面，再检查 Word 中的实际字号。
- 灰度区分检查默认开启；色觉模拟需显式 `--colorblind`。`--allow-raster-text` / `--exit-zero` 等放宽选项只用于明确说明的中间检查，不能冒充严格终检通过。
- 数字检查覆盖已识别的 N/统计量/p/百分比及表图/漏斗，p 与系数按正文打印精度匹配，不能以叙述数字或模型编号证明 p 值；它仍不能理解所有自然语言指代，正文、表注、模型与证据的语义对应需要逐项审查。
- 模型样本量以 `fit.csv` / `coef_*.csv` 的 **`n`** 为准；`n_dropna` 是因缺失剔除的行数，不能当作 N。V-05 差异/无法核对项须说明原因并回查，插件接入文案见 [字段与状态语义](empirical-research-pipeline/references/10-contracts.md#13-模型样本量与-v-05插件接入语义)。
- 最后渲染 Word/PDF 逐页检查表格、分页、裁切、字体、图表与引用。没有真实资料时不产出貌似真实实证的结果或论文。

## 脚本索引

路径均在 `empirical-research-pipeline/scripts/` 下。

| 工具 | 职责 |
|---|---|
| `audit_corpus.py` / `dedupe_corpus.py` | 全文件状态、保守文本/字节重复组、统一去重计划与工作副本回滚 |
| `text_extract.py` | 多格式文字/结构检查；严格处理部分读取失败 |
| `make_coding_sheet.py` / `extract_lib.py` | 文档工作表、配置化字段候选、证据和歧义 |
| `check_decisions.py` | 判断台账、证据与候选、有效改判链和未决项 |
| `verify_dataset.py` | 全格来源重读、精确派生复算、prepare/final与版本绑定 |
| `run_model.py` / `source_guard.py` | 任意可信实现执行、全原件保护与恢复、输入/代码/输出回执 |
| `research_gate.py` | 来源、数据集、模型、补数、样本键与实际运行绑定的一致性 |
| `analysis_utils.py` | 编码、CSV读取、样本过滤、显式类型与角色 |
| `auto_stats.py` | 描述/关联/单变量筛查、OLS/Logit规格与诊断 |
| `methods_lib.py` / `methods_pack.py` | 内置方法内核、运行编排、实际N、方法图与报告 |
| `csv_to_spss_syntax.py` | CSV导入语法、变量名称/标签/缺失声明；不执行SPSS |
| `pubfig.py` / `auto_chart_pack.py` | 统一图形样式、常见研究图型与自动初始图包 |
| `paper_figures.py` | 多面板正文图与图表清单 |
| `assemble_manuscript.py` | 按配置与CSV/PNG组装DOCX及数字/回填映射 |
| `export_pdf_hires.py` | Word导PDF、严格图题定位、高清回填与有效dpi |
| `verify_numbers.py` / `qa_outputs.py` | 正文表图数字、样本流程、文件完整性与实际版面质量 |
| `review_pack.py` | 汇总已有证据和未解决问题供实际审稿，不代替研究判断 |

## 测试、审计与打包

所有测试资料运行时构造并明确作为合成 fixture；不依赖真实研究数据、网络或 SPSS。可用时测试真实 Word COM/PDF；环境不具备时相应测试跳过，不能据此声称已验证该链路。

```powershell
$env:PYTHONUTF8 = '1'
python -m unittest discover -s tests -p 'test_*.py' -v
python tools/build_skill.py
python tools/build_skill.py --check
```

测试含已知答案、独立公式、故障反例、跨脚本契约和实际 CLI 行为。源码审计、隔离行为验证、数值校核和真实 Word/PDF 验证的具体范围见 [本轮审计报告](docs/AUDIT-2026-11-13.md)，历史变化见 [CHANGELOG](CHANGELOG.md)。测试通过不等于验证所有领域、所有引擎或所有语义。

`build_skill.py` 将 SKILL、scripts、references、assets、profiles 打入安装包，排除 evals、测试、字节码与真实项目数据。构建采用固定 ZIP 元数据，可重复产出相同字节。`.skill.sha256` 记录**整个安装包文件的标准 SHA256**；构建输出另列内部内容摘要，两者用途不同。

```powershell
Get-FileHash -LiteralPath ./dist/empirical-research-pipeline.skill -Algorithm SHA256
Get-Content -LiteralPath ./dist/empirical-research-pipeline.skill.sha256
```

升级代码、修改原件、数据、codebook、证据或适配器后，必须重新生成快照、实际复核并重跑受影响产物；不能复用旧“已通过”的文件。

## 进一步阅读

- [技能入口](empirical-research-pipeline/SKILL.md)
- [开放研究与全格复核契约](empirical-research-pipeline/references/12-exhaustive-research.md)
- [跨脚本数据契约](empirical-research-pipeline/references/10-contracts.md)
- [字段抽取与证据](empirical-research-pipeline/references/09-field-extraction.md)
- [编码协议](empirical-research-pipeline/references/02-coding-protocol.md)
- [模型扩展](empirical-research-pipeline/references/08-analysis-expansion.md) / [内置方法说明](empirical-research-pipeline/references/11-methods-catalog.md)
- [出版图形](empirical-research-pipeline/references/04-figures-publication.md) / [图形图谱](empirical-research-pipeline/references/07-chart-atlas.md)
- [组稿规范](empirical-research-pipeline/references/05-manuscript-assembly.md) / [交付终检](empirical-research-pipeline/references/06-qa-checklist.md)
