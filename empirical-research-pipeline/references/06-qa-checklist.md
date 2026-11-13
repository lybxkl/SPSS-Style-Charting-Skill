# 交付前质检清单

## 先检查全量与回源

- [ ] 原始清单逐份有处置，重扫无新漏文件；发现报告覆盖实体、字段、章节/表格/附件和未利用项。
- [ ] 数据集数量/形态由资料决定，各自有单位、单/复合主键、codebook 和可核对关联，原生文件与无损审计视图都保留。
- [ ] 全部单元格（含键、空值、标记、派生值）有精确来源哈希/定位/原值或独立复算输入。
- [ ] 整合后再次逐格复读原材料与上下文，非抽样、非只看 flags、非批量盖 verified；数据/来源/规则变化后旧复核不复用。
- [ ] `verify_dataset.py --stage final` 返回 0，报告 stage=final、status=verified；原件/规则版本与当前一致。
- [ ] 开放模型清单逐项有数据/设计诊断；缺数模型已回全部材料，找到的真实数据已补入并重新复核，无法获得的留缺口与原因。
- [ ] 每个完成模型有实际命令/代码/环境、输入/输出 SHA256 回执、样本键与 N；所有有意义、不显著、失败和不适用项目都有可查看位置。
- [ ] `research_gate.py` 返回 0；随后仍需下面的统计/图表/文稿检查。详细契约见 `12-exhaustive-research.md`。

## A. 样本与资料

- [ ] 原始文件数、有效资料数、唯一样本数、分析样本数各有明确来源。
- [ ] `._*`、`.DS_Store`、0 字节、损坏、加密、无文字层文件均已分类。
- [ ] 重复副本按 MD5 **与内容指纹**分组，保留规则有记录；副本已移动而非删除。
- [ ] 同名不同文、同文不同名均已人工复核。
- [ ] 时间范围、资料类型、地区范围与抽样框一致；审计输出里能读到抽样框字段。
- [ ] 每个排除项都有 `exclusion_reason`，且 `skipped_documents.csv` 逐条可查（不是只打印一行计数）。
- [ ] 样本流程表由 `sample_flow.csv` 生成，每一档数字能对上 CSV/JSONL/SAV。

## B. 编码

- [ ] codebook 在编码前冻结，版本号与日期可查。
- [ ] 每个变量有定义、取值、判断规则、证据位置、正例、反例、缺失规则。
- [ ] 每个编码值都有 `*_ev` 证据句，或明确标 `NA/未记载`。
- [ ] 否定表述、他人意见、转述内容未被误编码为事实认定。
- [ ] “未记载”与“明确为否”分开编码。
- [ ] 有序层级按最高可查证事实编码，规则一致。
- [ ] 理论编码变量在方法部分说明来源，未写成文本直接测量。
- [ ] 10%–15% 双编码/重编码，报告 κ 或一致率。
- [ ] 编码日志记录了所有规则变更及影响范围。

## C. 数据集

- [ ] 一行 = 一个分析单位（或项目定义的单位），无重复 ID。
- [ ] 主键列名遵循契约（`rel_path`，兼容 `relpath/file/path/doc_id/id`）；键列缺失是**错误**而不是警告。
- [ ] `in_scope`、`in_analysis`、`model*_sample` 标记互不混用。
- [ ] 非直接抽取的字段带 `<字段>_src` 来源列（年份、审级、法院层级、罪名、省份等）。
- [ ] A、B 分别生成 `sample_flow.csv` 与 `skipped_documents.csv`；两者相加应等于扫描到的文件数。
- [ ] 每个模型 N 能从筛选条件重算，并与表注一致。
- [ ] SAV 的变量类型、宽度、值标签正确；字符串未截断。
- [ ] CSV 编码 UTF-8-SIG，Excel 打开不乱码。
- [ ] JSONL 保留全文/证据，可回溯到原始 PDF 路径。
- [ ] 原始 PDF 路径在数据集中可定位，没有断链。

## D. 模型

- [ ] `analysis_manifest.md` 列出主分析、扩展分析、跳过项及原因。
- [ ] 自动筛查（auto_stats）没有被当作最终模型；多变量模型要么用 `--spec` 显式声明，要么在 SPSS/R/Stata 里按预设规格估计。
- [ ] 用 `--spec` 时参照组、聚类单位、稳健标准误都在 spec 里写死，不用脚本默认值。
- [ ] 因变量、参照组、核心自变量、控制变量在表中写明。
- [ ] OR、95%CI、p、N、拟合指标齐全。
- [ ] 每个模型单独 N，没有用描述样本 N 代替。
- [ ] 完全分离、小单元格、多重共线性已检查或说明；多分类自变量的空单元已检查（不是只查 2×2）。
- [ ] 交互项模型报告了分组预测值/简单斜率，未把主效应当平均效应。
- [ ] 正文措辞为“关联/对应/更可能”，未写因果。
- [ ] 所有系数能从 SPSS 输出文件追溯到表格。

## E. 图表

- [ ] `chart_manifest.csv` 覆盖所有图，含问题、变量、N、图注、路径；`qa_outputs.py --manifest` 检查 N、图注 N= 与文件路径。
- [ ] manifest 的 `n` 允许区间（如 `3111→2713`），但必须写 `n_scope`（`sample`/`subgroup`/`corpus`）；语料级漏斗图的 N 大于数据行数属正常，脚本在 `sample`/`subgroup` 范围下要求 N 不大于数据行数。
- [ ] `--figures` 检查的是**有效 dpi**（像素宽 ÷ 版面英寸），不是像素宽；15 cm 宽的 600 dpi 图是 3543 px，3000 px 只有 508 dpi。
- [ ] 正文主图与附录图不重复；每个主发现至少有主图 + 稳健性/诊断图。
- [ ] 图数没有被人为压到 8 张；分布、异质性、诊断图齐全或已说明跳过原因。
- [ ] 每张图有 PNG 600 dpi、PDF 矢量；投稿要求 TIFF 时用 `auto_chart_pack.py --tiff` 输出 LZW 无损 TIFF（`pubfig.save_fig` 默认已含 tiff）。
- [ ] 图在实际安置宽高下最小字号合格；严格检查传 `--docx`、对应原始 PNG/同名矢量 PDF 和 `--min-fontsize 7.2`，不能只检查源图字号。
- [ ] 类别多/名称长时同图倾斜 45°，必要时 60°/75° 并增加底部留白；没有自动分页、截掉项目或缩小字号，导出后无重叠/裁切。
- [ ] 中文宋体、西文 Times New Roman，PDF 字体嵌入。
- [ ] 图内无标题；图题、图注在 Word 中。
- [ ] 误差线为 95%CI，图注说明。
- [ ] 颜色语义全稿一致；灰度打印可区分。
- [ ] 图注含 N、样本范围、变量定义、数据来源。
- [ ] 图、图题、图注在同一页。
- [ ] 正文首次引用图号与图一致。
- [ ] PDF 内嵌图按**版面尺寸**折算的有效 dpi ≥600（15 cm 宽时 3543 px）；脚本按图幅过滤 logo/公式碎片，只报真正插图。
- [ ] Word 导 PDF 后已用 `export_pdf_hires.py` 回填，且回填后旧位图已清除（同一图只剩 1 个 xref）。
- [ ] 图题编号能识别“图1：”“图 1.”“Table 1:”等写法；`export_pdf_hires.py` 的 tag 匹配有数字边界，不会把“图1”替换到“图10”；所给标题也必须匹配，所有请求回填项均完成，无 unmatched。

## F. 文稿

- [ ] 摘要、正文、表、图、附录 N 全部同源。
- [ ] 百分比合计与四舍五入说明。
- [ ] 表格三线表、表头重复、行不跨页。
- [ ] 图题在图下，表题在表上。
- [ ] 所有“见图 X/表 X”都能找到对应对象。
- [ ] 参考文献格式统一。
- [ ] PDF 页码、目录、字体正常。
- [ ] 文件命名含版本/日期，旧版未混入交付目录。

## G. 结论与表达

- [ ] 研究问题、数据、方法、结果、结论一一对应。
- [ ] 没有把文本关联写成因果效应。
- [ ] 没有把理论编码写成文本测量。
- [ ] 没有用“显著”替代“重要”；大样本下小差异也要解释实质意义。
- [ ] 局限部分写明：资料选择偏差、编码单位、未记载不等于未发生、公开资料覆盖限制。
- [ ] 政策/规范建议从结果推出，不超出数据能支持的范围。

## H. 判断台账与复审

- [ ] 每个 `needs_review=true` 的字段都能在 `decisions.jsonl` 找到同 target 的记录。
- [ ] `check_decisions.py` 0 error；`needs_human` 要么为 false，要么作者已在对话里拍板（不是用 `--allow-unresolved` 跳过）。
- [ ] 每条 decision 的 `evidence` 能在原文命中；`extract` 的 `value` 是候选之一。
- [ ] 抽样 10 条：`dataset.csv` 的值 → `evidence.jsonl` 的 span → 原文逐字命中。
- [ ] `review_pack.md` 的五个“审稿人问题”都能回答；答不上来的已补分析或降结论。
- [ ] 删除、覆盖、外发、定稿四类操作都有作者明确同意。

## 一键检查

```bash
python scripts/check_decisions.py --decisions decisions.jsonl --root "资料目录" \
  --review output/coding/extraction_review.csv --out output/qa/decision_issues.csv

python scripts/review_pack.py --data "data/analysis.csv" --stats output/stats \
  --figures output/chart_pack/chart_manifest.csv --verify output/verify/number_issues.csv \
  --decisions decisions.jsonl --sample-flow output/coding/sample_flow.csv \
  --missing output/coding/missing_by_source.csv --out output/review/review_pack.md

python scripts/qa_outputs.py \
  --docx "成稿.docx" \
  --pdf "成稿.pdf" \
  --figures "figures" \
  --data "data/analysis.csv" \
  --audit "output/audit/corpus_files.csv" \
  --manifest "output/chart_pack/chart_manifest.csv" \
  --min-dpi 600
```

**退出码**：0 = 通过；2 = 有 error（低分辨率图、键列缺失、`n` 非法、`sample` 范围下 N 超过数据行数、文件缺失、空数据）。`--exit-zero` 可把 2 降级为 0（只用于中间流程，不要用在交付前）。`--strict` 已无必要，保留兼容。

`--key` 默认 `auto`：按 `rel_path → relpath → file → path → doc_id → id` 顺序找主键，找不到直接报错——不会静默跳过重复检查。

脚本只查格式、可计算项和台账契约；A–H 中涉及研究判断的条目仍需人工过一遍。

