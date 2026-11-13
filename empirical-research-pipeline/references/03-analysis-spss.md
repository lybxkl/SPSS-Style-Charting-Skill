# SPSS 分析与结果表

> 先用 `scripts/auto_stats.py` 做描述/双变量/单变量筛查；它只用于发现值得建模的变量。最终模型用同一脚本的 `--spec` 入口估计（见下节「多变量模型」），或按预设定规格在 SPSS 中估计；参照组、聚类与样本筛选必须在建模前写死。

## 分析计划先于结果

在跑第一个模型之前，写清楚：

| 项目 | 必须写死 |
|---|---|
| 因变量 | 名称、取值、参照组、时间口径 |
| 核心自变量 | 层级/分组、参照组、是否连续 |
| 控制变量 | 类别、地区、年份、程序性变量 |
| 样本 | 每个模型单独的筛选条件与 N |
| 估计方法 | 二元 Logistic / 多分类 / 线性 |
| 报告内容 | OR、95%CI、p、N、拟合指标 |
| 稳健性 | 替换变量、替换样本、增减控制 |

不要在看到结果后改参照组或删控制变量来“凑显著”。

如果结果是“是/否”文本，先在数据层编码为 0/1，或在 `auto_stats` / `auto_chart_pack` 配置里用 `outcome_map` 指定正类；SPSS 语法不负责猜标签方向。

## 描述统计

### 比例与 Wilson CI

不要用正态近似算小样本比例 CI。用 Wilson：

```python
import math

def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0, center - half), min(1, center + half)
```

报告格式：`54.7%（95%CI 51.9–57.5%，n=1,200）`。示例数值为虚构，仅示格式。

### 分母必须写清

- 阶段内结果率：分母是该阶段记录数。
- 类别内发生率：分母是该类别记录数。
- 全样本结果率：分母是分析样本数，不是模型样本数。
- 年度结果率：样本量 < 30 的年份不单独下结论，图上可标注或合并。

## 模型设定模板

| 模型 | 因变量 | 样本 | 核心自变量 | 控制 | N |
|---|---|---|---|---|---:|
| 模型 1a | 二元结果（1=是） | 阶段 2–5 | 阶段3、4、5（参照：阶段2） | 类别、地区、年份 | 1,000 |
| 模型 1b | 同上 | 同上 | 同上 | + 程序性控制、实体性控制 | 1,000 |
| 模型 2 | 高阶段结果（1=阶段4/5） | 阶段 3–5 | 类别（参照：类别1） | 地区、年份 | 920 |
| 模型 3 | 二元结果 | 阶段 2–4 | 阶段3/4、调节变量、交互项 | 地区、年份 | 880 |

注意：

- 模型 2 的因变量只在“阶段3/4/5”中定义，阶段2不进入。
- 模型 3 若纳入交互项，主效应不能单独解释为“平均效应”，要报告分组预测值或简单斜率。
- 每个模型的 N 不同，表注必须分别写。
- 表中 N 全部为虚构示例，实际项目必须按筛选条件重算。

## 多变量模型：用 `--spec` 生成可审计的系数表

`auto_stats.py` 的单变量结果只是筛查。多变量模型（含聚类稳健标准误、显式参照组）走独立入口 `--spec`，它不会改变单变量筛查的行为：

```bash
python scripts/auto_stats.py --data data/analysis.csv --out output/analysis_pack \
  --spec specs/model_spec.json --separation drop --vif --roc
```

```json
{"models": [
  {"id": "M1", "type": "logit", "outcome": "restore_any",
   "predictors": ["gongyi", "year_c", "C(charge_f, Treatment('森林资源'))"],
   "cluster": "province", "cov": "HC1", "dropna": true}
]}
```

- `predictors` 里的裸列名按**连续**变量进入；分类变量必须写成 `C(名)` 或 `C(名, Treatment('参照'))`，或在 `ref` 字典里声明参照组。**未声明参照组的分类变量直接报错退出（码 2）**，不再默默用字典序首水平。
- `cluster`（如 `province`）让标准误按该列聚类（`cov_type="cluster"`，组数写进 `se_type`）；`cov` 取 `HC0/HC1/HC3`；两者并存时 `cluster` 优先。
- `--separation drop|merge|error` 在**拟合前**检查空单元格（某水平在结果 0 或 1 上为 0 例）：`drop` 剔样本、`merge` 并入参照组、`error` 报错；处理明细写 `separation_report.csv`（`variable,level,n,events,action`）和 `model_summary.md`。估计后还有熔断：`|β|>12` 或 `se>8` 的项不写入系数表，避免分离造成的 `OR≈1e9` 进入正文。
- 输出：`coef_<id>.csv`（`model,term,beta,se,beta_ci_low,beta_ci_high,p,or,or_low,or_high,ci_low,ci_high,metric,estimate,n,n_events,outcome,ref,note,se_type`）、`model_summary.md`（样本、参照组、分离处理、拟合、VIF/ROC）、`model_meta.json`；`--vif` 写 `vif.csv`，`--roc` 写 `roc.csv`（AUC + 1000 次 bootstrap 95%CI）。logit 的 `ci_low/ci_high` 是 OR 尺度，`beta/se` 是对数尺度；OLS 的 `metric=beta`。
- `coef_<id>.csv` 可直接交给 `auto_chart_pack.py --coef` 画森林图，不需要再手抄 SPPS 输出。
- `--max-models` 与 `--max-predictors` 默认 0=不限；正数是显式分批/试跑预算，不能作为研究范围的固定上限。

下面的 SPSS 语法仍适用于必须在 SPSS 内出表的场合；两者应当给出同方向的系数与 CI，若不一致先核对参照组与样本筛选。

## SPSS 语法骨架

### 用脚本生成读入语法

不要手写 70 列的 `GET DATA`。先跑：

```bash
python scripts/csv_to_spss_syntax.py --csv data/analysis.csv   --out-sps syntax/import.sps --sav-out data/analysis.sav
```

脚本会根据实际数据推断 `F`/`A` 宽度，并处理：

- 表头含空格、括号、连字符、点号、重复名、空名、保留字（`ALL`/`TO`/`BY` 等）→ 生成合法且唯一的变量名。
- 变量名超过 64 字节 → 截断并保证唯一。
- 原始表头写入 `VARIABLE LABELS`，所以即使变量名被清理，中文含义仍保留。
- CSV 为 GBK/GB18030 时，用 `--csv-encoding gb18030`；`--encoding` 仅控制 SPSS 读取时的编码。
- 宽度不足会截断字符串；脚本按样本最大值加余量，但长文本字段仍建议检查 `A` 宽度。
- 二值文本列（“是/否、有/无、支持/不支持”等）会自动追加 `RECODE`，生成 `*_num` 数值列并写值标签；Logistic 用 `*_num`，不要直接拿字符串列进方程。不需要时加 `--no-recode`。

生成后先在 SPSS 里跑 `EXECUTE.`，确认变量数、行数、中文标签、`*_num` 列无误，再建模。

### 读入 CSV（手写示例）

```spss
GET DATA /TYPE=TXT
  /FILE='data/analysis.csv'
  /ENCODING='UTF8'
  /DELIMITERS=","
  /QUALIFIER='"'
  /ARRANGEMENT=DELIMITED
  /FIRSTCASE=2
  /VARIABLES=
    id F8.0
    file A260
    year F4.0
    stage F1.0
    outcome_binary F1.0
    lv3 F1.0
    lv4 F1.0
    lv5 F1.0
    c2 F1.0
    r2 F1.0
    model1_sample F1.0.
EXECUTE.
```

字符串宽度按最长文件名设置，宁大勿小；宽度不足会截断，后续无法回溯。

### 二元 Logistic（哑变量版）

多分类自变量（类别、地区、审级、阶段）不要以 1、2、3 直接进协变量；在 SPSS 中用 `CATEGORICAL`/`CONTRAST` 或预先建哑变量。`auto_stats.py` 的自动筛查已对多分类自变量做哑变量化，项名为 `变量[T.水平]`，参照组取该变量出现最多的水平并写入 `ref` 列。注意筛查的自动判定规则：**不同取值 ≤ `--max-categories`（默认 12）的数值列也会被当成分类变量**哑变量化（例如编码好的 `year_c`），所以年份这类变量在筛查表里可能显示为多个哑变量；`--spec` 不受此影响（裸列名按连续处理），要强制分类就写 `C(year_c)`。

```spss
SELECT IF (model1_sample = 1).
EXECUTE.

LOGISTIC REGRESSION VARIABLES outcome_binary
  /METHOD=ENTER lv3 lv4 lv5 c2 c3 c4 c5 c6 c7 c8 c9 r2 r3 r4 r5 year
  /PRINT=CI(95)
  /CRITERIA=PIN(0.05) POUT(0.10) ITERATE(20) CUT(0.5).
```

参照组由“不进入方程的哑变量”决定：

- `lv2`（阶段2）不进入 → 参照组。
- `c1`（类别1）不进入 → 参照组。
- `r1`（地区1）不进入 → 参照组。

每跑一个模型，先 `SELECT IF` 重设样本，避免上一个模型的筛选污染下一个模型。

### 保存系数

```spss
OUTPUT EXPORT
  /CONTENTS EXPORT=VISIBLE
  /DOCUMENTFILE='output/model1.docx'.
```

或用 `OMS` 抓取 `Variables in the Equation` 表，导出 CSV 后再解析。不要手工抄 OR；抄写是数字不一致的主要来源。

## 结果表模板

| 变量 | 模型 1a OR（95%CI） | 模型 1b OR（95%CI） |
|---|---|---|
| 阶段3（参照：阶段2） | 1.80（1.40–2.30）*** | 1.60（1.22–2.10）*** |
| 阶段4（参照：阶段2） | 1.15（0.90–1.47） | 1.25（0.95–1.64） |
| 阶段5（参照：阶段2） | 1.60（1.05–2.44）* | 1.90（1.20–3.01）** |
| 类别哑变量 | 是 | 是 |
| 地区哑变量 | 是 | 是 |
| 年份 | 是 | 是 |
| 程序性控制 | 否 | 是 |
| N | 1,000 | 1,000 |
| Nagelkerke R² | 0.12 | 0.24 |

表中 OR、CI 与拟合指标均为虚构示例，只示格式；实际结果必须从 SPSS 输出直接生成。

表注必须写：因变量、参照组、控制变量、显著性规则、模型样本筛选。

## 诊断

- **完全分离**：某阶段 100% 出现/100% 不出现结果，OR 会爆炸。`--spec` 路径先用 `--separation drop|merge|error` 处理（明细见 `separation_report.csv`），估计后还有 `|β|>12`/`se>8` 熔断；单变量筛查则把这类模型写进 `univariate_skipped.csv`。仍需保留时改用 Firth 惩罚回归（SPSS 扩展/R `logistf`，**本脚本未实现**），并在局限中说明。
- **多重共线性**：交互项与主效应相关很高；`--vif` 输出 `vif.csv`（对设计矩阵逐列回归，含截距版本），常用阈值 VIF>10 提示。
- **单元格过小**：类别×阶段某些格子 n<10，OR 的 CI 会很宽；不要过度解释。
- **聚类**：同一机构/同一地区的记录可能相关；spec 里 `"cluster": "province"` 得到聚类稳健标准误，或 `cov: HC1/HC3` 做异方差稳健；单变量筛查可用 `--robust HC1`。聚类只修正标准误，不等于固定效应；要固定效应用 `C(地区)` 哑变量。
- **缺失值**：报告每个变量缺失数；`dropna` 默认完整案例，`dropna: false` 会在有缺失时报错。**多重插补本脚本未实现**，需外部脚本或 SPSS。

## 解释措辞

| 不要说 | 可以说 |
|---|---|
| 阶段3导致结果概率提高 3 倍 | 阶段3的结果优势比为 1.80 |
| 处理有效 | 处理事实与结果表述存在关联 |
| 证明机构偏好某类处理 | 文本层面，阶段3比阶段4更容易出现结果表述 |
| 因为支付所以从轻 | 阶段3与结果相关，但本研究不能识别因果 |

OR 的解释要带参照组：“相对于阶段2，阶段3的结果优势比为 1.80”，不能只说“阶段3 OR=1.80”。
