# 交付清单

可投稿档交付注册表、抽样复核、模型回执、图表、文稿和数字核对。下面带「全格」「逐格」「final」「research_gate」的条目只在归档档勾选。

## 全资料与数据集

- [ ] `research_registry.json`：任意数量/形态的数据集，各自单位、主键与关联
- [ ] 完整原始清单、`source_coverage.jsonl`、`discovery_report.md`，遗漏与未利用项均有处置
- [ ] 每个数据集的原生文件 + 无损 CSV 审计视图 + codebook + 全格 provenance
- [ ] 整合后的逐格回源复读记录（含键/空值/派生值）；prepare 后实际完成，禁止批量盖章
- [ ] `dataset_verification.json`：stage=final、status=verified、0 error，版本仍有效
- [ ] 各数据集的排除/去重记录、样本流程、关联基数核对
- [ ] 阶段 1 审计产物 `corpus_files.csv` + `sample_flow.csv` 存在并逐档对账（自写 diagnostics 不算审计）
- [ ] `scope_conformance.py` 通过：每个数据集分类列分布对照 scope.json 白名单，无范围外命名类别；小样本单元格已声明
- [ ] 每个阶段≥2遍、角度互异审计，`stage_audit.jsonl` 台账齐备且 `stage_audit.py --require <全部已完成阶段>` 退出 0，无未解决 finding
- [ ] `layout_conformance.py` 退出 0：无未声明杂散目录（自定义目录已在注册表 `layout` 挂到规范组），表/文档组交付件均有中文标题来源
- [ ] 如需 SPSS：实际执行 `.sps` 得到 SAV 并复核；其他任务不强制 SAV

## 语法与结果

- [ ] 开放 `model_plan.jsonl`：所有合理候选、适用性/要求、诊断与状态，不设模型数上限
- [ ] 每个缺数模型的实际材料回查记录；能恢复的已补数/重建/重核，不能取得的明确说明
- [ ] Agent 自选引擎的实际代码/规格、依赖版本、种子、超参数和复现命令
- [ ] 每个模型的成功运行回执、输入/代码/输出 SHA256、原始输出、诊断、样本键与实际 N
- [ ] 完整描述/模型/敏感性结果与解释，包含不显著、失败、不适用及未估计项目
- [ ] `research_gate.json`：status=verified，0 error

## 图表

- [ ] `output/figures/fig*.png` 600 dpi
- [ ] `output/figures/fig*.pdf` 矢量
- [ ] `output/figures/fig*.tiff` LZW
- [ ] `output/figure_specs.md` 图注与规格
- [ ] `output/chart_pack/chart_manifest.csv` 图表清单（问题/变量/N/图注）
- [ ] `qa_outputs.py --manifest` 检查图号唯一、N 合理、图注含 N=、路径存在
- [ ] 分析报告覆盖各数据集、方法依据、效应/区间/诊断/局限；自动筛查只是其中一部分
- [ ] `analysis_manifest.md` 主分析/扩展分析/跳过项
- [ ] `output/figures/figures_all.pdf` 仅预览

## 成稿

- [ ] `output/*.docx`
- [ ] `output/*.pdf`（需要时交付；按实际安置尺寸有效 dpi ≥600）
- [ ] 命名源 `figure_map.json` + `manuscript.json` + `table_map.json` + `doc_map.json` 齐备（无论通用或自写组装器；后两者覆盖全部交付表/文档）；`qa_outputs.py --figure-map --manuscript-spec --table-map --doc-map` 通过
- [ ] `output/修订说明.md`：旧数字→新数字对照
- [ ] `output/qa_report.json`：终检结果
- [ ] `verify_numbers` 数字溯源报告；DOCX/PDF 已渲染逐页核对排版、字体、表图与引用

## 说明

- [ ] 数据来源与检索式
- [ ] 样本口径与排除原因
- [ ] 复现步骤
- [ ] 已知限制
- [ ] 版本与日期
