# 门禁报告与兼容状态

`scripts/gates.py` 只读检查当前项目产物，使用 `contracts/gates/catalog.json` 的稳定判据定义。

目录共有 76 个稳定 ID：70 个实际历史 ID，加源图分辨率/字号、v2 发布就绪、决定文件事实及两项正文题注 N 核验。61 个由技能负责，15 个由工作台负责。目录的 implemented 表示有实际检查入口，不能当作项目检查已通过。技能负责研究质量判定，工作台保留挂载、工作流、真实裁定与协议校验。

首次显式创建策略：

```text
python scripts/gates.py init-policy --root PROJECT
python scripts/gates.py evaluate --root PROJECT --stage dataset --checkpoint data-ready
python scripts/gates.py evaluate --root PROJECT --stage qa --checkpoint delivery-ready
python scripts/gates.py migrate-policy --root PROJECT --mode skill
python scripts/gates.py recover --root PROJECT
```

策略保存在 `.workbench/gates/policy.json`。独立 CLI 初始化默认 compare；兼容当前契约的工作台新项目直接消费包内 policy-template.json，默认 skill。已有项目保留原模式，显式迁移保留 before/after 记录。legacy 使用旧规则，shadow 只生成新报告，compare 并列显示，skill 正式使用技能事实；缺报告不会回退。删除硬要求、放宽 NA 或推迟到期点均被拒绝。升级目录后显式迁移策略再体检。

所有模式继续可选；legacy 的自动生产不强制追加技能体检，但显式 `data_analysis_gates(action=inspect)` 仍可运行技能检查，返回 `inspectionFacts`，不会替你切换模式或阻止继续研究。迁移回执说明前后模式，状态工具区分“兼容执行成功”和“完整质量验收”。

自定义产物使用注册表 `artifact_paths` 的逻辑路径到实际相对路径映射（目录映射作用于其子路径），报告绑定实际文件和注册表；映射不删除缺项，也不将缺文件视为通过。自定义复算器可通过 `verification.adapters` 登记，CLI 和门禁共享同一实现及导入依赖。报告紧凑写入，消费者不以固定 8 MiB 或固定来源数量拒绝合法研究规模；每条证据、成员及当前哈希仍完整核对。工具只回摘要，完整报告和单项证据保留。

面板可初始化、重做、停止、恢复体检及打开哈希绑定的证据；模型入口为 data_analysis_gates。体检不经过生产 Runner，不虚构 runId，不改生产退出码。面板、工具与自动链使用相同的消费和准入逻辑。force 不能绕过正式 skill 准入或项目锁。NA 必须有目录许可、规则和范围证据；尚未到期的要求不提前阻断生成其证据的步骤。

报告位于 `output/gates/runs/<attempt>/report.json`，当前权威指针位于 `output/gates/state/<stage>.json`。阶段同名 JSON 只是兼容副本。体检失败保留旧报告历史，但不能继续用旧报告作为当前通过。`completed` 仅表示体检完成，不代表检查通过。

生产和体检共享 owner-token 排他锁，checker 借用宿主锁。取消会终止进程树，等真实退出才释放。恢复拒绝存活 owner/child 或外机锁。原件、目录成员、规则、脚本、模型样本和产物按内容绑定；同大小同时间改内容也会失效。解释器与依赖版本也参与当前性验证。报告不写机器绝对路径；外部资料仅通过本机 roots.json 中明确登记的 material 根解析。换机器后需重新登记映射并体检。

检查原始图像在实际 DOCX/PDF 的安置，复用 layout_check.check_placement。PNG 元数据不能证明最终有效分辨率或字号。旧数字检查回执缺少输入与输出绑定时必须重新执行 verify_numbers，不得把旧空问题表当成当前通过。

统计支持 auto_stats 实际行号回执、v1 run_model 任意引擎样本键回执和 v2 当前执行记录。缺 in_analysis 仅在数据集明确登记 analysis_selection.kind=all、reason 和非空 evidence 文件清单时接受全部纳入。未登记就保持未判。旧生产没有内容回执时需重跑对应最小生产阶段；体检不能事后伪造生产凭据。

结论比较检查正文登记文本和当前数据/执行产物。不能机器解析的引用保持未判。v2 仅在当前发布 evaluation.project_ready 为 true 时满足完整研究就绪，有限范围发布不能替代它。人工签收和代码阅读覆盖记录绑定当前 snapshotHash；coverage.checked 不能覆盖失败/未判的机器事实，AI 不得代签真实人工项。

修改 schema 后运行 `python tools/build_gate_schemas.py`，更新代码后运行 `python tools/build_gate_contract.py`。manifest 绑定脚本、规则、资源、profile 和协议。完整回归后运行 `python tools/build_skill.py` 与 `--check`，验证源码、dist、干净解包与安装副本一致。安装不自动迁移或签收已有研究项目。

jsonschema 4.x 是运行依赖，完整依赖见仓库 requirements.txt；测试依赖见 requirements-dev.txt。工作台跨语言验收用 DSA_SKILL_ROOT 显式指向待测包，运行 npm run test:gates:integration，不隐式误测旧安装副本。原始资料、复读批准和真实人工签收不由开发测试生成。

报告所需能力包含 project-aliases-v1 与 package-closure-v1：每个项目路径别名必须仍指向原来的逻辑根和文件；manifest 除逐文件哈希外还核对整个发布目录的成员集合。增加未登记的可导入脚本也会失效，不能继续使用旧绿灯。集合扫描失败或超预算保持未判。

工作台的可选 datasets/index.json、models/index.json 若存在，必须与技能登记和实际执行一致，不能静默忽略冲突。数据检查遵守登记的 encoding/delimiter；模型输入必须属于已登记待核验数据。正文段落和选列后的表格内容按实际 DOCX 核对，数字断言至少引用一个真实登记的数据集或模型，常量等式不能充当研究溯源。

签署快照覆盖问题台账、复核报告、资料选取记录、文件集合、技能及工作台检查代码、Python 依赖和宿主版本。仅重做相同内容的体检不会使签署失效；增加源文件或脚本、改问题台账或检查实现会要求重检/重签。先写 report.md 和明确的空/非空 issues.jsonl，再取得快照，把 snapshotHash 放在 coverage.json 的逐项记录和签署中；不要求在 report.md 中回写其自身快照哈希。coverage 的十二项均须有实际说明，空快照不能通过。损坏/重复的问题行保持未判；deferred 仍是未解决问题，wontfix 必须写理由，正式路径拒绝在损坏台账上覆盖保存。

生产回执须记录实际解释器与依赖版本，缺失时不能证明当前环境下的新鲜度。识图日志区分 input_sha256（渲染页）、source_sha256（原件）和 derived_sha256（识别稿）；旧日志不补造哈希，需重跑识别再复核。宿主管理的派生根须与真实缓存挂载一致。错误解释器产生的不完整 state 可在修正后重新体检；历史请求/报告确定后续 generation，原 state 以 previous-state.bin 原样归档，不靠覆写历史报告修复。
