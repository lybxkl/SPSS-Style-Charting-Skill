# CHANGELOG

## 2026-11-18 批次6：增量断点 + rerunRules 细化 + dist/manifest 一致性（提交 ed23c94 之上）

- **`audit_corpus.py --resume`**（十万级语料中断续跑）：`corpus_files.csv` 新增 `mtime` 列（`st_mtime_ns`，纳秒精度）；`--resume` 读上一轮 csv（复用行数值列从 CSV 字符串水化回 int/None——`keeper_score`/汇总对字符串行会 TypeError，含重复副本的语料首轮即触发），对每个文件先 stat——**大小与 mtime 都未变即复用上一轮整行**（状态/页数/字符/MD5 全不重算），变更/新增照常处理，消失文件移除并在 `corpus_summary.json` 的 `resume` 块计数（reused/reprocessed/vanished；`--max-files` 截断的运行不把未走到行计成 vanished）；抽样框（--ext/--skip-dir/--min-chars）或哈希模式（--no-hash）不一致直接 exit 2 拒绝（不混框）；**上轮 summary 缺失（csv 独存）同样拒绝**——没有快照就无法证明旧行出自本次抽样框；去重分组与汇总每轮全量重算。**续跑产物与全量重跑逐字节一致**（回归测试钉住，含重复副本语料与截断→续跑场景）。SCRIPT_VERSION 2.1.1。
- **`make_coding_sheet.py --resume`**（抽取层断点）：每处理完一份文档即把**整份产物**（rec/编码行/字段行/证据/复核行/NA 分桶；含读失败的 unreadable 跳过）追加写 `<out>/extract_journal.jsonl` 并 flush——日志每次运行都写，不只 --resume 时；续跑命中判据同审计层（size+mtime），复用输出**逐字节一致**；日志每行带 `frame`（root/ext/min-chars/keywords/profile/audit/dedupe 的 sha256+文本开关），不一致 exit 2；崩溃半行（torn tail）忽略并提示；收尾压缩重写（每文档最后一行胜出；**完成整趟遍历才把未见到条目判为消失剔除，`--max-files` 截断保留截断点之后的条目**），不跨轮增长；位置性编号（run_order/_row_id）按本轮遍历重新编号；`run.json` 记 resume 块。SCRIPT_VERSION 2.2.1。
- **rerunRules 细化**（workflow.json 34→57 条，引擎语义=数组顺序首条命中）：34 条 `scripts/<名字>.py` 精确规则**排在通用 `scripts/` 前缀之前**——改一个脚本只重跑它实际供血的阶段（含传递下游）：`pubfig.py`→stats/figures/manuscript/qa、`assemble_manuscript.py`→manuscript/qa、`qa_outputs.py`→qa、`audit_corpus.py`→全链。映射由工作流自身声明推导（step/action 执行→所属阶段+传递闭包；库脚本→导入它的那些脚本（含传递导入）的**阶段并集**）；**建议性工具映射为仅自身阶段**（mine_candidates/suggest_profiles/check_decisions/sample_review/compute_kappa——产物无机器下游消费者）；未覆盖脚本保守落 `scripts/`=全链；recheck/publish 维持不进任何规则的既有约定。references/10 新增第 14 节记录语义。
- **dist/manifest 一致性修复**（批次0 起预存）：`build_skill.py` 打包时**重写内嵌 `contracts/gates/package-manifest.json`**，剔除不随包成员（evals/evals.json——发运策略明言 evals 不随包），归档自洽（归档内 manifest 成员=归档实际文件）；`--check` 按重写字节比对；意外成员被剔除时 SystemExit 拒绝静默改写；仓库侧 manifest 不变（CI 重建的是它）。
- 测试：test_audit_regressions 新增 AuditResume 12 例（逐字节一致/mtime 捕获同尺寸改写/size 变更/消失文件/框拒绝（min-chars+ext+skip-dir）/哈希模式拒绝/无前轮全量跑/**重复副本语料续跑存活**/**summary 缺失拒绝**/**截断→续跑=全量等价**（4 产物+9 键）/截断不误报 vanished）；test_coding_layer 新增 TestExtractResume 10 例（逐字节一致（10 产物）+run.json 复用计数/同尺寸改写重抽/size 变更重抽/profile 变化拒绝/ext+min-chars+no-text 框拒绝/断尾容忍/日志不增长/**--max-files 截断保留条目+跨截断回放=全新全量跑**/**消失文档剔除**）；test_workflow_contract 新增 3 例（精确规则先于前缀+具体映射钉死+规则与自有 step/导入闭包对账——advisory/库白名单）。
- 文档：01「断点续跑」节（判据、诚实边界：mtime 判据非哈希、对抗性场景不在防线、框一致性、逐字节一致承诺）+表格列加 mtime；09 §3.5 抽取断点节；SKILL.md 审计命令段+脚本表两行；10-contracts §14。evals id29。

## 2026-11-18 批次5：成稿适配（提交 8dcbd97 之上）

- `assemble_manuscript.py` 三类新 block（成稿侧「只能去 Word 里手点」的三件事脚本化）：
  - **交叉引用**：正文任何文本写 `[@tab:N]`/`[@fig:N]` → 渲染为指向表/图题书签（`_RefTabN`/`_RefFigN`）的 Word REF 域（`\h` 超链接），域带缓存文本「表N」——`verify_numbers.py` 在 F9 之前也能读到编号。表/图编号改为**预扫描两遍法**：先扫全部 blocks 定号（显式 `number` 优先、重复 exit 2）再渲染，前向引用（正文在表前说「见表2」）合法；引用不存在的编号 exit 2 报错，不把 `[@tab:9]` 原样印给读者。
  - **参考文献**：`{"type": "references", "csv": ..., "title": ...}` 读一列 `text` 的 CSV——每条是研究者**已排好版式**的条目（GB/T 7714/APA/Vancouver 由研究者定，顺序=CSV 行序，脚本不替研究选样式）；悬挂缩进按字符（`w:hangingChars`，默认 2）+ 可选 `[n]` 编号（`numbering: bracket|none`）；条目支持 `{key}` 占位符；空行 exit 2、重复条目 WARNING 留痕。
  - **目录**：`{"type": "toc", "levels": "1-3"}` 插入 Word TOC 域（fldSimple），域内缓存「打开后 Ctrl+A、F9 更新」提示——页码只有 Word 渲染时才知道，导 PDF 前必须更新域；levels 参数校验（低≤高）。
- `pubfig.py` 新增两个纯 matplotlib 绘图函数（无新依赖）：
  - `sankey(ax, left_labels, right_labels, matrix, ...)`：两列流向图，条带/节点高度严格按计数成比例（两列共用同一值-高度比例尺），负值/NaN/零总数/标签维度不符 ValueError 拒绝；
  - `upset(ax_sizes, ax_matrix, ax_sets, set_labels, combos, sizes, ...)`：UpSet 交集图三轴布局（交集大小柱+成员矩阵+集合大小柱），校验组合非空/不重复/索引在界内/集合总数与组合一致，排序归调用方（不替数据排名）。
- `auto_chart_pack.py`：CHART_CATALOG 新增 D 段两行 `flow_sankey`（两列类别交叉表计数，每侧 >8 类拒绝留痕不发明「其他」桶）与 `binary_upset`（≥2 个二元变量；≤5 个画全部非空交集，>5 只画单变量+两两交集并在图注/manifest 声明；含缺失行完整案例剔除并计数；不属于任何集合的观测不进图但写进图注；combos_shown/combos_total 进 chart_pack.json）；**`--width-cm`**（3–30，默认 15）全包统一改输出宽度，px_width 随宽度换算、600 dpi 不变；修复两个既有缺陷：①`group==treatment` 时 `df[[g,t]]` 双列同名使每处 `cell[g]` 变 DataFrame（C 段 Grouper 报错、D 段 ValueError: 2——现可见跳过/回退去重候选列）；②`outcome_group_treatment_heatmap` 对数据中不存在的 group×treatment 组合 `int(cnt.values.sum())` 遇 NaN 崩（现 N=完整案例三列计数）；③无图可出的运行此前不写 chart_pack.json（跳过台账全丢）——现 manifest/json/md 恒写、exit 3 语义不变。
- `qa_outputs.py --min-fontsize` help 修正：默认**不启用**（帮助文本此前谎称 default 7.2；实际设计=始终测量并报告、只有显式传值才作为闸门，避免分辨率专项跑被字号误伤）。
- 测试：test_assemble_manuscript 19→42 例（REF 域 XML/书签/缓存文本/前向引用/坏引用 exit 2/显式编号/占位符后交叉引用/悬挂缩进/编号开关/空行/缺列/缺 CSV/重复条目/TOC 域/坏 levels/提示文案）；test_chart_pack 新增 16 例（sankey 发图+caption、>8 类拒绝、group==treatment 不崩、UpSet 全组合/单二元跳过/集合大小数值断言/丢弃组合台账/非 0/1 拒绝、--width-cm 换算 px_width、越界拒绝、pubfig 级 upset 真值/单例推导/缺单例报错/重复索引/小数拒绝、sankey scale 守卫）。evals id27/28。
- 文档：05 新增「交叉引用、参考文献与目录」节+组装器段落更新；07 图谱表+两行/SPSS 对照表两行/§3 选图表/「Sankey 与 UpSet 的边界」段（含 figsemantics 不自动覆盖这两类、集合大小=逐列真值、combos_total 语义、--figure-width-cm 同步提醒的诚实声明）+宽度段改口；SKILL.md blocks 类型清单+两个要点+脚本表两行。
- 第一轮独立审计（batch5-audit）**有条件通过**：OOXML 经真实 Word 打开-更新域-重存全链路验证（REF 解析为书签文本、TOC 填充页码与超链接）、sankey 几何逐坐标手算全对、07 表与 CHART_CATALOG 程序化逐行全等、三处既有缺陷修复实测生效。1 重要+7 次要+8 建议全部修复：
  - **#1（重要）UpSet 左面板集合大小数值错误**——原实现把显示中的重叠组合相加（同一行被计 2^(|M|-1) 次，可印出超过 N 的数；截断后非空集合可印 0）：改为 `binary_upsets` 从数据逐列传真 `set_totals`，pubfig.upset 的 set_totals 校验从「对账重叠和」（主动拒绝真值）改为真值权威+整数校验；无 set_totals 时只从单例组合推导（缺单例=报错要求数据）；重复索引组合与小数 sizes 拒绝；`dropped_combos`（名字+大小）与 `set_totals` 进 chart_pack.json；pubfig 级数值断言测试（3,3,2,1 案例与 N 上界）。
  - #2 TOC 缓存提示「1-1-3」拼接错误→「域参数 1-3 级标题」；#3 近似笔误标记（`[@TAB:1]`/`[@tab: 1]`）静默照印→XREF_NEAR_MISS 双层守卫（spec 预扫描+_add_text 运行时），参考文献行同样覆盖；#4 书签 start 插在 pPr 前（CT_P 序违反，Word 容忍但严格校验器不保证）→插到 pPr 后；#5 references 行 XREF 逃过预扫描→运行时守卫；#6 声明式 binary 非 0/1 值（{1,2} 编码）静默误读→与 binary_prevalence 同口径拒绝留痕（字符串列「无法按数值读取」单独分账）；#7 sankey scale≤0（≥30 节点或 gap 过大）不报错画垃圾→ValueError+gap∈[0,1) 校验；#8 sankey 轴标签硬编码「来源/去向」→参数化（引擎不定义列语义）；#9 显式+自动混排非单调编号→WARNING；#10 截断丢弃组合 size 全丢→dropped_combos 台账；#12 组合内重复索引双计→拒绝；#13 节点总量 int() 截断→整数原样/小数保留；#14 05 缓存文本空格表述修正；#15 07 补 --figure-width-cm 同步句；#16 CHANGELOG 措辞+文件尾换行。

## 2026-11-18 批次4：统计现代化（提交 2549807 之上）

- `auto_stats.py --spec` 支持五种模型类型与三项字段扩展，全部带类型归属校验（字段写错类型直接 exit 2，不静默忽略）：
  - **交互项** `interactions: [["a","b"]]`（两变量须在 predictors 里）：数值×数值/数值×分类/分类×分类乘积列 + **联合 Wald χ² 检验**（手工约束矩阵，对 OLS/Logit/GLM/MixedLM/PHReg 统一；统计量进 fit.csv 的 `test_stat/test_df/test_p`）；
  - **线性混合模型** `"type": "mixed"` + `groups`（必填）+ 可选 `random_slopes`：REML、固定效应入 coef 表、组数/ICC/方差成分入 fit.csv；
  - **Cox 比例风险** `"type": "cox"` + `time`/`event` + 可选 `strata`：Breslow ties、无截距、HR=exp(β)（metric=HR、CI 在 HR 尺度）；修正 statsmodels 0.15 PHReg 签名坑（旧 `cov=` 关键字被 **kwargs 静默吞掉、事件列会被当协变量拟合——所有 PHReg 调用改为具名参数并加了 `_ArrayResultsAdapter` 让 ndarray 结果按列名索引）；
  - **log-rank 检验** `"type": "logrank"` + `time`/`event`/`group`（+`strata`）：单一检验不产系数行（coef 表按 S-09 写头零行），纯 logrank spec 合法 exit 0；
  - **抽样权重** `weights`（仅 logit/ols）：WLS / GLM freq_weights；点估计=加权估计、**SE 是模型基不是设计基**（摘要与 03/08 文档明说）、weighted_n 入 fit.csv、AIC/BIC/LLR 标注「按重复样本解释仅作参考」、权重须正有限；
  - **多重插补** `impute: {m≥2, seed 必填, cycles≥1}`（仅 logit/ols）：statsmodels MICE（**PMM 抽补**——MICEData 的 impute 恒走 impute_pmm，`perturbation_method` 只控参数扰动；探针实证同 seed 逐字节一致）+ 分类变量编码解码保水平 + 逐填补集空单元格检查（任一集出现即 exit 2，因各集删行不同无法合并）+ **Rubin 合并**（合并 β/总方差/Rubin df/t 分布 p/FMI）+ 结构性列（cluster/weights）从不插补先剔除 + 合并行与完整案例参照行同表 + `impute_report.csv`（within/between/FMI/cc_beta/cc_p）；MI 不报告单一似然/AIC/ROC；CC 参照拟合失败不杀合并估计（摘要记失败原因）。
- **VIF 标志线统一 ≥5**：`model_summary.md` 此前 >10、`methods_lib.py` ≥5，两处矛盾，现统一（VIF_FLAG 常量）。
- fit.csv 扩列（`n_groups/icc/var_group/var_resid/weighted_n/mi_m/test_stat/test_df/test_p`）；`_run_one_model` 重构为调度器 + `_fit_from_work` 公共拟合核（普通路径与 MI 逐填补共享同一条设计/分离/拟合管线，合并估计与 CC 参照可比）。
- 测试新增 `tests/test_stats_modern.py` 48 例：五类已知答案（交互真值 1.2 恢复、混合 ICC≈0.76 校验、Cox HR≈exp(-0.4) 恢复+分层与不分层估计可区分、logrank 检出 0.5 log-HR、MI 恢复种植系数 1.0 且 FMI∈(0,1)）、权重行展开对齐（WLS≈行重复 OLS、GLM freq_weights≈行重复 Logit 点估计）、MI 同 seed 逐字节一致/异 seed between_var 变化、空单元格任一填补集拒绝、字段归属矩阵（含 logrank×interactions/outcome、cox×outcome、空 weights 名负例）、交互列爆炸守门（列行比>1/5 拒绝）、MI 全缺失行剔除不崩（默认路径+impute_outcome=true 真崩溃路径双覆盖）、MI 结局缺失默认排除+`impute_outcome` 可选+事件数观测口径、MI+交互合并与联合检验、MI cluster 缺失报错/weights 缺失入账/空 impute 对象拒绝、mixed 随机斜率 ICC 无定义（NaN+摘要说明）、mixed subset 账面（n_before 经 model_meta 核对）、VIF ≥5 标志线、纯 logrank spec 合法；38 项既有 stats 测试零回归。evals id25/26。
- 第一轮独立审计（batch4-audit）有条件通过，4 重要+5 次要+7 建议全修：①MI 全缺失行崩溃（MICEData 内部 dropna(how="all")+reset_index 会使按位赋值错位——预估全缺失行并计入 n_dropna）②带随机斜率时 ICC 改为 NaN+摘要说明（原按纯截距公式照算无意义值）③MI 插补结局改为显式决策（默认 `impute_outcome=false` 不插补结局=协变量 MI；true 才插补；摘要写明模式、事件数恒为观测口径）④owners 矩阵补 `interactions`/`outcome` 归属（logrank/cox 不再静默吞字段）⑤MI 行 n_events 从 CC 口径改为观测口径⑥07 号文档 Cox 行同步内置⑦空字符串 weights 报错⑧交互列>30 警告、列行比>1/10 警告、>1/5 拒绝⑨MI 循环内 VIF/ROC 旁路跳过⑩`_pred` 死代码删除+used_rows 统一走 `_used_rows()`⑪`_rubin_pool` k=1 防御。审计的统计正确性复算全部一致（联合 Wald 五类 8 位小数、Rubin 合并 10 位、分层 Cox 与手写 Breslow 偏似然 8 位、PMM 声明经 statsmodels 源码核实、普通路径四场景 CLI 双版本字节级一致）。
- 第二轮复审（batch4-audit-r2）**通过**（回归面与 HEAD 双版本五场景字节级一致、manifest 102/102、docs/evals 对齐）；其 5 次要+3 建议也全修：①`_design_columns` 排除交互列（`name[T.` 前缀会捞到交互列使 >30 警告虚报 150/25）②MI 结构性列账目（cluster 缺失=报错与普通路径同语义、weights 缺失=剔除计入 n_dropna+摘要点名；此前静默丢且不入账）③MI 行 used_rows 改为 MI 估计样本（原取 CC 参照行与 n 对不上）④03 文档两处残留矛盾（「多重插补未实现」「VIF>10」）⑤补 `impute_outcome=true`+全缺失行的真崩溃路径测试（反事实证明无修复即崩）⑥`impute: {}` 空对象报错⑦插补结局时事件率分母用观测数（不再 133/300 混口径）。测试 44→48 例。
- 文档：03「五项现代统计」新节（字段/边界/诚实声明）、08 字段表扩五列+旧「未实现」声明更新（交互/插补/Cox/logrank/权重从外部脚本转为内置；PH 检验仍外部）、SKILL.md 4B-2 节+脚本表+「只做 logit/ols」改口、workflow stats 阶段 manualInstructions 加类型声明指引。

## 2026-11-18 批次3：材料数据挖掘候选层（提交 e93c7f5 之上）

- 新增 `scripts/mine_candidates.py`：挖掘候选层——TF-IDF 关键词、句内共现词对（PMI add-one 平滑）、NMF 主题（K 归人声明，`--scan-k` 只给轮廓曲线）、可选 jieba 分词（无则确定性降级：英文空格+中文单字与字 bigram）；产物 keyword/pair/topic/k_profile 候选表（每行 rel_path+行号证据锚）+ mine_receipt.json（清单格式/哈希算法/跳档明细/语料字节数/参数与 seed/分词器档位）。候选不是事实：引擎不写任何 decisions/claims/闸门，采纳归研究者。
- 输入契约直连 audit：corpus 清单认 `audit_corpus.py` 的 `corpus_files.csv`（`status != valid`/`dedupe_role = duplicate` 的行按 audit 机器事实跳过，md5/sha256 列字节校验）或手写 TSV `rel_path[\tsha256]`；重复 rel_path 去重、不可解码文件与缺失分开记录、编码链 utf-8-sig→gb18030→big5 覆盖清单与停用词文件。
- 第一轮独立审计 19 项发现全部修复，其中三个重要级：F1 证据锚选择错误（CSR `getcol().indices` 是列索引——锚恒指清单第一份文档且近半虚构；改 `.tocsc()` 取真行索引+词不在文档正文时不再虚构行号）、F2 输入契约断桥（文档引用的 `corpus_files.txt` 全仓无生产者；改为直读 corpus_files.csv）、F3 `--topics` 无 k 守卫（k≥文档数/超出词表规模曾裸 traceback exit 1；现 exit 2 报原因，且全部表先在内存构建、失败不留孤儿 CSV）。次要：全角拉丁字母/半角假名不再当标点丢弃（\W/\d 已正确划分全角区段）、undecodable 与 missing 分账、`--scan-k` 解析提前、jieba 构建日志静默、--out/--corpus 相对基准在 help 写明。
- 测试 21→39 例：新增锚真实性类（逐行验证词/词对真的在锚定行、唯一词锚到唯一文档、CRLF 行号、second 文档真实存在）、audit CSV 清单类（audit 机器事实分账、md5 校验、重复去重、部分哈希跳档、corpus_bytes）、k 守卫类（k≥文档数/单文档/超词表 exit 2 且无孤儿表）、隔离类（假 sklearn 包→exit 3 干净消息；假 jieba 包→CLI 级 fallback 档位+bigram 进表）、全角字母存活于引擎地板；evals id23 基准同步。

## 2026-11-18 批次2：核实溯源强化

- claims 语义硬化：子句级否定检查（长程否定中「并没有因此出现明显的上升」、英含缩合否定 didn't/wasn't 整族）与指代主语检查（该效应/此/it 开头的 cue 句）——机器解不开的 cue 从判定中拿掉，报 `cue_negation`/`anaphora` 警告（warning 级、不改论断状态）转人工读句；相邻否定窗对 never/缩合形统一路由到子句过滤器，宁可警告不可静默。因果检测力代价（否定词把因果判定降为警告）已在 14 文档点名，复核 `claims review` 须覆盖此类句子。
- 新增 scripts/sample_review.py 结构化抽样复核协议：draw 种子必填、分层（--strata 列 + needs_review 强制第二维度）、--n/--rate 互斥、--min-per-stratum 保底（floor 先行按层规模封顶，再按剩余容量最大余额分配——无 trim 环，保底不破）；同 seed 重跑逐字节复现；每行带 rel_path/field/span/raw 回源锚。tally 三值裁决（保持/改判/无法核对），改判必须给 corrected_value（引擎强制 exit 2）、未知拼写拒绝、未填完拒绝；--fail-above 执行用户声明的改判率上限。
- claims CLI review 子命令错误路径对齐 `FAIL:`+exit 2 契约（Path NameError 及 scopes 文件缺失/坏 JSON/语义覆盖机器矛盾均无裸 traceback）。
- 三轮独立审计（行为+代码复检+修复复核）：Z1 缩合否定死分支、Z2 改判强制、C1/C2 抽样口径、F1 trim 环击穿保底、F2 预检同口径、F4 review 契约等全部修复；fuzz 2500 组抽样不变量零违例。测试 test_claims 31 + test_sample_review 22；全量 1165 OK。
- 文档同步：02 新增「结构化抽样复核」节、SKILL.md 编码阶段第5条与脚本清单一行、14:49 扩写、evals id21/22。

## 2026-11-18 批次1：数据清洗引擎与全量报表（提交 182194a 之上）

- 新增 `scripts/clean_data.py`：配方驱动清洗——七种步骤（去重/值映射/类型转换/越界标记/缺行剔除/重命名/弃列）全部执行项目自写的 `draft/cleaning.json`，不做任何未声明清洗；`max_drop_fraction` 必填护栏、`id_columns` 每步后与结束时查唯一、空串恒缺失（na_values 只追加）；`cleaning_log.jsonl` 记录行数入出/改格数/丢行 id 样本/sha_in→sha_out 内容指纹链，同一数据集+同一配方重放逐位相同；`--flow-out` 把清洗行幂等并入 sample_flow.csv（认 kind 列变体、gb18030/big5 解码）。
- 新增 `scripts/report_tables.py`：全量数据报表——变量档案/描述统计（SPSS 式 G1/G2）/频率表（缺失记(缺失)、基数上限可跳过并写明原因）/交叉表/缺失两表/重复表（含 id_missing 行）/缺失来源四列/`data_report.md`；`report_index.json` 用 sha256 把每张表锚定数据集字节并上溯清洗链；清洗结束行数与数据集行数不符时写陈旧警告。
- 新增 `analysis_utils.validate_csv_shape`/`validate_csv_header`：stdlib 逐行字段数与表头名校验，拒绝 pandas 静默吸收/补齐/改名的行（含溢出成 inf 的值与 `1_000` 字面分隔符拒收）；两个 CLI 读表前必调。
- workflow.json dataset 阶段挂两步（clean_data 带 --flow-out、report_tables 带 cleaning-log/missing-reasons）+ manualInstructions 重写；rerunRules 补 output/dataset/、output/cleaning/、draft/cleaning.json 规则；SKILL.md 与 references/03「数据清洗与全量报表」节同口径；evals id19/20 基准。
- 经五轮独立审计（行为正确性、代码级复检、端到端实跑、细节专项、修复复核）：第一轮 F1-F14/S1-S5、第二轮 N1-N11/G1-G11 全部修复（含台账 header 列快照、manifest 过期致 gate 层 33 例假失败两个真缺陷）；第三轮端到端通过（指纹链逐环咬合、26 组负路径探针零失守、无判断权残留）；第四轮 18 项细节（输出路径守卫、死键拒绝、generated_at 时间戳约定、md 单元格转义等）全部修复；新增 90 个回归用例。
- `tools/build_gate_contract.py` 把 evals/ 纳入 manifest 扫描（成员 100）；package-manifest/catalog/policy 由该工具统一重建。

## 2026-11-18 批次0：判断权收口（提交 182194a）

- 删除 CLI 特权档与领域默认：`make_coding_sheet.py` 移除 `--profile/--doc-type` 读者、裁判文书嗅探（法院正则/省份表/案由词典）与 court/case_no/province 输出列；包内 profiles/ 作为 `--extract` 输入被拒绝（realpath+扩展前缀防御，指向 draft/）；词表与 evals 基准同步中性化；`suggest_profiles.py` 改为无条件提示「示例剖面只是字段形状模板」。
- 新增 `scripts/compute_kappa.py`：双人编码信度（Cohen's κ，KEY_COLUMNS 对齐、单侧变量点名、(未编码) 约定、disagreements 与 coding-sample.md 产出）。
- `verify_numbers.py` V-06 支持多链漏斗（funnel= 消歧、kind=excluded/model、跨链单调性）；`analysis_utils.py` 支持 outcome_map null=声明缺失并分型错误消息。
- 独立审计 8 项发现全部修复；1037 项回归 OK；manifest 98/98。

## 2026-11-15 跨功能逻辑审计

- 修复严格文本解码、重复 JSON 键、同名字段覆盖、活跃来源/恢复代次、不可变表示及逐单元覆盖；PPTX 正文/表格/备注恢复与未解视觉范围分别记录。
- 发现、索引和发布核对实际表示哈希；恢复修订也使索引过期。整单元范围复读绑定实际报告，blocked 缺数仍属未完成。
- 缓存绑定实现及实际环境，重复复用幂等；依赖步骤写入前拒绝重复 ID、未知父节点和环。
- 模型规格路径避免 ID 冲突，缺完整规格不再猜补；新增实际条件适配器，CSV/TSV 保留身份字符串，原始 beta 与 OR/IRR 不混标。外部日志保留原始字节，原生 JSON 严格解析。
- 独立校核逐字段绑定实际 N，精确大整数保持差异；未核标准误/区间/p 值不借系数通过放行。预测按真实数值/日期时间分组，变体路径、尺度可比性和检验族一并检查。
- 发布评估改为只读、前后核对依据并自动补齐正文/论断/图的模型与数据依赖；当前发布重评、阶段 complete 与完整研究 project_ready 分开。
- 同步 README、契约文档与维护流程；完整模块/函数清单、实际入口观测、专项反例与本轮执行证据见 `docs/comprehensive-audit-2026-11-14/`。该目录沿用审计开始日期；最终时间以实际回执为准。

## 2026-11-14 独立审计修复

- 正式发布消费当前全格 final、全来源覆盖、模型独立数值与方法评估、语境复读、实际成稿和各图安置证据；不信任状态字样。
- 统一工作台与核验器完整签名，区分源单元与数据格事件；输入、代码、原件、复核事件及重新拟合均有版本失效检查。
- 账本正常读取检查契约和完整性；事务限制路径、绑定代码、串行原子发布并保留不同输出，锁保护活进程及 owner。
- 搜索去除长文本静默截断，记录实际扫描范围与当前原件清单；补数关闭须实际补格、整表复核及模型重评。
- MILP 保留整数域，非线性方法核边界与约束；开放 Python/命令执行器和非系数结果，保留原生输出独立校核。
- 补充真实聚类/GEE、全规格处置、多重比较、训练内预处理、按组/时间留出和结果口径可比性；未执行、未收敛不冒充通过。
- 补充多维原生审计视图、DOCX 注释部件、CSV 逻辑记录及压缩成员安全提取，保留精度与成员身份。
- 科研配色仍为推荐；实际保存图与图元绑定，同图斜排保留全部标签。文稿保留自选章节/附录，导出原子替换且核对实际 PDF。
- 验收保存真实执行结果、源码/fixture/日志哈希及执行前冻结映射；历史声明与当前证据分开。

变更按日期记录。历史缺陷编号见 `docs/ISSUES-FIXED.md`；资料、统计与交付审计见 [2026-11-13 报告](docs/AUDIT-2026-11-13.md)，配色与展示完整性复核见 [2026-11-14 报告](docs/AUDIT-2026-11-14-PALETTE.md)。

## 2026-11-14 v2 契约层（研究证据台账）

- 新增可选 v2 契约层（`references/13-contract-v2.md`）：31 类记录、状态迁移、内容哈希、特性协商与拒绝；`cell_evidence.prepared → verified` 为非法跳转。
- 新增资料恢复层：`source_units`（物理文件/逻辑单元/独立观察三数分开，容器成员不重复计数，扫描页只判 `partial` 并写 `unrecovered`，旧版 Office 写 `unsupported_format` 回执）、`ocr_provider`（真实 RapidOCR，转写永远未核，复核走 `adjudicate`）、`asr_provider`（真实 Vosk，片段可回放，说话人未定）、`table_recovery`（跨页续表/重复表头/合并单元格/公式缓存与独立复算）。
- 新增审计视图：`audit_view` 对 CSV/JSONL/XLSX 做独立对账（原始 XML 读单元格、日期序列号、公式文本、JSON 重复键与大数精度、0.10 不被写成 0.1）；空表只给范围证据，不报 0/0=100%。
- 新增发现与回查：`discovery` 两条路径并写结构覆盖；`search_index` 索引过期即拒绝回答「没有」；`gaps` 的 resolved/unavailable/exhausted 各有真实前提。
- 新增逐格复核工作台：离线页面、盲第二次抽取、冲突只记 `differs` 不投票、补丁父版本校验与全表复核作废。
- 新增实体/关系/合并审计与单位换算；`models` 开放注册表（四态、按角色的多输入、数学模型的求解质量：infeasible/unbounded/timeout/local/certified_global、无样本 N 不编 N）；`validation` 独立数值校核（共享预处理只能算 `agrees_but_not_independent`）与规格稳定性（无通过校核不得扩展）。
- 新增 `claims`（方向/极值/分母/单位/时间/因果措辞/文献访问层次/数字可溯的机器核查、成稿块指纹与实印比对、失效传播）、`layout_check`（按最终 DOCX/PDF 实际安置尺寸量 dpi/字号，位图无文字层判不了就不放行）、`lifecycle`（环境前后快照、缓存复用写新运行记录、步骤依赖与预算）、`release`（complete/limited/not_ready/failed 四态，limited 仍需硬闸门全过）。
- 新增测试 8 个文件、174 项：`test_contract_v2`、`test_research_core`、`test_recovery_layer`（真实 OCR+ASR）、`test_discovery_review`、`test_models_entities`、`test_lifecycle_release`、`test_claims`、`test_layout`。完整回归见 `docs/implementation/verification/`。

### 2026-11-14 第二轮：补齐审计发现的缺口

- `verify_dataset.py` 增加 v2 检查（值类型义务、证据单元版本、`partial` 单元只能支撑 `image_approx` 且需记录回读、合法空表的范围证据、`review_event` 的签名/归属/时间/独立性），v2 账本不存在时行为不变。
- 新增 `designcheck.py`：设计特征→必须报告的诊断、角色 N 按观测单位计、训练/测试泄漏与重复测量检查；结果写 `validation_result(kind=design_linkage)`。
- 新增 `refs.py`：DOI 元数据核验、访问层级（summary/abstract/full text）与证据哈希、verbatim 引文支持；摘要不能支撑全文论断。
- 新增 `manuscript.py`：从 `manuscript_block` 组装完整论文，拒绝缺章/占位/不可溯数字，真实 Word→PDF，回读实印文本与审核文本比对，不一致即 stale。
- 新增 `figsemantics.py`：从真实 artist 读柱高/误差棒/散点/折线/图例并与数据对账；60 类密集标签用旋转矩形 SAT 实测重叠；布局只给 rotate/expand/widen/subplot 方案，配色只作建议。
- 新增 `faults.py` 与硬化测试：ENOSPC 半写、pointer 替换前杀进程、检查点五层失效、超时只能 cancelled、200k 行分块与 50k 行读回、并发提交幂等。据此修复：`txn` 先发布后写回执（改为先回执后指针）、`Project.latest` 不容忍撕裂尾行、`checkpoint_state` 不看状态、`recover` 选错 commit、缓存 `is_valid` 与 status 矛盾、`models` 数学规格被要求 fit/train、`solve` 不调用问题构造器、`audit_view` 缺 PDF 视图、`table_recovery` 无缓存公式的判定。
- 新增 `tools/acceptance_cards.py`（validate/render/batch-gate/order-check/drift）。原实现曾自报 60/60；独立审计 F21 发现执行证据和场景错配，该历史通过声明已撤回。当前为 59 项实际回归通过、A60 历史批次顺序未核，见修复报告。
- 新增 4 个端到端项目（定量问卷、定性访谈、数学规划、混合材料）与守卫/实体身份测试；回归 842 项通过（508 s）。
- 尚未接线：`references`/`figure_spec` 生成端/`manuscript_block` 组装器只提供记录与检查，未提供生成脚本；`research_gate.py`（v1）未改写，v2 的消费端是 `release.py`。这些缺口逐项记在实施台账中，未计入「已完成」。

## 2026-11-14 配色细节与展示完整性复核

- 修复完整 Lab 色差阈值未生效、黑白仅因同色相而误报警、非法颜色却标为已检查、透明度未标未完成等诊断问题。合法配色默认仍为建议；显式严格分类色检查无法解析时报告失败，不以未核冒充通过。
- 色名/HEX 别名按实际 RGBA 识别，带空格的命名色可用明确分隔符保留；系列数不接受非有限数/小数后静默截断。仅推测默认色环、连续/自定义用途等未核范围保留，并进入审稿包。
- 自动图包的自定义分类色板实际传给绘图，按完整变量类别维持子集颜色；清单从实际图元收集颜色，支持 NumPy RGBA、短色名、黑白和透明度。连续映射单独记录色图，不展开成类别色或填补虚假默认色板。
- 去掉 MDS/KM 的隐藏前 6 组显示限制；MDS 用实际坐标范围，避免极端点被默默裁切。KM 图逐有效组给出 n，低样本曲线只支持相应描述，推断仍由研究设计/诊断评估。
- 实际渲染发现 9 类顶部图例与标题仍可重叠；最终导出在斜标签调整后测量并分开标题/顶部图例，为新增标题位置预留画布，不改数据、不分页。
- 图包程序化入口提前初始化尚未设置的字体样式，避免首次绘图直到保存才初始化；保留用户已选的项目样式。
- 缺字检查同时覆盖布局预渲染与最终写图，避免文字缓存吞掉第二次缺字警告而放行中文方框。
- 新增 `test_palette_audit.py` 的独立合成反例，复核脚本行为、绘图对象、跨图颜色、清单、审稿包、组别与坐标覆盖；完整回归结果另记本轮审计报告。
- 最终全量回归 585 项通过、0 跳过；新增反例单独运行 24 项通过。保留合成 PNG/PDF、实际 QA、可复现脚本、日志及源码指纹；49 文件安装包重建并通过源码一致性/标准 SHA256 检查。

## 2026-11-13 科研配色改为推荐方案

- 按用户要求补充单色、分类、顺序、发散、循环及自定义映射的选择思路、示例起点与可访问性复核建议；不限定固定色号、色板或类别数，用户/领域/期刊需要可调整。清理 SKILL、README、图形契约与图谱中“唯一色环/必须 ΔL*≥10”等强制措辞。
- `qa_outputs` 的分类色板低灰度间隔默认 warning，不再阻断交付；显式 `--strict-palette` 才启用这条额外严格检查。色觉模拟也只作为提示，并说明辅助编码与实际渲染仍需复核；原有文件、数据、N、分辨率等校验保持各自行为。
- manifest 可选 `palette_kind`，分类用途才套两两色差启发式；连续/循环/单色/自定义映射明确记录未由此方法核查，避免将其误判或宣称已验证。未知用途可保留自定义描述，不限制绘图实现。
- 增加默认建议/显式严格、非分类映射、独立色觉模拟、真实 N 错误不被降级，以及 9 色自定义图无 8 色上限的回归覆盖。
- 定向回归 85 项通过：论文图/配色 51 项、自动图包 21 项、交付层 13 项（含本机 Word 高清回填）；compileall、skill quick_validate、安装包源码一致性与标准 SHA256 检查通过。本次未重跑全量研究管线测试。

## 2026-11-13 明确完整论文的交付终点

- 对照旧论文 PDF 与当前代码确认：Word 组稿和 PDF 导出能力保留，通用组稿器只排版输入内容，不自动写研究叙事；只生成文件或方法报告不能作为论文完成的依据。
- SKILL、组稿规范、开放研究契约与 README 明确：论文/全流程研究任务默认交付完整论文式 DOCX + PDF，由 Agent 撰写正文并按学科组织论证、结果、讨论、局限、结论和必要附录；用户只要求局部环节时保持其范围。
- 保留数据/模型/章节形式与数量的自由度，以及真实数据/真实文献/结论边界要求。未新增固定章节验证器或伪造示例论文；未将用户旧论文的数字、结论或项目路径复制进通用 skill。

## 2026-11-13 外部反馈：修复 V-05 误用剔除数

- 确认并实际复现单一 OLS 项目的假错：真实 `n=5,n_dropna=0` 被报为 `V-05 5 vs 0`。根因是消费者优先读 `n_dropna`，并非模型结果错误。
- `verify_numbers.py` 更新至 **1.0.1**，版本写入运行记录，供插件识别修复版。V-05 只使用实际估计样本数 `n`，保留真实 N 冲突检查；只有剔除数或 n 为空时明确 warning，不以剔除数回退。`--fail-on-warn` 可阻止未核项通过严格终检。
- 保留 `fit.csv.n_dropna` 的列名兼容性，明确它只表示因缺失剔除的行数。修正错误代码注释、历史 CHANGELOG 说明、README/SKILL 与跨脚本契约，提供插件名称、tooltip、prompt 和待复核状态语义。
- 补充无缺失/有缺失 OLS 实际输出→V-05、剔除数 0/2/空值、真实 N 冲突及无法核对场景的回归测试。旧版错误结果需要修复后重跑；此前 551 项验证没有覆盖这个生产/消费字段契约，不能据此认定旧版无此缺陷。

## 2026-11-13 源码审计、交付闸门与同图斜标签

- 资料层：全原件备份/只读与恢复保护、旧回执不可剥字段复用、observed 空值拒绝、精确大数派生与 JSON 来源、损坏来源拒纳；去重保留数值标点/大小写并统一 keeper，Office 追加故事与备注，部分读取 PDF 不再视为完整资料。
- 提取与复审：精确候选比较/改判链、最终证据和缺失/漏斗/run 元数据同步，抽取失败明确返回错误，合理全 NA 不再误报错配 profile。
- 统计：缺失类别不误作参照组；显式测量类型/角色；EFA 完整样本一致；Welch 主检验；并列分数 ROC/AP；实际 N/配对 N/时点 N；正确 PCA 载荷/碎石图分母、p 控制限、LDA 协方差判别、时间排序/频率、配对图、KM 掩码、Wald 与二元映射；显式请求的错误列/Kano 配对不再静默丢弃。
- 交付：中文/空数字占位符、严格 CSV、损坏文件/空产物、双轴 dpi、Word 实际字号、窄图、模型/指标/精度数字溯源、图注自引用、严格图题回填与未完成项、零问题报告、语义标题、标准安装包 SHA256。
- 密集图：按用户要求保留同图，横轴标签自适应 45°/60°/75°，增加底部留白；实际旋转矩形检测碰撞和裁切，不自动分页/缩字/省略项目。自动图包与多面板导出共用该检查。完整标签和合法全 0/1 变量保留；无效二元值不能截算比例。
- README 完整更新，补审计报告、合成绘图重现脚本、600 dpi PNG/矢量 PDF、预览和图形 QA；新增独立反例回归测试。验证命令、实际结果及覆盖限制见审计报告；安装包与源码同步重建。

## 2026-11-13 开放研究范围与整合后的逐格回源复核

- skill 明确开放数据集数量/形态、脚本/引擎与数学/统计模型；先全资料发现，逐候选检查数据/设计，缺数必须回原材料和附件补取，补数后重整合/复核，不把内置方法当上限。
- 新增 `verify_dataset.py`：全部单元格的来源 SHA256、CSV/JSON/JSONL/文本/PDF页/XLSX/元数据定位与 raw 回读，派生值独立复算，显式可信适配器扩展；prepare 仅生成 pending 任务，final 要求逐格回源复读的版本签名/时间/记录。不能用抽样、只审 flags 或自动盖章代替真实复核；语义真实性仍需实际复读。
- 新增 `run_model.py` 任意命令执行回执；新增 `research_gate.py` 全来源覆盖、原始目录重扫、开放模型终态/缺数回查、样本键/N、输入/代码/输出哈希和数据复核版本检查。
- 新增注册表示例与 `references/12-exhaustive-research.md`，同步跨脚本契约与交付清单。
- `auto_stats` 的预测变量/模型数和 `auto_chart_pack` 总图数默认 0=不限；移除相关统计前14列与若干单变量/降维图的静默列数截断。图表数据指纹改为全表值/顺序 SHA256，防止总和不变的换值逃过版本检查。
- 自动 PCA 默认完整案例且不插补/截尾，显式处理才在图注留痕；相关散点按变量对处理缺失，不再因第三列缺失丢掉本来可画的数据，相关热图分别报告样本框/成对样本范围/完整案例数。
- 新增 39 项来源真实性、全格复核、版本失效、模型补数、任意引擎执行与开放覆盖测试；独立合成资料前向实测覆盖 3 数据集、42 格复读和 10 个模型候选，资料/模型闸门通过。
- 三条新契约补上正反用例：可读页不完整的 PDF 默认拒绝（只有 `allow_partial=True` 才返回已读页）、位图图不显式声明 `--allow-raster-text` 时计为「未核」而非通过、manifest 行必须给出 png/pdf。`tests/_helpers.py` 固定子进程 `PYTHONIOENCODING=utf-8`，`ΔL*`/`ΔE` 断言不再依赖哪个测试模块先被导入。

## 2026-11-13 LLM 原生：候选集、判断台账与复审闭环

- 抽取层不再静默取值：数值/日期/时长先同行，标签行 NA 短语优先于跨行数字；孤立的「点/點」不再读成 0；`canon` 过滤被更长命中包含的子串（`不满意` 不再同时算 `满意`）。
- 每个字段带 `candidates` / `flags` / `needs_review`，新增 `extraction_review.csv`、`extraction_candidates.jsonl`、`decisions_todo.csv`；`--require-review` 把任一 flag 变成退出码 2。
- 新增 `decisions.jsonl` 契约与 `check_decisions.py`：schema、证据 span/引文、候选值是否真的出现过、重复 target、`needs_human` 未决，全部机器校验。
- `make_coding_sheet.py` 新增 `--decisions` / `--allow-unresolved`：`value` 写回 dataset 并把来源记为 `decision`，`na` 记为 `decision:na`，`exclude` 移除整份文档；`run.json.review` 记录复审与决策计数（重跑不会再保留旧计数）。
- 新增 `review_pack.py`：样本/缺失来源/漏斗、模型 N、图表状态、数字溯源、未决 decisions、审稿人最可能先问的问题；Markdown + JSON 双出。
- `methods_pack.py` 的 m09/m16 增加 EFA 前置闸门：KMO<0.6 或 Bartlett 不显著时跳过并给出诊断值，不再把不可解释的因子解标成“完成”。
- 修复 `references/10-contracts.md` 第 9 节的控制字符损坏（`assemble`→`ssemble`、`exit`→`xit`），并补第 10 节判断台账契约。
- 测试 446 → 464；dist 41 → 43 文件。

## 2026-11-10 审计：十六种方法的数值、编排与配图

第五轮审计按四个角度做：数值正确性（用 scipy/statsmodels/手算三条独立路径比对）、
编排与退出码、16 张图的逐张核对、变异检验。发现的问题集中在两类：**算错的数不报错**，
和**图与自家的 CSV 不一致**。以下每条都附了反例用例（`tests/test_methods_known_answers.py`，
62 例）与变异验证（8/8 变异被用例抓住）。

### 数值

- **PCA 的"载荷"是单位特征向量**（`pca`）。载荷 = 特征向量×sqrt(特征值) = `corr(x, PC)`；
  实测 x1 从 0.587（错）改为 0.904（对）。此前"载荷>0.4 才解释"的阈值作用在错的量上。
- **Mann-Whitney 秩相关符号反**（`1-2U/(n1n2)`）。改为 `2U/(n1n2)-1`，判定语写明
  "r>0 表示第一组的秩更高"，并补了换组顺序后符号翻转的用例。
- **n>5000 的轮廓系数返回 NaN**，判定于是读成"结构弱，K 可能不合适"——5100 行、
  三个相距 8 个标准差的簇被判不合格。改为固定种子子样本估计，并在判定语里说明是估计值。
- **`describe` 把 `normality_p=None` 当成"正态通过"**（n>5000 无法做 Shapiro），
  指数分布（偏度 1.9）仍被推荐"均值±标准差"。改为按中位数报告并注明未做检验。
- **EFA 旋转后方差仍用未旋转特征值**（[74.5,10.0] vs 真值 [43.0,41.4]）：`variance.csv`
  增加 `ss_loading_rotated / variance_pct_rotated / cumulative_pct_rotated`，未旋转的
  `eigenvalue` 保留给 Kaiser 与碎石图（两者用途不同，不能混）。
- **OLS 默认 HC1 却不在输出里标 `se_type`**：`model.csv` 增加 `se_type` 列，判定语说明
  "与 SPSS 的普通 OLS 标准误不同，别拿两张表直接比 t 值"。
- **Wilcoxon 丢零差不说**：现在把丢弃的对数写进判定语。
- **Kano 分档表与死代码矛盾**：统一成教材 5×5 表（`(5,5)→Q`、`(5,4..2)→A`、`(5,1)→O`、
  `(4..2,1)→M`、`(4..2,2..4)→I`、`(1,2..5)/(4..2,5)→R`），并新增逐格对照教材的用例
  （原来的用例拿实现反推预期，变异照样绿）。

### 编排

- **`pca/efa/validity/correlation` 静默丢列**：列名写错时 `[c for c in cols if c in df]`
  会默默少一列照跑，现在直接 `MethodError` 并列出可用列。
- **m18 的 `positive` 把三分类静默并成二分类**：必须显式给 `collapse`，否则拒绝，
  并说明"系数会随合并方式变化，脚本不替你合并"。
- **ARIMA 阶数 `p` 被当 p 值印**（"p=0，aic=222.5"）：m08 单独显示 `ARIMA(p,d,0)`。
- 三态（完成/跳过/出错）分开计数；图链接改 `figures/<name>`（原来 16 条全部失效）；
  坏 JSON 给行列号 + rc 2；`--list` 的"需要"列改成代码真读的槽位；未知异常只打一行。

### 图

- **m03 相关热图与自家 CSV 全面不符**：`corr_heatmap` 对已算好的相关矩阵又 `df.corr()`
  了一遍（对相关系数求相关）。实测 0.599→0.76、−0.062→−0.655（符号翻转）。现在方阵且对称
  就直接用，并加了"传相关矩阵时图上数字必须等于矩阵"的用例。
- **m14 Kano 图没有四象限**：阈值线画在 worse=0 与 better=0.5、轴未固定，两个点相距 4px、
  两条线成了边框；字号 7.0pt 过不了终检。现在固定 0–1 × −1–0、象限线在 0.5、标注 7.6pt、
  四角标出 A/O/M/I（位置按"右上 A、右下 O、左下 M、左上 I"，首版画反了）。
- **manifest 的 n 相加了成对样本量**（28 行 × 样本量 = 25625，而数据只有 2878 行）：
  只有带分组列（group/cluster/level）时才求和，否则取最大。
- m05 轴标签改真实列名并给色标加单位；m07 加数值标注（0.002 的条本来不可见）；
  m16 按列定向（因子正负号任意）；m08 按时间聚合后建模（原来模型 320 行、图上年均值）；
  m11/m18 森林图带系数值；碎石图钉整数刻度 + Kaiser 线 + 图例。

### 字体

- **缺字形只警告、图照样写出**：matplotlib 遇到字体里没有的汉字只发一条
  `UserWarning: Glyph … missing from font(s) DejaVu Sans`，然后照常写出满是方框的
  图，退出码仍是 0。`save_fig` 现在捕获这条警告并抛 `RuntimeError`，指出该调
  `set_style(font_cjk=…)`，并给出用例（`test_missing_cjk_glyphs_raise_instead_of_drawing_boxes`）。
- **程序化用法拿不到中文字体**：`set_style()` 原先只在三个 CLI 的 `main` 里调用，
  直接 `new ChartPack(...)` 或 `methods_pack.draw` 时中文标签落到 DejaVu Sans。
  新增 `pubfig.ensure_style()`，`ChartPack.save()` 与 `methods_pack._fig()` 各自兜一次。

### 文档

- `references/11-methods-catalog.md`：二元 Logistic 的编号 `m10`→`m18`（m10 是聚类）、
  聚类一节的表名改成真实产物、相关分析补 `stars/direction/strength` 列、
  Kano 写明 5×5 分档表与 better/worse 分母口径（R/Q 不进分母）、OLS 与 EFA 的列名对齐代码。

## 2026-11-10 新增：十六种经典方法（`methods_pack.py`）

教材与 SPSS 笔记里那 16 种分析方法此前只能靠人肉在 SPSS 里点，脚本层只有二元 Logit 与 OLS。
本轮把它们做成一条命令，并且**把"这份数据能不能做这个方法"写进代码**：

- 新增 `scripts/methods_lib.py`（约 1200 行）：描述统计（按正态性选均值/中位数并写明理由）、
  正态性、卡方（含 Cramér's V 与稀疏格 Fisher）、两两比较（Bonferroni）、独立/配对 t（先 Levene / 先配对相关）、
  ANOVA（η²、Levene、Welch）、事后比较、Kruskal-Wallis、Mann-Whitney、Wilcoxon、相关（自动 Pearson/Spearman）、
  线性回归（HC1、标准化 β、VIF、DW、Breusch-Pagan、残差正态）、Logistic（OR+CI、McFadden、LLR χ²、HL、
  EPV 提醒、分离时拒绝解释 OR）、KMO/Bartlett、EFA（varimax）、PCA、Cronbach α（含 item-total r 与删题后 α）、
  效度（复用 EFA 并说明内容效度不替代）、K-means（k-means++ + 轮廓系数）、层次聚类、Fisher 判别（Wilks Λ，
  回代准确率标注为上限）、ARIMA（AIC 选阶 + Ljung-Box）、中介（Baron-Kenny + Sobel + percentile bootstrap）、
  Kano（better/worse 系数）；`sem()` **显式拒绝**并给三条替代路径。
- 新增 `scripts/methods_pack.py`（约 800 行）：`CATALOG` 18 条（1–16 号与清单逐条对应，17 非参数族、18 二元 Logit），
  `--list` / `--methods all|m04,m05|family` / `--only`；每个方法先自查槽位与前置条件，缺列、组数不对、
  因变量不是 0/1、题项不足、KMO 过低一律 `skipped` 并写替代方法，**不抛 traceback、不硬算**；
  产出 `methods_report.md`（总览 + 每法一节 + 报告句式表）、`methods_manifest.csv`（含 `status`/`reason`）、
  每张表一份 CSV、**每个跑通的方法一张 600 dpi/15 cm 配图**（共 16 种图）。
- 退出码：有 `error` → 2；一个方法都没跑通 → 2（沉默的零产出不算成功）。
- 文档：新增 `references/11-methods-catalog.md`（16 方法 × 变量要求 × 前置判据 × 表/图 × 报告句式 × 常见误用 +
  两步法流程 + 三件脚本不替你做的事）；`SKILL.md` 阶段 4 增 §4C、脚本清单与参考文献索引更新；README 增功能条目与快速开始 6b。
- 测试：`tests/test_methods_pack.py` 18 例（含"三组数据做 t 检验必须被拒"、"SEM 必须被拒"、
  "因变量三分类做 Logit 必须被拒"、"配置列不存在是 skip 不是崩溃"、"空配置下 m01 仍能跑但 m18 不能"、
  以及 α 范围、中介间接效应 = a×b、PCA 累计方差 = 100%、稀疏格提示等数值断言）。

## 2026-11-10 第四轮：全局审计后的修复

第四轮换了方法：不再逐文件找 bug，而是先建"脚本—产物—消费者—文档承诺"的全局图，
再让不参与实现的 agent 从**跨切面**审计（接缝、整链、文档契约、测试强度、遗留物）。
五份报告合计 100+ 条，下面只列改了什么行为；编号对不上的地方以本节命令为准。

### 会静默算错的

- **`in_analysis` 闸门不再被 `filter` 顶掉**（`analysis_utils.apply_filter`）。此前 config 里一给 `filter`，
  闸门整条失效：2878 → 2710，而真值是 2710 里有 2581 份属于分析样本——**129 份程序性裁定被静默放回（+5%）**。
  现在顺序固定为"先闸门、后条件"，stderr 与返回描述都写 `in_analysis==1 (2878→2713) then … (2713→2581 rows)`；
  要故意越界必须显式 `keep_out_of_scope`，描述里会留 `in_analysis NOT applied`。
  **副作用必须说清**：本轮之前用旧口径跑出的模型 N（含我自己的 2690/2578）都偏大约 4%，需按新口径重跑。
- **`outcome` 自动推断不再撞 `has_outcome`**：正则 `outcome|target|结果` 曾把辅助标志列选成因变量，
  默认命令直接失败。现在要求列名不像 `has_/is_/n_/num_/count_` 前缀**且确实是 0/1**。
- **缺列报错要能读懂**：`filter_query` 用了不存在的列时给 `did you mean: outcome_binary`；
  `auto_chart_pack` 在过滤**之前**一次性列全 config 声明但数据里没有的列，并附数据表头前 25 列。
- **`--audit` 指错根目录不再伪装成"全都不合格"**：`read_valid_paths` 现在返回 audit 里出现过的全部路径，
  路径完全对不上直接 `ERROR: --audit lists a different directory than --root` + 退出码 2；
  单行理由也从 "status is not valid" 改为 `not listed in the --audit CSV (wrong --root…)`。
- **缺失分来源**：`make_coding_sheet --extract` 新增 `missing_by_source.csv`
  （`not_found` / `negated` / `redacted` / `na_phrase` / `unparsed` 分开计数）。此前三类 NA 在 `dataset.csv` 里
  全压成空串，唯一记理由的 `evidence.jsonl` 没有任何消费者。
- **`n_scope=subgroup` 不再被当成 sample**：`verify_numbers` 的 `SCOPE_ALIASES` 补了 subgroup/亚组/子组，
  这类图按变量分别报 N，不参与跨表一致性比较（此前每张图都报一条假错，而图-表比对被静默跳过）。
- **模型表仅使用 `coef_*.csv` / `fit.csv`**，避免把图表清单当模型表。当时新增的“V-05 优先 n_dropna”错误地把剔除数当 N，已在本日外部反馈修复中撤销，正确字段为 `n`；这条旧实现不能作为插件规则依据。
- **中文字体没有粗体也要说**：`pubfig.check_cjk_font` 增加 bold 面探测，缺了打一行 warning
  （matplotlib 会把 weight 700 静默降到 400，屏幕上完全看不出，印出来就是"加粗的标题其实没加粗"）。
- **拟合告警不再被吞**：`auto_stats` 用 `catch_warnings(record=True)` 收集 statsmodels 的收敛/奇异矩阵告警，
  写进 stderr、`model_meta.json` 与 `model_summary.md` 的「拟合告警」段。

### 会假装通过的

- **`--figures` 指向空目录 / 指到父目录**：`images_checked=0` 由 warning 改 **error**（退出码 2），
  文案直接说"多半是把 `--figures` 指到了 `chart_pack` 而不是 `chart_pack/figures`"。
- **位图判据按对象分档**：`--figures` 里的 PDF 每页单独判（整页文字 span < 3 才算"图被拍平"），
  技能自己出的热图 PDF 不再被自己判死；成稿 PDF 里的位图仍是 warning（Word→PDF 的正常形态），但分辨率不达标仍 error。
- **`--colorblind` 真的会触发**：原判据要求 `ΔE76<8` 且 `ΔL*≥10`，而 ΔE≥ΔL*，数学上永不成立；
  现在只判色度距离。
- **`--min-fontsize` 语义与文档一致**：不带也测量并报告，带上才判错；`--min-width` 真正停用（传了只打一行退休提示）。
- **`dedupe_corpus` 无重复不再是失败**：干净语料上 rc=0 并写空计划（此前文档第 2 步在任何无重复语料上都红）。
- **跨 profile 抽取全空会退出码 2**：`ERROR: profile 'x' matched 0 of N fields in M document(s)`；
  部分字段全缺给 warning 并列出字段名。`--profile legal` 用内置示例词典时也明说类别是占位符。
- **`paper_figures` 的 N 只认声明**：`"n": "auto"` 必须配 `--data`，否则报错而不是拿面板行数当样本量；
  示例规格 `assets/paper_figures.example.json` 换成合成数据（此前内联的是一份真实研究的数字，跑出来是假图）。
- **测试补到能挡住变异**：新增"量级递增断链"（`5万1亿`）、`negate` 窗口上限、零惰性对应分析三道反例，
  逐条验证过——把守卫改掉，对应用例立刻红。

### 补上的半成品

- **阶段 6 有了组装脚本**：新增 `scripts/assemble_manuscript.py`（`manuscript.json` → `.docx` +
  `<out>_numbers.csv` + `figure_map.json`）。三线表边框/`cantSplit`/`tblHeader`、`w:eastAsia` 四属性、
  `firstLineChars` 双写、图默认按正文栏宽 14.66 cm（超宽报错并给修法，PDF 图直接拒绝）、`{key}` 缺值退出码 2。
  实测链路 `assemble → export_pdf_hires → qa`：`min_fontsize 9.0`、`dpi_min 613.9`、`error_count 0`。
- **契约随包走**：`docs/CONTRACTS.md` → `references/10-contracts.md`（安装包里原本没有契约文件，等于没有契约）；
  `tools/build_skill.py` 的 INCLUDE 补 `profiles`。
- **`sample_flow.csv` 由 audit 真正写出**（契约承诺过、`--sample-flow`/V-06 消费，此前是幽灵文件）。

### 文档改成与代码一致

`--sample-flow` 的真实路径（`output/coding/sample_flow.csv`，不是 `output/tables/`）、
`--min-fontsize` 的真语义、图数改成实测区间（小语料 15–21、2878 行语料 44 张跳过 3 张）、
`--figures`/`--manifest`/`--tables` 各指哪一份产物、`3→5` 该不该带 `--audit`、`.sps` 用 SPSS 打开（本 skill 不调 SPSS）、
`CATEGORICAL` 八色是"各色 L*"而不是"相邻差"（两两最小差 10.62，余量只有 0.62）、测试数 360。

## 2026-11-10 Sprint A/B/C：把"能从材料做到正文"的三段补上

第二轮审计（5 个角度、81 条）的结论不是"哪里还有 bug"，而是**四段能力要么没有、要么只是个说法**：字段抽取层不存在、多面板正文图不存在、数字溯源不存在、装的是旧代码。本轮按 A/B/C 三个 sprint 补齐，每个 sprint 完成后由不参与实现的独立 agent 审计一次（报告不入库，只把结论并入本文件与 `docs/ISSUES-FIXED.md`）。

### A. 字段抽取层（新增 `scripts/extract_lib.py`、`profiles/`、`references/09-field-extraction.md`）

- **新增 12 个纯函数原语**：`num`、`quantity`、`date`、`duration`、`kv_block`、`section`、`items`、`window`、`negate`、`canon`、`count_unique`、`pattern`/`contains`。**`extract_lib.py` 里没有任何学科词**（有测试 `LibraryIsDomainNeutralTest` 钉住），领域写在 profile JSON 里：换一份 profile 就换领域，不是 `if` 分支。
- `make_coding_sheet.py --extract profiles/<x>.json` 产出三件套：`dataset.csv`（一行一个观测，每个字段带 `<字段>_src` 来源列）、`evidence.jsonl`（每个值带 `name=snippet@start-end`，偏移可在原文逐字回验）、`run.json`（profile 路径 + sha256 + 每字段命中/缺失数 + 脚本版本）。
- **两个示例 profile 跑同一条命令**：`profiles/legal-judgment.json`（11 字段，表格式头部逐字换行）、`profiles/eldercare-interview.json`（8 字段，Q/A 访谈）。它们只是夹具，**不代表推荐任何研究设计**。
- **一个数只读一遍**：`num` 与 `quantity` 共用同一条"从左到右、量级递减"的链式读取器。此前 `quantity` 走另一套倒序规则，同一个 `1亿零5万` 在前者得 1e8、在后者得 50000——两个解析器各自自洽、一起与文书不符。`零` 是连接词（`1亿零五万`=1.0005e8），空格也是（PDF 抽取常见 `1亿 5万`）。
- **别名自带的量级不再乘第二次**：`1200万元`=1.2e7，`十五万元`=150000。此前 `十五万元` 得 1.5e9。
- **`contains` 认 `|` 分隔的多别名，并按整行 `exclude` 过滤**：`"投诉|反映|不满意|意见"` 此前被当成一个字符串，`complaint_any` 恒为 False，而真值也恒为 False——**验收是空转的**。同时提问行（`^(问|Q)[：:]`）不再计入受访者表态。
- **`kv_block` 取冒号后整行余量，绝不跨行**；空值不再吞下一行字段（`案号：\n案由：盗窃` 曾把 `案由：盗窃` 当成案号）。
- **`date` 支持被脱敏的年**：`裁判日期：2021********` 返回 `2021`，不再回落到正文里另一个事件完整日期（此前 51/2964 份的年份会错，最坏差 30 多年）。`anchor` 让"离锚点最近"胜过"更完整"。
- **`validate_profile` 拒绝该 func 不读的键**（`kv_block` 带 `pattern` 直接报错）。写错键名的字段原本静默忽略那段配置。
- 实测：真实判决书 120 份，条件召回 `fine_yuan` 100%、`sentence_months` 100%、`restore_amount` 100%、`probation` 100%，`bad_span=0`；合成访谈 20 份对真值 73/73。

### B. 多面板正文图 + 投稿级图检（新增 `scripts/paper_figures.py`，补 `assets/paper_figures.example.json`）

- `--paper paper.json` 按图组装多面板（GridSpec），产出 `FigureN.png|pdf|tiff` + `paper_figures_manifest.csv`（与图表包 manifest 同构，含 `palette`、`dpi`、`px_width`、`min_fontsize`）。`SKILL.md` 一直指向 `assets/paper_figures.example.json`，而该文件此前不存在——现在存在，且 `--paper` 跑它得 3 图 0 error。
- **生产者与检查者共用一个 N 解析器**：`paper_figures` 不再自带 `\d[\d,]*`（那会把 `3 111→2 713` 读成 `3`，然后把图注改写成 `N=3`，而检查器验的是被污染的值——两边自洽、exit 0）。
- **N 只认声明，不推断**：缺 `n` 写 `n=NA` + `status="skipped: n unknown"`，绝不拿面板数据行数当样本量。
- **图注只替换第一处 `N=`**，第二个不同数值原样保留并记 `n_conflict`。
- `CATEGORICAL` 6→8 色且**两两 ΔL* ≥ 10**——8 个颜色的 L* 依次为 32.1/64.7/43.2/21.5/53.9/10.5/75.5/86.3，**两两之差的最小值是 10.62**（第 1 与第 4 色），余量只有 0.62；列举的是各色 L*，不是相邻差。超出的序列 `warnings.warn`；manifest 必写实际用到的 `palette`（此前缺这一列，"灰度可分性"从未真正执行，7 类罪名在黑白下只能数出 3 类）。
- `qa_outputs.py` 补 **`--min-fontsize`**（按 PDF span 实测并按安置宽折算）、**灰度可分性**、**色盲模拟**（判据改为 `ΔE76<8` **且** `(Δa*,Δb*)` 模 <6——只看 ΔE 时因 ΔE≥ΔL 永远不触发）。
- **`no_text_layer` 按对象分档**：成稿 PDF 里的位图（Word→PDF 的正常形态）记 warning 并写明"字号须在源图 PDF 上核"，但位图分辨率不达标仍是 error；`--figures` 目录里被拍平的矢量图仍是 error。此前一律 error，导致**每一篇正常论文都必然红**——闸门永远响等于闸门不存在。
- **缺中文字体不再静默画豆腐块**：`set_style()` 先验字体，可替换则向 stderr 报一行替换提示，一个中文字体都没有才 `RuntimeError` 并列出本机候选；`paper_figures` 删掉了吞 `findfont` 的那行 `filterwarnings`。

### C. 数字溯源（新增 `scripts/verify_numbers.py`）

- 六项检查：V-01 表内合计、V-02 表与图注同值、V-03 正文数字找回表、V-04 图号连续且被正文引用、V-05 样本 N 跨表一致、V-06 漏斗单调不增。产物 `number_issues.csv`（`severity,check,where,expected,actual,detail`）+ `number_trace.csv`（每个数字追到哪个文件哪一格）+ `run.json`。
- **溯源要"同语义"，不是"任意单元格出现过"**：此前表里 `p=0.0494` 可以"证明"正文 `4.94%`、`est=1358` 可以"证明" `N=1,358`，实测 exit 0。现在列名决定语义（count/p/estimate/pct），只有同语义单元格能作证据，否则报 error 并写明"其他语义的列不能作为证据"。
- **`p<.001` 与表里 `p<0.001` 互认**（保留比较符），`p=X` 对表里 `p<X` 报 error（表只给了上界）。论文最常用写法此前被误杀。
- **缺输入不再静默空跑**：`--check all` 缺 `--tables`/`--docx`/`--sample-flow` 时逐项写 `missing input <flag>` 并 exit 2。
- **`--numbers` 承接叙述性数字**（`value` 列）、**`--figure-data` 承接图内数字**（`figure,label,value`，只认 count/pct，语义不符的数字照样报 error）。优先级 `figure-data → numbers → 表`。
- **图表包 manifest 的 `id` 不是 `图N` 时按行序映射**，不再 44 条假报错（`A01/F01` 是图包编号，不是书内图号）。
- `sample_flow.csv` 支持 `kind ∈ stage|excluded|model`（`model` 行须 `note=stage=<名>`，只校验 ≤ stage）；缺 `kind` 的行会在 detail 里说明怎么补。
- 真实项目回归：193 个正文数字，加 `--numbers` 后 **193/193 traced、0 error**。

### 横切

- 每个脚本写 `SCRIPT_VERSION` 到产物（`run.json`/导出报告/`.sps` 注释/`stderr` banner）；`dist/*.skill` 旁写 `.sha256`。
- `audit_corpus.py` 写 `corpus_fingerprint`（文件数、字节数、`rel_path\tbytes\tmd5` 的 sha256），语料换了能看出来。
- `tools/build_skill.py` 的打包清单加入 `profiles/`（否则 `--extract` 在安装包里必然找不到 profile）。
- 测试：159 → **329** 例（新增 `test_extract_lib` 53 / `test_figures_paper` 31 / `test_verify_numbers` 59，其余为反例补充）。

### 已知未修（有意留在边界内）

- `--jobs`/断点续跑（S1）未做：3111 份实测 audit 2.2 s / 抽取 3.0 s，本规模不需要。
- 方法承诺仍未实现（KMO/Bartlett、平行分析、轮廓系数、中介、多重插补、交互与简单斜率、训练/验证拆分），`references/03`、`08` 已标明"需外部脚本"。
- Cohen's κ 仍无脚本（属人工协议）。

---
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

