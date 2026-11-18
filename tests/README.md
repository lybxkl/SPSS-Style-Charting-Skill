# 测试说明

本目录是技能的**回归测试**，覆盖 `scripts/` 下每个脚本里被修掉的缺陷，以及 `docs/CONTRACTS.md` 里的跨脚本契约。

## 运行

仓库根目录下：

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

只跑某一层：

```bash
python -m unittest discover -s tests -p "test_output_layer*.py" -v
python -m unittest discover -s tests -p "test_audit_layer*.py" -v
python -m unittest discover -s tests -p "test_coding_layer*.py" -v
python -m unittest discover -s tests -p "test_stats_charts*.py" -v
python -m unittest discover -s tests -p "test_chart_pack*.py" -v
```

要求：Python 3.9+，只用标准库 `unittest`（不依赖 pytest）。第三方依赖与技能本身一致（PyMuPDF、pandas、numpy、matplotlib、statsmodels、python-docx、scipy）；`mine_candidates.py` 另需 scikit-learn（jieba 可选，缺了自动降级并在 receipt 记录分词器档位，两条路径都有测试）。

## 约定

- **不提交任何二进制 fixture**：`.gitignore` 忽略 `*.csv/ *.pdf / *.docx / *.png`，所有样例数据在临时目录里现造（见 `_helpers.py`）。
- **不依赖网络和真实语料**：每个用例在自己的 `TempCase` 临时目录内构造最小输入。
- **Word COM 用例会 skip**：`test_output_layer.py` 里回填 PDF 的用例需要 Windows + Word + pywin32，缺任一条件 `skipTest`，不会让 CI 变红。
- **断言写在行为上**：断言退出码、CSV 的列与值、manifest 字段、PDF 内嵌图数量/有效 dpi；不断言日志措辞（日志会改）。

## 目录

| 文件 | 覆盖 |
|---|---|
| `_helpers.py` | `run()`（UTF-8 子进程）、`write_csv`、`make_png`、`make_figure_pdf`、`make_docx`、`TempCase` |
| `test_output_layer.py` | `qa_outputs.py`（键列、N 契约、caption、有效 dpi、退出码）、`export_pdf_hires.py`（回填后清内容流） |
| `test_audit_layer.py` | `audit_corpus.py`、`dedupe_corpus.py`、`text_extract.py` |
| `test_coding_layer.py` | `make_coding_sheet.py`、`analysis_utils.py`、`csv_to_spss_syntax.py` |
| `test_stats_charts.py` | `auto_stats.py`、`pubfig.py` |
| `test_stats_modern.py` | `auto_stats.py` 批次4：交互项（联合 Wald）、mixed（ICC）、cox（HR 尺度/分层）、logrank、抽样权重（WLS/GLM 行展开对齐）、多重插补（Rubin 合并、逐字节确定性）、VIF ≥5 统一 |
| `test_chart_pack.py` | `auto_chart_pack.py` |
| `test_kappa.py` | `compute_kappa.py`（κ 数学、KEY_COLUMNS/单侧字段、coding-sample.md） |
| `test_clean_data.py` | `clean_data.py`（配方执行、拒绝路径、台账指纹链、flow 合并） |
| `test_report_tables.py` | `report_tables.py`（报表包、溯源锚、skipped/warnings 可见性） |
| `test_mine_candidates.py` | `mine_candidates.py`（挖掘候选、证据锚真实性、两种语料清单、k 守卫、无 sklearn/jieba 的降级路径） |

## 新增用例时

1. 先想清楚**缺陷的可观测后果**（退出码？缺一行 CSV？多一个 xref？），再写断言。
2. 一个用例只钉一个缺陷；跨脚本契约单独成类。
3. 需要 PDF/PNG/DOCX 时用 `_helpers` 生成，尺寸参数要能算出期望 dpi。
