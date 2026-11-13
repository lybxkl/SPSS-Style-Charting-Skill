# 跨脚本契约（v1.1）

内置脚本与 Agent 自选实现通过文件契约衔接。数据集形态、数量、模型与引擎开放；来源、版本、逐格复核和样本口径必须统一。
下面是硬契约：**生成方必须写、消费方必须认、缺了必须报错**。
所有实现与测试都以本文件为准；修改本文件需要同步 `SKILL.md` 与相应脚本。

---

## 1. 键列（key）

以下 `rel_path` 约定用于文件审计/旧编码管线。一般数据集使用 registry 各自声明的 `key`（字符串或复合键列表），无需强制每个个人、事件或图边都以文件路径作为主键；各自的单位和关联基数必须明确。

- **规范名**：`rel_path`。
- **生成方**（`audit_corpus.py`、`make_coding_sheet.py`、`dedupe_corpus.py`）必须**同时**写出
  `rel_path` 与旧名 `relpath`（完全相同取值），保证老下游不断。
- **消费方**（`qa_outputs.py`、`dedupe_corpus.py`、`make_coding_sheet.py`）按以下优先级解析，
  第一个命中的即用：
  `rel_path` → `relpath` → `file` → `path` → `doc_id` → `id`。
- **一个都不存在 = error**（不是 warning）：打印实际列名，退出码 2。
- 相对路径一律用 `/` 分隔；生成方转换，消费方两种都接受。

## 2. 样本漏斗（sample flow）

- 文件名固定 `sample_flow.csv`，列 `stage,n,note`，可选第 4 列 `kind`。
- `kind` 值域（缺省 `stage`，非法值报 error 并列出三种合法值）：
  - `stage`：**累计**口径，必须单调不增；
  - `excluded`：本步剔除数，只要求 `0 ≤ n ≤ 上一条 stage 的 n`（不与累计序列比大小）；
  - `model`：某个模型的估计样本，`note` 必须写 `stage=<阶段名>`，只要求 `0 ≤ n ≤ 该 stage 的 n`，**不参与单调性**。
  有了 `kind`，"累计阶段 / 剔除数 / 模型样本"三类行不再混在一个单调序列里——混在一起会让漏斗看起来永远自相矛盾，于是没人再看它。
- `stage` 是**人写的短语**，`n` 是整数，`note` 可空。**不做机读枚举**——但 `kind=stage` 的行必须满足
  `n` 单调不增，且相邻两行差值可由 `note` 解释。
- 每张表与每张图都要能声明自己的分母：表用 `--table-scope 表名=sample|corpus`，
  图用 `--figure-scope 图号=sample|corpus`（优先于 manifest 的 `n_scope` 列）。
  同一份稿子里 corpus 图（如"全语料结构"）与 sample 表（如"分析样本描述"）并存是正常的，
  **跨 scope 的 N 不等只记 warning**——把它记成 error 会让真错误淹掉。
- 生成方：
  - `audit_corpus.py` 写 `output/audit/sample_flow.csv`（文件总数 / 元数据 / 0 字节 / 可读 / 有效 / 唯一）；
  - `make_coding_sheet.py` 写 `output/coding/sample_flow.csv`（有效 / 排除 / 编码 / 跳过），
    **被 `--audit`、`--dedupe-plan` 排除的文件必须逐条落进 `skipped_documents.csv`**（含原因）。
- 消费方：正文与图注只从本文件取数，不手写。

## 3. 图表 N

- `chart_manifest.csv` 必填列：`id,question,chart_type,variables,n,png,pdf,caption`，
  可选 `n_scope,dpi,px_width,model_id,data_hash,tiff,note`。
- `n` 允许三种写法：
  1. 整数（`2713`，可带千分位）；
  2. 区间（`3111→2713` / `3111-2713`）——**取第一个整数**作为 N；
  3. 带前缀（`N=2713`）。
- 成功 manifest 行至少给出一条真实 PNG/PDF 产物路径，损坏文件也是 error，不能以存在扩展名作为通过。
- `n_scope` ∈ `sample`（默认）| `corpus` | `subgroup`。
  - `sample`/`subgroup`：`n` 必须 ≤ `--data` 的行数，否则 error；
  - `corpus`：允许 `n` > 行数（漏斗图、语料级图），只做 warning 提示。
- `caption` 必须出现 `N=<解析出的 n>`（允许千分位与全角等号）；缺失是 **warning**，
  但 `n` 非法是 **error**。

## 4. 缺失值（NA）

- **未提及 ≠ 0**。任何「文书中未出现」的字段一律留空（NaN），不得填 0。
- 脚本侧硬约束：
  - `analysis_utils.outcome_kind()` 对**整列缺失**必须返回 `unsupported`，不得返回 `binary`；
  - `encode_binary()` 对整列缺失返回 `(None, {})`；
  - `csv_to_spss_syntax.py` 必须写出 `MISSING VALUES`（对每个数值变量声明 `-99 -98 -97`，
    若数据里出现这些哨兵值则改用不冲突的哨兵并在报告里说明）与 `VARIABLE LEVEL`；
- 数据集可附 `na_policy` 列或 `docs/codebook.md` 的「缺失处理」小节，逐字段声明
  `NA | 0 | 类别`。

## 5. 来源（provenance）

- 任何**不是直接从原文抽取**的字段，必须在同一行给出 `<field>_src`，取值是短语（如
  `裁判日期`、`案号`、`文件名`、`正文（定罪罪名）`、`目录名`）。
- 至少覆盖：`year_src`、`trial_level_src`、`court_level_src`、`charge_src`、`province_src`。
- 生成方：`make_coding_sheet.py`（通用层给 `doc_type_src`、`case_no_src`、`province_src`）。
- 消费方：`qa_outputs.py` 不强制，但报告的「数据质量」一节必须能引用这些列。

## 6. 证据（evidence）

- `make_coding_sheet.py` 的证据列格式固定：`<字段>=<原文片段>@<char_start>-<char_end>`，
  多个用 `；` 分隔；片段长度 ≤ 200（超出用 `…` 截断，偏移量仍指向完整片段）。
- 否定优先：同一句里同时命中肯定与否定模式时，先看否定（`不|未|无|驳回|不予`），不得只因
  命中关键词就判为肯定。

## 7. 图与 PDF

- `pubfig.save_fig()` 默认不裁边、不 `bbox_inches="tight"`（会降分辨率）；需要留白时用
  `fig.subplots_adjust(top=...)`。
- 对数轴：设置 `xscale("log")` 后必须同时关闭次刻度标注
  （`ax.xaxis.set_minor_formatter(NullFormatter())`）。
- `export_pdf_hires.py` 回填原图后必须 `page.clean_contents(sanitize=True)`，
  并以 `garbage=4` 保存；否则旧低分辨率副本留在 `/Resources` 里。所给图题必须匹配；缺图、定位失败和多条映射重复指向同图以错误结束。
- `qa_outputs.py` 的分辨率判据是**有效 dpi**（像素宽 ÷ 版面宽英寸），不是像素宽；
  默认 `--min-dpi 600`，`--min-width` 仅作兼容保留。
- **字号也按版面折算**：独立源图用 `--min-fontsize 7.2` 与 `--target-width-cm`（默认 15）；最终稿须传 DOCX 的实际宽高，以图片内容 SHA 关联源 PNG/同名矢量 PDF，不能对所有图统一套默认 15 cm。
  15 cm 的图排进 8.5 cm 双栏后，8.5 pt 只剩 4.8 pt——按原始宽度报"合格"等于没检查。
  PDF 里没有文字层的图（回填成位图之后）**不能因为"没有 span"就判通过**，必须显式报 `no_text_layer`。
- **分类色两两灰度 ΔL\* ≥ 10**（CIE Lab，D65）。`CATEGORICAL` 是唯一色环，多系列图都从它取色；
  色板写进 manifest 的 `palette` 列（`#RRGGBB|#RRGGBB|…`），`qa_outputs --graycheck` 才能真的检查，
  否则它会静默跳过并报 `palette_unchecked`。
- 多类别长横轴保留同图，倾斜 45°/60°/75° 并增加底部空间；导出前检测实际旋转文字边界，不能容纳时明确失败，不自动分页、截断或缩小字。
- **多面板**用 `pubfig.compose_figure()` → 返回 `panel_sizes_cm`（每格实际厘米）与 `min_fontsize_pt`（实测），
  不要在自写脚本里手算 figsize；面板字母字号 = `max(8.5, base_size)`。

## 8. 退出码

- `0` 成功；`2` 参数错误或校验失败。
- `qa_outputs.py` 发现 error 时**默认返回 2**；`--exit-zero` 可显式降级（CI 里不要用）。
- 任何脚本「产出 0 行」都不得视为成功：必须有非零退出或显式 `--allow-empty`。
- `check_decisions.py` 有任何 error 返回 2；`make_coding_sheet.py --require-review` 在仍有未复审字段时返回 2（即使 dataset 已写出，也明确告知不是成品）。

## 9. 成稿（manuscript）

- 成稿由 `assemble_manuscript.py` 生成，**不手打表格**。规格文件 `manuscript.json` 的 `blocks` 引用 CSV 与 PNG；`{key}` 占位符只从 `--numbers` 取，取不到即 exit 2（禁止印出不完整数字）。
- 组装器必须同时产出三件：`<name>.docx`、`<name>_numbers.csv`（列 `key,value,source`，键名 `table<N>_n` / `figure<N>_n`）、`figure_map.json`（列 `[{tag,title,image}]`，image 为绝对路径）。`verify_numbers.py --numbers` 直接吃 `_numbers.csv`，`export_pdf_hires.py --figure-map` 吃 `figure_map.json`。
- 表：三线（顶 1.5 pt、表头下 0.75 pt、底 1.5 pt），无竖线；每行 `cantSplit`；首行 `tblHeader`；数字右对齐、首列左对齐。
- 图：按**正文栏宽**放置（默认 `min(15, 页宽-左右边距)`），显式宽度超过栏宽是 exit 2 而不是静默压缩；图题与图同页（`keepNext`）；Word 不能嵌 PDF，给 PDF 是 exit 2。
- 字体：每个 run 同时写 `w:rFonts/@w:ascii|@w:hAnsi|@w:eastAsia`，只写 ascii 会让中文回落主题字体；首行缩进用 `w:ind/@w:firstLineChars`（按字符），不要只写厘米。

## 10. 判断台账（`decisions.jsonl`）

- 一行一个判断；读取按 `utf-8-sig`，允许 `#` 注释行与空行。
- 必填：`id, stage, target, decision, reason, evidence, confidence`。
- `stage ∈ audit|extract|dataset|stats|figures|manuscript|qa`。
- `decision ∈ keep|drop|exclude|include|na|value|method|skip|accept|reject|note`。
- `target`：`<rel_path>#<field>` / 整份文档的 `<rel_path>` / `model:<id>` / `table:<n>` / `figure:<n>`。
- `evidence`：`<path>@<start>-<end>`（可选 `quote` 必须与片段一致）、`<path>`、`<path>::<locator>`。
- `confidence ∈ [0,1]`；`needs_human=true` 在交付闸门报错，只有草稿可 `--allow-unresolved`。
- 同一 target 的第二条必须带 `supersedes`，否则 `check_decisions.py` 报 `duplicate`。
- `extract` 阶段的 `value` 必须是 `extraction_review.csv` 的当前值或 `alternatives`；`na` 不要求候选，但必须给 span。
- 产物：`decision_issues.csv`（`severity,check,id,target,detail`）；有 error 退出 2。
- `make_coding_sheet.py --decisions` 把 `value` 写进 `dataset.csv` 并把 `<field>_src` 记为 `decision`，`na` 记为 `decision:na`；`exclude` 的 target 是整份文档的 `rel_path`，该行从 `dataset.csv` 移除，并在 `run.json.review.documents_excluded_by_decision` 计数。

## 11. 全资料、全数据集与整合后的逐格复核

- 完整 schema 与例子见 `references/12-exhaustive-research.md`；入口 `assets/research_registry.example.json`。registry 不限制数据集数量，`unit/key/codebook/path/provenance/review` 各自声明；原生格式自由，为每个经验字段提供无损 CSV 审计视图。
- `source_inventory` 的每份文件都有 `source_coverage` 记录；来源必须真的参与声明的数据集，遗漏、新文件和 excluded 仍供值均报错。原件与产出分目录，原件不移动。
- `provenance.jsonl` 一格一条，含 `key,column,value,kind`；实测/缺失/结构标识都有 `sources`（path/sha256/locator/raw），派生值有精确 `inputs` 和独立复算 `rule`。键、标记和空格同样覆盖，漏格、重复格、伪值、错位置、错哈希或循环依赖 exit 2。
- prepare 只能生成 pending 模板和快照；final 必须在整合后逐格重新读原材料/上下文，再校验 `record_sha256/status/source_reread/reviewer/method/checked_at/note`。禁止抽样代替全检、自动批量盖章；原件/数据/codebook/证据/适配器变更使旧复核失效。
- `dataset_verification.json` 中 stage=final、status=verified、error_count=0 是数据进入正式计算的必要条件。数字溯源 `verify_numbers` 是不同层的检查，不能替代本层。哈希与声明不能证明语义真实，Agent 仍必须执行并如实记录复读。

## 12. 开放模型、缺数回查与实际执行

- `model_plan.jsonl` 的 family 自由文本，数据集/模型数量均不封顶；内置方法不是候选清单上限。每候选明确问题、数据/设计要求、诊断、选择理由与状态。
- 数据不足必须回查原始清单；每个 gap 的 searches 覆盖所有来源，逐份记录 found/not_found/unreadable/not_relevant、哈希与依据，found 写 resolution；补取后重建数据与全格复核。无实际回查不能只写 skipped。
- completed 模型绑定 `run_model.py` 的成功回执、诊断文件、样本键 CSV 与实际 N；回执记录任意引擎的命令及所有输入/代码/输出完整 SHA256。输入、代码或结果变化不能沿用旧回执。
- `research_gate.py` 对资料覆盖、模型终态、补数过程、复核版本、运行回执和样本键作统一检查，有 error exit 2。它检查注册覆盖，不能证明所有潜在变量/模型已经被穷尽。
- `auto_stats` 的 max-predictors/max-models 默认 0=不限；`auto_chart_pack` 的 max-charts 默认 0=不限。正数预算须显式给出，试跑/图内展示取舍不能冒充完整交付；图表 data_hash 绑定全表顺序和值，文件字节另由执行回执绑定。

## 13. 模型样本量与 V-05（插件接入语义）

本次修复的 `verify_numbers.py` 版本为 **1.0.1**，其 `run.json` 的 `version` 可供插件识别工具版本；同时保留实际脚本/包哈希。

`auto_stats.py` 的 `fit.csv` 字段保持兼容，含义必须按生产代码读取：

| 字段 | 含义 | 可否作为实际模型 N |
|---|---|---|
| `n` | 实际进入拟合的观测数，已完成本模型的缺失/分离等处理 | 是；与系数表的 `n` 核对 |
| `n_dropna` | 因缺失值而剔除的行数，可以为 0 | 否；既不是保留行数，也不是模型 N |
| `subset` / 系数表 `sample` | 筛选/子样本声明；`full` 是默认组 | 用于确定比较口径，不是计数 |

例：5 行无缺失的 OLS 写 `n=5,n_dropna=0`；7 行中因缺失剔除 2 行、无其他剔除时写 `n=5,n_dropna=2`。两者的模型 N 都是 5。不能以 `n_dropna` 覆盖 `n`，也不能从已经处理完的 `n` 再减一次 `n_dropna`。涉及分离等其他处理时，不能仅凭这两个字段反推完整样本漏斗。

V-05 当前按声明的 sample/subset 分组、按 n_scope 区分口径，对 `coef_*.csv` / `fit.csv` 中的实际 `n` 检查一致性；它不要求模型 N 等于原始资料数，也不能判断全部样本选择是否合理。不同模型的预测变量、缺失机制、筛选或分离处理可能导致实际 N 不同，应核对并声明真实分析样本。V-05 报差异不等于已经证明数据错误或造假，需回查实际样本记录。

缺少 `n` 或 `n` 无法解析而只有 `n_dropna` 时，V-05 留下“无法核对”的 warning，不回退使用剔除数；严格终检用 `--fail-on-warn` 阻止把未核项目当通过。

插件可采用以下文案，具体 UI 由插件实现：

- **名称**：模型样本量一致性（V-05）。
- **tooltip**：核对模型表的实际估计样本量 n 及声明口径；n_dropna 是因缺失剔除的行数，不参与 N 比较。差异或缺少可用 n 时，需结合筛选、缺失、分离等处理回查。
- **prompt/注释**：以 fit.csv、coef_*.csv 的 n 为实际估计 N；禁止使用 n_dropna 作为 N。逐模型说明样本范围与排除原因；对 V-05 的差异或无法核对项保留具体原因和证据，不改写统计结果来消除报警。
- **旧版本结果**：因 n_dropna 误用产生的 V-05 结果需用修复版重跑；临时“待复核”可注明“旧版字段语义错误，等待重新核查”，不能长期把该错误优先级解释为统计规则。
- **新版本结果**：仅在本次比较覆盖充分、无差异且无无法核对项时显示“本次 V-05 检查通过”；有实际差异、资料不足或其他未完成复核时保留“待复核”及具体原因。通过不代表所有数据来源与研究语义已经验证。

---

本文件随 skill 一起打包（`references/10-contracts.md`）。
