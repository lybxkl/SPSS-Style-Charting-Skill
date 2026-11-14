# 实施报告 · empirical-research-pipeline 强化方案（v1.1）

日期：2026-11-14
仓库：`F:\测试文件\SPSS-Style-Charting-Skill`
基线提交：`f0c45b4b5eafb86211640e2557ef013f066ef8c3`（未回退、未重置现场）
实施台账：[TASK-STATUS.json](TASK-STATUS.json) · 验收记录：[ACCEPTANCE-RESULTS.json](ACCEPTANCE-RESULTS.json)

## 1. 一句话结论

九项能力（R01–R09）已落下可运行的代码与真实测试，**第二轮把首轮列为 partial/未开始的项补齐**：
40 项任务全部 `implemented`，60 个验收场景全部 `passed`（且每张卡都有原件/步骤/独立期望/实际观察/
环境/证据路径与「期望早于实现」时间戳）。完整回归 **842 项通过（508 s）**，安装包 74 个文件
626,608 字节，整包标准 SHA256 `4f6126982efebc62068f2592ddec2a0607450711d599ac916715a88ab04fb045`，
隔离目录导入与真实调用通过。

仍然如实受限的部分（§6）：`research_gate.py`（v1）未改写，v2 发布消费端是 `release.py`；
文献只是元数据+访问层级+verbatim 引文，不能代替人工阅读原文；组稿器不生成研究叙事；
全部测试材料为 **synthetic**，没有真实研究材料，因此本报告不声称任何实证结论。
这些是「能力边界」，不是「未做的任务」。

## 2. 改了什么

### 2.1 新增契约层（T02/T03/T37）

- `scripts/contract_v2.py`：31 类记录、状态迁移表、内容哈希、特性协商、v1 迁移（不继承 verified）。
  `cell_evidence.prepared → verified` 被状态机禁止，必须经 `review_pending`。
- `scripts/depgraph.py`：依赖节点/边/事件，负向边（排除、缺失判断）可成环，影响传播会重新触发否定判断。
- `scripts/txn.py`：staging → 内容寻址对象 → 原子发布指针；父版本校验、输入复验、幂等提交、
  中断恢复、`O_EXCL` 锁（含死进程回收）。

### 2.2 资料恢复层（T04–T07、T38）

- `source_units.py`：物理文件 / 逻辑单元 / 独立观察三个数分开；PDF 页分文本/扫描/混合/空白，
  扫描页只判 `partial` 并写 `unrecovered`；Office 内嵌对象与 zip 成员单独成单元、不重复计数；
  旧版 `.doc/.xls/.ppt` 写 `unsupported_format` 回执而不是假装可读。
- `ocr_provider.py`：真实 RapidOCR；旋转页面坐标变换（0/90/180/270）经**独立文本层 bbox** 校验
  IoU>0.55；OCR 转写永远不是 verified，复核走 `adjudicate` 并保留原转写。
- `asr_provider.py`：真实 Vosk；词级时间戳、低置信词、说话人未定；`replay` 用 ffmpeg 切出原区间。
- `table_recovery.py`：跨页续表（重复表头不重复计数）、两级表头、单位与脚注、合并单元格空值、
  xlsx 公式缓存与独立复算（999 vs 42 判 mismatch）、日期序列号、前导零。
- `audit_view.py`：CSV/JSONL/XLSX 视图与原始 XML/JSON **独立**对账；发现重复键、大数精度丢失、
  `0.10`→`0.1`、公式被缓存值替代；空表只给范围证据，不报 0/0=100%。

### 2.3 发现、回查与逐格复核（T08–T12）

- `discovery.py`：材料优先 + 问题优先；每个结构有覆盖处置；未匹配只写 `unresolved` + 原因
  （"not proof the field is absent"）。
- `search_index.py`：索引绑定来源哈希；过期索引**拒绝**回答「没有」；每次检索写 `search_run`
  （query/index/hits/snippet/executed）。
- `gaps.py`：`resolved` 必须有 `found` 检索并写数据集；`unavailable` 至少一次检索；
  `exhausted` 必须覆盖全部来源且哈希一致。
- `review_workbench.py`：离线页面列出全部格与证据、明确「没有一键 verified」；盲第二次抽取不含
  第一遍值；冲突只记 `differs`；通用备注/快照前时间戳/签名不符/缺定位/缺审阅人一律拒绝；
  补丁父版本不符转 `conflict`，应用后声明全表复核作废。

### 2.4 实体、模型、校核（T14–T22）

- `entities.py`：实体类型/稳定 id/别名合并与冲突、关系基数、join 审计（一对多、未匹配、
  口径冲突、结果观测单位）、单位换算留痕（万元→元 因子 10000）。
- `models.py`：开放注册表；统计模型必须声明观测单位与结果语义，数学模型必须 `n_semantics=none`
  且给维度/约束；多输入按角色绑定数据集版本；条件检查（版本、唯一键、参数数、变异性）；
  求解质量 `infeasible/unbounded/timeout/local_optimum/certified_global`（子进程墙钟超时）；
  `assert_conclusion_scope` 拒绝因果/全局最优/无样本 N 的措辞。
- `validation.py`：独立 OLS（numpy lstsq）与自写 IRLS；**共享预处理只算
  `agrees_but_not_independent` 且状态 failed**；规格稳定性必须在其之后（T22 先于 T21），
  符号翻转/CI 跨零进 `fragile`。

### 2.5 论断、版面、发布（T26、T31、T32、T24、T25、T40）

- `claims.py`（子代理实现）：方向/极值/分母/单位/时间范围/因果措辞/文献访问层次/支持缺失/
  数字可溯 9 类机器核查；块指纹与实印文本比对；依赖传播。
- `layout_check.py`（子代理实现）：按最终 DOCX/PDF 的**实际安置尺寸**量 dpi 与字号；跨格式用
  **解码像素哈希**配对（Word/PyMuPDF 会重编码，字节哈希必然不同）；位图无文字层 → `unassessed`。
- `release.py`：四态 `complete/limited/not_ready/failed`；空 scope、缺证据、硬闸门未过都不 complete；
  `limited` 需显式声明且硬闸门全过。
- `lifecycle.py`：环境前后快照（python/packages/engines/规则哈希）、缓存复用写**新**运行记录
  （`ran_again=false`，不 re-date）、步骤依赖与预算、超预算标记、失败依赖阻塞后继。

### 2.6 文档与打包（T35/T36）

- 新增 `references/13-contract-v2.md`（记录种类、命令、硬性拒绝、与旧链路关系、已知边界）；
  `SKILL.md` 加入口段落；`README.md` 更新脚本索引与「进一步阅读」；`CHANGELOG.md` 记录本轮。
- 安装包：69 文件、573,883 字节；`--check` 源码一致；整包 SHA256 与 sidecar 一致；
  隔离目录解包后导入 20 个模块并跑通 `source_units` 与真实 OCR/ASR provider 枚举。

### 2.9 第二轮补齐（2026-11-14 下午）

- **T13**：`verify_dataset.py` 增加 v2 检查（值类型义务、证据单元版本、partial 单元只能支撑
  `image_approx` 且需记录回读、0 行数据集必须有范围证据、`review_event` 的签名/归属/时间/独立性），
  报告增加 `contract_v2` 段；无 v2 账本时行为不变。
- **T20**：`designcheck.py` 把设计特征（聚类/重复测量/权重/匹配/分层/面板/小样本/缺失/多结局）
  映射为必须报告的诊断，并按角色与观测单位核算 N、检测 fit/test 泄漏与重复测量。
- **T23**：`claims.link_dependencies` 与 `manuscript.register_media_dependencies` 把 claim、
  manuscript_block、figure 与 result 接成依赖边，`propagate` 覆盖下游失效。
- **T27**：`refs.py` 记录 DOI 元数据核验、实际读到哪一层（full_text/abstract/metadata/
  unavailable）、证据路径与哈希；摘要层不能支撑全文论断，引文必须 verbatim。
- **T28**：`manuscript.py` 从成稿块组装完整论文：必需章节/最小篇幅/占位符拒绝、数字必须同时有值
  和 trace、图表插注、真实 Word→PDF、回读实印文本与审核文本比对，不一致即 stale。
- **T29/T30**：`figsemantics.py` 从真实 artist 读柱高/误差棒/散点/折线/图例并对账数据；
  60 类密集标签用旋转矩形 SAT 实测重叠；布局只给 rotate/expand/widen/subplot，配色只作建议。
- **T31**：`layout_check` 与 `figsemantics.check_saved` 分别覆盖最终安置尺寸与保存文件，
  判不了的项一律 `unverifiable` 且整体不放行。
- **T33**：四个端到端已知答案项目（定量问卷、定性访谈、LP 优化、混合材料）真实跑通。
- **T34**：`faults.py` + 硬化测试（ENOSPC 半写、杀进程、检查点失效、超时、200k 行规模、并发提交），
  并据此修复 5 个真实缺陷（见 §4）。
- **T39**：`tools/acceptance_cards.py` 校验并生成 60 张验收卡，`validate` 60/60、`order-check`
  60/60、八个批次门检全部退出 0。

## 3. 怎么验证

| 验证 | 命令 | 结果 |
|---|---|---|
| 基线（改动前） | `python -m unittest discover -s tests -p 'test_*.py' -v` | 585 项通过，318.348 s |
| 首轮完整回归 | 同上 | 759 项通过，见 `verification/regression-final.log` |
| **第二轮完整回归** | 同上（新增 10 个测试文件） | **842 项通过、0 失败、0 跳过**，508.423 s，见 `verification/final/regression-v4.log` |
| 验收卡 | `python tools/acceptance_cards.py validate` / `order-check` | 60/60 通过；期望时间早于实现时间 |
| 批次门检 | `batch-gate --batch M0..M7` | 八个批次全部退出 0 |
| 台账一致性 | `python tools/impl_ledger.py check` | `OK: ledger is internally consistent` |
| 安装包 | `python tools/build_skill.py` + `--check` | 74 文件一致，626,608 字节 |
| 整包哈希 | `Get-FileHash` vs sidecar | 均为 `4f6126982efebc62068f2592ddec2a0607450711d599ac916715a88ab04fb045` |
| 隔离安装 | `python docs/implementation/verification/install_check.py` | 74 文件解包，无 tests/docs/pycache；新模块可导入，提供方枚举正确 |

关键反例（不是「跑通」而是「该失败时失败」）：扫描页不判 verified；越界 bbox 抛 ValueError；
过期索引拒绝回答；缺证据的格被拒绝；公式缓存 999 与复算 42 判 mismatch；共享预处理判
`agrees_but_not_independent`；篡改估计被独立校核发现；父版本不符的补丁转 conflict；
位图无文字层的版面判 unassessed；空 scope 不能 complete；摘录层不能支撑全文论断；
缺 trace 的数字拒绝排印；实印文本与审核文本不一致即 stale；ENOSPC 后发布指针不动；
被杀的运行只能是 cancelled。

## 4. 为什么这样改（关键决策）

1. **v2 层可选、不替换旧链路**：585 项既有测试是资产，直接重写 `verify_dataset.py`/`research_gate.py`
   会把「已有修复」置于风险中。因此 v2 记录与旧闸门并存，发布层同时读两者；逐格复核的唯一真相
   仍是 `verify_dataset.py` 的 review 文件，v2 只加审计记录。
2. **状态机而不是自由字段**：`prepared→verified` 直接非法，是让「没复读就 verified」在类型层面做不到。
3. **转写/近似永不算实测**：OCR/ASR 结果只标 `partial`，复核必须回到原件；像素读数属
   `image_approx`，与 `observed` 分层。
4. **独立校核要真的独立**：共享预处理的两个算法一致不算证据，故单列
   `agrees_but_not_independent` 并阻断稳定性扩展。
5. **超时用子进程墙钟**：`multiprocessing` 在 Windows + unittest 下会被 spawn 重新导入主模块，
   导致不可复现的失败；改为独立进程 + `subprocess.run(timeout=)` 后行为稳定。
6. **版面检查用像素哈希**：Word 与 PyMuPDF 都会重编码图片，字节哈希必然不同；按解码像素配对，
   同时保留字节哈希备考。

## 5. 兼容性

- 既有 CLI/字段/行为未改；新增模块都在 `scripts/`，旧脚本未改动（`research_gate.py` 未改）。
- v1 数据可用 `contract_v2.py --migrate-v1` 迁移，但**不继承 verified**；旧读取器缺特性时被拒绝。
- 安装包仍只含 `SKILL.md/assets/profiles/references/scripts`；测试、docs、真实研究材料不入包。

## 6. 未完成 / 未核 / 受限（逐条）

任务与场景已无未完成项；下面是**能力边界**与仍然判不了的情形，均已在代码里显式表达：

| 项 | 状态 | 说明 |
|---|---|---|
| v1 `research_gate.py` | 未改写（有意） | v2 的发布消费端是 `release.py`；两者都通过才算发布。旧调用不受影响 |
| 文献全文 | 受限 | `refs.py` 只做 DOI 元数据、访问层级、verbatim 引文核对；不能代替人工阅读，也不代取全文 |
| 论文叙事 | 工具边界 | `manuscript.py` 只组装与核验，章节内容必须由 Agent 写入 `manuscript_block` |
| 位图图元/字号 | 判不了 | `figsemantics` 对位图只核尺寸/像素；`layout_check` 无文字层即 `no_text_layer`，整体不放行 |
| OCR/ASR 语义 | 判不了 | 转写永远是 `partial`，必须回原图/原音复核；识别引擎本地可替换（RapidOCR/Vosk） |
| Tesseract / LibreOffice / R / Julia / Stata | 本机不可用 | 已记录在环境快照；Tesseract 提供方 `available=false`，PDF 导出走 Word COM，不用未安装的引擎冒充 |
| 规模上限 | 有界 | 实测 200k 行分块与 50k 行读回；`verify_dataset.read_csv` 仍是整表读入（未做流式接口），更大规模未测 |
| 真实研究材料 | 未涉及 | 全部 fixture 为 **synthetic**；四个端到端项目是流水线验证稿，不是实证结论 |
| 批次门检 | 自检性质 | `batch-gate` 验证的是台账与本批证据的一致性，不等于外部同行评审 |

## 7. 恢复入口

1. `docs/implementation/TASK-STATUS.json`：40 项全部 implemented，`gaps` 为空；要看每项改了什么、
   用什么证据，读 `changes` / `verification`。
2. `docs/implementation/ACCEPTANCE-RESULTS.json` 与 `ACCEPTANCE-CARDS.md`：60 张卡各自带
   fixture / steps / observed / environment / evidence / 时间戳；要复核就按卡上的命令重跑。
3. 重跑顺序：完整回归 → `acceptance_cards validate` / `order-check` → `batch-gate` →
   `build_skill.py` + `--check` → `install_check.py`。
4. 继续扩展时不要让 `planned/partial` 冒充完成：`tools/impl_ledger.py check` 与
   `acceptance_cards validate` 会拒绝没有证据的「通过」。

## 8. 复现命令

```powershell
$env:PYTHONUTF8='1'
$env:VOSK_MODEL='F:\测试文件\SPSS-Style-Charting-Skill\docs\_providers\vosk\vosk-model-small-en-us-0.15'
cd tests; python -m unittest discover -s . -p 'test_*.py' -v
cd ..; python tools/acceptance_cards.py validate
python tools/acceptance_cards.py order-check
foreach ($b in 'M0','M1','M2','M3','M4','M5','M6','M7') { python tools/acceptance_cards.py batch-gate --batch $b }
python tools/build_skill.py; python tools/build_skill.py --check
Get-FileHash dist/empirical-research-pipeline.skill -Algorithm SHA256
python docs/implementation/verification/install_check.py
python tools/impl_ledger.py status; python tools/impl_ledger.py check
```

> ASR 说明：vosk 的原生加载器不能打开非 ASCII 路径，测试会把模型镜像到 `%TEMP%\skill-vosk-model`；
> 未安装模型时 ASR 用例记为 `skip`（不计为通过），本机已真实运行。

## 9. 审计项对照（P01–P20，逐条落到实现与测试）

| 审计项 | 实现 | 验证 |
|---|---|---|
| P01 容器父子与三种计数 | `source_units` 容器/成员/父原件；`summary` 输出 physical/logical/observations | `test_recovery_layer::TestSourceUnits` |
| P02 审计视图与合法空表 | `audit_view`（含 PDF 视图）、`empty_table_evidence`；`verify_dataset` v2 检查 | `test_recovery_layer::TestAuditView`、`test_design_v2` |
| P03 生成值来源性质 | `audit_view.VALUE_KINDS/OBLIGATIONS` + `verify_dataset.v2_cells` | `test_recovery_layer`、`test_design_v2` |
| P04 多输入与 N 闸门 | `models.validate_spec/conditions`、`designcheck.role_accounting`、`release` | `test_models_entities`、`test_design_v2` |
| P05 结果公共语义元数据 | `models._write_result`（target/unit/scale/sample_scope/interval） | `test_models_entities` |
| P06 状态与退出判据 | `contract_v2` 状态机、`release` 四态、`txn` 指针 | `test_contract_v2`、`test_lifecycle_release` |
| P07 事务/并发/恢复 | `txn`（staging→对象→指针）、`Lock`、`recover` | `test_research_core`、`test_hardening` |
| P08 后加图文节点接线 | `claims.link_dependencies`、`manuscript.register_media_dependencies` | `test_claims`、`test_refs_manuscript` |
| P09 校核先于稳定性 | `validation.stability` 要求 `val:<spec>:<param>=passed` | `test_models_entities` |
| P10 核心/集成依赖分开 | 各模块独立测试；组合验收在 M7 | 全部测试文件 |
| P11 每批前置期望 | 计划卡冻结于 13:41，测试实现于 14:20 之后；`order-check` | `test_acceptance_cards` |
| P12 可执行验收卡 | `tools/acceptance_cards.py` + 60 张卡 | `validate` 60/60、`order-check` 60/60 |
| P13 求解质量状态 | `models.SOLVE_QUALITIES`、证书字段 | `test_models_entities`、`test_e2e_projects` |
| P14 独立性的层次 | `validation` 的 layers/shared 与 `agrees_but_not_independent` | `test_models_entities` |
| P15 版本/特性/规范化 | `contract_v2` schema、特性协商、canonical_json | `test_contract_v2` |
| P16 全文编辑后支持失效 | `claims.review_block`（块指纹 + 实印比对） | `test_claims`、`test_refs_manuscript` |
| P17 环境执行时点 | `lifecycle.snapshot/compare`（前后快照 + 外部输入哈希） | `test_lifecycle_release` |
| P18 规模与预算声明 | `faults.big_csv` 规模测试、`workflow_step.scope.budget` | `test_hardening`、`test_lifecycle_release` |
| P19 开放调度与恢复 | `lifecycle.plan/start/finish`、`txn.checkpoint_state` | `test_lifecycle_release`、`test_hardening` |
| P20 partial 不降标准 | `release` 硬闸门 + `partial` 不能绕过；`review_gate` | `test_lifecycle_release`、`test_discovery_review` |
