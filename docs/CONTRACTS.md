# 跨脚本契约（v1.1）

这 11 个脚本是一条流水线，不是一个库。过去它们各自选列名、各自理解 N、各自处理缺失，
结果是「接上一个真实项目就得重写中间层」。下面六条是硬契约：**生成方必须写、消费方必须认、缺了必须报错**。
所有实现与测试都以本文件为准；修改本文件需要同步 `SKILL.md` 与相应脚本。

---

## 1. 键列（key）

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
  并以 `garbage=4` 保存；否则旧低分辨率副本留在 `/Resources` 里。
- `qa_outputs.py` 的分辨率判据是**有效 dpi**（像素宽 ÷ 版面宽英寸），不是像素宽；
  默认 `--min-dpi 600`，`--min-width` 仅作兼容保留。
- **字号也按版面折算**：`--min-fontsize 7.2` 与 `--target-width-cm`（默认 15）一起用。
  15 cm 的图排进 8.5 cm 双栏后，8.5 pt 只剩 4.8 pt——按原始宽度报"合格"等于没检查。
  PDF 里没有文字层的图（回填成位图之后）**不能因为"没有 span"就判通过**，必须显式报 `no_text_layer`。
- **分类色两两灰度 ΔL\* ≥ 10**（CIE Lab，D65）。`CATEGORICAL` 是唯一色环，多系列图都从它取色；
  色板写进 manifest 的 `palette` 列（`#RRGGBB|#RRGGBB|…`），`qa_outputs --graycheck` 才能真的检查，
  否则它会静默跳过并报 `palette_unchecked`。
- **多面板**用 `pubfig.compose_figure()` → 返回 `panel_sizes_cm`（每格实际厘米）与 `min_fontsize_pt`（实测），
  不要在自写脚本里手算 figsize；面板字母字号 = `max(8.5, base_size)`。

## 8. 退出码

- `0` 成功；`2` 参数错误或校验失败。
- `qa_outputs.py` 发现 error 时**默认返回 2**；`--exit-zero` 可显式降级（CI 里不要用）。
- 任何脚本「产出 0 行」都不得视为成功：必须有非零退出或显式 `--allow-empty`。
