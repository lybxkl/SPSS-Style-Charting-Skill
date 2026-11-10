# 十一种图、十六种方法：把"该用什么方法"落到命令上

这份文件回答三个问题：**这份数据能不能做这个方法**、**跑出来该看哪张表**、**正文怎么写**。
方法清单来自常见教材与 SPSS 课堂笔记的顺序（描述 → 差异 → 关联 → 模型 → 降维 → 测量 → 分类），
**1–16 号与方法清单逐条对应**；非参数检验（17）与二元 Logistic（18）是同一批笔记里单列的两节，
教材把它们当"替代方案"和"回归的特例"，这里也同样单列，不占用 1–16 的编号。

```bash
python scripts/methods_pack.py --list                       # 十六个编号
python scripts/methods_pack.py --data data.csv --config methods.json \
       --out output/methods --methods all
python scripts/methods_pack.py --data data.csv --config methods.json \
       --out output/methods --only m04,m05
```

产物固定四件：`methods_report.md`（总览 + 每方法一节 + 报告句式）、`methods_manifest.csv`
（`id,nr,method,family,status,n,key_stats,figure,tables,reason`）、`<id>_<表名>.csv`（每张表一份）、
`figures/`（每个跑通的方法一张图，600 dpi / 15 cm）。

**被跳过的办法不是失败**：`status=skipped` 且 `reason` 写明缺什么，并给出替代方法。
若一个都没跑通，脚本 `return 2`——沉默的"零产出"不算成功。

---

## 0. 先定变量类型，再选方法

| 变量类型 | 判据 | 能用什么 |
|---|---|---|
| 连续数值（计量） | 有单位、可做四则运算（金额、月数、人数） | 均值类方法：t、ANOVA、Pearson、OLS、PCA、时序 |
| 分类（计数） | 取值是标签 | 卡方、Logistic、Kano、判别（作因变量） |
| 其中**无序**分类 | 取值无大小（性别、地区、罪名） | 只能哑变量化，不能当连续变量放进回归 |
| 其中**有序**分类 | 取值有顺序（学历、Likert 5 点） | 可当有序因子；当连续用需说明理由 |

三条最容易犯的错：

1. 把编码 1–7 的省份当连续变量做相关——数字是身份证号，不是数量。
2. 把"未提及"记成 0——那是把"没写"当成"没有"，方向可能整个反掉（见 `references/09-field-extraction.md` 的 NA 纪律表）。
3. 因变量是 3 分类却用二元 Logistic——系数会随合并方式变化，应改用多分类模型或先合并并说明理由。

---

## 1. 描述性统计 `m01`

- **变量要求**：无。任何数据第一步。
- **判据**：连续变量先看偏度与 Shapiro；`p<α` 说明分布偏离正态，**报告用中位数（P25，P75）**，不要报均值±标准差。
- **表**：`descriptive.csv`（variable/type/n/missing/mean/sd/median/p25/p75/min/max/skew/kurtosis/normality_p/report/levels/mode/mode_pct）。
- **图**：直方图 + 箱线图（`plot_distribution`）。
- **句式**：「连续变量以 M±SD 或 M（P25，P75）描述，分类变量以 n（%）描述。」
- **误用**：偏态变量报均值；`missing` 不报；分类变量算均值。

## 2. 主成分分析 `m02`

- **变量要求**：≥3 个连续变量（`config.cluster_vars`）；样本量建议 ≥5×变量数。
- **判据**：特征值 >1 的成分个数、累计解释方差；载荷 <0.4 的变量不解释。
- **表**：`loadings.csv`、`variance.csv`（特征值/方差%/累计%）、`scores.csv`。
- **图**：碎石图（`scree_plot`）。
- **句式**：「前 k 个主成分累计解释 …% 的方差，PC1 解释 …%。」
- **误用**：把 PCA 当因子分析解释潜变量（PCA 是线性组合，不是潜变量模型）；不报累计方差。

## 3. 相关性分析 `m03`

- **变量要求**：≥2 个数值列；含分类变量时应转 Spearman。
- **判据**：脚本按 Shapiro 自动选 Pearson/Spearman；`|r|≥0.7` 强、`0.4–0.7` 中等；同时给 p 与 n。
- **表**：`correlations.csv`（`var1,var2,n,r,p,stars,direction,strength`；`method` 记在
  报告与 `stats` 里——**整张矩阵统一用一种方法**，不是逐对挑 Pearson/Spearman）。
- **图**：相关矩阵热图（`corr_heatmap`）。
- **句式**：「r=…，p=…（Pearson/Spearman）。」
- **误用**：相关当因果；只报 r 不报 n；把 r>0.85 的两个自变量同时放进回归（共线，见 m11）。

## 4. 方差分析 `m04`

- **变量要求**：1 个连续因变量 + 1 个 ≥3 水平的分组变量。
- **前置**：Levene 方差齐性（不齐时脚本给 Welch）；显著（`p<α`）后**才**做事后比较，脚本自动追加 Bonferroni。
- **表**：`groups.csv`（各组 n/mean/sd）、`anova.csv`（F/df/p/eta2/levene_p）、`posthoc.csv`。
- **图**：各组均值 + 95%CI（`bar_with_ci`）。
- **句式**：「F(df1,df2)=…，p=…，η²=…；事后比较采用 Bonferroni 校正。」
- **误用**：不做事后比较就宣称"某两组有差异"；方差不齐仍报普通 F；把 Bonferroni 校正后的 p 再手动乘一次（SPSS 已乘）。

## 5. 卡方检验 `m05`

- **变量要求**：两个分类变量（`config.row` / `config.column`）。
- **前置**：期望频数 <5 的单元格超过 20% 时，脚本补 Fisher 精确检验并在 notes 里点名。
- **表**：`contingency.csv`、`expected.csv`、`row_percent.csv`（**正文引用的通常是行百分比**）。
- **图**：行百分比热图（`heatmap`）。
- **句式**：「χ²(df)=…，p=…，Cramér's V=…。」
- **误用**：用列百分比解释行变量；三分类以上不做事后两两比较就下结论（脚本会追加 `chi_square_pairs`）。

## 6. 结构方程模型 `m06`（脚本明确拒绝）

- **为什么拒绝**：SEM 需要专门引擎（semopy / lavaan / Mplus）。用一堆 OLS 拼出"路径图"再标 SEM，是伪造方法名。
- **替代**：① `pip install semopy` 后用它的 CLI；② 路径回归 + m13 中介检验近似；③ 只验证测量结构用 m16（EFA）。
- **报告里怎么写**：「本研究未拟合结构方程模型，路径关系用多元回归与 bootstrap 中介检验估计。」

## 7. 判别分析 `m07`

- **变量要求**：1 个分类因变量（≥2 组）+ ≥1 个连续自变量（`config.discriminant`）。
- **判据**：Wilks' Λ（越小判别力越强）、标准化判别系数（比较变量贡献）、回代准确率。
- **表**：`coefficients.csv`（variable/LD1/standardised）、`summary.csv`（functions/wilks_lambda/resubstitution_accuracy）。
- **图**：标准化判别系数条形图。
- **句式**：「Wilks' Λ=…，提取 k 个判别函数；回代准确率 …%（上限估计，非泛化精度）。」
- **误用**：把回代准确率当预测准确率；组样本极不均衡时不看先验概率。

## 8. 时间序列分析 `m08`

- **变量要求**：1 个时间列 + 1 个数值列（`config.time`），≥8 个时点。
- **判据**：ARIMA(p≤2, d∈{0,1}, 0) 按 AIC 选阶；残差 Ljung-Box `p≥0.05` 才说明白噪声。
- **表**：`params.csv`（term/coef/se）、`fitted.csv`（time/observed/fitted）、`fit.csv`（p/d/aic/ljungbox_p）。
- **图**：观测值（按时间均值）与拟合值；**首个 d 个拟合值是占位，脚本已置空**。
- **句式**：「按 AIC 选择 ARIMA(p,d,0)，AIC=…；残差 Ljung-Box p=…。」
- **误用**：把"时间列"当时间序列（观测点重复且无间隔 = 面板数据，应先聚合）；用 R² 评价时序模型；不做残差诊断。

## 9. 因子分析 `m09`

- **变量要求**：≥3 个题项（`config.items`，可写 `{"scale": [...]}`）。
- **前置**：KMO ≥0.6（<0.5 不宜做）、Bartlett `p<0.05`；主成分法 + Kaiser 特征值>1。
- **表**：`loadings.csv`（F1..Fk + 共同度）、`variance.csv`
  （`eigenvalue,variance_pct,cumulative_pct` 是**未旋转**的；旋转后另给
  `ss_loading_rotated,variance_pct_rotated,cumulative_pct_rotated`）、`kmo_bartlett.csv`。
  论文写"旋转后累计解释 …%"必须取 `*_rotated` 那三列。
- **图**：碎石图。
- **句式**：「KMO=…，Bartlett χ²(…)=…，p<.001；提取 k 个因子，累计解释 …%。」
- **误用**：KMO 0.4 还硬做；旋转后不提载荷阈值；把因子个数交给软件默认值而不看碎石图。

## 10. 聚类分析 `m10`

- **变量要求**：≥2 个连续变量（`config.cluster_vars`），必须先标准化（脚本自动做 z 分数）。
- **判据**：轮廓系数（>0.5 结构清晰、0.25–0.5 尚可）；K 由轮廓系数与业务可解释性共同决定。
- **表**：`profile.csv`（**原始单位**的簇均值 + 每簇 n）、`profile_z.csv`（z 分数中心，只看相对贡献）、
  `summary.csv`（k / n / silhouette）。
- **图**：`m10_cluster_sizes`（各簇规模柱状图）。轮廓系数随 K 的变化需要自己按 `--only m10`
  改 `config.cluster_k` 逐次跑，脚本不代做选择。
- **句式**：「取 K=…，轮廓系数=…，各类规模 n=…。」
- **误用**：不标准化直接聚类（量纲大的变量支配结果）；用 K-means 处理明显非球形簇；把聚类结果当既定分类再做回归而不说明。

## 11. 回归分析 `m11`

- **变量要求**：1 个连续因变量 + ≥1 个自变量；分类自变量自动哑变量化（`drop_first`，参照组=第一水平）。
- **判据**：R²（>0.5 好、>0.2 可用）、F 检验、系数 t/p、标准化 β、**VIF<5**、残差近似正态、Breusch-Pagan 异方差。
- **表**：`coefficients.csv`（`term,beta,se,t,p,stars,std_beta,vif`）、
  `model.csv`（`n,r2,adj_r2,F,F_p,rmse,se_type,durbin_watson,breusch_pagan_p,resid_normality_p`）。
  默认 **HC1 异方差稳健标准误**（`se_type=HC1`），与 SPSS 的普通 OLS 标准误不同，换软件复算
  t 值前先对齐口径。
- **图**：系数森林图（β 与 95%CI，`ref=0`）。
- **句式**：「R²=…，F(…)=…，p<…；β=…，95%CI […]；VIF 均<5。」
- **误用**：不报 VIF；用 R² 比较不同因变量的模型；把哑变量系数解释成"每增加 1 个单位"。

## 12. T 检验 `m12`

- **变量要求**：**恰好 2 组**（脚本对 3 组直接跳过并指向 m04）；`config.continuous` + `config.group`。
- **前置**：独立样本先 Levene（`p≥0.05` 用等方差）；配对样本先看配对相关（`p<0.05` 才适合配对分析）。
- **表**：`groups.csv`、`test.csv`（t/df/p/mean_diff/CI/cohens_d/levene_p）；配对另出 `paired.csv`。
- **图**：两组均值 + 95%CI。
- **句式**：「t(df)=…，p=…，Cohen's d=…（均值差 …，95%CI […]）。」
- **误用**：三组两两做 t 检验不做校正（应 ANOVA + 事后）；方差不齐仍报等方差结果；配对数据用独立样本检验。

## 13. 中介效应 `m13`

- **变量要求**：三个连续变量 `config.path = {x, m, y}`；建议 n≥200（bootstrap 需要分布）。
- **判据**：bootstrap 95%CI 不含 0 才算中介成立；报告间接效应、直接效应、占总效应比例、Sobel z。
- **表**：`paths.csv`（a/b/c/c′）、`effect.csv`（indirect/boot_lo/boot_hi/sobel_z/sobel_p/share）。
- **图**：间接效应森林图（bootstrap CI，`ref=0`）。
- **句式**：「间接效应=…，bootstrap 95%CI […]；占总效应 …%。」
- **误用**：横断面数据讲因果（脚本会在 notes 里明确点出）；只做 Sobel 不做 bootstrap；中介比例 >100% 还照写。

## 14. 卡诺模型 `m14`

- **变量要求**：每个需求一对列（功能题 + 反功能题），1–5 分；`config.kano = {需求名: [功能列, 反功能列]}`。
- **判据**：按经典 5×5 评价表（Berger et al. 1993，行=功能题 1–5、列=反功能题 1–5）
  分类为 A（魅力）/O（期望）/M（必备）/I（无差异）/R（反向）/Q（可疑）；四个角
  (5,5) 与 (1,1) 是 Q，(1,5)(5,1)(4,5)(1,4) 等是 R。
- **系数**：`better=(A+O)/valid`、`worse=-(O+M)/valid`，**分母只含 A/O/M/I**；
  R（题目写反）与 Q（自相矛盾）记为 `excluded`，算进分母会把系数稀释。
- **表**：`kano.csv`（feature/n/valid/A/O/M/I/R/Q/excluded/better/worse/category/label）。
- **图**：`m14_kano`，better(X,0–1) × worse(Y,−1–0)，象限线在 0.5：
  **右上=魅力型、右下=期望型、左下=必备型、左上=无差异**。
- **句式**：「‘响应速度’属期望型需求（better=…，worse=…），应作为改进优先项。」
- **误用**：把"无差异"当"不重要"删掉；不分需求类型就平均排序；用四象限阈值
  （better/worse 是否过 0.5）替代分档表——两者口径不同，象限只作展示，类别以 5×5 表为准。

## 15. 信度分析 `m15`

- **变量要求**：≥2 个同构念题项；建议 ≥3。
- **判据**：Cronbach's α ≥0.7 可接受、0.8–0.9 良好、**>0.95 反而可能题项冗余**；同时看 `item_total_r`（<0.3 考虑删题）与 `alpha_if_deleted`。
- **表**：`reliability.csv`（item/mean/sd/item_total_r/alpha_if_deleted）、`summary.csv`（k/alpha/n）。
- **图**：项目-总体相关条形图。
- **句式**：「Cronbach's α=…（k=…，n=…）。」
- **误用**：α 高就认为效度好（信度≠效度）；反向计分题未反向；删题后不重算。

## 16. 效度分析 `m16`

- **变量要求**：≥3 个题项。
- **判据**：结构效度看 KMO、Bartlett、因子载荷是否按预期聚成维度；**内容效度靠专家评审，效标效度需要外部金标准——脚本不替代**。
- **表**：`loadings.csv`（F1..Fk + 共同度）、`variance.csv`
  （`eigenvalue,variance_pct,cumulative_pct` 是**未旋转**的；旋转后另给
  `ss_loading_rotated,variance_pct_rotated,cumulative_pct_rotated`）、`kmo_bartlett.csv`。
  论文写"旋转后累计解释 …%"必须取 `*_rotated` 那三列。
- **图**：因子载荷热图（`RdBu_r`，−1…1）。
- **句式**：「KMO=…，Bartlett p<.001；k 个因子累计解释 …%，题项按预期归类。」
- **误用**：用 EFA 结果声称"内容效度高"；样本量不足时做 EFA（建议 ≥5×题项数）。

## 17. 非参数检验 `m17`（T/ANOVA 的替代）

- **变量要求**：1 个连续因变量 + 分组变量；或一对配对列。
- **判据**：2 组 → Mann-Whitney（秩相关 r）；3 组以上 → Kruskal-Wallis（ε²）；配对 → Wilcoxon。
- **表**：`groups.csv`（**中位数与四分位**）、`kruskal.csv` / `test.csv`。
- **图**：各组分位数条形图。
- **句式**：「各组中位数（P25，P75）分别为…；H(df)=…，p=…，ε²=…。」
- **误用**：非参数检验仍写"均值±标准差"；数据其实近似正态却弃用 t 检验（损失效能）。

---

## 18. 二元 Logistic 回归 `m18`

- **变量要求**：因变量**必须二分类**（0/1）；config.outcome = {col, positive} 可指定哪一类算 1，其余合并为 0。
- **前置**：EPV（每参数事件数）<10 时脚本警告系数不稳；出现准完全分离（某类别 0 事件）时 OR 可能为 inf，
  脚本会把这条写进 notes 并拒绝让你照抄那个 OR。
- **表**：coefficients.csv（term/B/se/wald/p/OR/OR_ci_low/OR_ci_high/stars）、model.csv（n/events/McFadden R²/LLR χ²/HL p/AIC）。
- **图**：OR 与 95%CI 森林图（对数轴，
ef=1）。
- **句式**：「OR=…，95%CI […]，p=…；模型 χ²(…)=…，McFadden R²=…，n=…（事件 …）。」
- **误用**：因变量是三分类还硬跑二元模型；不写参照类别；把 OR 说成"风险增加 X 倍"（OR 是发生比，不是风险比）；
  只报 p 不报 CI；EPV 不足 10 还解释单个系数。

## 19. 综合案例的正确顺序：两步法

教材里那张"综合案例注意事项"讲的是一条流水线，脚本能替你把每一步都跑出来：

1. **单因素筛查**（一次一个自变量）：分类×分类用卡方（m05），分类×连续用 ANOVA（m04）或 t（m12），
   连续×连续用相关（m03）。不显著（`p≥α`）的变量先不要放进多因素模型。
2. **共线检查**：自变量之间 `|r|≥0.85` 视为共线（m03 直接给矩阵），二者只留一个；
   留两个时看 VIF（m11 已算，>5 就要处理）。
3. **多因素模型**：因变量连续 → 多元线性（m11）；因变量二分类 → 二元 Logistic（m18，
   `Exp(B)=OR`、报 95%CI、参照类别取第一个水平并在表注写明）。
4. **稳健性**：换样本范围、换参照组、加/减控制变量各跑一次，看关键结论是否翻转。

`--methods all` 会把这条链上的每一环都跑一遍，报告里的"总览"表就是这一步的检查清单。

## 20. 三件脚本不替你做的事

1. **选哪个变量当因变量**——这是研究问题，不是数据属性。脚本只按 `config.outcome` 走。
2. **样本量够不够**：EPV（每参数事件数 <10）、KMO <0.5、某组 n<2 等脚本会拒绝或警告，
   但"再补多少样本"要你按效应量估算（`auto_stats.py --roc` 给的是现有样本的判别力，不是所需样本量）。
3. **因果**：所有 `p<0.05` 都只说明"在这份数据里不太可能是偶然"。
   观察数据的因果要靠设计（时间顺序、工具变量、准实验），不能靠方法名。