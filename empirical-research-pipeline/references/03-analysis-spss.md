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

## 数据清洗与全量报表

### 清洗：先声明，后执行

清洗的每一个决定——哪些行算重复、哪些值要归并、哪个范围算越界、缺失到什么程度才剔行——都是研究判断，由读过这批样本的人/模型写进 `draft/cleaning.json`；`scripts/clean_data.py` 只执行声明过的步骤，不做任何未声明的清洗，也不给默认值。`python scripts/clean_data.py --emit-template draft/cleaning.json` 输出骨架起步。字段数与表头不一致的行、空白（非空）行会被直接拒绝（exit 2 并给出行号，这两条比 pandas 更严；完全空行与 pandas 一致按惯例跳过）；pandas 对超字段行是**静默吸收**（前置多余字段升级为索引列）、对短行**静默补齐**，清洗引擎与报表引擎都不接受这种结构改写。表头重名/空名的文件也拒绝（pandas 会静默改名成 `id.1`/`Unnamed: 1`）。未闭合引号不在此列——那类文件 pandas 读入时就报错（exit 2, "dataset not readable"）。`1e999` 这类溢出成无穷的值与 `NaN`/`inf` 拼写同样对待：是值不是数。

配方结构（`recipe_version: 1`）：

| 字段 | 必填 | 含义 |
|---|---|---|
| `id_columns` | 否 | 标识列；声明后在每一步之后与结束时必须唯一（初始重复 id 合法，只能靠去重步消除），否则中止 |
| `max_drop_fraction` | **是** | 累计丢行比例上限（0–1，边界值本身放行）；超限立即中止——这是防手滑的护栏，作者必须自己写一个数 |
| `na_values` | 否 | 在此之上**追加**的补充缺失词汇（如 `"未记录"`）；空串**恒为缺失**且引擎内无法复活——要给空串当值只能改写源数据文件（`map_values` 的 `""` 键是死键，会被拒绝）；`NaN`/`inf` 是普通值不是数：映射掉、让它按 `on_fail` 报错、或用 `coerce_type` 的 `on_fail=missing` 记为缺失，三选一 |
| `steps` | 否 | 步骤列表；留空 = 不执行任何步骤（`na_values` 词汇表仍生效，输出仍会重写为规范形式） |

七种步骤（引擎全部机械执行，逐条进台账）：

| op | 关键参数 | 行为 |
|---|---|---|
| `drop_exact_duplicates` | `columns` | 按 columns 组合去掉完全重复的行，保留首行 |
| `map_values` | `column, map, unmapped` | 命中映射表的值替换；`unmapped=error` 出现表外非缺失值即中止并列出，`keep` 保留并计数 |
| `coerce_type` | `column, to, on_fail, trim` | 转 int/float/text；`on_fail=error` 列出失败值中止，`missing` 记缺失；int 拒绝非整数（`3.0` 收，`3.5` 拒）。数值解析**总是先忽略首尾空白**（数字不是文本）；`trim=true` 额外作用于 text 列。`1_000` 这类字面分隔符是值不是数。float 的规范形式取最短往返串（repr 语义），不丢精度 |
| `flag_outliers` | `column, rule{min,max}, action` | 闭区间外即越界；`set_missing` 记缺失，`report_only` 只记录；列必须先 coerce 成数值 |
| `drop_rows_if_missing` | `columns, mode, reason` | `any`/`all` 命中缺失的行整行剔除；`reason` 必填并进 flow 备注 |
| `rename_column` | `from, to` | 重命名；目标名不得与现存列冲突 |
| `keep_columns` | `columns` | 只保留列出的列（顺序按清单），弃列记名 |

产出（`--out`，默认 `output/cleaning/`）：

- `clean_dataset.csv`——清洗后的表（utf-8-sig，缺失写空串）。
- `cleaning_log.jsonl`——header（数据集/配方 sha256、列清单）+ 每步一条（config 原样（`_` 前缀注释键除外）、行数入出、改格数、丢行 id 样本、`sha_in`/`sha_out` 内容指纹）+ summary（final sha256）。**同一 dataset + 同一 recipe 重跑得到同一指纹链**：复核清洗靠重放比对，不靠信任。指纹分隔符是控制字符（`\x1d/\x1e/\x1f/\x00`）——含这些字符的单元格会被直接拒绝（exit 2），防止伪造列/行边界。
- `cleaning_log.md`——同一台账的可读版（清洗在读取数据集时即失败的话，只有失败段）。
- `flow.csv`——`stage,n,note`（清洗前/去重后/缺失剔除后/清洗后）；用 `--flow-out output/coding/sample_flow.csv` 让引擎自动并入（文件已有 `kind` 列时清洗行补 `kind=stage`，重复清洗会**替换**上一轮的清洗行而不是堆叠）；不传就只有独立 flow.csv。这些数进 `sample_flow.csv` 后由 `verify_numbers.py` V-06 按链核对单调性；不要手抄进正文。

复核方式：重跑一次比对 `sha_in`/`sha_out` 链与 `clean_dataset.csv` 哈希；任何一步的 `config` 就是当初的声明原文。缺行剔除没有隐式兜底——没写 `drop_rows_if_missing` 就一行不丢。

### 全量数据报表

分析表建好后、登记 `research_registry.json` 之前，先跑 `scripts/report_tables.py`（Windows PowerShell 里把多行命令写成一行再执行）：

```bash
python scripts/report_tables.py --dataset output/dataset/analysis.csv \
    --out output/reports --id respondent_id --outcome satisfaction \
    --crosstab "gender,age_group" \
    --cleaning-log output/cleaning/cleaning_log.jsonl \
    --missing-reasons output/coding/missing_by_source.csv
```

| 产物 | 内容 |
|---|---|
| `variable_report.csv` | 每列一行：角色（`--id`/`--outcome` 是声明，其余 variable）、类型（numeric/categorical/text/empty——按解析率与基数算的机械事实）、n、缺失、唯一值、众数 |
| `descriptive_stats.csv` | 数值列：mean/sd/se/min/p25/median/p75/max/iqr/skew/kurtosis（SPSS 式调整统计量 G1/G2；n 不足留空） |
| `frequency_tables.csv` | 低基数列（唯一值 ≤ `--max-cardinality`，含数值列）的取值×频数×累计；缺失记 `(缺失)`，字面等于 `(缺失)` 的真实值与标记不可区分；分母=全部行；text/empty/超基数列都进 `report_index.json` 的 skipped，一个不漏 |
| `crosstabs.csv` | 声明的列对（A≠B）：格频数与行内百分比；非 categorical 的列**跳过并写明原因**，不硬算 |
| `missing_report.csv` / `missing_patterns.csv` | 每列缺失 + 共缺失模式（Top 50，超出部分有一行汇总；模式不含 id 列） |
| `duplicate_report.csv` | id 重复组、id 缺失行数（`id_missing` 行的 `n_extra` 有意留空——该行没有「重复之外的多余行数」概念；与清洗端“缺失 id 互相碰撞即不唯一”的口径互补）与全行重复 |
| `missing_reasons_by_field.csv` | `--missing-reasons` 给定时收录抽取层缺失来源账的 field/bucket/n/share_of_na 四列 |
| `data_report.md` | 可读总表：清洗链、每变量摘要、缺失/重复要点、报表清单、警告（清洗台账失败、或清洗结束行数与本数据集行数不一致——后者可能是分析表落后于清洗，除非中间做了单位重构/in_analysis 筛选） |
| `report_index.json` | **溯源锚**：每张报表的 sha256 + 数据集 sha256（+cleaning_log/missing_reasons 的 sha256）；`skipped` 列出未生成的表及原因，`warnings` 列出上面两类警告 |

列名与取值约定：`n`＝非缺失观测数，`n_rows`＝行数（两个概念两种列名，不是不一致）；pct/pct_missing/cumulative_pct/pct_within_a 一律 0–100。台账与索引的时间戳键为 `generated_at`（UTC，秒精度）。

溯源链：正文数字 ← `verify_numbers` 对表 ← 报表文件（report_index 记 sha）← dataset sha256 ←（清洗时）cleaning_log ← 原始 dataset sha256。任何一环哈希对不上就是被改过，不要改数凑对，去查哪一步动了。

角色与类型是两回事：`--id`/`--outcome` 是**你声明的**角色；numeric/categorical/text 是脚本按机械规则报的**事实**（全部可解析为有限数=numeric；唯一值≤`--max-cardinality`=categorical；否则 text）。`--id` 声明的列不进频率表、描述统计与交叉表（variable_report 仍给出它的全量档案）。写论文时的“分类变量/连续变量”是研究决定，参考报表事实后自己定，别把 `kind` 当决定抄。

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
- **VIF 标志线全仓统一为 ≥5**：`model_summary.md` 与 `methods_lib.py` 的线性回归都按 ≥5 提示共线性（此前摘要按 >10、方法库按 ≥5，两处口径不一致）。

### 五项现代统计（spec 里的字段与边界）

同一 `--spec` 入口支持五种模型类型：`logit` / `ols` / `mixed` / `cox` / `logrank`。字段用错类型（如 `mixed` 里写 `cluster`、`logrank` 里写 `interactions` 或 `outcome`）直接报错退出，不会静默忽略。`fit.csv` 的 `test_stat/test_df/test_p` 一列两义：声明了 `interactions` 时是交互项联合 Wald χ²；`logrank` 模型时是 log-rank χ²。交互守门：交互列超过 30 列或设计列行比 >1/10 警告、>1/5 报错退出。

1. **交互项**（`interactions: [["a","b"], ...]`，两变量都须在 `predictors` 里）：数值×数值、数值×分类（乘每列哑变量）、分类×分类（哑变量两两乘积），交互列排在主效应之后、note 标「交互项」；同时做**交互项联合 Wald χ² 检验**（手工构造约束矩阵，OLS/Logit/GLM/MixedLM/PHReg 通用），写进 `fit.csv` 的 `test_stat/test_df/test_p` 与摘要。交互项的 VIF 天然偏高，判读时以联合检验为准。
2. **线性混合模型**（`"type": "mixed"` + 必填 `groups`，可选 `random_slopes: ["x"]`）：REML、随机截距（+随机斜率）；固定效应写 `coef_<id>.csv`，方差成分与 ICC 写 `fit.csv`（`n_groups/icc/var_group/var_resid`）。ICC 仅在纯随机截距下定义。不接受 `cluster/cov/weights/impute`。`subset` 与其他类型同一语义（先子集后完整案例，`groups` 缺失算入 n_dropna）。
3. **Cox 比例风险**（`"type": "cox"` + 必填 `time`/`event`，可选 `strata`）：Breslow ties、**无截距项**；效应列为 **HR=exp(β)**、CI 在 HR 尺度（`metric=HR`）；偏对数似然写 `loglik`。事件列须为 0/1（文本标签用 `outcome_map`）；无事件直接报错。ph 假设检验（Schoenfeld）未内置，写论文时须另行检验。
4. **log-rank 检验**（`"type": "logrank"` + 必填 `time`/`event`/`group`，可选 `strata`）：单一检验，不产系数行（`coef_<id>.csv` 按 S-09 惯例只写表头）；χ²、df、p 写 `fit.csv` 的 `test_*` 列。**纯 logrank 的 spec 合法**（exit 0，note 提示看 fit.csv）。
5. **抽样权重**（`weights: "wtcol"`，仅 logit/ols）：OLS 走 WLS、logit 走 GLM(freq_weights)。**诚实边界：点估计是加权估计；标准误是模型基，不是设计基**——没有分层/PSU 的复杂抽样方差（摘要里明说）。加权 N 写 `fit.csv` 的 `weighted_n`。权重必须为正有限数（0/负值先在数据侧排除）；GLM 下的 AIC/BIC/LLR 按重复样本解释，仅作参考。`weights` 与 `cluster` 并存时 statsmodels 会警告 cov_type 与 freq_weights 组合不完全支持（警告如实进摘要），建议分敏感性核对。
6. **多重插补**（`impute: {"m": ≥2, "seed": 必填, "cycles": ≥1 默认 5, "impute_outcome": true|false 默认 false}`，仅 logit/ols）：statsmodels MICE（PMM 抽补，分类变量按编码解码、水平保真），m 次独立填补（rng=seed+i 确定性）→ **Rubin 合并**（合并 β、总方差、Rubin df、t 分布 p、FMI）；逐填补集做与完整案例完全相同的**空单元格检查**（任一集出现空单元格即报错——各集删行不同无法合并）；结构性列（cluster/weights）**从不插补**：cluster 在建模样本里有缺失直接报错（与普通路径同一语义）；weights 缺失行剔除并计入 n_dropna；全部模型变量（结局+预测变量）都缺失的行剔除并计入 n_dropna；**默认不插补结局**（结局缺失行从每个填补集排除=协变量 MI；`impute_outcome: true` 才声明插补结局——插补结局是研究决定，摘要会写明跑的是哪种模式；插补结局时事件数仍按观测口径报告并注明）。产出：合并行（`sample="MI(m=…)"`）+ 完整案例参照行（`sample="… (complete-case)"`）同表，`impute_report.csv` 给每项 within/between/total 方差、FMI 与 CC 参照值。**MI 模型不报告单一似然/AIC**（fit.csv 留空）；ROC 不计算。完整案例参照拟合失败时（如分离 drop 掉整个水平）不杀合并估计，只在摘要记一条失败说明。

同 seed 重跑逐字节一致（MI 表与系数表都做了字节级回归测试）。

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
- **多重共线性**：交互项与主效应相关很高；`--vif` 输出 `vif.csv`（对设计矩阵逐列回归，含截距版本），全仓统一按 **VIF≥5** 提示共线性（`model_summary.md` 与 `methods_lib.py` 同口径）。
- **单元格过小**：类别×阶段某些格子 n<10，OR 的 CI 会很宽；不要过度解释。
- **聚类**：同一机构/同一地区的记录可能相关；spec 里 `"cluster": "province"` 得到聚类稳健标准误，或 `cov: HC1/HC3` 做异方差稳健；单变量筛查可用 `--robust HC1`。聚类只修正标准误，不等于固定效应；要固定效应用 `C(地区)` 哑变量。
- **缺失值**：报告每个变量缺失数；`dropna` 默认完整案例，`dropna: false` 会在有缺失时报错。多重插补用 spec 的 `impute` 字段（MICE-PMM + Rubin 合并，见上文「五项现代统计」第 6 条：默认不插补结局、结构性列不插补、`impute_report.csv` 给 FMI 与完整案例参照）。

## 解释措辞

| 不要说 | 可以说 |
|---|---|
| 阶段3导致结果概率提高 3 倍 | 阶段3的结果优势比为 1.80 |
| 处理有效 | 处理事实与结果表述存在关联 |
| 证明机构偏好某类处理 | 文本层面，阶段3比阶段4更容易出现结果表述 |
| 因为支付所以从轻 | 阶段3与结果相关，但本研究不能识别因果 |

OR 的解释要带参照组：“相对于阶段2，阶段3的结果优势比为 1.80”，不能只说“阶段3 OR=1.80”。
