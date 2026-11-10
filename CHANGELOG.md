# CHANGELOG

本仓库此前没有版本记录，从本轮起按日期记。缺陷编号对应 `docs/ISSUES-FIXED.md`（审计索引），审计明细在 `docs/skill-audit/` 之外未随仓库发布——本文只保留可验证的行为变化。

---

## 2026-11-10 缺陷修复轮次

一次逐文件读码审计（4 份报告，132 条缺陷：P0 4 / P1 61 / P2 67）之后的系统性修复。所有改动向后兼容：旧列名、旧参数全部保留，新行为只加不减。

### 新增：跨脚本契约与测试

- `docs/CONTRACTS.md`：8 节契约（主键、样本漏斗、图表 N、缺失值、来源、证据句、图与 PDF 规格、退出码）。此前脚本之间对同一概念各写各的，缺陷大多出在这些缝隙上。
- `tests/`：159 个 `unittest` 用例（audit 44 / coding 59 / stats+charts 25 / chart-pack 18 / output 13），fixture 全部运行时生成，不需要网络、真实资料、SPSS 或 Word；检测不到 Word COM 时相关用例自动 skip。

### 资料审计与去重（`audit_corpus.py`、`dedupe_corpus.py`、`text_extract.py`）

- **单个文件读不出不再让整次扫描崩溃**（AUD-01）。此前 `os.path.getsize()` 在遍历循环里没有 try/except，一个坏文件抛错会丢掉已扫描的全部结果；现在记 `status="unreadable"` + `error_kind` + `error`，末行汇总 `unreadable: N`，`--fail-on-issues` 可要求退出码 2。
- Windows 隐藏文件按 `st_file_attributes` 判定（AUD-02），不再只认点开头。
- 新增 `chars_effective`：剔除纯页码行（`1/3`）与空白后的有效字符数（AUD-03/04）。`--min-chars` 与 `textless`/`image_only` 判定改用它；`chars` 保留原义以免破坏旧脚本。此前 26 页纯扫描件每页印一个页码，`chars=147` 就被判为 valid。
- 新增 `--content-dedupe`（AUD-05）：对 valid 文件的正文做归一化 sha1，写 `dup_content_group` / `dup_role_content`。MD5 只能抓字节相同的副本，同一判决的不同导出版本（带法院前缀、`- 副本`、下载时间戳）此前完全漏掉。
- `corpus_summary.json` 新增 `sampling_frame`（root / ext / skip_dir / min_chars / content_dedupe / generated_by），报告顶部打印「抽样框」（AUD-06）。没有抽样框就无法判断样本是怎么来的。
- **列名统一**（AUD-07）：审计 CSV 同时写 `rel_path`（首列，契约规范名）与旧名 `relpath`。此前只有 `relpath`，下游按 `rel_path` 取会静默得到 0 行。
- 根目录文件 `top="(root)"`（AUD-08），此前为空串，无法与省级目录区分。
- `--skip-dir` 用 casefold 比较（AUD-09）；`--out-dir` 位于 `--root` 之内时按产物文件名跳过，二次运行 `total_files` 不再自我膨胀（AUD-11）。
- keeper 选择顺序对齐 `references/01`（valid → year → 无副本痕迹 → 路径浅 → 文本完整 → 字节大），并把理由写进 `keeper_reason`（AUD-13）。
- `dedupe_corpus.py --apply` 前校验 keeper 仍在盘；缺失时整组跳过并记 `skipped`（DED-01）。此前删掉 keeper 后唯一副本会被搬走且退出码 0。`failed>0 or skipped>0` 一律退出码 2（DED-02）。新增 `move_log.csv`（group/src/dest/action/status/reason）与 `--undo`（DED-04）；`--undo` 同时处理 move/copy，copy 仅在 MD5 一致时才删。
- `text_extract.py` 新增 CLI（EXT-01）：`--root` / `--file`（可重复）/ `--out`（csv|jsonl）/ `--ext` / `--max-files` / `--min-chars` / `--text`。此前该文件只有函数、没有 `__main__`，文档却把它当脚本用。
- latin-1 兜底解码现在会被标记（EXT-02）：`encoding="latin-1(fallback)"` + `error="decoded as latin-1; mojibake likely"`。此前损坏文件被静默"成功"解码成乱码。
- 抽取返回同时给 `chars` 与 `chars_effective`（EXT-10），消除 skill 内部三处口径不一致。

### 编码与数据集（`make_coding_sheet.py`、`analysis_utils.py`、`csv_to_spss_syntax.py`）

- **排除必须留痕**（B7，唯一 P0）：`--audit` / `--dedupe-plan` 的排除此前是裸 `continue`，排在所有 `skip()` 之前，被排除的文件不进 `skipped_documents.csv`；`--audit` 全部无效时照样退出码 0 并打印 `extracted: 0`。现在走统一的 `skip()`，逐条写 `skipped_documents.csv`（含 reason / detail / skip_stage / file_kind），全部无效时退出码 2，正常结束打印 extracted / skipped / excluded 三个数，并生成 `sample_flow.csv`（stage,n,note）。样本漏斗第一次可以从产物重建而不是靠手写。
- 案号正则从 8 种案由扩到 19 种（含民申/民辖终/执异/破申/诉前调），并覆盖「字第」「之一」（B1）。
- 法院名必须有行政区划前缀或为最高法，排除"原审/一审/二审/本院"误抓；被 `****` 脱敏的记空串并标 `court_src=redacted`（B2）。
- 文书类型判定取正文尾部 1500 字，先看「裁定如下」再看「判决如下」（B5）；`--doc-type` 可重复并做白名单校验（B6）。
- **证据句契约化**（B8）：格式 `<字段>=<原文片段>@<char_start>-<char_end>`，顿号/逗号也参与分句，片段超 200 字加「…」但偏移量始终指向整句。此前 `sent[:500]` 硬截断会把长判决主文砍掉六成，且没有任何位置信息，无法回到原文定位。
- **否定优先**（B9）：同一句先判否定，命中项带 `negated` / `polarity`。此前"驳回…管护费的诉讼请求"这类否定句与肯定句并列命中，`references/02` 承诺的"否定优先"零实现。
- 关键词命中合并案由与文件名两路并去重；`--profile legal` 未给 `--keywords` 时自动载入 `assets/coding-keywords.json`（B10）。
- 标题解析跳过法院/检察院行（B11）；遍历顺序稳定并写 `run_order`（B12）；新增 `--max-text-chars` / `--no-text` 与 `text_truncated` 标记（B14）。
- `analysis_utils.outcome_kind()`（A1/A2）：整列缺失返回 `unsupported`，不再伪造 `{'0':0,'1':1}` 映射；新增 `is_code_like()` 判定码值列（基数 > 12，或基数 ≥ 5 且占行数一半以上）避免把省份码 1–31 当连续变量塞进 OLS。
- NA 哨兵归一（A4）；`_src` / `_ev` 辅助列不再进入建模（A5）。
- `apply_filter`（A6）：比较前统一 dtype；过滤后 0 行 `raise ValueError` 而非静默返回空表；显式 `filter_query` 与 `in_analysis` 并存时在 stderr 打印「in_analysis ignored」；描述统计标题带「X→Y rows」。
- `csv_to_spss_syntax.py`：千分位与 NA 哨兵并存时仍识别为数值列（S1）；新增 `--encoding`（默认 utf-8-sig），写文件编码与 `/ENCODING` 声明一致，GBK 用 gb18030 落盘（S2）；数值变量写 `MISSING VALUES`（哨兵冲突时换 -999999）、每列写 `VARIABLE LEVEL`、分类变量写 `VALUE LABELS`（S3）；分隔符嗅探 `, ; \t |`（S4）；值标签截到 118 字节（S5）；改名结果写 `renamed_map.csv`（S9）；CJK 支持扩到非 BMP（S10）。

### 统计与图表（`auto_stats.py`、`pubfig.py`）

- **新增 `--spec` 多变量入口**（S-01）：logit / ols，支持 `cluster` 聚类稳健、`cov=HC0|HC1|HC3`、显式参照组、`dropna`、`outcome_map`；输出 `coef_<id>.csv`、`model_summary.md`、`model_meta.json`。此前 `auto_stats.py` 全程只有 4 处单变量 `sm.Logit/OLS`，多变量主模型在架构上根本无法由本 skill 产出。`coef_<id>.csv` 的列可直接喂 `auto_chart_pack.py --coef` 画森林图。
- 参照组必须显式声明（`C(名, Treatment('水平'))` 或 spec 的 `ref`），未声明退出码 2 并列出全部可选水平（S-03）。
- 拟合前逐分类变量做空单元格检测，`--separation drop|merge|error`（默认 drop）写 `separation_report.csv`；`|β|>12` 或 `se>8` 的估计熔断且不写进系数表（S-02）。此前分离检测只覆盖二分类单变量层，多分类哑变量分支完全无防护，准分离会产生 OR=161 这类假结果。
- NaN 不再变成字面量 `"nan"` 水平（S-04/06）；新增 `p_bh`（BH-FDR）（S-07）；Fisher 检验时把 statistic 成对改成 OR（S-11）；率一律带 95% CI 与 n（S-12）；结局识别收敛到 `resolve_outcome`（S-13）；偏态连续变量自动改用 Spearman（S-06）。
- **六处静默 `continue` 全部落表**（S-08 / S-09 / S-10）：`univariate_skipped.csv` 记 stage / outcome / predictor / reason / n / events，空表也写表头（S-09 的空表不落盘）。`filter_query` 含 `@` / `__` / `import` / `exec` / `eval` / `lambda` / `;` 直接退出码 2。
- 新 CLI：`--spec`、`--separation`、`--vif`、`--roc`、`--robust{HC0,HC1,HC3}`、`--only`、`--sections`、`--max-predictors`（默认 60）、`--max-models`（默认 20）；超限报错而不是静默截断。
- **log 轴次刻度**（P-07，同一个缺陷在交付层记为 D-03）：新增 `_fix_log_ticks()`（NullLocator + NullFormatter + `{x:g}` 固定主刻度），`forest_plot` 与 `scatter_fit` 的 log 轴都调用。此前 `4×10⁻¹` 这类科学计数次刻度会与主刻度混排。
- **留白不再靠 `bbox_inches="tight"`**（P-01/P-02/P-05/P-06，交付层同一组缺陷记为 D-04）：`save_fig()` 新增 `pad` 参数走 `subplots_adjust`；`stacked_bar` / `stacked_area` 新增 `legend_loc` / `legend_anchor` / `adjust_top` 并返回实际 top；`bar_with_ci` 新增 `ylim_headroom` / `annotate`；`pie_chart` 新增 `label_threshold`。实测 `bbox_inches="tight"` 会把 885 px 图压到 724 px、3543 px 压到 2899 px，直接跌破 600 dpi 门槛。
- `forest_plot` 新增 `_clip_huge_span()`（P-04）：log10 跨度 > 8 时裁 xlim 并注明「部分 CI 超出显示范围」。
- `short_label`（P-03）：`var[T.水平]` → `var：水平`，只有超长才截断加「…」；同时剥掉 patsy 外壳，`C(x)[T.甲]` → `x：甲`、`C(g, Treatment('a'))[T.b]` → `g…：b`。
- `set_style` 真正写 `figure.figsize`（15 cm），显式 figsize 优先（P-16）。

### 图表包（`auto_chart_pack.py`）

- manifest v2 固定 17 列：`id,question,chart_type,variables,n,n_scope,png,pdf,caption,dpi,px_width,model_id,data_hash,tiff,note,section,status`；`dpi` / `px_width` 由 PIL 从 PNG 读回，`data_hash` = 列名 + 行数 + 关键列 md5 前 8 位。
- `parse_n()` 支持整数 / 千分位 / 区间（`3111→2713`，取首整数入库、display 保留原文）/ `N=` 前缀；`fill_caption_n()` 全局替换每个 `N=`（原实现 `count=1` 漏掉第二个）；`n<=0` 记 `status="skipped: n<=0"` 并保留在 manifest；`n > 数据行数` 且 `n_scope != corpus` 记 error 并退出码 2。
- 多变量图不再有单一 N 的假象：`binary_prevalence` 的 manifest `n` 从 `min(sizes)` 改为区间 `min→max`，`n_scope="subgroup"`，`note` 写明 per-variable n 范围。
- 新 CLI：`--only`（图号 / slug / 片段 / 逗号分隔 / `前缀*`）、`--sections`（字母或中文段名）、`--max-charts`（默认 60，0 或负数 = 不限）、`--list-charts`、`--n-scope`、`--no-tiff`（TIFF 现为默认开，对应 P-08 的"只出这几张"入口与 P-12 的"TIFF 应为默认"）。
- 版式：新增 `adjust()` / `_legend_overflow()` / `_lift_legend()`，轴外图例先重锚再按实测溢出收 `top`（pie / donut 另收 `right`），`note` 记 `top=` / `right=`。不再依赖会压扁柱子的 `tight_layout`。`note` 列不再恒为空（P-10）。
- manifest 的 png / pdf / tiff 全为相对 manifest 目录的 POSIX 路径（新增 `rel_path()`），移动整个输出目录后仍可定位。
- 全部图统一 15 cm 版心：Q-Q 与环形图的 `figsize=(4.8, 3.8)` 改为 `(FIG_W, 3.8)`，43 张图 `px_width` 全为 3543（此前有 2880）。
- 森林图按 `metric` 分组绘制（logit → OR 对数轴、OLS → β 线性轴），混排不再丢行；`metric` / `rows_plotted` / `rows_dropped` 进 JSON 与 Markdown，丢行同时写进图注。
- `short_label` 删掉本地副本，委托 `pubfig.short_label`，只保留剥 `C(...)` 的那一层。
- `references/07-chart-atlas.md` §1 的图型表改为直接对应代码里的 `CHART_CATALOG`（49 行，同序无缺无多）；§5 补 `--max-charts` 成本说明，§6 换 v2 表头。

### 交付与终检（`pubfig.py` 之外：`qa_outputs.py`、`export_pdf_hires.py`）

- **Word→PDF 回填不再残留旧图**（D-01，P0）：`page.replace_image()` 之后调用 `page.clean_contents(sanitize=True)`，保存改 `garbage=4`（原 `garbage=3`）。实测不清理时成品从 4 张图变 16 张、5.3 MB 变 9.8 MB——Word 压缩过的 200 dpi 旧副本全部留在 PDF 里，而 `qa_outputs.py` 只看第一张位图，于是"高清成品"里一半是低清图。
- **qa 按有效 dpi 而不是像素宽判定**（D-02，P0）：`check_pdf()` 逐图算 `dpi = width_px / (rect.width / 72)`，新增 `low_dpi` / `dpi_min`；图幅判定 `rect_w_pt >= 56.7 or width*height >= 200000`（避免 1000×10 的横线被当成图）；dpi 容差 0.5%（15 cm @600 dpi = 3543.3 px，实测 3543 px 只有 599.9，硬阈值会误杀）。原实现要求像素宽 ≥ 3000，而 3000 px 在 15 cm 版面上只有 508 dpi——门槛本身就不等于 600 dpi。`n` 的解析同时改为接受区间与空格千分位（D-09 / D-10：`N = 3 111` 不再被读成 3）。
- `check_figures()` 新增（原实现只 `listdir` 数文件，D-13）：读像素与 dpi 元数据，按 `--figure-width-cm` 折算有效 dpi，低于阈值记 error。
- **主键契约**：`--key` 默认 `auto`，按 `rel_path → relpath → file → path → doc_id → id` 解析；一个都找不到记 error（此前只是 warning，重复键检查等于没做）。显式 `--key` 仍然优先。新增空主键检查。
- manifest 校验：`n_scope ∈ sample|subgroup|corpus`，未知值记 warning；`corpus` 允许 `n > 数据行数`（只 warning），`sample` 超出记 error；caption 比较前压掉空白并把全角 `＝` 归一为 `=`；可选 `dpi` / `px_width` 列的非法值记 warning。manifest 的列要求在 `references/06` 里按真实 8 列写全（D-19）。
- 退出码：有 error 默认返回 2（D-14；原实现只有传 `--strict` 才返回 2，CI 里等于永远绿灯）；`--exit-zero` 供中间流程降级。`--strict` 保留兼容但已无必要，`--min-width` 保留但停用。
- `export_pdf_hires.py`：`image_widths()` 返回 `page,xref,width,height,rect_w_pt,dpi`；新增 `--min-dpi 600` 与 `--allow-low`，报告含 `low_dpi`，低于阈值返回 2。

### 文档

- `SKILL.md`：修正四处与代码不符的承诺——① Cohen's κ 明确标注为**人工协议，无脚本实现**；② 阶段 3 的"必须包含的标记列"表改为"谁产生"三列表，写明 `in_scope` / `in_analysis` / `model*_sample` / `exclusion_reason` / `<字段>_src` 没有任何脚本生成或校验（只有 `dup_group` / `dup_role` 来自审计）；③ 阶段 4 不再写"最终模型仍按预设定规格在 SPSS/R/Stata 中估计"，改为给出 `--spec` 与外部软件两条路；④ 两处闸门的"内嵌图宽度 ≥ 3000 px"改为"有效 dpi ≥ 600"。另补 `--max-charts` / `--only` / `--sections` / `--list-charts`、`--content-dedupe`、dedupe 三步用法、`unreadable` 不中断、`--out-dir` 不要放进 `--root`。
- `references/01`：字段表按真实 21 列重写，补抽样框、`chars` 与 `chars_effective` 两个口径、内容级去重、keeper 理由。
- `references/04`：新增"导出后检查"三条硬规则——log 轴次刻度必须关（附代码）、不要用 `bbox_inches="tight"`（附实测像素数）、轴外图例是条件性风险（默认余量 −26 px，`top=0.92/0.95/0.99` 分别溢出 40/91/158 px）。
- `references/05`：`cantSplit` 补 python-docx 手写 OOXML 示例（`OxmlElement("w:cantSplit")` + `row._tr.get_or_add_trPr()`），并写明 `keep_with_next` 加在表格单元格上会被 Word 忽略、真正有用的是表题段落；`numbers.csv` 标注为约定而非脚本产物；Word→PDF 段写明依赖 Windows + Word + pywin32（**不需要 LibreOffice**），回填后必须 `clean_contents(sanitize=True)` + `garbage=4`，并按版面算有效 dpi。
- `references/03` / `08`：补 `--vif` / `--roc` / `--robust` / `--spec`；把 KMO、Bartlett、平行分析、轮廓系数、中介、多重插补、交互与简单斜率、训练/验证拆分这些**未实现**的承诺明确标注为"未实现，需外部脚本"。
- `references/06`：A 段改为按 MD5 **与内容指纹**分组、抽样框字段、排除逐条落 `skipped_documents.csv`、漏斗由 `sample_flow.csv` 生成；C 段加主键契约与 `<字段>_src`；D 段加 `--spec` 的参照组 / 聚类 / 空单元要求；E 段加 manifest 区间 N 与 `n_scope`、`--figures` 查有效 dpi、`--tiff` 属于 `auto_chart_pack.py` 而非 pubfig；一键检查命令改 `--min-dpi 600` 并写明退出码。

### 端到端回归新发现（本轮真实数据跑出来的，不在审计清单内）

用一个真实论文项目的数据（2 878×84 分析表、40 份 PDF 子集）跑完整链路时暴露的三个问题：

- **一张图崩掉整包**（`auto_chart_pack.py`）：对应分析（`correspondence`）遇到只有两列的交叉表时，第二维奇异值恰好为 0（实测 `sv = [0.220, 9.8e-17]`），`y` 轴数据跨度缩到 `1e-16` 量级，逐点标签的显示坐标溢出 int64，matplotlib 在 `_set_transform` 抛 `TypeError`，进程在写 manifest **之前**退出——43 张已画好的图全部作废。修法两层：① `correspondence()` 先判惰性，`第二维 / 总惰性 < 1e-6` 或总惰性为 0 或坐标含非有限值时改为 `skip`（写明是哪条），并显式设定坐标范围（文本不参与自动缩放，退化的自动缩放窗口是崩溃的直接诱因）；② `save()` 与 `main` 里的每个图表族都包了 try/except，失败写进 manifest 的 `status="error: ..."`、计入 `errors`、其余图继续画，全部跑完后退出码 2。**失败必须可见，但不能毁掉整个交付物。**
- **正确的图被判低分辨率**（`qa_outputs.py --figures`）：15 cm 宽、600 dpi 的图是 3543.3 px，导出成 3543 px 后按版面算得 599.9 dpi，`--min-dpi 600` 把 44 张全部判为不合格，报错文本还是自相矛盾的 `44 figure(s) below 600 dpi ... (600dpi)`。`check_pdf()` 早有 0.5% 容差，`check_figures()` 漏了；现已统一。
- **改列名没留旧名**（`audit_corpus.py`）：逐文件清单从 `corpus_audit.csv` 改叫 `corpus_files.csv` 后没写回旧名，而 README 快速开始、`SKILL.md`、`references/06` 和 `make_coding_sheet.py --audit` 全都指向旧名——按文档执行会直接报 `audit file not found`。现在两个名字都写（同一张表，逐字节一致），`corpus_report.md` 里注明旧名是兼容别名，文档统一改用 `corpus_files.csv`。

### 已知未修

见 `docs/ISSUES-FIXED.md` 的「未修」段。要点：`--coef` 无 `n` 列时仍回退 `len(self.df)`；数值列取值 ≤ 12 时仍被哑变量化；`references/03`、`08` 承诺的 KMO / 中介 / 插补 / 交互等方法未实现；Cohen's κ 无脚本。

---

## 此前

- `f55c1ab` fix: clamp Wilson CI to bracket p so all-0/all-1 groups do not crash charts
- `1779ab0` fix: harden corpus audit, encoding, and figure QA
- `c58bf36` feat: generalize pipeline to any research materials
- `7d72ad7` feat: publish sanitized legal empirical pipeline skill
- `183b667` Initial commit

