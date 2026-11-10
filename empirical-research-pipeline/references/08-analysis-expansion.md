# 分析扩展清单：不要只跑一个主模型

用户给的数据通常足够支撑一组“主分析 + 描述 + 异质性 + 稳健性 + 诊断”的组合。默认把能做的都做一遍，再把不支持的写明原因；不要等用户反复追问“还能不能再看点什么”。

先跑自动筛查：

```bash
python scripts/auto_stats.py --data data/analysis.csv   --config assets/chart_config.example.json --out output/analysis_pack
```

它给出描述统计、组间检验、相关、单变量模型和 `univariate_skipped.csv`，帮你快速判断哪些变量值得进入多变量模型。再配合 `auto_chart_pack.py` 看分布、异质性和时间趋势。自动筛查是探索性的，最终模型必须按分析计划估计，不能按 p 值筛变量。

`--only/--sections` 可选段运行（`descriptives,group_tests,binary_rates,correlations,univariate,models,vif,roc`，或快捷组 `screen`/`all`/`models`），例如只要描述统计：

```bash
python scripts/auto_stats.py --data data/analysis.csv --out output/analysis_pack --only descriptives
```

`--max-predictors`（单变量筛查的预测变量上限，默认 60）与 `--max-models`（spec 模型数上限，默认 20）是显式的规模上限；超过上限直接报错退出（退出码 2），不会静默截断。

### 多变量入口：`--spec`（已实现）

筛查只回答“哪个变量值得进模型”。真正的主模型/稳健性模型用 `--spec model_spec.json` 估计，输出 `coef_<model_id>.csv`、`model_summary.md`、`model_meta.json`，并可同时产出 `separation_report.csv`、`vif.csv`、`roc.csv`：

```json
{"models": [
  {"id": "M1", "type": "logit", "outcome": "restore_any",
   "predictors": ["gongyi", "year_c", "C(charge_f, Treatment('森林资源'))"],
   "cluster": "province", "cov": "HC1", "dropna": true},
  {"id": "M2", "type": "ols", "outcome": "sentence_months",
   "predictors": ["gongyi", "charge_f"], "ref": {"charge_f": "森林资源"},
   "cov": "HC3", "dropna": true}
]}
```

| 字段 | 含义 |
|---|---|
| `id` | 模型名，决定输出文件名 `coef_<id>.csv` |
| `type` | `logit` 或 `ols` |
| `outcome` | 因变量列名；logit 需可识别为 0/1（文本标签用 `outcome_map`） |
| `predictors` | 变量列表：裸名按**连续**处理；`C(名)` 按分类；`C(名, Treatment('水平'))` 指定参照组 |
| `ref` | 分类变量的参照组（裸名写法用）；**分类变量必须显式声明参照组，否则报错退出** |
| `cluster` | 聚类稳健标准误的组列（如省/法院）；优先于 `cov` |
| `cov` | `HC0`/`HC1`/`HC3`；留空为非稳健标准误 |
| `dropna` | `true`（默认）完整案例；`false` 时存在缺失即报错 |
| `outcome_map` | 可选，`{"是": 1, "否": 0}` 形式的文本标签映射 |

`coef_<id>.csv` 的列：`model,term,type,beta,se,beta_ci_low,beta_ci_high,p,or,or_low,or_high,ci_low,ci_high,metric,estimate,n,n_events,outcome,ref,note,se_type`。logit 的 `ci_low/ci_high`、`or` 为 **OR 尺度**，`beta/se` 为对数尺度；ols 的 `ci_low/ci_high` 为 β 尺度且 `metric=beta`。这一列名与 `auto_chart_pack.py --coef` 对齐，可直接画森林图；`ref` 列写出每个哑变量项的参照组，`note` 记录合并水平等处理。

空单元格（某分类水平在因变量 0 或 1 上计数为 0）会在拟合**之前**检查：`--separation drop`（默认）剔除该水平的样本、`merge` 并入参照组、`error` 直接报错；处理结果写入 `separation_report.csv`（`variable,level,n,events,action`）与 `model_summary.md`。估计完成后还有一道熔断：logit 的 `|β|>12` 或 `se>8` 的项不写入系数表（记在 `model_summary.md` 的排除项），避免 `OR≈1e9` 这类分离产物进入正文。

结果变量类型由脚本自动判断，不要强行套二元模板：

| 结果类型 | 自动处理 | 图形 | 注意 |
|---|---|---|---|
| 0/1 | Logistic OR、组间率+Wilson CI | 结果分布、组率、趋势 | 事件数 <10 会警告 |
| 连续 | OLS β、均值+95%CI、Pearson/ Kruskal | 直方图、分组均值、均值趋势 | 偏态做 log/P99 并注明 |
| 多分类结果 | 卡方/Cramér's V、Kruskal；二分类单变量模型跳过 | 构成条形、组内 100% 堆叠、构成趋势 | 不把类别编码当连续值；改用多项 Logit |
| 多分类自变量 | 自动哑变量化后进入单变量 OLS/Logit，项名为 `变量[T.水平]`（参照组为频数最高的水平，并写进 `ref` 列） | 类别构成、分组比较 | 参照组可显式指定；高基数变量先合并 |
| “是/否”文本 | 常见标签自动映射；其他用 `outcome_map` | 同二元 | 脚本不猜正类方向 |

完全分离、空 2×2 单元格、估计不稳定的单变量模型会写入 `univariate_skipped.csv`（多变量模型则写入 `separation_report.csv`）；不要把这些“巨大 OR”写进正文。过滤后 0 行、结果列全缺失、`filter_query` 写错时脚本直接报错退出。`filter_query` 只接受简单比较/布尔组合：含 `@`、`__`、`import`/`exec`/`eval`/`lambda` 或分号的查询会在执行前被拒绝（防注入），需要复杂条件请先用脚本生成布尔列。

## 0. 原则

- **先预设，后看结果。** 主模型、核心变量、参照组在看结果前定好；扩展分析可以探索，但必须标注“探索性”。
- **报告全部，不挑显著。** 跑过的模型/图都进清单；不要只留下 p<0.05 的。
- **效应量优先。** 除了 p，报告 OR/β、95%CI、边际效应、预测概率。
- **每个扩展都写“回答什么问题”。** 没有问题就不做。
- **数据不支持就跳过并记录原因。** 不要用假数据凑图。

## 1. 数据质量

- [ ] 样本流程图：原始文件→可读→范围→去重→分析。
- [ ] 缺失率：变量级条形图；关键变量缺失是否与结果相关。
- [ ] 异常值：连续变量箱线/散点；是否截断/缩尾。
- [ ] 重复：MD5/稳定标识；重复率与去重后 N。
- [ ] 年份/地区/类别覆盖：是否存在空档、极端集中。
- [ ] 编码一致性：κ/一致率；分歧案例。

## 2. 描述统计

- [ ] 核心结果总发生率 + 95%CI。
- [ ] 核心自变量各层级 N、占比。
- [ ] 因变量×核心自变量交叉表（行%/列%）。
- [ ] 主要类别×结果率 + 95%CI。
- [ ] 连续变量分布（直方图+箱线；偏态用 log/截断）。
- [ ] 年份趋势：样本量、结果率、构成。
- [ ] 地区/审级差异：结果率+CI。

## 3. 双变量

- [ ] 分类×分类：堆叠柱/热图/对应分析。
- [ ] 分类×连续：提琴/箱线+散点；均值差+CI。
- [ ] 连续×连续：散点+拟合、相关热图、偏相关。
- [ ] 二元×二元：2×2 表、OR/RR+CI。
- [ ] 关键变量与结果的关系是否单调/非线性；必要时加二次项/分段。

## 4. 多变量

- [x] 主模型：因变量、参照组、核心自变量、控制变量 —— `--spec` 的 `predictors` + `ref`。
- [x] 逐步加控制：模型 1 基础、模型 2 + 程序性变量、模型 3 + 固定效应 —— 写多个 `id` 的模型，`model_summary.md` 并列 AIC/BIC。
- [x] 类别/地区/年份固定效应或哑变量 —— 用 `C(变量, Treatment('参照'))` 显式哑变量；水平很多时注意自由度，或改用 `cluster` 稳健标准误。
- [ ] 交互：调节变量×阶段、地区×阶段、年份×阶段 —— **未实现，需外部脚本**（先在数据里生成交互列，再作为预测变量写进 spec）。
- [ ] 分组模型：分类别/分地区/分审级 —— **未实现，需外部脚本**（每次用 `filter_query` 或 `filter` 配置单独跑一遍 spec）。
- [x] 替代因变量：连续/有序/二元版本 —— 同一 spec 里放多个 `outcome`。
- [x] 替代样本：去重前后、排除极端年份、仅一审 —— 换 `config` 的 `filter_query`/`filter` 重跑。
- [x] 替代编码：层级合并/拆分、不同参照组 —— 改 `Treatment(...)` 或 `ref`。
- [x] 模型比较：AIC/BIC、拟合优度、解释力 —— `model_summary.md` 与 `model_meta.json`。

## 5. 模型诊断

- [x] 完全分离/稀疏单元格：`--separation drop|merge|error` + 估计后熔断（logit `|β|>12` 或 `se>8` 不入表）。**Firth 惩罚回归未实现**，需要时用 R `logistf` 或 SPSS 扩展。
- [x] 多重共线性：`--vif` 输出 `vif.csv`（对设计矩阵逐列回归）。
- [ ] 影响点：Cook's distance/dfbeta（线性）或预测概率异常 —— **未实现，需外部脚本**。
- [ ] 校准：预测概率 vs 实际率 —— 自动分箱表**未实现**；只有 `pubfig.calibration_plot(ax, y_true, y_prob)` 这一张图，分箱与样本量需自己算。
- [x] 区分度：`--roc` 输出 `roc.csv`（AUC + 95% percentile bootstrap CI，1000 次，固定种子）。
- [ ] 拟合：Hosmer–Lemeshow 或校准斜率 —— **未实现，需外部脚本**。
- [x] 聚类/稳健标准误：spec 的 `cluster`（`cov_type="cluster"`）或 `cov`（HC0/HC1/HC3）；单变量筛查用 CLI `--robust HC1`。
- [ ] 缺失机制：完整案例 vs 多重插补敏感性 —— **未实现，需外部脚本**（`dropna=false` 只会在有缺失时报错，不做插补）。

## 6. 异质性

> 本段全部需要**外部脚本**：`auto_stats.py --spec` 只估计给定模型，不会自动分组重估。可行做法是按亚组生成多份 filter 配置分别跑 spec，再用 `auto_chart_pack.py --coef` 把系数拼成森林图。

- [ ] 分类别：核心系数森林图。
- [ ] 分地区：东部/中部/西部/东北。
- [ ] 分审级：一审/二审。
- [ ] 分年份：早期/中期/晚期。
- [ ] 分调节变量水平：高/低或分组。
- [ ] 交互模型 + 分组预测值 —— **未实现**（spec 不支持交互项；需先生成交互列）。
- [ ] 亚组样本量是否足够；小样本组只描述不推断。

## 7. 机制与解释

> 本段全部需要**外部脚本**（边际效应、中介、剂量反应都不在 `auto_stats.py` 内）。

- [ ] 中介分析（只有理论+时序支持时才做；否则只写“可能机制”）。
- [ ] 边际效应：在代表性取值上的预测概率。
- [ ] 交互图：不同调节水平下阶段→结果的预测概率。
- [ ] 剂量反应：阶段/金额/时长的连续化。
- [ ] 文本机制：原文/访谈记录中的关键词/证据句分布。
- [ ] 竞争解释：程序性/实体性控制变量是否解释掉核心系数 —— 用多个 spec 模型（逐步加控制）比较系数变化。

## 8. 预测与分类（如适用）

- [ ] 训练/验证划分或交叉验证 —— **未实现，需外部脚本**。
- [x] ROC/AUC + 95%CI —— `--roc` 与 spec 同跑，输出 `roc.csv`（`model,auc,ci_low,ci_high,n_events,note`；percentile bootstrap 1000 次、固定种子）。
- [ ] PR 曲线 + AP（正类较少时优先于 ROC）—— 自动输出**未实现**；只有 `pubfig.pr_curve(ax, y_true, y_score)` 能画曲线并返回 AP。
- [ ] 校准曲线 + Brier score —— 自动分箱与 Brier **未实现**；`pubfig.calibration_plot` 只画图，分箱/样本量自算。
- [ ] 混淆矩阵/阈值表 —— **未实现，需外部脚本**。
- [x] 十分位 Lift/增益表 —— `pubfig.lift_chart(ax, y_true, y_score, bins=10)` 返回 `bin,n,events,event_rate,lift` 表（D1=预测概率最高组的修复版语义），表可直接落 CSV。
- [x] 变量重要性/系数森林 —— `coef_<id>.csv` + `auto_chart_pack.py --coef` 直接出森林图。
- [ ] 决策曲线（如临床/政策场景）—— **未实现，需外部脚本**。
- [ ] 有随访时间/事件列时：Kaplan–Meier + Cox（检查 PH 假设）；没有就写明跳过 —— **未实现，需外部脚本**（`pubfig.kaplan_meier` 只能画 KM 图，Cox/PH 需 lifelines 或 R）。

## 9. 降维与聚类（探索）

- [ ] 相关热图 + Bartlett/KMO（因子适用性）—— **未实现，需外部脚本**（`pubfig.corr_heatmap` 只画相关矩阵；KMO/Bartlett 无实现）。
- [ ] 碎石图 + 平行分析 —— **未实现，需外部脚本**（`pubfig.scree_plot` 需要你自己算好解释方差）。
- [ ] PCA/因子载荷 + 双标图 —— 因子分析/PCA **未实现**；`pubfig.biplot` 只能画你算好的得分与载荷矩阵。
- [ ] 系统聚类树状图 + 轮廓系数 —— **未实现，需外部脚本**（`pubfig.dendrogram_plot` 要你传入距离矩阵；轮廓系数无实现）。
- [ ] 对应分析/MDS（类别变量）—— **未实现，需外部脚本**。
- [ ] 明确标注“探索性”，不据此下因果结论。

## 10. 文本与编码

- [ ] 关键词年度热度。
- [ ] 编码类别共现矩阵/热图。
- [ ] 证据句类型分布。
- [ ] 代表性案例表（不是图）。
- [ ] 主题模型/词云只作辅助，不替代人工编码。

## 11. 交付前的“分析清单”

在 `analysis_manifest.md` 里列：

| 分析 | 问题 | 样本 | N | 图/表 | 状态 | 备注 |
|---|---|---|---|---:|---|---|
| 主模型 1a | 阶段→结果 | 阶段 2–5 | 1,000 | 表 5/图 5 | 完成 | 控制类别/地区/年份 |
| 稳健性 1 | 去重后重跑 | 唯一样本 | 980 | 附表 2 | 完成 | 结论方向一致 |
| 交互模型 | 调节变量 | 阶段 2–4 | 880 | 表 7/图 6 | 完成 | 探索性 |
| 生存分析 | 履行/再犯时间 | 有随访列 | 按列缺失 | KM 图/附表 | 有则做 | Cox 在 SPSS/lifelines，检查 PH；无随访列写明跳过 |

这张表就是“为什么没做/做了什么”的答案，能显著减少用户反复追问。

输出规模有硬上限：`--max-predictors`（默认 60，筛查的预测变量数）与 `--max-models`（默认 20，spec 模型数）超限即报错（退出码 2），不静默截断。图表那边 `auto_chart_pack.py --max-charts`（默认 60）同样是硬上限，另有 `--only/--sections` 只跑指定图；典型任务的图数约 40–55 张，宽表会先撞到 60 的上限，需要更多时显式调大或分两次跑。

## 12. 不要做的事

- 不要跑 20 个模型只报 1 个显著的。
- 不要用 p 值筛选变量后再解释。
- 不要把探索性 PCA/CA/聚类写成验证性结论。
- 不要在没有时序/理论时做中介。
- 不要用预测模型代替因果模型。
- 不要为了图多而重复画同一信息；每张图要有独立问题。
