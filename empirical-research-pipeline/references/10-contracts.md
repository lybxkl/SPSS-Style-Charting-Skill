# 跨脚本契约（v1.1）

内置脚本与 Agent 自选实现通过文件契约衔接。数据集形态、数量、模型与引擎开放；来源、版本和样本口径各档统一。逐格复核只在归档档统一，见第 11 节。
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
- 至少覆盖：`year_src`、`trial_level_src`、`court_level_src`、`charge_src` 等你声明的派生字段。
- 生成方：你在编码时加；`make_coding_sheet.py` 通用层只给 `year_src`、`doc_type_src`，`--extract` 层为每个抽取字段写 `<字段>_src`。
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
  默认 `--min-dpi 600`。旧的像素宽旗标 `--min-width` 与空操作旗标 `--strict` 已删除
  （传入 exit 2 报无法识别；解析器关闭前缀缩写，`--strict` 不会被吞成 `--strict-palette`）。
- **字号也按版面折算**：独立源图用 `--min-fontsize 7.2` 与 `--target-width-cm`（默认 15）；最终稿须传 DOCX 的实际宽高，以图片内容 SHA 关联源 PNG/同名矢量 PDF，不能对所有图统一套默认 15 cm。
  15 cm 的图排进 8.5 cm 双栏后，8.5 pt 只剩 4.8 pt——按原始宽度报"合格"等于没检查。
  PDF 里没有文字层的图（回填成位图之后）**不能因为"没有 span"就判通过**，必须显式报 `no_text_layer`。
- **配色为可调整的推荐**：`CATEGORICAL` 是 8 色默认值，不是唯一色环或系列数上限。Agent 可按数据含义与用户/期刊要求选择其他颜色/映射/冗余编码；详细建议见 `04-figures-publication.md`。
- manifest 的 `palette` 记录实际可提取的数据图元颜色（含边线/CI/透明度，不等同于语义类别数）；`palette_source` 记录来源，`colormaps` 记录实际标量色图。`palette_kind` 可自由声明用途，未声明的新图按艺术对象推断；旧清单缺省 categorical 仅为兼容诊断。连续映射不展开成离散类别色，也不以默认色环填充空取色。
- `qa_outputs --graycheck` 默认提供分类色板建议，低于内部 `ΔL*` 阈值只 warning；色觉模拟 `--colorblind` 也只提示。`--strict-palette` 是用户/项目明确选择时的额外严格检查，不是通用投稿要求。未知/不适用用途、未解析/透明色、只推测的默认色环等保留为未完成/未适用，`pairwise_checked` 与 `complete` 不得伪报；按有效图统计 `palette_unchecked` 并传给审稿包。显式严格的分类色检查无法解析时报错，透明度/背景仍转实际渲染复核。元数据本身不证明真实图像颜色正确。
- 多类别长横轴保留同图，倾斜 45°/60°/75° 并增加底部空间；导出前检测实际旋转文字边界，不能容纳时明确失败，不自动分页、截断或缩小字。
- **多面板**用 `pubfig.compose_figure()` → 返回 `panel_sizes_cm`（每格实际厘米）与 `min_fontsize_pt`（实测），
  不要在自写脚本里手算 figsize；面板字母字号 = `max(8.5, base_size)`。

## 8. 退出码

- `0` 成功；`2` 参数错误或校验失败。
- `3` 是**少数脚本各自成文的特定非致命/环境边界**，语义按脚本 docstring：`mine_candidates.py`=挖掘引擎自身失败（缺 scikit-learn）；`auto_chart_pack.py`=一张图都没产出（数据列或 --only/--sections 过滤问题，台账仍写出）；`gates.py`=台账锁冲突（并发写，重试即可）。其余脚本不用 3。
- `qa_outputs.py` 发现 error 时**默认返回 2**；`--exit-zero` 可显式降级（CI 里不要用）。
- 任何脚本「产出 0 行」都不得视为成功：必须有非零退出或显式 `--allow-empty`。
- `check_decisions.py` 有任何 error 返回 2；`make_coding_sheet.py --require-review` 在仍有未复审字段时返回 2（即使 dataset 已写出，也明确告知不是成品）。

## 9. 成稿（manuscript）

- 成稿由 `assemble_manuscript.py` 生成，**不手打表格**。规格文件 `manuscript.json` 的 `blocks` 引用 CSV 与 PNG；`{key}` 占位符只从 `--numbers` 取，取不到即 exit 2（禁止印出不完整数字）。
- 组装器必须同时产出三件：`<name>.docx`、`<name>_numbers.csv`（列 `key,value,source`，键名 `table<N>_n` / `figure<N>_n`）、`figure_map.json`（列 `[{tag,title,image}]`，image 为绝对路径）。`verify_numbers.py --numbers` 直接吃 `_numbers.csv`，`export_pdf_hires.py --figure-map` 吃 `figure_map.json`。**这是脚本无关的硬契约**：自编写稿脚本同样必须产出 `figure_map.json` 与 `manuscript.json`（含 title/table blocks）作为图/表/文稿的显示名来源；`qa_outputs.py --figure-map --manuscript-spec` 在终检校验二者存在且可解析，缺任一即 error。只产 docx 而跳过命名源，会让下游查看器把全部图/表回退成英文文件名。
- 命名源不止正文引用的表/图：交付还必须含 `table_map.json` / `doc_map.json`（`[{tag,title,file}]`，file 可相对可绝对，默认位于 `output/` 根），覆盖**全部**交付表/文档（报表、稳健性表、复核包、修订说明等）。`report_tables.py` 自动登记其报表与 data_report.md，`assemble_manuscript.py` 自动登记正文表，`review_pack.py` 自动登记复核包；合并以归一化 file 路径为键，后写覆盖同名条目，不丢其他来源的条目。`qa_outputs.py --table-map --doc-map` 校验存在、可解析、有带标题条目（缺=error）；`layout_conformance.py` 另按目录骨架核覆盖（§17）。
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

本节只在验收档 archive 执行。explore 与 submission 不把逐格 final 当作统计或交付的前提。

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

## 14. 重跑规则（`workflow.json` 的 `rerunRules`）

- 规则按**数组顺序、首条命中生效**（引擎 `rerunStages` 用第一个 exact 或前缀匹配）。因此 34 条 `scripts/<名字>.py` 精确规则排在通用 `scripts/` 前缀之前；改一个具体脚本只重跑它实际供血的阶段（含传递下游），不再整链重来。
- 规则清单由工作流自身声明推导：某脚本被某阶段的 step/action 执行 → 该阶段 + 传递依赖闭包；库脚本（`pubfig`/`methods_lib`/`analysis_utils`/`text_extract`/`extract_lib`）→ 导入它的那些脚本（含传递导入）的**阶段并集**。
- **建议性工具映射为「只重跑自己的阶段」**：`mine_candidates.py`/`suggest_profiles.py`/`check_decisions.py`/`sample_review.py`/`compute_kappa.py` 的产物没有机器下游消费者，改它们只影响各自的建议/校验输出，不推翻数据集。
- 其余约 30 个未被任何 step/导入链覆盖的脚本（`entities.py`、`validation.py`、`gates.py`、`claims.py` 等；`contract_v2.py` 有自己的精确规则，不在其中）落到通用 `scripts/` 前缀=全链重跑：引擎无法推断时的保守默认。
- `recheck`/`publish` 不进任何规则（既有约定：归档档与宿主交接由引擎另行驱动）；`scope` 阶段同不进规则（范围界定永远人工发起）。
- `data/` 前缀=全链（输入变了，一切下游作数）；各 `output/` 前缀=其消费者阶段。`output/mining/` 等无机器消费者的目录不加规则（与建议性工具同口径）。

## 15. 范围符合性（scope conformance）

**硬闸门，不是建议。** 分析样本里出现声明范围外的命名类别即数据错误，必须在进统计前排除或显式修订白名单；不得以"图已经画了""数字对得上"为由保留。

- 每个数据集在 `scope.json`（或 `scope.md` 的机读段）为决定范围的分类列声明纳入白名单：`{"columns": {"<列>": {"include": [...]}}, "min_cell_n": N}`。纯通用契约，引擎不内置任何学科类别词。
- 生成方：你在阶段 0/3 声明；消费方：`scripts/scope_conformance.py --data <分析表> --scope scope.json`。
- 判据：分析表中**任何声明范围外的命名类别只要 n>0 即 error（exit 2）**；声明列在数据中缺失即 error；缺失值记 warning 并要求声明处理方式；`--cell-cols A,B` 对 n<min_cell_n 的单元格记 warning（率表/热图小样本格不稳定）。
- 产出 `scope_conformance.csv`（`column,value,n,in_scope,severity,note`）。范围外类别须按声明排除或显式修订白名单并记录理由，不得静默留在分析样本。
- 与样本漏斗（§2）互补：漏斗核"掉多少"，本契约核"留下的类别是否都在声明范围内"。两者都对任何学科适用。

## 16. 阶段双遍审计（stage audit，零信任）

**硬闸门，不是建议。** 每个阶段完成后必须≥2遍、角度互异、**方法互异**的全方位审计，留台账并经**零信任**机器校验，才能进下一阶段。审计器不信任被审计步骤的任何自报：退出码、证据字符串、中间 CSV 都要被重跑/回读/重算验证。

- 台账 `output/qa/stage_audit.jsonl`，一行一遍：`{"stage","angle","method","artifacts","evidence","findings","at"}`。
  - `method ∈ recompute|rerun|rescan|replay|reextract|reread|mutation`（必填）。
  - `artifacts`：`{相对路径: sha256}`，本遍审计过的产物快照（必填，≥1 项）。审计器重算哈希，字节变过即该遍作废。
  - `evidence.commands`：`[{"cmd","exit"}]`。审计器用 shlex 解析、**无 shell 实际重跑**，真实退出码与声明比对；命令必须是幂等校验命令，且**必须能从 `--root` 直接运行**（在项目目录运行时写 skill 脚本的绝对路径，不要写相对 `scripts/`，否则重跑会因找不到脚本而假失败）。**白名单（零信任）**：台账本身是不可信输入，审计器只重跑 `audit_probe.CHECKER_ALLOWLIST` 里的已知校验脚本，拒绝 `python -c/-m` 与任何非校验脚本——伪造台账不能把审计器当武器去执行任意/破坏性代码。
  - `evidence.samples`：`[{"rel_path","span":[s,e],"quote"?,"field"?,"value"?}]`（结构化，自由文本不算证据）。审计器自己回读原文（二进制走 `text_extract`、CRLF 归一），核 span，**quote 必须 ⊆ span**；给 field+value 时比对 `--data` 单元格。
  - `findings`：`[{"detail","resolved","resolution"?}]`。`resolved=false` 报错；`resolved=true` 必须带 `resolution`（`{"cmd","exit"}` 或 `{"artifacts":...}`），命令同样被重跑。
- 生成方：你在每阶段完成后追加两遍（第 1 遍机器/口径，第 2 遍独立/语义/漂移）；消费方：`scripts/stage_audit.py --ledger ... --require <阶段> --root . [--data ... --scope ... --registry ... --flow ...]`。
- 判据：每阶段≥2遍、≥2互异角度、≥2互异方法、每遍产物哈希绑定且未变、命令重跑退出码一致（且命令在白名单内）、样本机器回读通过、**至少一遍回读原始资料**、方法标签与证据一致、无未解决/无 resolution 的 finding；审计器另从表本身重算漏斗单调（含 excluded/model 边界）、范围/时间符合性、声明关联基数。任一不满足 → exit 2。**自动探测**：未显式给 `--scope/--registry/--data` 时，自动探测项目根的 `scope.json`/`research_registry.json` 与 `output/dataset/analysis.csv`，使默认 `--root .` 调用即触发重算，而非靠可选旗标才生效。
- 深度随验收档（submission 抽样、archive 逐格），但遍数≥2、角度互异、方法互异、留台账、零信任验证任何档不豁免。`--no-rerun`/`--no-recompute`/`--exit-zero` 仅调试，交付禁用。
- 原语库 `scripts/audit_probe.py` 是哈希绑定/命令重跑/原文回读/span-quote/漏斗/键唯一/重扫/重放/关系/时间的唯一实现；测试与审计都调用它，不得各写一份。

## 17. 目录骨架与全量命名覆盖（layout conformance）

**硬闸门，不是建议。** 查看器与下游消费者需要跨运行/跨模式稳定的目录面：物理别名归入规范骨架，杂散目录与无标题交付件在交付时被卡住。「目录是脚本默认写出的」「别名目录历史上就这么叫」「表不在正文里」「查看器能显示英文就行」**都不是**跳过理由；交付说明必须写 `layout_conformance.py` 的实际命令与退出码，只写「已检查」视为未检查。

- 规范骨架（闭合枚举，`scripts/layout_conformance.py` 是唯一知识源）：`output/audit`=审计；`output/coding`=编码（含 kappa）；`output/dataset`=数据（含 cleaning/datasets/data_verification）；`output/stats`=统计（含 models/methods/analysis_pack）；`output/figures`=图（含 chart_pack/paper_figs）；`output/tables`=表（含 reports）；`output/docs`=文档（含 review）；`output/qa`=质检；`output/verify`=溯源；`output/ledger`=台账（含 gates/v2/recheck/claims）；`output/mining`=挖掘。
- 已知别名自动归组，无需声明；自定义目录在 `research_registry.json.layout` 声明“规范组 → 物理目录列表”，例如 `{"output/tables": ["output/custom_tables"]}`。未声明的杂散目录、非规范键、同一目录挂两个组均 error；空目录 warning。`artifact_paths` 保持原语义（门禁资源绑定），不替代 `layout`。
- **已知别名目录不得经 `layout` 改挂其他组**（改挂即 error）：把表组目录挂去不核覆盖的组即可逃避命名契约，故堵死。交付表/文档一律写入表组/文档组目录，不得借统计/质检等不核覆盖的组目录存放交付件逃避命名；阶段双遍审计的第二遍必须专查此类逃避。多轮编码等额外目录放规范组子目录（`output/coding/r1`、`output/coding/r2`），不建 `coding-r1` 这类一级杂散目录。
- 契约面同步：workflow.json 在 assemble/report_tables/review_pack 的 produces 声明 `table_map/doc_map`，qa 步骤带四个命名源旗标，rerunRules 为 `output/table_map.json`/`output/doc_map.json` 各加 exact 规则（manuscript,qa），与 figure_map 同口径。
- 命名覆盖：表组内全部 `.csv/.tsv/.md`、文档组内全部 `.md/.docx/.pdf`、output 根同级 `.md/.docx/.pdf`（manuscript.docx/pdf 除外，由 manuscript.json title block 覆盖）必须在 `table_map.json`/`doc_map.json`（或 manuscript.json table block）有非空标题条目，否则 error。
- 消费方：`scripts/layout_conformance.py --root <项目根>` 退出码 0 才能交付；分组与裁决写 `output/qa/layout_conformance.json`，只读查看器据此渲染规范组（插件不内嵌别名表，避免双份维护漂移）；无该报告的旧工作区回退物理目录显示。`--exit-zero` 交付禁用（同 qa_outputs）；扫描上限到达时 coverage 可能不完整，报告留 warning，不得据此宣称已核覆盖。
- 终检 `qa_outputs.py --table-map --doc-map` 与 `--figure-map` 同语义：命名源缺失/不可解析/无带标题条目 = error。

## 18. 关系与单位符合性（relation conformance）

**硬闸门（声明了跨数据集关联时）。** 关联是*声明*，不是引擎虚构的外键。提交档用轻量检查补上跨表关系的机器核对，与归档档 `entities.py` 的 join 账本互补。

- 注册表 `research_registry.json` 除 `datasets`（各自 `id/path/key/unit`）外，可声明 `joins`：`[{"left","right","on","how","expect","result_n"?,"unit"?}]`。`on` 为列名或 `[左列,右列]` 对；`expect ∈ 1:1|1:N|N:1`；`how ∈ left|inner`。
- 消费方：`scripts/relation_conformance.py --registry ... --root .`。判据（从表本身重算）：每个数据集 key 列存在且唯一（重复键=error，单位声明不符）；**join 列必须在两表都存在**（缺列=error——否则空键会把每行伪匹配在一起）；`how ∈ left|inner`、`expect ∈ 1:1|1:N|N:1`（非法值=error）；join 的孤儿键、fan-out（`expect=1:1/N:1` 时一个左键匹配多右键=error）、**声明基数中“1”侧的连接键必须唯一**（1:N 的左键、N:1 的右键重复=error）、`result_n` 行数对账（声明≠重算=error）。
- 粒度不一致强行建模（个人-时期并进个人、many-to-many 放大 N）在此暴露，而不是画进图里才发现。不声明 joins 不报错，但等于把关系正确性完全交给模型自觉——审计第二遍必须专查。

## 19. 时间规则（temporal scope）

范围符合性不止分类白名单。`scope.json` 可声明通用时间规则，引擎不内置任何领域日期：

```json
{"columns": {"...": {"include": ["..."]}},
 "temporal": [{"col": "date", "min": "2021-01-01", "max": "2021-12-31"}],
 "intervals": [{"key": "id", "start": "valid_from", "end": "valid_to"}]}
```

- `temporal`：日期列越界（含未解析 warning）即 error；`intervals`：同一主键的生效区间重叠（同一时刻两条记录都有效，SCD/拉链合法性）即 error，**区间 end 早于 start 即 error**，不可解析的区间日期记 warning。**月精度边界按整月展开**：`max: 2021-12` 含到 2021-12-31，`min: 2021-01` 从 2021-01-01 起（不是 12-01/01-01 截断）。
- 消费方：`scope_conformance.py`（声明了 temporal/intervals 时自动核）与 `audit_probe.check_temporal`（stage_audit 重算用）。日期解析支持 `YYYY-MM-DD`/`YYYY-MM`；区间 end 缺失按开放区间处理。
- 业务状态机的*转移合法性*属领域逻辑，写进项目剖面/代码book，不写死在引擎；本契约只提供通用的时间边界与区间重叠核。

## 20. 全量证据回验（evidence replay）

**硬闸门（有抽取层时）。** 把 references/09 §5 的"证据 100% 可回验"从夹具测试变成可交付闸门。

- 消费方：`scripts/evidence_replay.py --evidence output/coding/evidence.jsonl --root <资料根> [--dataset ...] [--profile ...]`。逐条 evidence 行回读原文（二进制走 `text_extract`、CRLF 归一）跑 `extract_lib.verify_evidence`；给 dataset 时再核字段 span 与单元格值，并核**覆盖率**——每个数据集行都必须有对应证据记录，缺记录的行=error（coverage gap）。
- receipt 绑定 `extract_lib.py`/`text_extract.py` 的 sha256 与 profile sha256——换解析器不能沿用旧"verified"。任何失败/缺源/空输入 exit 2。

## 21. 语料重扫（rescan / freshness）

**交付前必跑。** 审计台账是审计时刻的陈述，证明不了目录还是那个目录。

- 消费方：`scripts/rescan_corpus.py --root <资料根> --audit-out output/audit`，或终检 `qa_outputs.py --audit output/audit/corpus_files.csv --rescan`（从 `corpus_summary.json` 读 root 自动重扫）。用同一抽样框复用 `audit_corpus` 重扫到 scratch，比对 `corpus_fingerprint` 与逐文件 `rel_path/bytes/md5`。新增/消失/内容变更 = error，须重审。方法复用原审计，不另写一份会漂移的实现。**诚实边界**：原审计用了 `--no-hash` 时 md5 不可用，内容变更只能按字节数判（同尺寸改动证不出），报告留 warning——要铁证就带哈希重审。

## 22. 清洗重放（cleaning replay）

**硬闸门（做过清洗时）。** "复核靠重放"落成命令。

- 消费方：`scripts/cleaning_replay.py --dataset ... --recipe draft/cleaning.json --audited-out output/cleaning`。同 dataset+recipe 重跑到 scratch，比对 `clean_dataset.csv` 字节与 `cleaning_log.jsonl` 的 `sha_in/sha_out` 链；并枚举**完整**丢行集——声明了 `id_columns` 按 id 枚举，未声明则按整行内容枚举（不止日志里的 20 条样本，也不因没声明 id 就返回空）。分歧 exit 2。

## 23. 闸门金丝雀（gate canary，元审计）

审计器本身也要被审计：恒返回 0 的闸门等于没有闸门。

- 消费方：`scripts/gate_canary.py [--only ...]`。在合成夹具上跑各闸门：clean 副本必须 exit 0，植入已知错误的副本必须 exit 2。漏抓或误报即判该闸门坏，exit 2。安装/升级后或 CI 中跑，确认装上的闸门真能抓错。覆盖 scope_conformance/check_decisions/relation_conformance/clean_data/evidence_replay/stage_audit/rescan_corpus/cleaning_replay/temporal。

---

本文件随 skill 一起打包（`references/10-contracts.md`）。
