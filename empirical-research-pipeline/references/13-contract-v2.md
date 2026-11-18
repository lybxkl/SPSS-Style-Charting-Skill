# 13 · 契约账本层（研究证据台账）

当前维护流程与审计修正规则同时见 [references/14-reviewed-workflow.md](14-reviewed-workflow.md)，特别是签名、实际复读、版本绑定和正式发布；旧实现记录不能代替当前执行证据。

本文件描述归档档深度核验链的契约账本层（模块名沿用 `contract_v2` 等历史命
名）：它把「资料恢复 → 发现/回查 → 逐格复核 → 模型/校核 → 论断/版面 → 发
布」的每一个中间结论都落成带内容哈希、带状态机、带来源绑定的记录。这是单一
流水线的一部分，不是第二条链：统计与成稿始终用主链引擎
（`auto_stats.py` / `assemble_manuscript.py` / `export_pdf_hires.py`），
本层补主链没有的数据面（OCR/ASR/表格恢复/来源单元）、多输入模型登记与
发布事务。explore/可投稿档不启用；归档档的深度检查依赖它产出的账本。
没有 v1→v2 迁移路径：账本要么按当前契约建立，要么不存在。

启用方式：给项目建一个 `output/v2/`（`Project(root)` 会自动建），然后按下面的
顺序调用。模块位于 `scripts/`；有 CLI 的模块用 `python <module>.py --help` 查看参数，其余通过 Python API 调用。下面是 Bash 命令示意，含占位值的行需要按实际项目填写，不是自动批量确认流程。

## 1. 为什么要这一层

主链的问题是「结论无法溯源到证据形态」：一个 `verified` 只说明某个人说见过，
不说明他见过的是原件、OCR 转写还是模型输出；一个 `N` 只说明某张表有多少行，
不说明这些行是不是独立观测。账本层把这些问题拆成互不替代的记录：

| 问题 | 记录 | 谁写 |
| --- | --- | --- |
| 这份资料到底是什么形态、恢复到什么程度 | `source_unit` / `container` / `recovery_receipt` | `source_units.py`、`ocr_provider.py`、`asr_provider.py` |
| 某个结构有没有被看过、有没有被丢掉 | `structure_coverage` | `discovery.py` |
| 发现了哪些字段/数据集/实体候选 | `discovery_candidate` | `discovery.py` |
| 「没找到」是不是真的找过 | `search_index` / `search_run` | `search_index.py` |
| 缺的数据最终怎么处理 | `data_gap` | `gaps.py` |
| 每一格是不是回到原件复读过 | `review_event` / `review_patch` / `cell_evidence` | `review_workbench.py`、`verify_dataset.py` |
| 跨资料的同一个人/机构/口径 | `entity` / `relation` / `join_audit` | `entities.py` |
| 模型候选、四态、按角色的多输入 | `model_spec` / `model_result` | `models.py` |
| 数字有没有第二种独立算法 | `validation_result` | `validation.py` |
| 结论、成稿、图、版面 | `claim` / `manuscript_block` / `figure_spec` / `layout_check` | `claims.py`、`layout_check.py` |
| 依赖、事务、缓存、环境、发布 | `dependency_*` / `workflow_step` / `cache_entry` / `environment_snapshot` / `release_snapshot` | `depgraph.py`、`txn.py`、`lifecycle.py`、`release.py` |

## 2. 记录信封与状态机

`contract_v2.make_record(kind, id, payload, producer, status, revision, input_refs,
requires_features, ...)` 生成：

```
kind, id, revision, status, data, producer{program, version, code_sha256, ...},
created_at, input_refs[], requires_features[], content_hash
```

- `make_record` 的 payload 参数存入信封的 `data` 字段；`content_hash` 覆盖内容身份，完整审阅签名使用 `signature`，账本另有信封校验；`validate_record` 会重算，
  改一个字节就 `IntegrityError`。
- 状态只能沿 `TRANSITIONS[kind]` 前进；`cell_evidence.prepared → verified` 是
  **非法**跳转，必须经过 `review_pending`。旧状态到新状态不合法时 `append` 直接拒绝。
- 每条记录声明自己需要的 `requires_features`；旧读者没有该特性时 `negotiate`
  **拒绝**而不是降级。
- `Project.append` 每行 fsync；`Project.latest(id)` 取同一 id 的最高 revision。

`python contract_v2.py --dump-schema` 打印全部 kind 的必填/可选字段，这就是
权威 schema；本文件不重复字段清单，避免两份定义漂移。

## 3. 一条完整的账本流程

```bash
SCRIPTS=empirical-research-pipeline/scripts

# 0) 事务：先开 staging，所有产物写在这里，成功才发布
python "$SCRIPTS/txn.py" --root . status

# 1) 资料恢复：物理文件 / 逻辑单元 / 独立观察 三个数分开
python "$SCRIPTS/source_units.py" --root . build --materials materials
python "$SCRIPTS/source_units.py" --root . summary

# 2) 扫描页 OCR（真实引擎；没有引擎会写 engine_missing 回执，不会假装成功）
python "$SCRIPTS/ocr_provider.py" --root . page --unit <unit_id> --dpi 300
# 复核：必须回到原图重读，adjudicate 会把 OCR 转写降级为「转写记录」
python "$SCRIPTS/ocr_provider.py" --root . adjudicate --unit <region_id> --text "实际回读内容" --reviewer agent:reread --note "实际原图定位及核对说明"

# 3) 音视频 ASR（真实引擎；片段可回放）
python "$SCRIPTS/asr_provider.py" --root . transcribe --unit <media_unit>
python "$SCRIPTS/asr_provider.py" --root . replay --unit <segment_id> --out clip.wav

# 4) 表格结构：跨页续表、重复表头、合并单元格、公式缓存
python "$SCRIPTS/table_recovery.py" --root . pdf --path materials/table.pdf

# 5) 原生数据 → 审计视图，并与原始 XML/JSON 独立对账
python "$SCRIPTS/audit_view.py" --root . build --path materials/book.xlsx
python "$SCRIPTS/audit_view.py" --root . verify --view output/v2/views/<x>.csv

# 6) 发现（材料优先 + 问题优先）与结构覆盖
python "$SCRIPTS/discovery.py" --root . run --questions questions.json
python "$SCRIPTS/discovery.py" --root . report

# 7) 检索：先建索引；索引过期时拒绝回答「没有」
python "$SCRIPTS/search_index.py" --root . build
python "$SCRIPTS/search_index.py" --root . search --query "随访" --limit 20

# 8) 缺数闭环
python "$SCRIPTS/gaps.py" --root . open --target model:M1 --requirement "随访时间"
python "$SCRIPTS/gaps.py" --root . attach --gap <id> --run <run_id> --conclusion not_found --note "..."
python "$SCRIPTS/gaps.py" --root . check

# 9) 逐格复核：离线页面 + 盲第二次抽取 + 冲突 + 补丁
python "$SCRIPTS/review_workbench.py" --root . export --dataset person
python "$SCRIPTS/review_workbench.py" --root . blind --dataset person
python "$SCRIPTS/review_workbench.py" --root . import --dataset person --file second_pass.jsonl
python "$SCRIPTS/review_workbench.py" --root . patch --dataset person --key P01 --column age --value 43 --parent <sha> --reason "..."

# 10) 实体、关系、跨表合并与单位统一
python "$SCRIPTS/entities.py" --root . entity --type firm --key A-001 --name "甲公司"
python "$SCRIPTS/entities.py" --root . join --left data/a.csv --right data/b.csv --on id --unit "一家企业"

# 11) 模型：注册 → 条件 → 拟合/求解 → 独立数值校核 → 规格稳定性
python "$SCRIPTS/models.py" --root . register --spec specs/M1.json
python "$SCRIPTS/models.py" --root . conditions --spec M1
python "$SCRIPTS/models.py" --root . fit --spec M1
python "$SCRIPTS/validation.py" --root . ols --spec M1
python "$SCRIPTS/validation.py" --root . stability --spec M1

# 12) 论断：登记、语义核查、成稿块指纹、失效传播
python "$SCRIPTS/claims.py" --root . check --claim <id>
python "$SCRIPTS/claims.py" --root . propagate --changed M1

# 13) 版面：最终 DOCX/PDF 的实际安置尺寸
python "$SCRIPTS/layout_check.py" --root . check --docx out/final.docx --pdf out/final.pdf --figure fig1.png=fig1

# 14) 环境、缓存、步骤
python "$SCRIPTS/lifecycle.py" --root . env --snapshot --name run1 --rules rules
python "$SCRIPTS/lifecycle.py" --root . env --compare --name run1
python "$SCRIPTS/lifecycle.py" --root . next

# 15) 发布：四态快照
python "$SCRIPTS/release.py" --root . build --scope scope.json
```

## 4. 各模块的硬性拒绝（这些是设计，不是缺陷）

- `source_units`：扫描页只标 `partial` 并写 `unrecovered`；`.doc/.xls/.ppt` 不
  假装能读，写 `unsupported_format` 回执；zip/Office 成员单独成单元，不重复计入
  独立观察。
- `ocr_provider` / `asr_provider`：转写永远 `partial`，`unrecovered` 明写
  「转写不是核实读数」；复核只能由人/Agent 回原件后 `adjudicate`。
- `search_index`：索引过期时 `search` 直接失败（`SystemExit`），除非 `--rebuild`。
- `gaps`：`resolve` 必须有 `found` 的检索；`unavailable` 至少一次检索；`exhausted`
  必须覆盖全部来源且哈希一致。
- `review_workbench`：盲模板不含第一遍的值；通用备注（"ok"）、快照之前的时间戳、
  签名不匹配、缺复核定位、缺审阅人，一律拒绝；补丁父版本不匹配即 `conflict`，
  应用后旧复核作废。
- `models.validate_spec`：统计模型必须声明 `n_semantics.kind=observation` 与观测
  单位；数学模型必须 `kind=none` 且给维度/约束，**不许编 N**。
- `validation`：明确记录共享层。数值确实一致但共享预处理时标 `agrees_but_not_independent`；不一致仍是 failed。独立校核逐字段生效，系数与 N 通过不证明标准误、区间、p 值或预测已经通过。
- `validation.stability`：没有通过的独立校核就不许扩规格（T22 先于 T21）。
- `release`：空 scope、缺证据、有未完成的硬闸门，都不会返回 `complete`；
  `limited` 需要显式 `allow_limited` 且硬闸门全过。

## 5. 与主链的关系

- 逐格复核的**唯一真相**仍是 `verify_dataset.py` 的 prepare/final 与 `review`
  文件；`review_workbench.import_second_pass` 产出的就是它要吃的主链 review 行，
  同时额外写 `review_event` 供审计。
- `release.py` 读取 `output/dataset/dataset_verification.json` 与
  `output/verify/number_issues.csv`，不会另造一套「已验证」。
- 模型结果在主链 `model_plan.jsonl` 与账本 `model_spec` 中各有一份时，两份都必须
  终态；账本侧负责多输入、无样本 N、求解质量和独立校核。
- **内部支撑模块**（被上述 CLI 与工作台门禁框架导入，不单独调用，无独立入口）：
  `evidence.py`（证据信封与 locator）、`execution.py`（执行回执：输入/代码/输出
  SHA256+退出码）、`support_review.py`（论断复核绑定）、`workflow_contract.py`
  （workflow.json 的 schema 校验）、`gate_facts.py`/`gate_checks.py`/
  `gate_claims.py`/`gate_lock.py`/`gate_roots.py`（工作台门禁框架的事实聚合、
  版面实测、论断语义、台账锁与项目根解析，消费方见 references/15）。

## 6. 第二轮补充（T13/T20/T23/T27/T28/T29/T30/T33/T34/T39）

- **verify_dataset 的账本检查**（`--stage prepare/final` 自动启用，条件是
  `output/v2/source_unit.jsonl` 存在）：值类型义务（`estimated/imputed/simulated/
  image_approx` 必须带 method/uncertainty/inputs 或 sources）、证据单元必须同版本、
  `partial` 单元只能支撑 `image_approx` 且需记录回读、0 行数据集必须有
  `audit_view` 范围证据（window/denominator/source hash/re-read），
  `review_event` 必须签名有效、归属当前格、时间晚于快照、独立性可解释。
  报告多出 `contract_v2` 段。项目没有账本时该段检查不存在（归档档应当有）。
- **`designcheck.py`**：`infer` 推断设计特征，`link` 检查结果是否报告了该设计
  要求的诊断，`roles` 按角色与观测单位核算 N 并检测 fit/test 泄漏与重复测量
  （行数≠独立单位）。`record_linkage` 写 `validation_result(target.kind=
  design_linkage)`；缺诊断即 `failed`。
- **`refs.py`**：`add/verify/access/support/check`。访问层级只有
  `full_text/abstract/metadata/unavailable`；`full_text` 需要实际取得的文本；短文本需解释真实范围，全文含参考文献不应被误判成未读。存储文本要求严格 UTF-8；其他编码先明确无损转换并保留原件绑定。摘要层不能支撑 `full_text` 的论断；引文必须
  在存储文本中 verbatim 出现。DOI 元数据可来自 Crossref 或本地记录，核验失败
  不会升级访问层级。
- **`manuscript.py`**：不排版。DOCX 只由 `assemble_manuscript.py` 生成、PDF 只由 `export_pdf_hires.py` 导出，本模块做印后核验。每个 `{number}` 必须同时有值和 trace
  （model/result/parameter/unit 或 dataset cell/aggregate 或 checked
  reference），否则拒绝；`{占位符}` 语法**总是**被解析——numbers 表为空时块文本
  里的占位符同样报错，字面花括号不是受支持的转义。`sections` 报告账本章节与
  字数，`--required` 声明的章节缺失或账本有 `stale` 块时 exit 2；`verify` 用回读
  的实印文本与**已代入数字**的审核文本做去空白包含比对，不一致把块置
  `stale`，PDF 侧同样做包含检查；表格逐行与数据源对账，不许丢格或造格。
  CLI `verify`（persist 语义）会把核验结果写进 `output/v2/manuscript/verification.json`
  快照；`release.evaluate` 以 persist=False 只读调用，不落盘。包含比对的诚实边界：
  去空白后无法区分「1 2」与「12」（数字精度另由 `resolve_trace` 的 1e-12 比对
  把关），且账本之外的多印文本不在本检查视野内——版面由 `layout_check` 与
  人工核对兜底。
- **`release.py` 的成稿 scope**：`docx`/`pdf` 是项目相对路径的真实产物；
  `numbers`/`trace` 是印出数字与证据 trace；`figure_specs`/`table_specs` 是印后
  核验用的题注/表格规格（`figures` 仍是 figure_spec 的 id 列表）。省略
  `numbers`/`trace` 时核验的数字为 0，**不会**把缺失的 number-trace 报告升级成
  「已验证」——只记 warning，`numbers_traceable` 保持失败。
- **`figsemantics.py`**：`describe_axes/check_figure` 从真实 artist 读柱高、误差
  棒、散点、折线、图例并与数据对账；`label_geometry` 用旋转矩形 SAT 测 60 类
  密集标签的真实重叠；`layout_options` 只给 rotate/expand/widen/subplot 且
  `deletes_labels=False`；`palette_report` 只给 suggestion（`mandatory=False`），
  不参与 `ok`；位图/PDF 判不了的项进 `unverifiable`。
- **`faults.py` + 硬化测试**：`disk_full` 真的写半截再抛 ENOSPC、`crash_at` 在
  子进程里杀自己、`big_csv` 流式造 200k 行、`kill_process` 强杀。据此修了
  `txn` 的发布顺序（先回执后指针）、账本正常读取拒绝撕裂/损坏行、
  `checkpoint_state` 校验 status、`recover` 优先指针所指 commit、缓存
  `is_valid` 与 status 一致。
- **`tools/acceptance_cards.py`**：`validate` 要求 passed 卡带 fixture/steps/
  observed/environment/evidence（存在）/两个时间戳，且期望早于实现；
  `order-check` 另查 `expectation_sha256` 未被事后改写；`batch-gate` 按批次表
  检查前置批；`render` 生成 `docs/implementation/ACCEPTANCE-CARDS.md`。

## 7. 已知边界（如实）

- `release.py` 是账本层的发布消费端；`research_gate.py`（主链门）未改写，
  发布端复用主链的来源/模型检查与当前 final，成稿核验消费 `assemble_manuscript.py`
  产出的真实 DOCX/PDF（scope 声明 `docx`/`pdf`/`numbers`/`trace`/`figure_specs`/
  `table_specs`，键语义见 §6），不要求用另一张状态 JSON 替代它。另一处如实边界：
  release 的 `failed` 状态目前只对含 tamper/contradict 字样的错误点火，docstring
  列举的 untraceable number/stale review 实际落 `not_ready`（同样拦发布，状态名
  不同）——预存在行为，收敛时未改动。
- `refs.py` 的 DOI 查询依赖网络且只取 Crossref 元数据，不能证明原文支持某句；
  真正的支持必须靠 `support` 的 verbatim 引文与人工阅读。
- `manuscript.py` 不生成研究叙事、也不排版：章节内容由 Agent 写进 `manuscript_block`（与 `assemble_manuscript.py` 的 spec 正文一致），排版归主链成稿器；`verify` 的包含比对验的就是「印出的就是审核过的」。章节/最低字数默认不固定，额外附录完整保留。正文、表格与图注须有真实溯源及实印核对。
- `figsemantics` 对位图只能核尺寸/像素，图元与标签几何判不了；
  `layout_check` 优先读取最终 PDF 的真实文字层；位图须有当前 `figure_spec` 的完整 live-artist 字体证据、交付 PNG 像素复现和 DOCX/PDF 实际匹配安置，才可换算字号。仅源 PDF 不够，没有这些证据仍是 `no_text_layer`，不放行。
- OCR/ASR 的引擎是本地可替换提供方（RapidOCR、Vosk）；没有引擎时记录
  `engine_missing`，不降级成「文本可用」。

## 8. 当前版本的消费约束

- `source_units` 的 materials.json 绑定活跃恢复代次与实现；历史记录保留但不计入当前覆盖。严格解码只自动识别 BOM/UTF-8，其他编码通过 `build --encodings encodings.json` 明确指定。表示文件按内容寻址，读取器同时验证原件和表示哈希。PPTX 原生文字、表格、备注可恢复；视觉内容仍须审阅。
- OCR/ASR 分块复读不能替代整页/整段覆盖。实际重开原件完成范围审查后，可调用 `SourceUnits.review_scope(id, report=实际报告路径, reviewer=身份, note=具体说明, remaining=仍未解决范围列表)`。报告须记录恢复子单元、剩余区域及不相关内容的理由；只有实际解决时才填空列表。此操作不代替数据集整合后的逐格第二遍复核。包含资料有未恢复范围、缺当前单元或报告被改动，会阻止完整交付。
- 原生模型可选 `conditions_runner="file.py:function"` 实际检验条件；CSV/TSV 内置入口保留身份字符串。外部命令声明全部实现文件及额外依赖包，日志保留原始字节，JSON 重复键、NaN/Infinity 不接受。
- 记录 `ready` 只表示规格已配置；`conditions`、执行、独立数值校核、方法评估、正式发布分别检验。原始 beta 不能只改标签冒充 OR/IRR；所选适配器必须实际执行变换。模型族仍开放。
- `validation.is_current(..., field=...)` 按已核字段判断。任意带点/斜线的参数名使用 RFC 6901 JSON Pointer，例如 `/coefficients/x.dot/estimate`；常用点路径继续兼容。独立统计校核必须覆盖实际 N。多重比较需要相关 p 值确已独立核对；完整保留未核项。
- `release.evaluate` 是只读评估，自动追踪正文/论断/图到模型与数据，前后核对全部依据。`release show` 返回当前再评估结果；历史 complete 不等于当前 ready。重新拟合/更新依据后须重建发布，不能只更新时间戳。
- `scope.deliverable_type="full_research"` 要求完整研究范围、实际 DOCX/PDF 和 `analysis_report` 文件；只有此范围全部通过才有 `project_ready=true`。数据、模型或图的阶段 complete 保留其实际范围。
- 新必需能力包括 `active-source-generation`、`source-representation-binding`、`cache-runtime-binding`、`validation-field-coverage` 和 `release-current-closure`。不理解这些语义的旧读者必须拒绝，不能把新回执降成旧版 passed。
