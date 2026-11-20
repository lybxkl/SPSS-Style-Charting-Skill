---
name: empirical-research-pipeline
description: 从混合研究资料中尽可能完整地发现、整合任意数量和形态的数据集，由 Agent 自选数学/统计模型与实现，回原材料补齐模型所需数据，按验收档产出论文级图集、分析报告和完整论文式 DOCX/PDF。可投稿档做抽样复核、注册表、模型、数字与图表；逐格回源只在归档档。适用于资料整理、编码抽取、问卷/访谈/实证分析、统计建模制图、论文组稿及追加材料。
---

# 实证研究数据流水线

在 DSH 中使用且工具表里看得到 `data_analysis_status` 和 `data_analysis_start` 时：用户明确调用本技能或要求开始研究后，先用可见文字说明正在启动，并调用 `data_analysis_start`。启动后以每一回合的任务卡为唯一规程，只做卡上的下一步。完整工作流要用 `data_analysis_workflow(action="describe", full=true)` 才返回。未关联时不要静默改走手工 Python。启动失败应立即说明具体原因；已有成果只作待验证输入，不能冒充本次执行。工具表里没有这两个名字时，当前宿主没有挂上工作台，不要反复寻找它们；按本文件后面的命令行流程做，并在范围说明里写明交付方式。

在 DSH 中工具表里看得到 `data_analysis_workspace`（实证研究查看器的只读绑定工具）时：**确定产物目录后立即调用它绑定本会话**（默认 `<cwd>/research`，或你实际使用的产物根目录），让用户在查看器里实时看到产出；**禁止**要求用户手动新建工作区或手动绑定目录。该工具只登记"会话↔目录"、不写目录、不跑脚本，绑定不改变研究流程与验收档；同一目录重复绑定会复用已有工作区，不会重复新建。产物目录中途变更时重新绑定一次。看不到该工具时跳过本条，不影响命令行流程。

工作台的阶段、顺序、依赖、命令、条件步骤、检查点、工具动作、任务说明和重跑范围由本技能的 [workflow.json](contracts/workflow/workflow.json) 唯一声明，结构契约见 [workflow.schema.json](contracts/workflow/workflow.schema.json)。修改研究流程时维护这份声明并重新构建发布清单，插件按当前契约读取；不要另在插件中维护一份阶段表。

验收档写在项目里，默认是可投稿（submission）。explore 只核审计和数据集骨架；submission 增加文件级来源处置、模型登记、数字回溯、图表和文稿；archive 才要求逐格全覆盖。低于当前档的判据标为不适用。降低档位要由用户自己改 `.workbench/acceptance.json`，不要调用工具把降档说成已经确认。有工作台时，下面的阶段图只供对照，不代替任务卡。

工作台门禁报告的入口、覆盖范围、迁移与恢复见 [门禁报告与兼容状态](references/15-gate-reports.md)。技能是研究质量判定的唯一实现来源，工作台保留挂载、工作流与真实裁定。报告只证明实际检查过的事实；缺失或失效证据保持未判。校验器读错原文时用 `data_analysis_dispute_gate` 登记争议，争议不把判据改成通过，也不再当作下一步。

自定义脚本、任意引擎、项目覆盖和兼容模式均可使用，**但下列契约在任何模式下一律不可省略：阶段 1 审计产物、范围符合性核对、命名源（figure_map/manuscript/table_map/doc_map）、目录骨架与全量命名覆盖、数字溯源**。选用兼容/对照模式时说明原因和实际验收范围，模式迁移成功不等于研究质量通过。自定义产物不必迁回默认目录：在 `research_registry.json.artifact_paths` 声明“默认逻辑路径 → 实际项目相对路径”，例如 `{"output/chart_pack/chart_manifest.csv":"output/figures/chart_manifest.csv","output/models":"output/analysis_pack","output/qa/qa_report.json":"output/qa"}`。`output/` 一级目录由 `layout_conformance.py` 归入规范骨架（审计/编码/数据/统计/图/表/文档/质检/溯源/台账/挖掘）：已知别名目录（analysis_pack、chart_pack、models、methods、reports、review 等）自动归组；自定义目录必须在 `research_registry.json.layout` 声明“规范组 → 物理目录”，否则交付时判杂散目录；表/文档组内的交付件必须都有中文标题来源。审计清单和生成文件放在产物目录，保留原材料扫描范围；材料通过已登记挂载读取。

## 计划模式与目标模式（宿主支持时强制，不可跳）

本流水线是长任务、多阶段、强闸门，**禁止无计划、无目标跟踪地裸奔**。宿主提供什么能力，就必须用什么能力，没有讨价还价余地：

- **计划模式**：工具表/宿主能力里看得到计划模式（如 `EnterPlanMode`/`ExitPlanMode` 或等价 plan 能力）时，**开工前必须进入计划模式**：先只读初读资料，把覆盖阶段 0–7 的执行计划写成计划文档——研究问题与验收档、产物目录、各阶段闸门命令、双遍审计安排、风险与回查预案——并经 `ExitPlanMode` 提交用户批准。**未获批准禁止执行任何阶段脚本**（计划模式内的只读初读除外）。只写"先审计再统计"这类口号不算计划；"用户已调用本 skill"**不等于**批准计划。执行中范围、资料形态或验收档发生变化，**必须**回计划模式修订并重新批准，**禁止**静默改道。
- **目标模式**：看得到目标工具（如 `CreateGoal`/`GetGoal`/`UpdateGoal` 或 `/goal`）时，接到研究任务**必须立即创建总目标**，objective 写清交付范围、验收档与终点产物；已有未完成目标就复用，**禁止**重复创建。阶段推进与受阻时核对目标状态；**只有全部硬闸门退出码 0、交付物齐备、终检通过后才允许标 complete**——闸门未过、产物缺失、审计未做就标 complete，视为伪造通过。确实受阻（缺材料/缺权限/环境故障）按宿主规则标 blocked 并向用户说明具体缺口，**禁止**既不推进也不标 blocked 地把目标挂死。
- **降级不豁免**：宿主没有这两类能力，或用户明确说"直接做、不用问"时，改为在对话里给出同等详细的书面计划再开工，并用任务清单（`TaskCreate`/`TaskUpdate` 或等价）逐阶段跟踪，完成判据与上面完全相同；在范围说明里写明降级原因。**禁止**以"宿主不支持"为由连书面计划和阶段跟踪都不做。
- 有工作台时，任务卡仍是唯一执行规程；计划与目标管开工对齐与全程跟踪，不替代任务卡，也不降低任何闸门。**查看器绑定不受计划批准闸门限制**：`data_analysis_workspace` 是只读登记、不是阶段脚本，确定产物目录后仍按硬规则 8 立即绑定；宿主计划模式不允许该调用时，批准后第一时间补绑，**禁止**拖到交付前或留给用户手动绑定。

## 手工模式硬闸门（无工作台时同样强制，不可跳）

没有工作台**不等于**没有闸门。下列检查在手工 CLI 模式**必须实际执行并通过**——可运行的检查退出码必须 0，产物类的检查（命名源/审计产物）必须实际存在且可解析——才能进入下一步；"已有成果""自定义脚本""材料太杂""时间不够"**都不是**跳过理由。未执行、退出码非 0 或产物缺失，即视为该阶段未完成：**禁止**进入下一阶段，**禁止**交付。

1. **审计先行**：先跑 `audit_corpus.py` 产出 `corpus_files.csv` + `sample_flow.csv` 并逐档对账。**在此之前禁止任何统计、建模、出图**。自写解析器只产一份 diagnostics.json **不算**完成审计。
2. **范围符合性**：每个数据集声明 `scope.json` 纳入白名单并跑 `scope_conformance.py`，退出码 0 才能进统计。范围外命名类别**必须**排除，或显式修订白名单并记录理由；**不得**静默留在分析样本。
3. **命名源齐备**：交付**必须**含 `figure_map.json` + `manuscript.json` + `table_map.json` + `doc_map.json`（无论通用组装器还是自编写稿脚本）；后两者覆盖全部交付表/文档，不只是正文引用的。
4. **终检**：`qa_outputs.py` 带 `--audit --figure-map --manuscript-spec --table-map --doc-map --min-fontsize 7.2`，退出码 0 才能交付。**禁止**用 `--exit-zero` / `--allow-empty` 把失败伪装成通过。
5. **阶段双遍审计**：每个阶段完成后必须做≥2遍、角度互异的全方位审计并记入 `output/qa/stage_audit.jsonl`，`stage_audit.py` 退出码 0 才能进下一阶段（见下节）。
6. **目录骨架与命名覆盖**：`layout_conformance.py` 退出码 0——无未声明杂散目录、别名目录不得改挂、表/文档组内交付件均有中文标题来源；分组结果 `output/qa/layout_conformance.json` 供查看器渲染规范目录。「目录是脚本默认写出的」「表不在正文里引用」「查看器能显示英文就行」「时间不够」**都不是**跳过理由；交付表/文档一律放表组/文档组目录，不得借其他组目录逃避覆盖；**禁止**用 `--exit-zero` 把失败伪装成通过。

每道闸门把**实际命令与退出码**写进交付说明；只写"已检查"而不给退出码，视为未检查。

## 阶段完成后双遍多角度审计（每阶段强制，≥2 遍）

每个阶段（范围/审计/编码/数据集/统计/图表/文稿/终检）执行完成后，**必须**做至少 2 遍、**角度互不相同**的全方位审计，把每遍记入 `output/qa/stage_audit.jsonl`（一行一遍：`stage/angle/evidence/findings`），并跑 `python scripts/stage_audit.py --ledger output/qa/stage_audit.jsonl --require <本阶段>` 退出码 0，**才能进入下一阶段**。一遍都不许少，两遍不许同角度。

- **第 1 遍·机器/口径**：跑本阶段相关校验脚本（审计对账、`report_tables`、`scope_conformance`、`layout_conformance`、模型诊断、`verify_numbers`、`qa_outputs` 等），核对数字、N、口径、范围、命名源与目录骨架；`evidence` 记命令+退出码。
- **第 2 遍·独立/语义/漂移**：换一条独立路径复核——回原材料抽样重读（submission 按声明抽样、archive 逐格）、对照 `scope.md` 研究问题检查是否跑偏、检查有无遗漏字段/单位/子样本、图与文方向是否一致；`evidence` 记抽样 `rel_path` 与检查项。
- 两遍发现的任何问题**必须**修复后重审；`findings` 里 `resolved=false` 的条目会被 `stage_audit.py` 判 error。
- 深度随验收档（submission 抽样、archive 逐格），**但"遍数≥2、角度互异、留台账"三条任何档都不豁免**。

这不是"跑两遍同一脚本"凑数：两遍必须方法/视角不同，第二遍必须独立于第一遍的产出重新取证，专门抓第一遍漏掉的细节和偏离研究问题的跑偏。

归档档才使用逐格复算适配器。可在注册表 `verification.adapters` 声明名称与脚本，供 CLI 与工作台共享，例如 `{"envcell":"scripts/envcell_adapter.py"}`。解析器重放可登记 `method=parser_replay`，如实说明它能核一致性、不能独立证明语义；`independent_reextract` 只描述实际独立实施的检查。适配器自动绑定已导入的本项目代码，其他依赖可在适配器的 `verification_dependencies` 列出。归档档里注册表、codebook、解析器或数据在 final 后改变时，重新 prepare/final。最终答复同时列出当前通过、未通过和未评估项。可投稿档不要为了这些句子去跑 prepare/final。

把“一堆杂乱资料”变成“可复核的样本流程 + 可追溯的编码/字段数据 + 可复现的模型 + 可投稿的图表与文稿”。本 skill 不限定学科、语言或文件格式；法律裁判文书只是“文本编码”的一个示例，问卷、访谈、新闻、政策文件、实验记录、开放数据、网页和数据库导出同样适用。

运行环境：Python 3.9+；门禁协议需 jsonschema 4.x；PDF 需 PyMuPDF；表格/统计需 pandas、numpy、scipy、statsmodels；图表需 matplotlib；Excel 建议 openpyxl；Word→PDF 需 Windows + Microsoft Word + pywin32；SPSS 语法由 SPSS 打开运行。其他模型可由 Agent 选择相应语言与引擎。

本仓库/包内的示例数字、文件名、路径与变量值均为虚构占位，不含任何真实资料、编码数据、SPSS 数据或论文成稿。

## 核心目标与自由度

**尽可能完整地开发现有资料的研究价值，同时让每一个数据值都能重新回到原始资料核对。** 数据集数、数据形态、处理脚本、引擎、模型族、规格数、图数及正文/附录篇幅均不预设。用户后补的数据集形式与资料继续纳入，不替代已经发现的有用数据。

Agent 负责发现单位/字段/关联键，自选或编写工具，广泛提出所有有合理数据联系的数学与统计模型；内置的十八个方法编号和自动图包只是可复用工具。每个候选逐一检查变量、有效样本、事件/配对/时点、设计/识别及假设；不足时必须回原材料、表格、脚注和附件继续补取，发现新单位则追加数据集。能取得就补齐并重新复核；确实不能取得才留缺失与完整回查记录，保留不可估计/不适用/失败项目供用户查看。不得靠虚构值、编造时间或对照组让模型成立。自写解析器先放在项目的 `draft/`，锁定后再由工作台采纳为阶段命令。

验收档为 archive 时阅读 [references/12-exhaustive-research.md](references/12-exhaustive-research.md) 和 [references/14-reviewed-workflow.md](references/14-reviewed-workflow.md)：开放数据集注册表、全资料覆盖、逐格证据、整合后的第二遍复读都在那里。submission 使用事先写明的抽样复读、全量解析器重放和残余误差样本，不把 14 万格逐格第二遍当作默认门槛。统计与图表的数字一致，不等于原始数据正确。

当前契约账本层在 archive 档使用上述维护流程：严格恢复解码、活跃来源代次、逐单元范围复读、按字段的独立校核，以及自动追踪依赖的只读发布检查。系数通过不代表标准误/区间/p 值已核；阶段 complete 不代表全研究 ready。完整交付范围须声明 `full_research` 并包含实际分析报告与 DOCX/PDF；`release show` 检查当前版本，旧发布状态不能沿用。

## 何时使用

- 用户给了一个文件夹，里面混有 PDF、Word、Excel、CSV、文本、网页、访谈稿、图片或扫描件，要求整理、编码、统计、出图或写成论文。
- 已有 CSV/SPSS 数据，需要清洗、合并、追加新资料、修正样本口径或重跑模型。
- 问卷、访谈、实验、观察、公开数据等需要描述统计、组间比较、回归、异质性、稳健性或预测评估。
- 需要把实证部分做成 Word/PDF，且图、表、正文数字必须一致。
- 用户说“类似资料还要再做一遍”，希望复用同一套流程。

## 资料类型与处理边界

| 资料 | 原生处理 | 说明 |
|---|---|---|
| PDF | 文字层、页数、字符数、图片数、加密状态 | 扫描件先 OCR；图片型 PDF 会被标记 `image_only` |
| DOCX / ODT / PPTX | 段落、表格、幻灯片文字 | `.doc/.ppt` 旧格式先转换 |
| XLSX / XLSM | 工作表、单元格文本；只读打开 | `.xls` 先转换；建议安装 `openpyxl` |
| CSV / TSV / JSON / JSONL | 字段、行数、编码、缺失；表格数据质量审计 | 编码工作表会跳过表格，直接走 `auto_stats` |
| TXT / MD / HTML / XML / YAML / RTF | 纯文本抽取；HTML 去标签 | 网页正文可用，脚本/样式会被去掉 |
| 图片（PNG/JPG/TIFF 等） | 文件清单；尺寸/页数；契约账本层可调用 RapidOCR | 需要实际安装 OCR 引擎；转写未核，必须回原图核对 |
| 音频/视频 | 文件清单；契约账本层可调用 Vosk、ffmpeg | 需要实际引擎与语言模型；保留时间定位、未听范围和说话人争议 |
| 压缩包 | 主链文件清单；契约账本层逐成员登记与安全提取 | 保留父原件、成员序号和哈希；成员数不是观察数，未知格式继续处置 |
| 未知/专有格式 | 文件清单 | 先转换或导出为上述格式 |

“任何资料”不等于“任何二进制都能直接解析”。本 skill 会先把所有文件纳入审计和样本对账；不能直接读的格式会明确标记并给出转换路径，不会静默漏掉。

## 硬规则

归档档的深度核验任务才读取 [references/14-reviewed-workflow.md](references/14-reviewed-workflow.md)。它规定该档的复核签名、搜索范围、执行绑定、独立校核、语境复读和发布行为；不能用台账里的 `verified/passed` 字样代替这些实际检查。可投稿档不要打开这份文档来补做全格复核。

1. **先审计，再编码/建模。** 没弄清文件数、可读文本数、重复数、字段缺失和排除原因之前，不要开始统计。没有工作台时同样必须先跑 `audit_corpus.py`（或等价产出 `corpus_files.csv` + `sample_flow.csv` 并逐档对账）；自写解析器只产一份 diagnostics.json 不等于完成阶段 1 审计，也不能据此跳过审计直接建模。
2. **按内容去重，不按文件名。** 同名不同文、同文不同名都很常见；至少用 MD5，再用标题/关键字段/正文抽样复核。
3. **每个数据集各有明确单位和主键。** 文书、个人、事件、个人-时期、题项、节点/边或其他形态按资料决定；新增形态就新增数据集和关联规则，禁止把不同单位混成无法对账的一张表。
4. **每个编码/抽取值要有证据。** 原文没有记载就记 `NA/未记载`，不要默认记 0；否定表述、他人建议、转述不能当作最终事实。
5. **描述样本 N ≠ 模型样本 N。** 每个模型单独报告 N 和筛选条件；正文、表、图、摘要必须用同一套口径。
6. **关联 ≠ 因果。** 写“关联/对应/更可能”，不写“导致/使得/证明有效”。
7. **按验收档复核，可投稿档不做全格回源。** explore 与 submission 的正式结果以注册表、抽样复核、模型回执、数字和图表为准。submission 把脚本抽出的语义值当作候选：写 `docs/decisions/coding-sample.md`，正文包含「抽样复核：」，记下抽查原文、脚本值是否一致和残留误差。archive 才要求主键、空值、标记、编码和派生值逐格回源，prepare 之后实际重读原材料再跑 final；这一档禁止用十行抽查、只看 flags、批量盖 verified 或旧复核代替全检。脚本不可能证明所有语义正确。可投稿档不要调用 `verify_dataset.py`、`verify_source` 或 `research_gate.py` 来换取统计或交付通过。
8. **查看器可用即自动绑定，不让用户动手。** 工具表见 `data_analysis_workspace` 就在确定产物目录后立即绑定本会话；禁止把"新建工作区/绑定目录"留给用户手动操作。绑定是只读登记，不影响流程。
9. **每阶段完成后双遍多角度审计。** 任何阶段做完必须≥2遍、角度互异的全方位审计并留 `stage_audit.jsonl` 台账，`stage_audit.py` 通过才能进下一阶段；防漏细节、防跑偏。遍数与角度互异任何验收档都不豁免。
10. **目录骨架与全量命名源。** `output/` 一级目录归入规范骨架，自定义目录在注册表 `layout` 声明，已知别名不得改挂；多轮编码等额外目录放规范组子目录（`output/coding/r1`），不建一级杂散目录；交付表/文档一律放表组/文档组并在 `table_map.json`/`doc_map.json` 登记中文标题，`layout_conformance.py` 通过才能交付，缺一项即视为该阶段未完成。
11. **宿主支持即走计划模式+目标模式。** 看得到计划/目标工具就必须用：开工前计划经用户批准再执行，任务开始即建目标，全部闸门通过才许标 complete；宿主不支持时书面计划+任务清单降级并在范围说明写明原因。禁止长流水线无计划、无目标跟踪地推进（见顶部「计划模式与目标模式」节）。

## 判断权：谁决定，谁举证

这个 skill 不把研究判断写成 if/else。代码负责**可验证的事实**，模型负责**语义与取舍**，作者负责**不可逆的决定**。

| 事项 | 谁决定 | 必须留下的证据 |
|---|---|---|
| 文件取舍、去重、异常件 | LLM | `decisions.jsonl` + 文件清单 |
| 变量定义、编码规则 | LLM | codebook + 正例/反例 + 双编码 |
| 缺失值处理 | LLM | 每字段策略 + `missing_by_source.csv` |
| 方法选择、参照组、稳健性 | LLM | `assumption_report` + 替代方案 |
| 图表取舍与叙事 | LLM | 图号 → 研究问题映射 |
| 数字、单位、格式、dpi、N | 脚本 | 可机器复算 |
| 删除、覆盖、外发、定稿 | 作者 | 明确同意 |

**代码越权的三种表现**（本项目已修）：用正则猜语义、用阈值替研究者拒绝方法、用 `skip` 代替诊断。遇到这类情况，脚本应输出 `candidates` / `diagnostics`，把判断交回模型，而不是替它下结论。

### 模型工作准则

1. **先读后写**：初读代表资料探索形态、字段位置、歧义与缺失写法，写 `corpus_memo.md`/`discovery_report.md`；试读数量不限制最终覆盖，最终逐份完成发现与处置。
2. **先定义后测量**：codebook 每个变量都要有 operational definition、正例、反例、缺失规则；先在小样本试编码，再全量。
3. **先诊断后建模**：每个模型前看 `assumption_report` / `missing_by_source.csv`；写清“如果假设不成立，结论会怎么变”。
4. **先自审后交付**：跑 `review_pack.py`，回答“审稿人最可能先问的五个问题”；答不上就补分析或降结论。
5. **不确定性显式化**：`confidence`、`ambiguity`、`needs_human` 写进 `decisions.jsonl`，不要只留在聊天里。
6. **广泛候选、逐项补数**：每个数据集都进入开放模型清单；不能因包里没有某模型就停止。未满足的数据条件触发原材料回查和重整合，记录实际搜索与结果；探索结果、失败、不显著和不适用项目均保留。广泛尝试时报告多重比较与预测泄漏控制。

### 判断台账 `decisions.jsonl`

一行一个判断。字段：`id, stage, target, decision, value, reason, evidence, quote, confidence, alternatives, needs_human, supersedes`。

- `target`：`<rel_path>#<field>`（抽取）、`model:<id>`（模型）、`table:<n>`（表）、`figure:<n>`（图）。
- `evidence`：`<path>@<start>-<end>`、`<path>` 或 `<path>::<locator>`；`quote` 必须与 span 对得上。
- `decision`：`value` / `na` / `exclude` / `keep` / `method` / `skip` / `accept` / `reject` / `note`。
- 同一 target 只能有一条；改判用 `supersedes`，不要追加第二条。
- `needs_human=true` 会在交付闸门报错，直到作者拍板或显式 `--allow-unresolved`（只用于草稿）。

```bash
python scripts/check_decisions.py --decisions decisions.jsonl --root "资料目录" \
  --review output/coding/extraction_review.csv --out output/qa/decision_issues.csv
```

## 流程总览

```
0 范围与问题 → 1 资料/数据审计 → 2 编码或抽取协议 → 3 数据集
                                      ↓
                         7 终检 ← 6 文稿组装 ← 5 出版级图表 ← 4 统计分析
```

每个阶段都有“闸门”。当前验收档以内的闸门不过，不进入下一阶段。低于当前档的判据不适用。有工作台时按任务卡推进；下面这张图是没有工作台时的 CLI 对照。

### 材料多时允许子代理并行（建议，非强制）

材料量很大（成百上千份文档、逐份 OCR/ASR/编码）时，可以把**纯机械的批处理**交给多个子代理并行做。这是吞吐建议，不是质量捷径，五条护栏必须守住：

1. **分片互斥**：每个子代理领一组互不重叠的 `rel_path`（或文件清单切片），不共享写同一份产物。
2. **契约不打折**：并行的是同一批 CLI 的同一套参数，审计/编码/转写的台账与证据锚一样不少；不能用「并行了」降低任何闸门判据。
3. **合并显式**：子代理只产出自己的分片产物；合并由主会话逐一验收（台账对账、去重、重编号）后写入总产物，不能各自直接写总目录。
4. **口径先行**：分词器档位、编码 sheet 字段、OCR 引擎、语言模型等口径先定并写进 frame/契约，子代理照抄，不得各自发明。
5. **收益刀刃**：只在每份材料独立、判断权已在协议里定死的环节并行（读文件/跑 OCR/抽字段）；抽样复核、争议裁决、语义判断留在单一会话里做。

并行数量由模型按材料规模与机器情况自定。支持 `--resume` 的阶段（语料审计、编码抽取）有逐字节等价的回归测试钉住，合并后应当抽查复跑验证；OCR/ASR/账本类分片产物没有等价的机器保证，靠护栏 3 的显式合并与对账兜底。

这不是只走一遍的直线：模型缺字段/样本时回到原材料与数据集阶段。可投稿档补数后重跑受影响的统计、图表和文稿，并更新抽样复核。归档档才在补数后做全格复核。内置脚本可被等价、自选实现替换，**但阶段 1 审计、范围符合性、命名源与目录骨架、来源/样本/运行回执契约在任何实现下都不能省略**——换脚本不换契约。

### 归档档深度核验链（契约账本层）

只有一个版本的流水线。归档档在混合资料里做「可审计的中间结论」（扫描页/音
视频/跨页表、逐格复核、多输入模型、独立数值校核、发布范围）时，用 `scripts/`
下的契约账本模块把每一步落成带内容哈希与状态机的记录：`source_units →
ocr_provider/asr_provider → table_recovery → audit_view → discovery →
search_index → gaps → review_workbench → entities → models → validation →
claims → layout_check → lifecycle → release`。它不是第二条流水线：数据面
（OCR/ASR/表格恢复/来源单元）与发布面（版本失效、发布事务）补的是主链没有的
能力，账本（`contract_v2`/`txn`，文件名沿用历史命名）把「恢复程度、没找到、
转写未核、N 的语义、求解质量、复核范围」这些容易被含糊掉的东西显式记下来；
统计与成稿**始终用主链引擎**（`auto_stats`、`assemble_manuscript`、
`export_pdf_hires`），`models` 只做归档档多输入模型的登记执行，
`manuscript` 只做印后数字溯源与实印核对——没有第二套统计引擎或成稿引擎。
没有 v1→v2 迁移路径：账本要么按当前契约建立，要么就不存在。
启用方式、记录种类、命令与每个模块的硬性拒绝见
[references/13-contract-v2.md](references/13-contract-v2.md)。
explore/可投稿档不需要这一层；归档档的深度检查依赖它产出的账本。

契约账本层的维护入口包括：

- **成稿**：`refs.py` 记录实际访问层级、原文支持与撤稿/更正查核；`manuscript.py` 不排版——DOCX 由 `assemble_manuscript.py` 生成、PDF 由 `export_pdf_hires.py` 导出，它只做印后核验（每个印出的数字绑定 validated 模型结果/已复核数据集单元/已查参考文献；实印文本与审核文本的包含比对；表格逐行对账）。章节和最低字数默认不固定。
- **设计与图**：`designcheck.py` 联查设计、诊断、角色 N 与泄漏；`figsemantics.py` 对账实际图元与交付 PNG，测量标签边界；配色只推荐。`layout_check.py` 检查最终安置。位图字号须有完全对应的实际渲染字体证据，单独的源 PDF 不能证明位图内部字号。
- **验收**：仓库的 `tools/run_acceptance.py` 保存真实执行、原始日志、逐项结果与当前代码/fixture 哈希；`tools/acceptance_cards.py` 核对执行前冻结的场景映射，不接受仅源码或自报 passed。历史先后顺序不能用事后时间戳证明。

---

## 阶段 0：范围与问题

先写一页 `scope.md`，至少包含：

- 研究问题、理论机制、预期贡献。
- 资料类型与来源：数据库、检索式/抽样框、时间范围、语言、地区。
- 分析单位：一份文档/一名受访者/一个案件/一个机构/一份问卷。
- 纳入/排除标准：时间、类型、语言、字数、重复、无法读取、关键字段缺失。
- 预期变量清单与角色：因变量、核心自变量、机制/调节变量、控制变量。
- 数据形态：文本、表格、混合；是否需要人工编码、问卷量表、实验分组或二手数据。

宿主支持计划模式时，本节范围与覆盖阶段 0–7 的执行计划**必须**在计划模式中产出并经用户批准后才开工（见顶部「计划模式与目标模式」节）；批准前除只读初读外**禁止**执行任何阶段脚本。

**闸门**：能用一句话说清“原始资料 → 可读资料 → 范围内样本 → 分析样本”的每一步会掉多少、为什么掉。

---

## 阶段 1：资料与数据审计（必须先跑）

### 1A 文件级审计

运行 `scripts/audit_corpus.py`：

```bash
python scripts/audit_corpus.py --root "资料目录" --out-dir "output/audit" --min-chars 100
```

十万量级语料的中断续跑用 `--resume`（原参数原样再来一遍，加 `--resume`；size+mtime 未变的文件复用上一轮整行，抽样框不一致直接 exit 2；详见 references/01 的「断点续跑」节）：

默认扫描所有支持的类型，不需要逐个写 `--ext`；可用 `--list-ext` 查看完整列表。它会输出：

| 文件 | 用途 |
|---|---|
| `corpus_files.csv` | 每份文件的扩展名、类型、字节数、页数/表数、字符数、**有效字符数**、图片数、MD5、状态、错误 |
| `corpus_summary.json` | 机器可读的汇总，含 `sampling_frame`（root/扩展名/跳过目录/min-chars/是否内容去重） |
| `corpus_duplicates.csv` | 重复组、保留/移除建议、`keeper_reason` |
| `corpus_report.md` | 可直接贴进项目日志的中文报告，顶部先写「抽样框」 |

主键列同时写 `rel_path` 与旧名 `relpath`（见 `references/10-contracts.md`）；下游脚本按别名顺序解析，找不到键列直接报错。

**字符数有两个口径**：`chars` 是抽取到的全部字符，`chars_effective` 去掉纯页码行、目录行与空白。`--min-chars` 判的是后者——扫描件每页印 `i/n` 能轻易凑出上百个字符，用 `chars` 判会把整本扫描件当"有文本"。`textless` / `image_only` 的判定也改用 `chars_effective`。

状态机（每份文件必须落入一类）：

| 状态 | 含义 | 是否进入分析 |
|---|---|---|
| `valid` | 可打开、有足够文本/数据 | 是 |
| `metadata` | `._*`、`.DS_Store` 等系统文件 | 否 |
| `hidden` | 隐藏文件/隐藏目录 | 否，除非用户确认 |
| `unsupported` | 未知格式、压缩包、旧版 Office、缺少解析器 | 否，先转换/解压 |
| `quarantined` | 位于 `_duplicates` 等跳过目录 | 否，已隔离副本 |
| `zero_byte` | 0 字节 | 否 |
| `corrupt` | 打不开、文件损坏 | 否 |
| `encrypted` | 有密码/权限限制 | 否，除非能解密 |
| `textless` | 有页面/单元格但文本不足 | 否，检查是否空文件或需重导出 |
| `image_only` | 图片/扫描件，无文字层 | OCR 后可用 |
| `media` | 音频/视频 | 先转写/抽帧 |

重复不是独立的 `status`：内容相同的文件仍是 `valid`，另用 `dup_group`/`dup_role` 标记 keeper/duplicate；报告中的 `unique_valid_files` 已扣除副本。

必须逐项处理：

- `._*`、`.DS_Store`：macOS 元数据，不是研究资料；计入“非资料文件”，不要计入样本。可读的 `._*` 会在 error 列标注，需人工确认。
- 隐藏文件/目录记为 `hidden`；扩展名不在支持列表的记为 `unsupported`；`_duplicates` 等跳过目录记为 `quarantined`。三者都不进样本，但必须出现在总数和报告里。
- 0 字节、打不开、加密、文本不足：分别记录为 `zero_byte` / `corrupt` / `encrypted` / `textless`；图片型 PDF 记为 `image_only`。
- 顶层/年份分布只统计唯一样本（`valid` 且非副本）；不要把元数据、损坏文件或重复副本算进样本结构。
- 重复副本：按 MD5/正文分组并复核保留件，分析按去重计划排除副本；冻结的原始目录保留全部文件。需要隔离时只在工作副本移动到 `_duplicates/`，不搬动或删除原件。
- 文件名截断、尾随点、超长路径：Windows 下常见；用 Python 读取并在报告中记录，不要靠资源管理器手工数。
- 同名不同文、正文相同但元数据/导出设置不同（MD5 不同）：必须按标题/关键字段/正文抽样人工复核，不能只靠 MD5 自动去重。需要自动查这一层时加 `--content-dedupe`：它把 valid 文件抽出的正文归一化后取 sha1，另写 `dup_content_group` / `dup_role_content`。默认关闭是因为要真正打开每个文件（大语料上很慢），而字节级分组已经够用；报告里会同时给出字节组与内容组的数字和口径关系。
- 单个文件打不开时不会中断整次扫描：该文件记 `status="unreadable"` 并在 `error` 列写异常，末行打印 `unreadable: N`；需要严判时加 `--fail-on-issues` 返回 2。
- `--out-dir` 不要放在 `--root` 里面；放进去也能跑，但脚本会按产物文件名跳过自身输出，报告里注明跳过了多少。放在语料目录外最省事（语料目录里的产出会被当成"资料"）。

然后运行 `scripts/dedupe_corpus.py` 生成去重计划：

```bash
# 先生成计划并查看（不移动任何文件）
python scripts/dedupe_corpus.py --audit "output/audit/corpus_files.csv" --root "资料目录" --out-dir "output/audit"
# 需要隔离时仅对工作副本执行；原始目录保持不动
python scripts/dedupe_corpus.py --audit "output/audit/corpus_files.csv" --root "工作副本目录" --out-dir "output/audit" --apply
# 反悔：把 move 的移回、把 copy 的删掉（仅当副本 MD5 仍与原件一致）
# 注意 --undo 后面必须跟 move_log.csv 的路径（--apply 才会生成它），不能只写 --undo
python scripts/dedupe_corpus.py --undo "output/audit/move_log.csv"
```

`--apply` 前会逐组校验 keeper 真的在盘（keeper 被删或改名就整组跳过并在 `move_log.csv` 记 `skipped`，不会把唯一副本搬走）。`move_log.csv` 记 `group/src/dest/action/status/reason`，`--undo` 靠它反演。**移动失败、跳过、或日志里有 conflict 时返回 2**，不能当成功处理；`--undo` 发现没有任何可复原条目时也返回 2（日志全是 copied 时会明确报 `nothing to undo`）。

**闸门**（未过**禁止**编码/建模/出图）：`corpus_files.csv` + `sample_flow.csv` 已实际产出，且 `sample_flow.md` 能对账：

```
原始文件数（含 .DS_Store/无扩展名文件）
- 元数据/隐藏文件
- 不支持/需转换（unsupported）
- _duplicates 等隔离目录（quarantined）
- 0 字节/损坏/加密/文本不足
= 可读资料数
- 不在范围（时间/类型/语言）
= 有效资料数
- 重复副本
= 唯一样本数（按 unique_valid_files）
- 关键变量缺失/无法编码
= 分析样本数
```

每个模型再有单独的 N，不要用一个 N 打天下。

### 1B 表格数据质量审计

如果资料本身是 CSV/Excel/SPSS 数据，先做字段级检查，再编码/建模：

- 行数、列数、每列类型（数值/分类/文本/日期）、缺失率、唯一值数。
- 主键/ID 是否唯一；重复行；同一单位多次记录。
- 分类变量取值是否拼写不一致（“是/否/1/0/TRUE”混用）；日期范围。
- 连续变量范围、异常值、P99 截断、是否需要 log 变换。
- 问卷量表反向题、多选拆分、单位一致性。
- 编码（UTF-8-SIG/GB18030）、小数分隔符、SPSS 变量名合法性。

`csv_to_spss_syntax.py` 会清理非法/重复变量名并生成 `.sps`；`auto_stats.py` 会给出描述统计、组间检验和相关，用于发现数据问题，但不替代正式模型。

**闸门**：能说清每一列的来源、类型、缺失处理、异常值处理和最终进入哪个模型。

---

## 阶段 2：编码/抽取协议

### 2.1 文本编码

1. 先写 `assets/codebook-template.md` 的实例：每个变量都要有**定义、取值、判断规则、证据位置、正例、反例、缺失规则**。
2. 用 `scripts/make_coding_sheet.py` 抽取全文和候选证据句，生成编码工作表；它只提供证据片段，不替你做最终判断，对任何文体的资料读法都一样（访谈、新闻、政策、报告、网页、会议记录……）。法院、案号这类某类文书的字段不内置：要抽什么，写进项目自己的 `--extract` 剖面。
   - CSV/TSV/JSON/XLSX 等表格会跳过并提示走统计流程；图片/音视频会提示先 OCR/转写。
3. 人工/LLM 编码时，每条记录至少保存 `*_ev` 证据句；没有证据句的编码视为未完成。证据句的格式是 `<字段>=<原文片段>@<char_start>-<char_end>`（片段超 200 字会加「…」，但偏移量始终指向整句），同一句先判否定再判肯定，命中项带 `negated`/`polarity`——**两个编码员的结果可以逐条按字段+偏移对齐，不必人工翻原文**。
4. 抽 10%–15% 资料双人/双轮编码，报告一致率或 Cohen's κ；分歧先裁决再改 codebook。用 `scripts/compute_kappa.py` 对齐两轮编码并计算：模型初编码与独立复读（或两名编码员）各产出一份 `dataset.csv`，脚本按文档+字段对齐，输出每变量 κ/一致率（`kappa_report.csv`）、逐条分歧及双方证据行（`disagreements.csv`）与 `coding-sample.md` 骨架；κ < 0.6 的变量自动点名。流程见 `references/02-coding-protocol.md` 的「信度检验」节。
5. 抽样复核用 `scripts/sample_review.py`，不要自己挑样本：`draw` 按声明种子分层抽样（`needs_review` 行强制单独成层），同一 seed 重跑逐字节复现，每行带 `rel_path/field/span/raw` 供回原文核对；复核者只填 `保持/改判/无法核对` 三值；`tally` 按层统计并列出改判项，一行没填就 exit 2，`--fail-above` 是你声明的改判率上限。详见 02 的「结构化抽样复核」节。
6. codebook 冻结后再全量编码；后续改动要记录版本与影响范围。

### 2.2 字段抽取（`--extract`，一行一个观测）

如果研究要的是**结构化字段**（每份材料的 X 等于几），不要停在"候选证据句"上。切段从哪开始、取第一次还是最后一次、在哪个词停下，由你读过这批样本后写进项目自己的剖面或 `draft/` 解析器。技能包里的剖面只展示字段可以长什么样，不是这批材料的抽取规则。

下面这条命令只说明 `--extract` 怎么调用：

```bash
python scripts/make_coding_sheet.py --root "资料目录" --out "output/coding" \
    --extract draft/fields.json
```

`draft/fields.json` 由你读样本后写成。不要把 `profiles/legal-judgment.json` 传给 `--extract`。

产出六件套（三件数据 + 三件复审；与 `coding_sheet.*` 并列，不替代）：

| 文件 | 内容 |
|---|---|
| `dataset.csv` | 一行一个观测；列由 profile 决定，每个字段后面跟一列 `<字段>_src` |
| `evidence.jsonl` | 每行一份材料的字段取值 + 证据 `<字段>=<片段>@<start>-<end>` + `na`/`negated`/`fallback_used` |
| `run.json` | profile 名与 `profile_sha256`、每字段 `hit`/`na`、`documents`/`errors`、`final_hits`、`review` |
| `extraction_review.csv` | 一行一个文档×字段：当前值、候选值、`flags`、`needs_review` |
| `extraction_candidates.jsonl` | 每个候选的 `value/raw/span/source/note`，被否决的读数留在这里 |
| `decisions_todo.csv` | 只列需复审字段，`target` 已拼成 `<rel_path>#<field>`，供模型写 decisions |

后三件是复审层：`--require-review` 用它们卡住交付，`--decisions` 用它们闭环。

要点（完整规范见 `references/09-field-extraction.md`，实现与本文件冲突时以它为准）：

**缺失要分来源**：`missing_by_source.csv` 把每个字段的 NA 按 `not_found`（材料里没有）、
`negated`（落在否定域）、`redacted`（被脱敏）、`na_phrase`（原文就写"未提及"）、
`unparsed`（找到文字但解析不出）分开计数。写论文时说"未提及占 30%"之前先看这张表——
把"解析失败"算进"未提及"，等于把工具的无能写成了研究对象的行为。

- **领域写在 JSON 里，不写在代码里**。`profiles/` 里的裁判文书、访谈和词汇满意度都是**示例夹具**，不是目标用户，也不限制研究领域；写一份新 profile 就能换领域，不用改 Python。引擎不内置任何文体的字段或切段，`--extract` 也拒绝直接使用包内 `profiles/`（要先把示例复制到 `draft/`、读过样本改好切段再传）。
- **先挖掘，再写 profile**。`scripts/mine_candidates.py` 从语料清单（audit 的 `corpus_files.csv`，或手写 TSV `rel_path`+可选 sha256）跑 TF-IDF 关键词、共现词对（PMI）与 NMF 主题，产出候选表（每行带 `rel_path`+行号证据锚，锚=词首次出现的真实行）与 `mine_receipt.json`（corpus/停用词 sha256、清单格式与哈希算法、跳档明细、参数与 seed 入账）。候选不是事实：哪些词是构念、哪些进 codebook、哪些进停用词表都由你读过候选后声明；主题数 K 你定（`--scan-k` 只给轮廓曲线）。详见 `references/09-field-extraction.md` §8。
- **`na` 必填**：缺失要落短语（`未提及` / `不适用` / `未判罚金`），不能落空串——空串分不清"没提到"与"不适用"。
- **NA ≠ 0 ≠ False**：`contains` 字段在段存在但未命中时是 `False`（不是 NA），`count_unique` 的 `0` 是值。把"没投诉"写成缺失，等于扔掉一次测量。
- **证据可回验**：每条证据的偏移必须能在原文 `text[s:e]` 命中，用 `extract_lib.verify_evidence()` 校验（不要自己另写一份解析）。
- **换行先归一**：偏移一律指向 `\r\n`→`\n` 归一后的文本。CRLF 文件不归一，每条偏移会按行数整体漂移。

### 2.3 问卷/量表/结构化抽取

- 先做项目级变量字典：题号、题干、取值、反向题、缺失码。
- 多选/排序题拆成 0/1 或多列；量表总分先检查信度（α/ω）和维度。
- 开放式题项可先主题编码，再转成计数/类别变量；不要直接把词频当主题。
- 表格数据的主键、单位、时间字段必须能回溯到原始文件。

**抽取结果先复审，再落库。** 加 `--require-review` 时，任何被标记的字段都会让退出码为 2；`extraction_review.csv` 给出当前值、候选值、flag（`cross_line_header` / `na_conflict` / `multiple_values` / `value_withheld`），`extraction_candidates.jsonl` 保留每个候选的 span：

```bash
python scripts/make_coding_sheet.py --root "资料目录" --out "output/coding" \
  --extract draft/eldercare-interview.json --require-review
python scripts/check_decisions.py --decisions decisions.jsonl --root "资料目录" \
  --review output/coding/extraction_review.csv --out output/qa/decision_issues.csv
python scripts/make_coding_sheet.py --root "资料目录" --out "output/coding" \
  --extract draft/eldercare-interview.json --decisions decisions.jsonl --require-review
```

（`draft/eldercare-interview.json` 指把示例剖面复制进 `draft/` 并按这批材料改过切段后的项目剖面；直接传包内 `profiles/` 会被拒绝。）

模型读 `extraction_review.csv` 与原文，逐条写 `decisions.jsonl`；`value` 必须是 `alternatives` 或当前值里出现过的候选，否则 `check_decisions.py` 直接拒绝——这是“不许凭空取值”的机器闸门。`na` 判断不需要候选，但必须给出原文 span。

**闸门**：编码抽取值要能从 `值 → 证据句/原始字段 → 原文/原始行` 回查。可投稿档用抽样复核记录抽查结果，`needs_review=true` 的字段要有处理记录。`evidence.jsonl` 与 `decisions.jsonl` 是候选证据，不自动等于分析事实，也不等于全格复核。全格 provenance、prepare 和 final 只在归档档，契约在 references/12。

详见 `references/02-coding-protocol.md`。

---

## 阶段 3：数据集

数据集由资料决定，可为任意数量和形态，逐一写入 `research_registry.json`。以下是单个文本编码数据集的常见产物示例，不是固定三件套或唯一宽表：

- `data/coded.jsonl`：逐份资料编码明细 + 证据片段，便于回溯。
- `data/analysis.csv`：分析用宽表，一行一个分析单位。
- `data/analysis.sav`：需要 SPSS 时执行生成的 `.sps` 得到，带变量标签/值标签；不需要 SPSS 时不强制。

每个数据集写明单位、主键和 codebook。长表/面板用复合键，网络/矩阵等保留原生文件并提供无损审计视图。逐格 provenance 和全格复核记录只在归档档建立，契约见 references/12。可投稿档把分析表登记进 `research_registry.json` 后即可进入统计。

**清洗：先声明，后执行**。要清洗就先写 `draft/cleaning.json`（`python scripts/clean_data.py --emit-template draft/cleaning.json` 起步）：去重键、值映射、类型转换、越界范围、缺行规则全部由你读过样本后声明；引擎只执行声明过的步骤，不做任何未声明的清洗。每一步记进 `cleaning_log.jsonl`（行数入出、改格数、丢行 id 样本、内容指纹链），同一数据集+同一配方重跑即得同一指纹链——复核靠重放，不靠信任。`max_drop_fraction` 必填：累计丢行超限立即中止；`id_columns` 声明后在每步之后与结束时必须唯一（初始重复 id 只能靠去重步消除）。`steps` 留空 = 不执行任何步骤（`na_values` 词汇表仍生效）。产出 `output/cleaning/clean_dataset.csv`，行数用 `--flow-out output/coding/sample_flow.csv` 自动并入（有 `kind` 列时清洗行补 `kind=stage`，重跑替换上一轮清洗行），不要手抄。

**全量数据报表**：分析表建好后、登记 `research_registry.json` 之前先跑 `python scripts/report_tables.py --dataset output/dataset/analysis.csv --out output/reports`（`--id`/`--outcome` 声明角色列，`--crosstab "A,B"` 指定交叉对，`--cleaning-log`/`--missing-reasons` 接清洗链与缺失来源），一次性产出：变量清单（`variable_report.csv`）、描述统计（`descriptive_stats.csv`）、频率表（`frequency_tables.csv`）、交叉表（`crosstabs.csv`）、缺失（`missing_report.csv`/`missing_patterns.csv`）、重复（`duplicate_report.csv`）、可读的 `data_report.md`，以及 `report_index.json`——它用 sha256 把每张表锚定到数据集字节（有清洗链时再上溯到原始数据集）。报表的 N 与后续文稿数字用 verify_numbers 对表，不手抄。协议细节见 references/03-analysis-spss.md 的「数据清洗与全量报表」节。

主键与标记列（`references/10-contracts.md` §1、§5）：

| 列 | 含义 | 谁产生 |
|---|---|---|
| `rel_path` | 相对资料根目录的路径，全链路主键 | `audit_corpus.py`、`make_coding_sheet.py` 都写；`audit_corpus.py` 同时写旧名 `relpath` 以兼容老脚本 |
| `in_scope` | 是否属于研究范围（时间、类型、地区、语言） | **你在编码时加**，脚本不生成 |
| `in_analysis` | 是否进入描述统计（排除无法编码/关键缺失） | **你在编码时加**；`auto_stats.py`/`auto_chart_pack.py` 的默认筛选读它，传了 `filter_query` 就不再叠加它 |
| `model1_sample` 等 | 每个模型单独的样本标记；不要用 `in_analysis` 代替 | **你在建模时加**；`auto_stats.py --spec` 会按模型写各自的 N |
| `dup_group` / `dup_role` | 重复组 ID 与 keeper/duplicate 角色 | `audit_corpus.py`（字节级）；`--content-dedupe` 另写 `dup_content_group`/`dup_role_content` |
| `exclusion_reason` | 排除原因，便于写样本流程 | **你在编码时加**；`make_coding_sheet.py` 把被 `--audit`/`--dedupe-plan` 排除的文件逐条写进 `skipped_documents.csv`（含 reason），不靠这一列 |
| `<字段>_src` | 非直接抽取字段的来源（`year_src`/`charge_src`/`court_level_src` 等） | **编码时加**；`make_coding_sheet.py --extract` 会为抽取字段写 `*_src` |

`in_scope`/`in_analysis`/`model*_sample`/`exclusion_reason` 这几列由你在编码/建模时写入（脚本不代写），**但写它们不是可选项**：每个分析数据集必须有 `in_scope` 与 `in_analysis`，且范围必须由 `scope.json` 白名单声明、经 `scope_conformance.py` 核对通过（见下）。样本流程对不上时第一件事就是查这几列。`sample_flow.csv`（列 `stage,n,note`）应由 `make_coding_sheet.py` 生成并逐档对账，**不要**手写正文里的漏斗数字。

**范围符合性必须机器核对，不能只靠 `in_scope` 自觉。** 每个数据集在 `scope.md`/`scope.json` 里为决定范围的分类列声明纳入白名单（`columns.<列>.include`，纯通用：类别、分层、地区族等任何分类字段都适用），进入统计前跑：

```bash
python scripts/scope_conformance.py --data output/dataset/analysis.csv --scope scope.json \
  --cell-cols "<分类列>,<时间列>" --out output/qa/scope_conformance.csv
```

它把分析表的实际类别分布对照白名单：**任何声明范围外的命名类别只要 n>0 就 exit 2**（子样本/并案/混入的无关类别在这一步暴露，而不是画进图里才发现）；缺失值记 warning 并要求声明处理方式；`--cell-cols` 另报小样本单元格（率表/热图在 n 极小的格子上会出现不稳定的 0%/100%）。范围外类别要么按声明排除、要么显式修订白名单并记录理由，不能静默留在分析样本里。这一步对任何学科都一样，引擎不内置任何领域的类别词。

用 `scripts/csv_to_spss_syntax.py` 生成 `.sps`，避免手写 `GET DATA` 时列类型错位。CSV 里若是“是/否、有/无、支持/不支持”等二值文本，脚本会自动追加 `RECODE ... ('是'=1) ('否'=0) INTO *_num`，Logistic 直接用数值列；不需要时加 `--no-recode`。

**闸门**（范围符合性未过**禁止**进统计）：每个数据集按自己的单位与键核对源记录、转换和样本流程；不同粒度的数据集行数不必相等，关联基数必须可解释；`scope_conformance.py` 退出码 0。可投稿档在注册表和抽样复核完成后进入统计，不运行 `verify_dataset.py`。归档档才先 prepare、逐格复读、再 final，通过后才把该版本用于正式结果。每个模型 N 从实际样本键与筛选条件重算。

---

## 阶段 4：统计分析与扩展

先按资料与问题写开放 `model_plan.jsonl`，再看结果；清单可随新数据和问题扩充并记版本。逐项考虑主分析、描述、关联、多变量、诊断、异质性、稳健性、预测及其他有依据的数学模型，适用与否逐项说明，不能按显著性只留一小部分。

先用自动筛查脚本把描述统计、组间检验、相关和单变量模型跑一遍：

```bash
python scripts/auto_stats.py --data data/analysis.csv --config assets/chart_config.example.json --out output/analysis_pack
```

它输出 `descriptives.csv`、`group_tests.csv`、`binary_rates.csv`、`correlations.csv`、`univariate_models.csv`、`univariate_skipped.csv` 和 `analysis_pack.md`，用于发现值得进一步建模的变量；**不要用自动筛查的 p 值筛变量**。

按模型需要选择实现，可以混用内置工具、自写脚本和专用引擎；统一的是输入版本、变量定义和结果契约：

```bash
# A. 用 spec 显式声明后由本脚本估计（写清参照组、聚类、稳健标准误）
python scripts/auto_stats.py --data data/analysis.csv --spec model_spec.json \
  --out output/models --separation error --vif --roc
```

`model_spec.json` 形如：

```json
{"models": [{"id": "m1", "type": "logit", "outcome": "y",
             "predictors": ["x1", "x2", "C(region, Treatment('华东'))"],
             "ref": {"region": "华东"}, "cluster": "province", "cov": "HC1"}]}
```

输出 `coef_<id>.csv`（可直接喂 `auto_chart_pack.py --coef` 画森林图）、`model_summary.md`、`model_meta.json`、`separation_report.csv`。**参照组必须显式声明**（`C(名, Treatment('水平'))` 或 `ref` 字典），未声明直接退出码 2 并列出可选水平——脚本不猜参照组。空单元格按 `--separation drop|merge|error` 处理（默认 drop，会写进 `separation_report.csv`）；`|β|>12` 或 `se>8` 的估计视为不可信，熔断且不写进系数表。

B. 或在 SPSS/R/Stata 中按同一份预设规格估计，把系数导出成同样列名的 CSV 再喂图表脚本。

脚本会自动识别结果变量类型：

- 0/1 → 二元结果（Logistic/OR）。
- 连续数值 → 连续结果（OLS/均值+CI），多分类时组间检验用 Kruskal–Wallis。
- 多分类 → 分类结果，组间用卡方/Cramér’s V；多分类自变量会用哑变量进入单变量 OLS/Logit，并以 `变量_水平` 形式报告。
- 多分类结果本身不做二分类 Logit；主模型应改用多项 Logit 或先合并类别。
- “是/否、有/无、支持/不支持”等常见文本标签会自动映射为 0/1；其他二值文本必须用配置项 `outcome_map` 指定正类。
- 完全分离、估计不稳定的单变量模型会写入 `univariate_skipped.csv`，不会给出虚假的巨大 OR。
- 结果列全缺失、过滤后 0 行、`filter_query` 拼错时直接报错退出。

按数据可支持性逐项评估，支持的尽量做全，不支持的回查并留原因：

- 描述统计：每个分组的 N、占比/均值、结果率、95% Wilson CI。
- 主模型：二元 Logistic / OLS / 多项 Logit，写清因变量、参照组、核心自变量、控制变量。
- 机制/调节模型：交互项、简单斜率或分组预测值。
- 稳健性：替换因变量、替换样本、加入/移除控制变量、去重前后。
- 诊断：多重共线性、完全分离、样本量不足的单元格、校准/区分度。
- 异质性：分类别/分地区/分年份/分群体。
- 能做的探索：PCA、对应分析、聚类、预测 ROC/校准；标注“探索性”。

报告表至少要有：系数/OR、95%CI、p、N、拟合指标、参照组说明。每个模型单独一行 N。

### 4B-2 五项现代统计（同一 `--spec` 入口）

多变量模型现在支持五种类型：`logit` / `ols` / `mixed` / `cox` / `logrank`，外加三项字段扩展（字段写错类型直接报错，不会静默忽略）：

- **交互项** `interactions: [["a","b"]]`：乘积项 + 联合 Wald χ²（fit.csv 的 `test_*` 列）；
- **抽样权重** `weights`：WLS / GLM freq_weights，点估计加权、SE 是模型基**不是设计基**（摘要明说）；
- **多重插补** `impute: {m≥2, seed 必填}`：MICE(PMM) m 次 + Rubin 合并 + FMI + 完整案例参照行 + `impute_report.csv`；
- **mixed**：随机截距（+`random_slopes`）、REML、ICC 进 fit.csv；
- **cox**：Breslow、HR=exp(β)、可选 `strata`、无截距行；
- **logrank**：`time/event/group`(+`strata`)，χ²/df/p 进 fit.csv，纯 logrank 的 spec 合法。

字段边界、验证规则与产物细节见 `references/03-analysis-spss.md`「五项现代统计」节。

### 4C 十六种经典方法一次跑完（`methods_pack.py`）

`auto_stats.py` 的 `--spec` 层覆盖 logit/ols/mixed/cox/logrank 与交互、权重、插补；教材里那套"描述 → 差异 → 关联 → 模型 → 降维 → 测量 → 分类"的方法清单
（描述统计、PCA、相关、ANOVA、卡方、SEM、判别、时序、因子、聚类、回归、T 检验、中介、卡诺、信度、效度）
由 `methods_pack.py` 统一执行，**每个方法先自检前置条件，不满足就 `skipped` 并指出替代方法**，绝不硬算：

```bash
python scripts/methods_pack.py --list                       # 十八个编号（16 个方法 + 非参数族 + 二元 Logit）
python scripts/methods_pack.py --data data/analysis.csv --config methods.json \
  --out output/methods --methods all
python scripts/methods_pack.py --data data/analysis.csv --config methods.json \
  --out output/methods --only m04,m05
```

`methods.json` 用命名槽位声明变量（不认识就跳过，不猜）：

```json
{"outcome": {"col": "restore_any", "positive": 1},
 "continuous": {"col": "restore_amount"},
 "predictors": ["gongyi", "charge_group", "year"],
 "group": "charge_group", "row": "charge_group", "column": "gongyi",
 "items": {"scale": ["q1", "q2", "q3"]}, "cluster_vars": ["v1", "v2"],
 "discriminant": {"group": "g", "vars": ["v1", "v2"]},
 "kano": {"响应速度": ["f1", "d1"]}, "path": {"x": "x", "m": "m", "y": "y"},
 "time": {"col": "year", "value": "amount"}, "cluster_k": 3, "n_factors": 2}
```

产物：`methods_report.md`（总览 + 每方法一节 + 可直接改写的报告句式）、`methods_manifest.csv`、
每张表一份 CSV、每个跑通的方法一张 600 dpi 配图。**一个都没跑通时退出码 2**——沉默的零产出不算成功。

方法选择、变量要求、前置判据、报告句式与常见误用见 `references/11-methods-catalog.md`。

把做过的和跳过的分析写进 `analysis_manifest.md`（模板见 `references/08-analysis-expansion.md`），不要只报显著结果。

SPSS 语法模板与解释规范见 `references/03-analysis-spss.md`；扩展分析清单见 `references/08-analysis-expansion.md`。

**闸门**：任意一个 OR/β 都能从 `analysis.sps → 输出文件 → 表格` 三段追溯；`analysis_manifest.md` 能解释每个分析做/不做、样本多少；正文没有把“文本里写了某情况”写成“实际产生了某效果”的因果结论。

---

## 阶段 5：出版级图表（默认做全景，不是只画 8 张）

可用 `scripts/auto_chart_pack.py` 生成初始图表包，再按全部数据集与模型清单补齐、自写需要的图，选择正文与附录：

```bash
python scripts/auto_chart_pack.py \
  --data data/analysis.csv \
  --config assets/chart_config.example.json \
  --out output/chart_pack
```

连续/多分类结果不需要改脚本：结果变量会自动切换为“结果分布 + 分组均值/构成”图；文本结果同样可用 `outcome_map` 指定编码。`--coef` 支持 `metric`（OR/HR/RR/beta）与 `n` 列，森林图会按模型样本量写 N；`--pred` 支持 0/1 或“是/否”标签，常数预测/单一类别会跳过 ROC/PR/校准并写明原因。`term_labels` 可把 `lv3` 这类模型项名映射为中文。双比例哑铃图需在 config 里用 `dumbbell` 指定两个 0/1 列。有随访时间与事件列时，用 `--survival-time`、`--survival-event`（可加 `--survival-group`）生成 Kaplan–Meier 曲线。

- 自动图包覆盖 7 组，默认 `--max-charts 0` 不封顶；图数随数据、问题和模型而变，实际数量以 `chart_manifest.csv` 为准。自动图包不代表已覆盖全部模型。
- 正数 `--max-charts`、`--only`、`--sections` 只用于显式选择的分批/试跑。分批结果最终合并并对照清单补全。宽表热图、类别 top-N、矩阵和树图仍有展示策略，必须另保留全量统计/明细并按实际空间调整图幅或同图分面，不能让展示抽样变成分析遗漏；不自动将图分页。

- **A 数据质量**：缺失率、样本类别/年份/地区、二元变量发生率。
- **B 单变量**：结果分布（二分类/连续/多分类分别处理，连续结果加 Q-Q）、处理构成（条形+环形）、数值分布、类别构成。
- **C 双变量**：类别×结果、阶段×结果、类别×阶段热图/堆叠、地区/审级差异、相关热图、散点拟合、气泡图；连续结果用均值+95%CI，多分类结果用组内构成堆叠图。
- **D 多变量**：提琴/箱线、散点矩阵、哑铃图、PCA 碎石/双标图/载荷热图、Ward 聚类树状图、经典 MDS。
- **E 时间**：结果率/均值趋势、3σ 控制图、样本量、阶段构成堆叠柱/面积；多分类结果加结果类别构成趋势。
- **F 模型诊断**：森林图、ROC、校准、预测分布、混淆矩阵、PR 曲线、十分位 Lift（需 `--coef` / `--pred`）；Kaplan–Meier（需随访列）。
- **G 附录**：对应分析、Pareto。

出图策略：

- **每个主发现至少 2 张图**：主结果图 + 稳健性/诊断/异质性图。
- **正文、附录和全图集数量按发现决定**，不预设张数；所有有意义结果与诊断都有可查看位置，密集横轴先倾斜 45°，必要时 60°/75° 并增加底部空间，保留同一张图、全部标签和字号；不自动分页。目标纸幅放不下时明确报错，调整图幅/纸幅或同图分面，并保持实际安置字号可读。
- 每张图先写“回答什么问题”；没有问题就不画。
- 用 `references/07-chart-atlas.md` 选型，覆盖 SPSS 常用高级图形：簇状/堆叠/100% 堆叠条形、线/面积、直方图、箱线/提琴、误差条、散点/气泡、散点矩阵、Pareto、ROC、校准、Kaplan-Meier（有生存数据时）、碎石图、因子载荷、聚类树状图、对应分析、MDS、控制图等。
- 每张图写入 `chart_manifest.csv`：图号、问题、类型、变量、N、图注、文件路径。
- 配色推荐见 [references/04-figures-publication.md](references/04-figures-publication.md#科研配色推荐可调整不是强制模板)：按数据含义、领域/期刊要求和用户偏好自选；可用单色、分类、顺序、发散、循环或其他合理方案，保持跨图语义清楚。色号、8 色默认值、类别数和内部色差阈值都不是强制；可结合线型/点形/纹理/标签表达。
- 图注写清 N、数据来源、模型设定、参照组；探索性图（PCA/CA/聚类）在图注标明“探索性”。

用 `scripts/pubfig.py` 统一风格：

```python
from pubfig import set_style, save_fig, wilson_ci, forest_plot
set_style()  # 15 cm 版心，宋体/Times New Roman，600 dpi
```

规范要点：

- 物理宽度 15 cm（A4 正文 15.4 cm 内），字号 7.2–8.5 pt。
- 中文宋体、西文 Times New Roman；PDF 字体嵌入（Type 42）。
- 图内不放标题；图题、图注在 Word 中排。
- 同时输出 PNG 600 dpi、矢量 PDF、LZW TIFF（TIFF 默认写出，不需要时 `--no-tiff`）。
- 误差线注明 95% CI；森林图实心点=显著、空心点=不显著。
- 偏态连续变量用 log10 或 P99 截断，并在轴标签/图注注明。

**多面板主图用 `scripts/paper_figures.py`**（图包负责"看全貌"，它负责"排进版面"）：

```bash
python scripts/paper_figures.py --paper assets/paper_figures.example.json --out output/figures
```

- 一个 `Figure` = 一个 `panels` 数组，用 GridSpec 组装成 (a)(b)(c)；`compose_figure()` 返回 `panel_sizes_cm`（每格实际厘米）与 `min_fontsize_pt`（实测最小字号），**不需要你猜字号会不会被缩放压小**。
- 支持 `bar` / `bar_with_ci` / `stacked_bar` / `line` / `scatter` / `hist` / `pie` / `forest`；`forest` 直接吃 `auto_stats` 的 `coef_<id>.csv` 或 `coef_all.csv`。
- 产出 `FigureN.png|pdf|tiff` + `paper_figures_manifest.csv`（与 `chart_manifest.csv` 同构，`n_scope`/`dpi`/`px_width`/`palette` 齐全），可直接喂 `qa_outputs.py`。
- 图注里的 `N=` 会被全局替换成该图真实 N（多图共用一段图注模板也不会串号）。

**闸门**：`chart_manifest.csv` 中每张图都有问题、N、图注、文件；正文主图与附录图不重复；PDF 内嵌图按版面尺寸折算的**有效 dpi ≥ 600**（15 cm 宽 = 3543 px；3000 px 只有 508 dpi）；**最小字号 ≥ 7.2 pt（按实际安置宽度折算，不是按原始 15 cm）**；配色按用途复核（灰度/色觉/色差为建议性诊断，不能把内部阈值当强制色卡）；图注、图、正文引用三者齐全。`qa_outputs.py --min-dpi 600 --min-fontsize 7.2` 一条命令查前三条。

详见 `references/04-figures-publication.md` 和 `references/07-chart-atlas.md`。

---

## 阶段 6：论文写作与文稿组装

**全流程研究/论文任务的默认终点是完整论文式 DOCX + PDF。** 用户要求论文、成稿或完整研究交付时，Agent 必须把核验后的材料与分析组织成可连续阅读的论文，不能以 `methods_report.md`、`chart_pack.md`、模型结果堆叠或图集代替正文。用户明确只要图表、数据、审计或局部分析时，按其范围交付。

- Agent 先确定贯穿全文的研究问题与结果主线，再按学科和材料组织标题、摘要/关键词、背景与可核查文献、数据/材料与方法、结果、讨论、局限、结论及必要附录；章节名称、顺序、篇幅不固定。所有候选模型仍在结果总表/附录可查，不把全部技术输出无选择地堆进正文。
- `assemble_manuscript.py` 是排版器：它消费 Agent 已写好的段落、CSV、图片和数字引用；退出码 0 不证明它已写成一篇论文。Agent 必须实际撰写正文并形成 `manuscript.json`，也可自编项目成稿脚本；没有包内专用脚本不能作为不写论文的理由。
- 摘要、结论、讨论与图表必须指向已核实的证据，区分观察、统计关联、解释与因果；文献、作者、年份、引文也须真实可查。材料不足时完成能够支持的段落，并说明具体缺口/限制，不编数据、理论出处或引用来补齐外观。
- 写作完成后组装 DOCX、导出 PDF 并逐页检查正文连续性、图表引用、分页和字号。PDF 导出受环境阻碍时继续完成可交付的 DOCX、记录实际故障与缺项，不能把只有图集/报告或缺失 PDF 的交付称作完整论文已完成。

**先跑组装脚本，再改 Word。** 手打表格是数字漂移的主要来源：表里的 N 和正文的 N 一旦各打一次，就再也对不上。

```bash
python scripts/assemble_manuscript.py --spec manuscript.json --out output/manuscript.docx \
  --numbers output/manuscript_numbers.csv   # 你写：key,value 两列（{key} 的来源）
```

`manuscript.json` 的 `blocks` 逐段声明 `title`/`authors`/`heading`/`para`/`note`/`table`/`figure`/`references`/`toc`/`pagebreak`。表格与图都**引用文件而不是复制数值**：

```json
{"type": "table", "csv": "output/tables/table1.csv", "caption": "罪名与修复责任",
 "n": "{n_analysis}", "columns": [
   {"col": "charge", "label": "罪名类别"},
   {"col": "n", "label": "文书数", "fmt": "{:,.0f}"},
   {"col": "pct", "label": "占比（%）", "fmt": "{:.1f}"}],
 "note": "注：占比因四舍五入不等于 100%。"}
{"type": "figure", "png": "output/figures/Figure1.png", "caption": "罪名结构",
 "n": "{n_analysis}", "note": "注：横轴为罪名类别。"}
```

- `{key}` 从 `--numbers` 取；**取不到就报错停下**，不会印出半个 `N=`。
- 正文里的 `[@tab:2]`/`[@fig:1]` 渲染成指向表/图题书签的 Word REF 域（支持前向引用；引用不存在的编号 exit 2）。导出 PDF 前记得全选+更新域。
- `{"type": "references", "csv": "...", "title": "参考文献"}`：CSV 一列 `text`，每行一条你已排好版式的条目（GB/T 7714 / APA 由你定）；悬挂缩进+可选 `[n]` 编号，顺序=CSV 行序。
- `{"type": "toc", "levels": "1-3"}`：Word 目录域；页码由 Word 更新域后生成，导 PDF 前必须 F9，否则目录页只有提示文字。
- 脚本同时写 `<out>_numbers.csv`（本文档实际印出的每个 N，键为 `table1_n`/`fig1_n`）——这是**输出**，与输入的 `--numbers` 不是同一个文件；`verify_numbers.py --numbers` 吃的就是这个输出。
- `figure_map.json` 供下一步回填 600 dpi 原图；图默认按**正文栏宽**放置（A4 + 3.17 cm 边距 = 14.66 cm，不是 15 cm），显式给 `width_cm` 超过栏宽会报错而不是悄悄压扁。
- Word 排版细节（图题与下段同页、表格行不跨页、表头重复）由脚本写进 docx，不要手工再设一遍，否则会与脚本的设置打架。

**闸门**：`assemble_manuscript.py` 退出码 0；docx 里表格是三条线且无竖线；每张图有图题、图题与图同页；`manuscript_numbers.csv` 与正文/表/图注逐个对得上。**无论用通用组装器还是自编写稿脚本**，交付必须同时含 `figure_map.json`（`[{tag,title,image}]`）与 `manuscript.json`（含 title/table blocks）作为图/表/文稿的显示名来源，以及覆盖全部交付表/文档的 `table_map.json`/`doc_map.json`（`[{tag,title,file}]`；report_tables/assemble/review_pack 自动合并写入，自写脚本自备）——这是脚本无关的硬契约（`references/10-contracts.md` §9/§17），缺任一则终检 error，否则下游查看器只能回退英文文件名。

Word 导 PDF 时，Word 会把 600 dpi 图压到约 200 dpi。用 `scripts/export_pdf_hires.py` 导出后回填原图：

```bash
python scripts/export_pdf_hires.py --docx "manuscript.docx" --out-pdf "manuscript.pdf" --figure-map "figure_map.json"
```

**闸门**：PDF 页数、图数、图题数一致；每张图按版面折算的有效 dpi ≥ 600（`qa_outputs.py --min-dpi 600` 会算）；表格没有断行/断表头。

详见 `references/05-manuscript-assembly.md`。

---

## 阶段 7：终检

可投稿档的终检核对数字、图表、文稿和注册表，不先做全格 final，也不运行 `research_gate.py`。归档档才先按 references/12 完成全格复核和研究总闸门；正文与图表核查不能替代那一档的回源核查。交付包含当前验收档要求的数据集、codebook、模型回执、图集、分析报告与最终 DOCX，不以图数或模型数够了作为结束条件。

运行：

```bash
python scripts/qa_outputs.py --docx "manuscript.docx" --pdf "manuscript.pdf" --figures "figures" --data "data/analysis.csv" --audit "output/audit/corpus_files.csv" --manifest "output/chart_pack/chart_manifest.csv" --figure-map "output/figure_map.json" --manuscript-spec "manuscript.json" --table-map "output/table_map.json" --doc-map "output/doc_map.json" --min-dpi 600
```

`--figure-map`/`--manuscript-spec`/`--table-map`/`--doc-map` 在终检校验显示名来源存在且可解析（缺=error）；`--audit` 指向阶段 1 的 `corpus_files.csv`，缺失即 error——把"审计先跑"和"命名源齐备"变成终检能卡住的事实，而不是口头约定。目录骨架与命名覆盖另跑 `python scripts/layout_conformance.py --root .`，退出码 0 才能交付（杂散目录、表/文档组无标题交付件均 error）。

退出码：0 = 通过，2 = 有 error（低分辨率图、键列缺失、`n` 非法、`sample` 范围下 N 超过数据行数、文件缺失、空数据、命名源/审计缺失）。`--exit-zero` **只允许**中间调试，**交付终检禁止使用**；用它把 error 压成 0 再交付，视为伪造通过。`--key` 默认 `auto`：按 `rel_path → relpath → file → path → doc_id → id` 找主键，一个都没有就报错，不会静默跳过重复检查。**终稿必须带 `--min-fontsize 7.2`**：不带这个参数时脚本仍会测量并在报告里写出实测最小字号，但不会判错（图和正文因此不会因字号失败）；带上之后才真正卡闸门（按实际安置宽度折算）。带上之后查字号（按实际安置宽度折算），`--graycheck`（默认开）给分类色板灰度建议，`--colorblind` 另加protanopia/deuteranopia 色觉模拟提示；这些默认不拦截配色选择，只有显式 `--strict-palette` 才将声明的分类色板低灰度间隔作为错误。

**数字溯源另跑一条** `scripts/verify_numbers.py`：

```bash
python scripts/verify_numbers.py --out output/verify \
  --tables output/tables --figures-manifest output/figures/paper_figures_manifest.csv \
  --docx manuscript.docx --sample-flow output/coding/sample_flow.csv
```

它查六件事：表内合计、表与图注同值、正文里每个 `N=/OR=/p</β=` 能否在表里找到、图号连续且被正文引用、样本 N 跨表一致、漏斗单调不增。V-05 使用模型表的 `n`；`n_dropna` 是因缺失剔除的行数，不能替代 N。差异或缺少可用 N 时回查实际样本与处理记录，不能直接判定数据错误；插件文案与状态契约见 [references/10-contracts.md §13](references/10-contracts.md#13-模型样本量与-v-05插件接入语义)。产物是 `number_issues.csv`（`severity,check,where,expected,actual,detail`）与 `number_trace.csv`（每个数字追到哪张表哪一格）。有 error 就 exit 2。叙述性数字用 `--numbers numbers.csv`（`value` 列，承接正文里确实没有对应表格的数，如扫描文件总数）或 `--ignore REGEX` 显式豁免，被豁免的数字会在 `number_issues.csv` 里以 `severity=info` 留痕，不会静默消失。

交付前先生成审稿包，让模型自审一遍：

```bash
python scripts/review_pack.py --data output/dataset/analysis.csv --stats output/stats \
  --figures output/chart_pack/chart_manifest.csv --verify output/verify/number_issues.csv \
  --qa output/qa/qa_report.json --decisions decisions.jsonl \
  --research-gate output/research_gate.json \
  --sample-flow output/coding/sample_flow.csv \
  --missing output/coding/missing_by_source.csv --out output/review/review_pack.md
```

`review_pack.md` 只汇总已有产物：样本与缺失、模型 N、图表状态、数字溯源 error、未决 decisions，再给出“审稿人最可能先问的五个问题”。它不替你回答，只确保你不会在没看见这些问题时交付。

再按 `references/06-qa-checklist.md` 人工过一遍。重点不是格式，而是：

- 样本流程每一档数字能对上。
- 重复副本已从分析样本移除，或明确报告未移除的影响。
- 正文每个 N 与对应表/图/模型一致。
- 图表与正文说的是同一个方向，没有“图上升、文说下降”。
- PDF 中的图注编号能识别“图1：”“图 1.”“Table 1:”等写法；低分辨率检查只看图幅足够大的图片；空 CSV 会直接报错。
- 理论编码变量在方法部分说明来源，不写成从原始资料直接测得。
- 结论使用“关联/对应”，不使用因果措辞。

---

## 脚本清单

以下命令假设当前目录是 skill 根目录；如果从项目目录运行，把 `scripts/` 换成 skill 的绝对路径。

| 脚本 | 作用 |
|---|---|
| `scripts/audit_corpus.py` | 扫描任意资料目录：文件状态、文本/页数、有效字符、MD5、mtime、重复、内容级重复（`--content-dedupe`）、抽样框、格式分布、年份提示；`--resume` 断点续跑（size+mtime 未变复用整行、抽样框不一致拒绝） |
| `scripts/dedupe_corpus.py` | 基于审计结果生成去重计划；`--apply` 移动/复制到 `_duplicates/`，`--undo` 反演，写 `move_log.csv` |
| `scripts/make_coding_sheet.py` | 从 PDF/Word/PPT/HTML/文本抽取全文与关键词证据句（对任何文体读法一致，不内置领域字段）；`--extract profile.json` 走字段抽取层（只接受项目剖面，拒绝包内示例），产出 `dataset.csv`/`evidence.jsonl`/`run.json`；`--resume` 断点续跑（extract_journal.jsonl 逐文档记账、frame 不一致拒绝、输出逐字节一致） |
| `scripts/compute_kappa.py` | 两轮独立编码对齐：按文档+字段算每变量一致率与 Cohen's κ，逐条分歧带双方证据行，生成 `kappa_report.csv`/`disagreements.csv`/`coding-sample.md` |
| `scripts/sample_review.py` | 结构化抽样复核：种子必填、分层+强制 flagged 维度、同 seed 逐字节复现；`tally` 统计保持/改判/无法核对并列改判项，未裁决完 exit 2，`--fail-above` 守用户上限 |
| `scripts/clean_data.py` | 按项目配方（draft/cleaning.json）执行清洗：去重/值映射/类型转换/越界标记/缺行剔除，逐步写台账（cleaning_log.jsonl 指纹链）与 flow.csv；未声明的清洗一律拒绝，max_drop_fraction 超限中止，`--emit-template` 起步 |
| `scripts/mine_candidates.py` | 材料挖掘候选层：TF-IDF 关键词/共现词对(PMI)/NMF 主题，候选行带 rel_path+行号证据锚；产出候选表+mine_receipt.json（corpus/停用词 sha256、seed 入账）；候选不是事实，采纳归研究者；需 scikit-learn，可选 jieba |
| `scripts/report_tables.py` | 全量数据报表：变量/描述统计/频率/交叉/缺失/重复 + data_report.md；report_index.json 以 sha256 把每张表锚到数据集字节（可接 cleaning_log 与 missing_by_source）；报表与数据报告自动登记进 table_map/doc_map |
| `scripts/scope_conformance.py` | 通用范围符合性：分析表分类列的实际分布对照 scope.json 的 include 白名单，范围外命名类别 n>0 退出 2，缺失值 warning，`--cell-cols` 报小样本单元格；不含任何学科词 |
| `scripts/stage_audit.py` | 通用阶段双遍审计台账校验：读 stage_audit.jsonl，每阶段≥2遍、角度互异、每遍有证据（命令+退出码/抽样/检查项）、无未解决 finding，否则退出 2；不含任何学科词 |
| `scripts/layout_conformance.py` | 通用目录骨架与命名覆盖：output/ 一级目录归入闭合规范骨架（已知别名自动归组，自定义目录须注册表 layout 声明），表/文档组交付件须有 table_map/doc_map 中文标题；杂散目录/无标题交付件退出 2，分组结果写 output/qa/layout_conformance.json 供查看器读取；不含任何学科词 |
| `scripts/extract_lib.py` | 字段抽取层的通用原语（数值/数量/日期/时长/键值块/段落/枚举/证据窗口/否定/同义词/去重计数）+ profile 校验；**不含任何学科词** |
| `scripts/paper_figures.py` | 按 `paper.json` 组装多面板正文图（GridSpec + 面板字母），产出 `FigureN.*` 与图表 manifest（可注明配色用途） |
| `scripts/assemble_manuscript.py` | 按 `manuscript.json` 组装 Word 成稿：三线表（1.5/0.75/1.5 pt）、行不跨页、表头重复、图按栏宽嵌入、图题不可分页、中西文字体分别设置、首行缩进按字符；交叉引用 `[@tab:N]`/`[@fig:N]` 渲染为 Word REF 域（前向引用可查、坏引用 exit 2）、参考文献块（悬挂缩进+可选编号）、目录 TOC 域；同时写 `*_numbers.csv`（文档实际印出的每个 N）、`figure_map.json` 并把正文表合并进 `output/table_map.json` |
| `scripts/verify_numbers.py` | 数字溯源：表内合计、表图同值、正文数字找回表（`--numbers`/`--figure-data` 承接叙述数与图内数）、图号引用、样本 N 一致、漏斗按链单调（`note` 写 `funnel=名` 分链） |
| `scripts/text_extract.py` | 通用文本抽取与文件检查（PDF/DOCX/ODT/PPTX/XLSX/HTML/文本/图片/音视频）；有 CLI（`--root`/`--file`/`--out csv\|jsonl`/`--text`） |
| `scripts/analysis_utils.py` | 内部共享函数：样本筛选、结果类型识别、二值标签编码；由自动统计/图表脚本导入 |
| `scripts/csv_to_spss_syntax.py` | 由 CSV 表头生成 SPSS `GET DATA` 语法；清理非法/重复变量名并写变量标签 |
| `scripts/auto_stats.py` | 自动描述统计、组间检验、相关、单变量模型（多分类自变量哑变量化）、完全分离检查；`--spec` 多变量层支持 logit/ols/mixed/cox/logrank + 交互项、抽样权重、多重插补（Rubin 合并） |
| `scripts/methods_lib.py` | 十六种方法的统计内核（描述/正态性/卡方/t/ANOVA/事后/相关/OLS/Logit/PCA/EFA/信度/效度/聚类/判别/时序/中介/Kano/非参数）；SEM 显式拒绝 |
| `scripts/methods_pack.py` | 按 `methods.json` 跑 1–16 号方法（另加非参数与二元 Logit）：前置条件不满足即 `skipped` 并给替代，产出 `methods_report.md`/`methods_manifest.csv`/每法一图 |
| `scripts/auto_chart_pack.py` | 按列角色自动生成数据质量/分布/双变量/聚类/时间/模型诊断/生存/Sankey/UpSet 图与 manifest；默认不设总图数上限；`--width-cm` 全包统一改输出宽度（3–30，px_width 随宽度换算） |
| `scripts/pubfig.py` | 出版图统一风格、Wilson CI、森林图、热图、提琴、ROC/PR、PCA、MDS、聚类、KM、控制图等 30+ 图型；`compose_figure()` 组装多面板并回读 PNG 校验 dpi |
| `scripts/export_pdf_hires.py` | Word→PDF 并回填 600 dpi 原图 |
| `scripts/qa_outputs.py` | 检查 PDF 有效 dpi 与**最小字号**、docx 图表数量、空数据、重复键、manifest 的 N/图注/路径、分类色灰度与色盲可分性 |
| `scripts/check_decisions.py` | 校验 `decisions.jsonl`：schema、证据 span/引文、候选值是否真的出现过、重复 target、`needs_human` 未决；有 error 退出 2 |
| `scripts/review_pack.py` | 交付前审稿包：样本/缺失、模型 N、图表状态、数字溯源、未决 decisions、五个审稿人问题；Markdown + JSON 双出，自动登记进 doc_map |
| `scripts/verify_dataset.py` | 仅归档档：对 CSV 审计视图逐格回读来源、哈希、位置并复算派生值。可投稿档不要运行 |
| `scripts/run_model.py` | 执行 Agent 自选的任意分析命令，记录实际输入、代码、输出的 SHA256、退出码与日志；不限制引擎或模型族 |
| `scripts/research_gate.py` | 检查原始文件全覆盖、数据复核版本、开放模型清单、缺数回查、样本键与实际运行回执 |

## 参考文档

| 文件 | 何时读 |
|---|---|
| `references/01-corpus-audit.md` | 开始审计、遇到重复/损坏/扫描件/多格式时 |
| `references/02-coding-protocol.md` | 设计变量、写 codebook、做信度检验时 |
| `references/03-analysis-spss.md` | 设定模型、写 SPSS 语法、解释 OR 时 |
| `references/04-figures-publication.md` | 画图、选颜色、导出投稿文件时 |
| `references/05-manuscript-assembly.md` | 排 Word、导 PDF、处理图注时 |
| `references/06-qa-checklist.md` | 投稿/交付前逐项检查时 |
| `references/07-chart-atlas.md` | 选图型、对应 SPSS 高级图形、确定图表数量时 |
| `references/08-analysis-expansion.md` | 主模型之外还要跑哪些分析、如何记录做/不做时 |
| `references/09-field-extraction.md` | 要把材料取成一行一个观测的结构化数据（写 profile、查证据、判 NA）时 |
| `references/10-contracts.md` | 查脚本之间的键列/漏斗/N/缺失值/退出码约定时 |
| `references/11-methods-catalog.md` | 选方法、查变量要求与前置判据、写结果句式、避开常见误用时 |
| `references/12-exhaustive-research.md` | 只在归档档阅读：全资料发现、开放数据集/模型、全格回源复核、补数闭环与交付契约 |
| `references/13-contract-v2.md` | 归档档深度核验链的契约结构：账本种类、状态机、复核签名与发布事务（`contract_v2`/`release`/`gate_facts` 深检的判据来源） |
| `references/14-reviewed-workflow.md` | 只在归档档阅读：契约账本层当前维护流程、真实复核、版本失效与成稿发布 |
| `references/15-gate-reports.md` | 工作台门禁报告的入口、覆盖范围、迁移与恢复；接 `data_analysis_*` 工作台或排查门禁报告时 |

## 模板

- `assets/scope-template.md`：研究范围、纳入/排除标准、样本流程骨架。
- `assets/codebook-template.md`：变量编码手册骨架。
- `assets/figure-spec-template.md`：图注与制图规格表。
- `assets/figure_map.example.json`：Word→PDF 回填图的映射示例。
- `assets/delivery-checklist.md`：交付清单。
- `assets/coding-keywords.json`：可替换的关键词词典（通用占位示例）。
- `assets/chart_config.example.json`：列角色、标签、分析样本筛选（`filter_query`）示例。
- `assets/analysis-manifest-template.md`：主分析/扩展分析/跳过项清单。
- `assets/research_registry.example.json`：开放数据集、原始材料覆盖与模型清单的项目注册表示例。

## 最常见的翻车点

1. **把文件夹里的文件数直接当样本量。** 必须先扣掉元数据、损坏、重复、格式不支持、范围外。
2. **只按文件名去重。** 同一内容常有“带标识/不带标识”“- 副本”“(2)”多个版本。
3. **描述统计 N 与模型 N 混用。** 模型有缺失值、筛选条件，N 一定更小。
4. **把“资料提到某情况”当成“实际发生了某结果”。** 这是文本关联，不是因果效应。
5. **Word 导出的 PDF 看着正常，图其实只有 200 dpi。** 必须回填并验证内嵌图像宽度。
6. **只画一张主结果图。** 分布、异质性、稳健性、诊断图都没画，用户只能反复追问。
7. **把引用/附件里的内容当成主资料。** 文书类型、报告类型、网页导航等要按标题/正文结构判断，不能只看全文关键词。
8. **结果是“是/否”文本却直接当连续变量。** 用 `outcome_map` 明确正类，或在 CSV 里编码为 0/1；脚本不会猜正负方向。
9. **审计只数某一种格式，静默漏掉其他文件。** 所有文件都要有状态；`total_files` 要能和资源管理器对账。
10. **把表格数据塞进文本编码。** CSV/Excel 直接走 `auto_stats`/SPSS 流程；文本编码适合文档、访谈、网页等非结构化资料。
11. **子样本/并案混入无关类别。** 分析样本的类别分布必须用 `scope_conformance.py` 对照声明的纳入白名单核对（任何学科）；只给主数据集加范围过滤、却让另一数据集"字段非空就入组"，会把无关类别画进图里。
12. **自编写稿脚本跳过命名源。** 不用 `assemble_manuscript.py` 时也要产出 `figure_map.json`/`manuscript.json`/`table_map.json`/`doc_map.json`，否则图/表/文稿在查看器里全是英文文件名；终检 `--figure-map`/`--manuscript-spec`/`--table-map`/`--doc-map` 与 `layout_conformance.py` 的命名覆盖会卡住。
13. **自定义目录不声明就交付。** `output/` 下超出已知别名的目录必须在注册表 `layout` 挂到规范组，否则 `layout_conformance.py` 判杂散目录 exit 2；查看器也只按分组报告渲染规范目录。
14. **宿主有计划/目标工具却不用。** 长流水线没有经批准的计划、没有目标跟踪，跑到一半跑偏，或闸门未过就把目标标成完成——顶部「计划模式与目标模式」节明确禁止；宿主不支持时也要书面计划+任务清单，不是什么都不做。

