# 图表图谱：从 SPSS 高级图形到出版级图

## 0. 原则

- **图是回答问题的，不是装饰。** 每张图先写一句“它回答什么问题”，再选图型。
- **先出全景，再选主图。** 先跑一遍数据质量、单变量、双变量、时间、模型诊断；再从里面挑正文主图。
- **一个主发现至少两张图。** 一张主结果图，一张稳健性/诊断/异质性图。
- **图数不设上限。** 正文与附录按实际发现和可读性安排，不预设张数；完整图集保留所有有意义结果与诊断。
- **同一变量同一颜色、同一顺序。** 跨图比较时不要重新排序或换色。
- **每张图有清单。** 图号、问题、变量、N、`n_scope`、图注、dpi、`data_hash`、文件路径，全部写进 `chart_manifest.csv`；画不出来的图也留一行说明为什么。

## 1. 默认图表包

`auto_chart_pack.py` 默认 `--max-charts 0` **不限制总图数**，图数随变量、模型和跳过项变化，以 `chart_manifest.csv` 为准。正数预算是明确的试跑/分批选择，超出数会在 stdout 报 limited；交付前必须按完整模型清单继续补齐。自动图包是初始工具，Agent 按需要自写/选择其他图形实现。

所有图统一 **15 cm 宽**（`FIG_W = 15/2.54 in`，600 dpi 下 `px_width = 3543`，方图也是一样），高度随内容变；默认三种格式 `png + pdf + tiff`，`--no-tiff` 可回到只出 `png + pdf`。

下表就是脚本里的 `CHART_CATALOG`，`--list-charts` 打印的是同一份清单；改代码时请同步改这张表，**图型、slug、触发条件以代码为准**。

| 组 | slug | 图型 | 回答的问题 | 触发条件 |
|---|---|---|---|---|
| A 数据质量 | `missingness` | horizontal bar | 哪些变量缺失最严重？ | 存在缺失列 |
| A | `sample_by_group` | bar | 样本在主要类别上如何分布？ | 识别到分组变量 |
| A | `sample_by_time` | bar | 样本随年份如何变化？ | 识别到时间变量 |
| A | `sample_by_region` | bar | 样本在地区上如何分布？ | 识别到地区列 |
| A | `binary_prevalence` | bar + 95%CI | 关键二元变量的发生率是多少？ | ≥1 个可用二元变量 |
| B 单变量 | `outcome_distribution` | bar / histogram + box | 结果变量的分布如何？ | 识别到结果变量 |
| B | `outcome_qq` | normal Q-Q | 结果变量是否接近正态分布？ | 连续结果 |
| B | `treatment_distribution` | bar | 处理阶段/核心分组的构成如何？ | 识别到处理变量 |
| B | `treatment_donut` | donut | 处理阶段/核心分组的占比如何？ | 处理变量 2–6 类 |
| B | `dist_{}` | histogram + box | 该变量的分布是否偏态/多峰/有异常值？ | 每个可用数值变量 |
| B | `cat_{}` | bar | 该变量的类别构成如何？ | 每个可用类别变量 |
| C 双变量 | `outcome_mean_by_{}` | bar + 95%CI | 连续结果的组间均值是否不同？ | 连续结果 + 分组/处理/地区/审级 |
| C | `outcome_composition_by_{}` | 100% stacked bar | 多分类结果的构成是否不同？ | 多分类结果 + 分组/处理/地区/审级 |
| C | `outcome_by_group` | bar + 95%CI | 不同类别的结果率是否趋同？ | 二分类结果 |
| C | `group_rate_bubble` | bubble | 类别结果率与样本量是什么关系？ | 二分类结果 |
| C | `outcome_by_treatment` | bar + 95%CI | 不同处理阶段的结果率如何变化？ | 二分类结果 + 处理变量 |
| C | `group_treatment_heatmap` | heatmap（行百分比） | 各类别内部的处理阶段构成是否不同？ | 分组 + 处理变量 |
| C | `group_treatment_stacked` | 100% stacked bar | 各类别内部的处理阶段构成是否不同？ | 分组 + 处理变量 |
| C | `outcome_group_treatment_heatmap` | heatmap | 类别×阶段的结果率是否存在结构差异？ | 二分类 + 分组 + 处理 |
| C | `outcome_by_region` | bar + 95%CI | 不同地区的结果率是否不同？ | 二分类结果 + 地区 |
| C | `outcome_by_trial` | bar + 95%CI | 不同审级的结果率是否不同？ | 二分类结果 + 审级 |
| C | `correlation_heatmap` | correlation heatmap | 变量之间是否存在明显相关/共线？ | ≥2 个数值/二元变量 |
| C | `scatter_{}_{}` | scatter + OLS | 两个变量是否相关？ | 全部可用数值变量对；max_scatter_pairs 可显式限制 |
| D 多变量 | `violin_{}` | violin + box + points | 该变量在不同类别间是否不同？ | 每个可用数值变量 + 分组 |
| D | `scatter_matrix` | scatter matrix | 数值变量两两之间是否存在非线性/离群结构？ | 数值变量 ≥2 |
| D | `two_rate_gap_dumbbell` | dumbbell | 两类处理比例差距多大？ | config.dumbbell 指定两个 0/1 列 |
| D | `pca_scree` | scree + cumulative | 前几个主成分解释了多少方差？ | 数值变量 ≥3 |
| D | `pca_biplot` | PCA biplot | 样本在主轴平面上是否形成类别结构？ | 数值变量 ≥3 |
| D | `pca_loadings` | PCA loadings heatmap | 哪些变量在主轴上的载荷最高？ | 数值变量 ≥3 |
| D | `cluster_dendrogram` | dendrogram | 样本/变量是否形成自然聚类？ | 数值变量 ≥2 且 N≥min-n |
| D | `cluster_mds` | classical MDS | 样本在低维相似性空间中是否分离？ | 同上且重复行 <25% |
| E 时间 | `sample_trend` | bar | 各年份样本量如何变化？ | 时间变量 |
| E | `outcome_trend` | line + 95%CI | 结果比例随年份如何变化？ | 二分类结果 |
| E | `outcome_control` | p control chart | 结果比例是否出现超出 3σ 的异常年份？ | 二分类结果且 ≥3 个年份 |
| E | `outcome_trend_mean` | line + 95%CI | 结果均值随年份如何变化？ | 连续结果 |
| E | `outcome_control_mean` | X-bar control chart | 结果均值是否出现超出 3σ 的异常年份？ | 连续结果且 ≥3 个年份 |
| E | `outcome_composition_trend` | 100% stacked bar | 结果类别构成随年份如何变化？ | 多分类结果 |
| E | `treatment_composition_trend` | 100% stacked bar | 处理阶段构成随年份如何变化？ | 时间 + 处理变量 |
| E | `treatment_composition_area` | 100% stacked area | 处理阶段构成随年份如何变化？ | 时间 + 处理变量 |
| F 模型诊断 | `forest_{}` | forest plot | 该模型的系数方向与不确定性如何？ | `--coef`（每模型 1 张） |
| F | `model_roc` | ROC | 模型的区分度如何？ | `--pred` |
| F | `model_calibration` | calibration curve | 模型预测概率是否校准？ | `--pred` |
| F | `model_pred_distribution` | histogram | 预测概率在两类之间是否分离？ | `--pred` |
| F | `model_confusion` | confusion matrix | 阈值 0.5 下的分类错误主要在哪里？ | `--pred` |
| F | `model_pr` | precision-recall | 正类较少时精确率-召回率表现如何？ | `--pred` |
| F | `model_lift` | decile lift | 高预测概率组的提升倍数有多大？ | `--pred` |
| F | `survival_km` | Kaplan-Meier | 不同组的生存/未再犯概率如何变化？ | `--survival-time/--survival-event` |
| G 附录 | `correspondence_biplot` | correspondence analysis biplot | 类别与处理阶段是否存在对应结构？ | 分组 + 处理变量 |
| G | `pareto_group` | Pareto | 类别分布是否高度集中？ | 识别到分组变量 |

选图与裁剪：

- `--only <ids>` 只跑指定图：接受完整 slug（`group_treatment_stacked`）、slug 片段（`stacked` 命中所有含该片段的图）、前缀通配（`model_*`）或图号（`F21`）；逗号分隔、可重复。
- `--sections <name,name>` 只跑某几段：接受字母（`A,C`）或中文段名（`数据质量,附录`）。
- `--list-charts` 打印上面这份清单后退出，不读数据，适合先挑图再跑。
- `--max-charts N` 限制张数（默认 0=不限制）；`--top-n` 控制图内类别展示，`--min-n` 控制最小分析单元；展示取舍不替代全量明细与模型覆盖。

模型图需要 `--coef`（系数表）或 `--pred`（预测表）；没有就跳过，并在清单里写明原因。`--coef` 的列名同时接受 `term`/`estimate`+`ci_low`/`ci_high`、`or`/`or_low`/`or_high`（`beta`/`beta_low`/`beta_high` 亦可），建议带 `metric`（OR/HR/RR/beta）与 `n` —— 没有 `metric` 时按每一行实际填了哪族列来定：`or*`→OR（对数轴，参考线 1）、`hr*`→HR、`rr*`→RR，只有 `beta` 的行走线性轴（参考线 0）。**同一个文件里混排 logit 行与 OLS 行不会丢行**：按 `metric`（或按行实测的列族）分组，各自成图，图名在多尺度时追加后缀；该图的 `metric`、`rows_plotted`、`rows_dropped` 写进 `chart_pack.json` 与 `chart_pack.md`，有未绘行时图注也会注明。`--pred` 支持 0/1 与“是/否”标签，常数预测或单一类别会跳过 ROC/PR/校准/混淆矩阵/Lift。`term_labels` 可把模型项名映射为中文。双比例哑铃图需在 config 的 `dumbbell` 里指定两个 0/1 列。小样本下脚本宁可不画，也不画误导性组间比较。有随访时间与事件列时，用 `--survival-time`、`--survival-event`（可选 `--survival-group`）画 Kaplan–Meier；参数缺失、列名不存在或绘图失败只会在 manifest 的 `status` 里注明 skipped，不会中断整包。

**样本对齐**：配置里的 `filter_query` 必须和论文分析样本完全一致。示例：`in_analysis == 1 and stage > 0` 得到 1,200；漏掉 `stage > 0` 会得到 1,260。图 N 与表 N 不一致，通常就是这里漏了条件。

## 2. SPSS 高级图表对照

| SPSS 图形 | 用途 | SPSS 入口 | Python 复现 | 注意 |
|---|---|---|---|---|
| 条形图（简单/簇状/堆叠） | 类别频数、组间比较 | 图形→图表构建器→条形 | `bar_counts`, `stacked_bar` | 不要用 3D |
| 100% 堆叠条形图 | 构成比较 | 图表构建器→堆叠 | `stacked_bar(normalize=True)` | 行列顺序固定 |
| 折线图/面积图 | 时间趋势 | 图表构建器→线/面积 | `line_ci`, `stacked_area` | 标注 N |
| 饼图/环形图 | 部分-整体 | 图表构建器→饼图 | `matplotlib` pie | 类别 >6 不用 |
| 散点图/气泡图 | 连续×连续、规模 | 图表构建器→散点 | `scatter_fit`, `bubble` | 大 N 用透明度/hexbin |
| 直方图 | 分布 | 图表构建器→直方图 | `plot_distribution` | 注明组距 |
| 箱线图 | 组间分布/异常值 | 图表构建器→箱线 | `plot_violin`/box | 不隐藏异常值 |
| 误差条形图 | 均值/比例+CI | 图表构建器→误差条 | `bar_with_ci`, `line_ci` | 注明 95%CI |
| 人口金字塔 | 年龄/性别结构 | 图表构建器→金字塔 | 水平条形 | 本类研究少用 |
| Pareto 图 | 集中度 | 图表构建器→Pareto | `pareto` | 累计线右轴 |
| 控制图 | 过程稳定/异常点 | 分析→质量控制 | `control_chart`（p 图/X-bar） | 需要时间序列 |
| ROC 曲线 | 二分类区分度 | 分析→分类→ROC | `roc_curve` | 报告 AUC/CI |
| PR 曲线 | 正类较少时的精确率/召回率 | 分析→分类→ROC（改画） | `pr_curve` | 报告 AP 与基线 |
| 混淆矩阵 | 阈值下的分类错误 | 分析→分类→混淆矩阵 | `confusion_heatmap` | 说明阈值 |
| Lift 图 | 头部提升倍数 | 分析→分类→增益 | `lift_chart` | 十分位需说明 |
| Kaplan-Meier | 生存/时间到事件 | 分析→生存→Kaplan-Meier | `kaplan_meier`（纯 numpy） | 需要随访时间+事件列 |
| Cox 回归 | 生存协变量 | 分析→生存→Cox | SPSS/lifelines | 检查 PH 假设；不自动画 |
| P-P/Q-Q 图 | 正态性 | 分析→描述→P-P/Q-Q | `qq_plot`（Q-Q） | 大样本不必过度依赖 |
| 散点矩阵 | 多变量两两关系 | 图表构建器→散点矩阵 | `scatter_matrix` | 偏态变量变换 |
| 因子分析碎石图 | 保留因子数 | 分析→降维→因子 | `scree_plot` | 结合平行分析 |
| 因子载荷图 | 变量聚类 | 因子分析→旋转 | `biplot` | 标注载荷阈值 |
| 聚类树状图/冰柱图 | 样本/变量聚类 | 分析→分类→系统聚类 | `scipy.cluster.hierarchy` | 说明距离/连接法 |
| 多维尺度 MDS | 相似性空间 | 分析→降维→MDS | `classical_mds`（纯 numpy） | 解释解释率；不要声称应力值 |
| 对应分析 | 类别×类别 | 分析→降维→对应分析 | `auto_chart_pack.correspondence` | 只作探索 |
| 多重对应分析 | 多类别变量 | 分析→降维→多重对应 | `prince`/`sklearn` | 类别多时慎用 |
| TURF 分析 | 组合覆盖 | 自定义表/语法 | 自定义 | 市场研究常用 |
| 词云/文本网络 | 文本主题 | 文本分析 | `wordcloud`/`networkx` | 不能替代编码 |
| 热图 | 交叉表/相关/载荷 | SPSS 原生较弱 | `heatmap`, `corr_heatmap` | 标注数值 |

SPSS 原生没有“森林图/小提琴图/相关热图”的标准入口时，不要硬用 3D 图替代。用 Chart Builder 的误差线或 GPL 语法做近似，再用 Python 出出版版；正文说明两者一致。

## 3. 按数据类型选图

| 数据类型 | 首选 | 备选 | 避免 |
|---|---|---|---|
| 一个分类变量 | 条形图 | 100% 堆叠（构成） | 3D 饼图、类别过多饼图 |
| 一个连续变量 | 直方图+箱线 | 密度图、QQ 图 | 只用均值柱状图 |
| 分类×分类 | 堆叠/簇状条形、热图 | 马赛克图 | 3D 柱 |
| 分类×连续 | 提琴/箱线+散点 | 均值+95%CI | 只画均值不画分布 |
| 连续×连续 | 散点+拟合 | hexbin、散点矩阵 | 大 N 不透明散点 |
| 时间×连续 | 线图+CI | 面积图 | 平滑掩盖波动 |
| 时间×分类 | 100% 堆叠柱/面积 | 分面线图 | 双 Y 轴误导 |
| 多变量 | 相关热图、PCA、聚类 | 平行坐标 | 把相关当因果 |
| 二分类预测 | ROC、校准、混淆矩阵 | lift/gain | 只报准确率 |
| 生存数据 | Kaplan-Meier、Cox | 累积风险 | 忽略删失 |

## 4. 按分析问题扩展

### 样本与数据质量
- 样本流程图（原始→可读→唯一样本→分析样本）。
- 缺失率条形图/缺失模式热图。
- 异常值/截断检查图。
- 样本类别、年份、地区、审级构成。

### 单变量
- 分布：直方图、密度、箱线、提琴、QQ。
- 集中趋势：均值/中位数+CI。
- 离散程度：IQR、标准差、变异系数。
- 类别构成：条形、Pareto、堆叠。

### 组间差异
- 连续结果：提琴/箱线+散点、均值差+CI。
- 二元结果：组间率+95%CI、风险差/OR 森林图。
- 多重比较：调整后 CI，不要只画星号。

### 关联与相关
- 连续×连续：散点+拟合、相关热图、偏相关。
- 分类×分类：堆叠柱、热图、对应分析。
- 分类×连续：分组分布、均值图。
- 二元×二元：2×2 热图、OR/ RR 森林图。

### 分类与预测
- ROC/AUC、PR 曲线、校准曲线。
- 混淆矩阵热图、阈值敏感性。
- 预测概率分布、决策曲线（如适用）。
- 变量重要性/系数森林图。

### 降维与聚类
- 相关热图、PCA 碎石图、双标图。
- 因子载荷热图。
- 系统聚类树状图、K-means 轮廓系数。
- MDS/对应分析（探索）。

### 时间
- 年度样本量、年度结果率+CI。
- 阶段/类别构成堆叠面积。
- 分段回归/中断时间序列（如政策节点）。
- 控制图/异常年份标注。

### 异质性与稳健性
- 分地区/分类别/分审级森林图。
- 替换因变量/样本/编码的系数对比图。
- 安慰剂/负向对照结果图。
- 模型规格曲线（specification curve）。

### 文本与编码
- 关键词年度热度图。
- 编码类别共现热图。
- 代表性案例证据表（不是图）。
- 主题比例趋势（如主题模型）。

## 5. 图表数量策略

| 论文部分 | 建议图数 |
|---|---:|
| 数据与样本 | 3–5 |
| 描述统计 | 5–8 |
| 双变量 | 5–8 |
| 多变量/模型 | 4–8 |
| 时间/异质性 | 3–6 |
| 诊断/稳健性 | 3–6 |
| 附录 | 10–40 |

经验法则：**每个主发现至少 2 张图；每个模型至少 1 张系数图 + 1 张诊断图；每个关键变量至少 1 张分布图和 1 张分组图。** 图多不是问题，图重复、图无信息才是问题。

`--max-charts` 默认 0=不限制。大图集可按数据集/问题/模型分批（`--sections`/`--only`），记录每批覆盖并最终合并，避免资源压力使任务中断；不能把某一批输出冒充全量交付。

## 6. 图表清单 manifest

`chart_manifest.csv` 是 manifest v2，契约原文见 `references/10-contracts.md` §3：

```csv
id,question,chart_type,variables,n,n_scope,png,pdf,caption,dpi,px_width,model_id,data_hash,tiff,note,section,status,palette
F01,哪些变量缺失最严重？,horizontal bar,amount;duration_days,120,sample,figures/fig01_missingness.png,figures/fig01_missingness.pdf,注：N=120；数据来源：分析数据集。,600,3543,,1c0ccdae,figures/fig01_missingness.tiff,top=0.977,A 数据质量,ok,#174B77|#C66E4A|#4B6E52|#A7A7A7|#C9C9C9|#5E0800
```

- `png` / `pdf` / `tiff` 是**相对 manifest 所在目录**的 POSIX 路径（`figures/fig01_xxx.png`），整个 `output/chart_pack` 目录可以随意搬动或拷贝到另一台机器而不失效；读取侧以 `chart_manifest.csv` 所在目录为基准拼绝对路径。
- `n` 允许三种写法：整数、区间（`3111→2713`，取第一个整数，图注里保留区间原文）、`N=2713` 前缀。caption 里**每个** `N=` 都会同步成解析出的值。
- `n_scope`：`sample`（默认，n 不得超过数据行数）、`subgroup`（子样本）、`corpus`（语料级/流程级计数，允许 n > 行数，如漏斗图里的“原始文献 N”）。超额且不是 `corpus` 时该图记 `status=error: …`、计入 `errors`，脚本退出码 2。
- `dpi` / `px_width` 从落盘的 PNG 读回（PIL），是**实际**像素，不是声明值。
- `data_hash` 是输入数据的列名 + 行数 + 关键列统计的 md5 前 8 位，用来核对“这张图是不是这批数据画的”。
- `note` 记录版式留白：`top=0.977` 是 `subplots_adjust(top=…)` 之后的坐标区上边界，图例越界时该值会变小；出现 `right=0.880` 表示右侧也为轴外图例让了位（饼图/环形图的侧边图例）。
- `status`：`ok`，或 `skipped: …` / `error: …` —— **画不出来的图同样有一行**，不再静默消失。
- `palette`：这张图取色所用的分类色环（`|` 分隔的十六进制）。`qa_outputs.py --graycheck` 逐行解析它，两两 `ΔL* < 10` 就判 error；色环本身的 8 个具名色（INK/RED/BLUE/GREEN/ORANGE/GRAY/LGRAY/GRID）排在 12.4 的 L\* 阶梯上，因此任意子集在黑白打印时仍然可分。
- `tiff` 默认就写（P-09 收掉），`--no-tiff` 时该列为空。
- 森林图另外在 `chart_pack.json` / `chart_pack.md` 里记 `metric`（OR/HR/RR/β）、`rows_plotted`、`rows_dropped`——混排 logit 与 OLS 系数时，未绘行数必须能追溯。

用途：

- 正文引用图号时直接从 manifest 取。
- 投稿时按 manifest 检查图数、图注、N、dpi。
- 附录排序按 manifest 的 `section`。
- `qa_outputs.py` 按 `n` / `n_scope` 校验图与表、图与正文的 N 是否一致。
- 复现时按 manifest 的 `data_hash` 与脚本参数重跑。

## 7. 常见错误

- 3D 柱/饼：看不出差异，投稿常被拒。
- 双 Y 轴：容易制造虚假交叉，能不用就不用。
- 只画均值不画分布：掩盖异质性。
- 饼图类别 >6：无法比较。
- 对数轴不标注：读者误读。
- 图内标题写成结论：图和正文重复，且带因果暗示。
- 颜色每图一变：读者无法跨图比较。
- N 与表/正文不一致：最容易被审稿人抓住。
- 把探索性图写成验证性结论：PCA/CA/聚类只能作探索。
