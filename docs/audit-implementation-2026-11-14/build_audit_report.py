"""Materialize the independent audit and its complete requirement matrix."""
import hashlib
import json
from pathlib import Path
import platform
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SRC = "empirical-research-pipeline/scripts/"

# Independent manual review, not a transformation of the implementer's pass flags.
FINDINGS = [
 ("F01", "P1", "事务暂存可在提交前覆盖原件", ["C09"], [("txn.py", 214)],
  "stage() 直接使用 staging / rel，没有拒绝绝对路径、盘符或目录逃逸。绝对路径使 staging 前缀失效。临时目录内的 materials/original.txt 从 ORIGINAL 变成 OVERWRITTEN，且尚未 commit。",
  "原件保护不能只由旧 run_model 路径提供；新事务入口已经可以直接写坏输入。",
  "暂存目标必须经解析后限制在本次 staging 内；拒绝绝对路径、..、链接逃逸以及输入/输出别名。所有写入入口统一使用这一检查；反例应在任何写操作之前被拒绝。"),
 ("F02", "P1", "MILP 被当作连续 LP 求解并错误认证全局最优", ["C04"], [("models.py", 591), ("models.py", 485)],
  "min x，x>=0.5，x 为整数，独立解析答案为 x=1。公开 register/solve 返回 x=0.5、objective=0.5、certified_global。family=milp 被改成 lp，linprog 未收到整数性约束。",
  "输出数值与声明模型不是同一个问题；错误还被标为已认证最优，可直接进入图文结论。",
  "按模型类别选择真实求解器并完整传递整数域、边界和约束；求解后独立检查整数性和约束残差，再决定认证等级。未实现的类别显式 unsupported，不能降成另一个模型。"),
 ("F03", "P1", "非线性求解忽略边界且未复核可行性", ["C05"], [("models.py", 498)],
  "min x²，x>=2，解析答案为 x=2、目标值4。默认 BFGS 路径给出 x≈-1.89e-8、目标值≈3.57e-16，仍记 local_optimum 和 execution.success。",
  "违反用户约束的解被当成可用最优解。constraints 元数据并未变成独立数值约束检查。",
  "选择支持实际问题约束的算法，显式拒绝不支持的约束组合；回算边界、等式/不等式残差、可行性和终止原因，求解器 success 不单独决定解的质量。"),
 ("F04", "P1", "v2 发布门禁仅信状态文本，可绕过来源复核与方法评估", ["C01", "C02", "C14"], [("release.py", 89), ("release.py", 155), ("release.py", 204)],
  "只写 status=verified、error_count=0 和一个不存在的数据集 ID，evaluate 返回 complete。只有 OLS 拟合及数值比对、没有任何数据 final 报告且 method_assessment=not_assessed，也返回 complete。必需缺口仍 open 时 gaps_closed.ok=True。",
  "正式发布状态无法证明用户要求的逐格回源、模型适用性和补数完成。旧 research_gate 仍可工作，但 release.py 没有实际执行其约束，不能声称新入口已统一消费两套闸门。",
  "从模型输入、数据集、图文产物展开真实发布依赖；调用最终报告的当前版本复验（已有 validate_final_report 可复用），消费实际研究覆盖、方法/设计与缺口终态，不能只读手写状态。范围受限也不得跳过声明结果所需的硬依据。"),
 ("F05", "P1", "旧数值校核可给新数据和新估计续签", ["C17"], [("release.py", 155), ("validation.py", 161)],
  "先验证 slope=3 的 M1，再用新 CSV 重注册并拟合 slope=7 的同名 M1，不重做独立校核。results_validated.ok=True，release=complete。旧验证中仍是旧数据哈希与估计3。",
  "同一个模型 ID 不等于同一个模型版本；追加材料或重跑后，旧证明被错误沿用。稳定性入口也只检查同名验证状态。",
  "验证目标绑定 spec/result 的 revision、内容哈希、输入/代码/环境和目标参数语义；消费时比对当前结果。数据变更和 refit 必须使旧校核及其下游失效。"),
 ("F06", "P1", "普通账本读取不执行契约、特性和内容哈希校验", ["C03"], [("contract_v2.py", 1058), ("contract_v2.py", 1075)],
  "合法写入 draft 论断后，直接改 JSONL 的正文和状态为 supported，不更新 content_hash。Project.read 和发布消费仍接受并 complete；显式 validate_record 才报告 content_hash mismatch。latest 还以 tolerant=True 跳过格式损坏记录。",
  "写入时有 validate_record 不代表消费时可信；手改、损坏、未知必需语义或坏的末条记录可能绕过本来存在的保护。",
  "所有正式消费者通过严格读取器进行类型/特性/哈希/修订校验；恢复性读取单独标记不完整，不得静默选旧版本后发布。摘要不能提供对恶意重签名的真实性保证，审计日志仍需实际依据。"),
 ("F07", "P1", "复核工作台与 final 使用不同的单元格签名", ["C08"], [("review_workbench.py", 93), ("review_workbench.py", 276), ("verify_dataset.py", 457)],
  "3×4 合成表完成真实第二次原 CSV 读取，工作台导入为 confirmed=12、complete=True；数据、证据、快照未变，写出的12条 review 全被 final 判为 review belongs to different data/evidence。工作台只哈希 dataset/key/column/value，Verifier 还绑定全部依据与证据记录。",
  "T11/T12 单独测试可过，但用户最关键的工作台→整表 final 链路无法正常完成。",
  "复用唯一的 prepare 目标签名与上下文，快照字段也统一；工作台记录既绑定真实第二遍输入，又能被正式 Verifier 消费。增加公开 CLI 串联验收，不允许测试用模板自动签齐来代替该链路。"),
 ("F08", "P1", "OCR/ASR 来源复读事件被误判成不存在的数据格", ["C21"], [("ocr_provider.py", 405), ("asr_provider.py", 303), ("verify_dataset.py", 609)],
  "OCR.adjudicate 产生 dataset=<source-unit> 的合法来源复读事件；v2_review_bound 将所有 review_event 当作数据格复核，报 review event points at a cell that does not exist。ASR 生产者采用同样事件形式；本次独立反例实际执行 OCR 事件生产/消费，没有声称重跑真实识别引擎。",
  "恢复层与数据 final 的事件语义未接通；有来源复读反而会污染后续 final。",
  "区分来源单元复读和数据格第二遍复核的类型/目标；各自校验后建立版本依赖。来源复读不能替代数据整合后的逐格复核，也不应被当成坏格事件。"),
 ("F09", "P1", "局部检索回执被冒算为全资料检索覆盖", ["C12"], [("search_index.py", 211), ("search_index.py", 241)],
  "a.txt、b.txt 两份资料，目标只在 b.txt。search(...sources=['a.txt']) 返回0命中，但回执 sources 保存整个索引来源；searches_cover 对两文件返回 complete=True、searched_sources 包含 b.txt。命中 limit 提前退出同样未记录未扫描范围。",
  "可以在仍有可获取数据时声明已经穷尽，直接违背不遗漏与尽力补齐要求。",
  "回执记录实际扫描单元/范围、过滤条件、停止位置与完整性；覆盖计算使用实际执行集合。命中分页与全量扫描分别记录，未扫描文件不能支持 exhausted。"),
 ("F10", "P1", "索引与发现有未披露的固定截断", ["C18"], [("search_index.py", 97), ("discovery.py", 208), ("discovery.py", 261)],
  "完整恢复的长文本，目标位于第200001字符之后，索引只保存前200000字符，检索0命中且来源仍宣称已搜索。代码还将文本发现限前4000行、工作表发现限前5000格，没有继续位置或部分范围回执。本次运行反例确认索引截断，另两处为直接源码证据。",
  "大材料尾部静默丢失，200k行 CSV 流式测试无法证明索引/发现路径无丢失。",
  "分块索引/发现并保留偏移与全量对账；若有显式预算，报告实际部分范围和继续位置，不能将部分索引计作全文覆盖。"),
 ("F11", "P1", "补数关闭只是填字段，没有实际数据整合与复核闭环", ["C13"], [("gaps.py", 75), ("gaps.py", 114)],
  "真实运行0命中检索后，attach_search 可宣称 found；resolve 接受不存在的数据集 does-not-exist 并置 resolved、found and integrated；completeness.errors 仍为空。没有证实值、数据集版本、目标格、重新 final 或模型重评。",
  "任务台账中的 resolved 不能证明补数已经完成。",
  "found 指向实际命中/原件定位；resolved 指向实际纳入的数据集版本和目标格，并消费整表重新复核及相应模型重评回执。不可取的数据保留终态理由和真实检索范围。"),
 ("F12", "P1", "任意 trace 字典即可让无来源数字进入且通过 DOCX 检查", ["C15"], [("manuscript.py", 107), ("manuscript.py", 348)],
  "不存在任何模型或数据依据，trace 仅写 model=DOES_NOT_EXIST；数字999999仍排进 DOCX，verify_printed.ok=True。resolve_numbers 只检查 trace 非空，后续比较同一套替换文本并不能证实数值。",
  "论文数字看起来有溯源字段，实际上无法回到真实结果。",
  "数字从当前已核证据/结果中解析，绑定对象版本、参数、尺度、分母、单位和格式/舍入；拒绝找不到目标或与真实值不符的 trace。最终数字校验和发布门禁实际消费该结果。"),
 ("F13", "P1", "固定组稿目录会静默丢弃已登记章节", ["C16"], [("manuscript.py", 44), ("manuscript.py", 206), ("manuscript.py", 381)],
  "5个默认正文块外再登记 appendix；build_docx 报 blocks=6，只输出5块，附录消失；DOCX verify_printed.ok=True，因为只遍历实际生成的 spans。源码同时固定必需章节和150/400字符门槛，与方案按研究/期刊/用户选择结构和字数冲突。PDF验证另有全块文本检查，但并不能使DOCX路径的静默丢失合理。",
  "用户已完成内容会被漏写；字数和固定章节也无法代替完整研究叙事。",
  "将章节顺序/必需项/篇幅改为用户或 Agent 选择的稿件配置；对全部登记块与输出逐项对账。未知章节保留或明确拒绝，绝不静默跳过；DOCX与PDF均检查遗漏。"),
 ("F14", "P1", "开放模型接口仍是白名单，自定义 runner 参数未执行", ["C06", "C07"], [("models.py", 86), ("models.py", 314), ("models.py", 354), ("models.py", 566)],
  "family=cox 即使声明用户实现仍被 unknown family 拒绝。内置允许的 gee 通过注册后，fit(runner=...) 不调用提供的函数，记录 family gee needs a custom runner。solve 的 runner 同样未被使用，ode/simulation/custom 都走统一 nonlinear 路径。",
  "v2 的开放适配要求没有落地。旧 run_model.py 仍有任意命令能力，所以此结论限定于新模型注册/执行/消费链，并非否认旧工具全部功能。",
  "内置 family 改为推荐适配器目录；允许显式外部执行器、扩展角色及结构化/原生结果契约。真正调用并记录 runner，缺实现如实 unsupported，不能把没有执行器说成数据不足。"),
 ("F15", "P1", "绑定的代码改变后仍可发布", ["C10"], [("txn.py", 241), ("txn.py", 266), ("txn.py", 288)],
  "bind_code 记录 analysis.py 旧哈希后修改该文件，commit 成功，manifest 中仍写旧代码哈希。提交前只 _check_inputs，不复核 self.code。",
  "发布回执声称的计算程序与实际当前文件不一致，无法满足版本可溯源。",
  "执行前固定实际代码/配置/环境，提交前复验其身份；更强的方式从不可变快照执行。改变时停止正式发布并保留真实失败/过期状态。"),
 ("F16", "P1", "父版本校验与发布不是一个并发原子操作", ["C19"], [("txn.py", 253), ("txn.py", 288)],
  "两事务都声明同一旧 result.txt 哈希、输出不同值。用线程屏障让两个 _check_parents 都在发布前完成，两者均 commit 成功，最后一个指针覆盖前一个，没有 ParentVersionError。该反例只控制调度，不改变校验逻辑。",
  "所谓过期父版本保护存在检查与使用间的竞态；事件或发布结果可能丢失。",
  "在同一项目提交锁内重新检查父版本并原子更新指针，或使用真正比较交换；并发测试必须使用不同输出和相同预期父版本，不能只测两次相同内容的幂等性。"),
 ("F17", "P2", "运行超过一小时的活锁可被其他运行抢走", ["C11"], [("txn.py", 118)],
  "锁元数据 PID 为本进程且仍活着，将 at 设置为两小时前；第二把同名锁仍成功 acquire。_stale 在确认 PID 活着后继续按时长判过期；release 也没有所有者令牌校验。",
  "长时间OCR、建模或大文件工作可能失去互斥，原持有者释放时还可能删除后来者的锁。",
  "明确活进程锁或租约/心跳模型；使用唯一所有者令牌，回收与释放都确认持有者身份。测试长任务、PID复用、主机变化与持有者中断。"),
 ("F18", "P1", "研究设计诊断只看字段存在，False 也能判通过", ["C20"], [("designcheck.py", 207)],
  "设计 clustered=True，结果 diagnostics 中 cluster_robust_or_mixed=False，linkage.ok=True。用字段不为 None/空串/空列表作为满足条件，不能表达未完成、失败、不适用或适用性依据。发布又没有消费 design:{spec} 的失败结果。",
  "没有真正进行的聚类修正等方法评估可被声明为已满足。",
  "诊断采用有含义的状态、数值、方法及依据；按诊断定义判断，而不是统一真值或非空检查。不适用必须有理由；发布消费当前设计/方法评估。"),
 ("F19", "P1", "设计联查不接受模型注册表正常产生的相对路径", ["C23"], [("designcheck.py", 240), ("designcheck.py", 378)],
  "模型公开注册/载入返回 dataset=data/linear.csv，设计 role_accounting 对同一 spec 直接报 input dataset path must be absolute。CLI roles 将原样读取的 spec 传给该函数；link 还查 res:M1，而模型默认结果ID是M1，结果诊断也放在 payload 内。独立反例实际确认相对路径冲突，其余两处为源码接口不一致。",
  "生产者和消费者分别测通，实际模型→设计评估链路却无法按文档正常使用。",
  "统一项目根解析、输入角色和结果ID/载荷读取契约；通过同一注册 spec 运行 fit→design roles/link→release 的CLI集成验收。"),
 ("F20", "P1", "未实现的稳定性规格被静默丢弃，零运行也能 passed", ["C22"], [("validation.py", 180), ("validation.py", 211), ("validation.py", 304)],
  "cluster/lag 属于公开 VARIANTS 和CLI允许值，但 _variant_specs 没有实现分支而 continue。明确只请求这两项，n_variants=0、actual_variants=[]，仍生成 status=passed。当前也未见真正完成T21要求的多重比较/完整样本外预测链路证据。",
  "用户要求的规格消失，稳定性空集被包装成成功；不能因此声称全面模型评估完成。",
  "每个请求规格都保留 executed/failed/not_applicable/unsupported/not_run 及理由；零执行不算稳定性通过。按预定检验族记录原始/调整值与真实数据划分/预处理/样本外表现；不可用项不能静默消失。"),
 ("F21", "P1", "60张验收卡的观察结果与原场景多处错配，证据门检不足以证明全通过", [], [("../../docs/implementation/ACCEPTANCE-RESULTS.json", 64), ("../../tools/acceptance_cards.py", 340), ("../../tools/acceptance_cards.py", 368)],
  "A21验收开放目录，observed却是数学模型无N；A23验收数值/方法未核不得推断，observed却是非线性超时；A34完整论文对应环境漂移，A35图元一致对应缓存，A36密集标签对应步骤预算，A56结果可比性对应limited，A57求解质量对应partial门禁。validate只证明字段与路径存在；本次drift为0 errors、105 warnings（60条命令不在证据、44条重复证据、1条证据晚于观察），涉及60卡。",
  "842测试通过可以核实，但‘60场景逐项实际集成通过、40项全部完成’没有被这些记录充分证明，其中多项已被本次反例推翻。不能将当前期望文本SHA和自填时间戳当成历史执行/冻结证明。",
  "逐卡绑定实际测试方法、冻结fixture/oracle和配置哈希、执行日志、产物、判定及变体范围；观察结果应回答本卡问题。错配/反例项改failed或partial，缺证据项unassessed。阶段门禁实际执行并校验对应证据，不根据自报passed自动验收。"),
]

TASK_NOTES = {
 "T01": "基线/本次回归可核；新增闭环反例未纳入原验收。",
 "T02": "不能签收：正式读取绕过契约校验，F06。",
 "T03": "依赖图有局部测试；当前结果版本仍可错用旧验证，F05。",
 "T04": "真实结构恢复有回归证据；恢复到final链被F08阻断。",
 "T05": "真实OCR与坐标测试通过；来源复读消费错误F08。",
 "T06": "合成续表/合并格/公式缓存等局部测试通过；不外推全部表格。",
 "T07": "Vosk真实提供方等回归通过；ASR同类事件消费需修复F08。",
 "T08": "发现实现有固定4000行/5000格截断，F10。",
 "T09": "实际搜索存在；范围回执错误、全文截断，F09/F10。",
 "T10": "不能签收补数闭环：F11/F04。",
 "T11": "工作台可导出/导入；不能接final，F07。",
 "T12": "差异记录有测试；第二遍完成不能被final消费，F07/F08。",
 "T13": "v2检查有代码与测试；工作台/来源事件接口未闭合，F07/F08。",
 "T14": "同名/别名/冲突等局部合成测试通过；全研究整合未充分证明。",
 "T15": "连接基数和单位换算有局部测试；诊断/发布完整链未签收。",
 "T16": "固定family/role目录与开放要求冲突，F14。",
 "T17": "runner未调用，设计消费者格式不兼容，F14/F19。",
 "T18": "method未核仍complete，旧验证可续签，F04/F05。",
 "T19": "MILP整数域与非线性边界错解，F02/F03。",
 "T20": "诊断False也通过、正常spec不能消费，F18/F19。",
 "T21": "cluster/lag静默未运行且passed；完整多重/预测证据不足，F20。",
 "T22": "OLS/IRLS局部独立算术通过；未绑定当前版本，F05。",
 "T23": "传播函数局部测试通过；真实refit后旧验证仍放行，F05。",
 "T24": "缓存/检查点局部测试通过；正式发布代码漂移未阻断，F15。",
 "T25": "当前环境快照和隔离导入可核；不是独立重建环境后的全研究重跑证明。",
 "T26": "论断规则局部测试通过；账本改写和无依据数字可过，F06/F12。",
 "T27": "元数据/摘录访问有合成测试；未实际审计真实论文/撤稿更正服务全链。",
 "T28": "真实DOCX/PDF回归通过；数字无绑定、附录丢失、结构写死，F12/F13。",
 "T29": "真实artist对账局部回归通过；A35记录错配，发布证据仍需修复。",
 "T30": "同图60标签旋转与建议配色测试通过；A36记录错配，最终版面另验。",
 "T31": "最终尺寸/图像匹配等局部测试通过；不能代替论文全内容/逐页语义检查。",
 "T32": "正式发布有可复现错误complete，F04/F05/F06。",
 "T33": "四个合成e2e通过；未覆盖工作台→final等真实断链，F07/F19。",
 "T34": "独立842项回归通过；另23反例存在，不可据数量认定全达标。",
 "T35": "README/契约已更新，但开放/闭环/全部完成等文案超出代码，F14/F21。",
 "T36": "74文件包/标准SHA/源码一致和隔离导入通过；包正确不证明功能全部完成。",
 "T37": "原件写坏、代码漂移、并发父版本和长锁均未防住，F01/F15/F16/F17。",
 "T38": "原生视图/精度/空表合成测试通过；全形态端到端未充分证明。",
 "T39": "60卡有结构，实际场景错配与证据链不完整，F21。",
 "T40": "调度局部测试通过；未核/开放缺口能流入complete，F04/F20。",
}

CASE_NOTES = {
 "A01": "原保护测试通过；新事务入口仍可覆盖原件，F01。",
 "A02": "observed错配为精度测试；严格读取存在反例，F06。",
 "A03": "observed错配为资料发现；已有精度回归通过不修复登记错误。",
 "A04": "混合PDF局部测试通过；不能由一个例子宣称所有模态全部恢复。",
 "A05": "旋转/bbox提供方局部测试通过；仅认可实际被测变体。",
 "A06": "来源复读事件与final不兼容，F08。",
 "A07": "续表/表头/脚注等局部测试通过；范围限实际fixture。",
 "A08": "合并格/公式缓存/日期/前导零局部测试通过。",
 "A09": "真实Vosk时间戳/回放回归通过；ASR事件与final需联验F08。",
 "A10": "公式/近似层局部证据；不能充分证明专有/多维原生无损全部要求。",
 "A11": "发现有固定截断，F10；不限形态整卡不成立。",
 "A12": "检索记录有执行，但实际范围失真，F09/F10。",
 "A13": "虚假found/不存在dataset也可resolved，F11。",
 "A14": "未检索资料也计覆盖，open不阻断complete，F09/F04。",
 "A15": "值差异裁决局部测试通过；实体/单位/时间联合变体证据不足。",
 "A16": "工作台签名不能接final，旧校核可用于新数据，F07/F05。",
 "A17": "局部定位规则有测试；全篇未记载证明受错误范围回执影响F09。",
 "A18": "身份/别名局部合成测试通过；未外推所有身份资料。",
 "A19": "一对多等局部测试通过；多对多及所有分母变体未充分证明。",
 "A20": "observed错配为fit/validate；单位转换有其他测试，时效口径证据不足。",
 "A21": "observed错配；开放family/runner反例，F14。",
 "A22": "observed错配为不可行/无界；V-05回归通过，多角色消费者存在F19。",
 "A23": "observed错配为超时；方法未核仍complete，F04。",
 "A24": "observed错配为N；数学模型错解F02/F03，动态/逆问题未充分证明。",
 "A25": "observed错配为N/dropna；诊断False仍通过F18，联查断链F19。",
 "A26": "observed错配为input_version；规格静默丢失F20。",
 "A27": "observed错配为独立算术；完整多重比较/预测链未证明，F20。",
 "A28": "OLS/IRLS和共享预处理局部测试通过；随机/等价解范围未充分证明。",
 "A29": "observed错配为稳定性前置；新数据仍消费旧验证F05。",
 "A30": "observed错配为符号翻转；工作台/final签名断链F07。",
 "A31": "环境对比局部测试通过；代码改变仍提交F15，干净环境全链不足。",
 "A32": "方向/极值/因果等局部规则回归通过；不等于全文事实审阅完成。",
 "A33": "摘要不冒充全文局部测试通过；撤稿/更正等整卡证据不足。",
 "A34": "observed错配为环境漂移；附录漏写且数字无来源可过F12/F13。",
 "A35": "observed错配为缓存；有另一个figure测试文件覆盖部分图元，卡应重挂证据。",
 "A36": "observed错配为步骤预算；实际密集标签测试在test_figure_semantics，需补正确记录。",
 "A37": "真实配色建议/mandatory=False测试通过，保留该实现方向。",
 "A38": "有效dpi/尺寸局部测试通过；认可实际被测摆放。",
 "A39": "observed只涉及无文字层位图；完整Word表/公式/交叉引用要求未充分证明。",
 "A40": "空scope测试通过但假verified仍complete，F04/F06。",
 "A41": "CSV流式规模测试通过；索引/发现仍截断F10。",
 "A42": "本次独立完整回归842项通过、0跳过；V-05仍使用n。",
 "A43": "容器/重复副本局部回归通过；仅认可已测成员类型。",
 "A44": "原生视图独立对账局部测试通过；记录证据应补具体变体与产物。",
 "A45": "角色核算局部测试通过，但真实registry相对路径无法接入F19。",
 "A46": "合法空表/无N局部测试通过；不能推出所有范围依据都已核。",
 "A47": "显式validator测试通过，正式读取却绕过F06。",
 "A48": "ENOSPC/指针中断局部测试通过；不能覆盖原件逃逸与代码漂移F01/F15。",
 "A49": "补丁冲突局部测试通过，但不同输出并发提交均成功F16/F17。",
 "A50": "检查点/终止子进程局部测试通过；事务代码漂移仍需F15。",
 "A51": "已知斜率算术/共享预处理测试通过；不证明所有原件恢复与数学结果正确。",
 "A52": "当前证据不足且大量错配，校验器结构通过不等于实际验收F21。",
 "A53": "显式失效传播局部测试通过；改写账本/结果版本仍可被发布F06/F05。",
 "A54": "正式入口可被未经复核状态放行，F04/F05。",
 "A55": "observed错配为发布四态；缓存有局部测试，旧验证仍续用F05。",
 "A56": "observed错配为limited；参数/尺度/分母可比性整卡未充分证明。",
 "A57": "observed错配为partial门禁；整数/边界错解仍优解F02/F03。",
 "A58": "生成值层次局部测试通过；来源复读消费断链F08。",
 "A59": "observed错配为调度依赖；长文索引仍截断F10。",
 "A60": "时间顺序字段和当前文本哈希不构成历史冻结/实际批次执行证明F21。",
}

REQ_NOTES = {
 "R01": "恢复提供方与结构解析已有真实合成测试；来源复读→final断链F08，不能整项签收。",
 "R02": "不可签收：检索覆盖失真、静默截断、假补数关闭F09/F10/F11。",
 "R03": "不可签收：工作台已复核记录被final全部拒绝F07。",
 "R04": "实体/连接/单位等局部能力有测试依据；尚不足证明所有整合→模型消费者闭合。",
 "R05": "不可签收：固定family、runner未执行、数学错解和设计消费者断链F02/F03/F14/F18/F19。",
 "R06": "不可签收：旧数值验证可续签新结果、未运行规格仍passed F05/F20。",
 "R07": "不可签收完整可复现发布：代码漂移、并发校验/锁错误F15/F16/F17。",
 "R08": "不可签收：无绑定数字写入、已登记附录丢失F12/F13；真实文献全链另需证据。",
 "R09": "图元、密集斜标签和建议配色有可运行测试；最终发布/全部论文安置整项证据仍不足。",
}


def main():
    plan = json.loads((ROOT / "docs/research-pipeline-enhancement-2026-11-14.json").read_text(encoding="utf-8"))
    task_doc = json.loads((ROOT / "docs/implementation/TASK-STATUS.json").read_text(encoding="utf-8"))
    card_doc = json.loads((ROOT / "docs/implementation/ACCEPTANCE-RESULTS.json").read_text(encoding="utf-8"))
    repro = json.loads((HERE / "repro-results.json").read_text(encoding="utf-8"))
    assert set(TASK_NOTES) == set(task_doc["tasks"])
    assert set(CASE_NOTES) == set(card_doc["cases"])
    assert set(REQ_NOTES) == {v["id"] for v in plan["requirements"]}
    assert len(repro["cases"]) == 23 and all(r["verdict"] == "counterexample_confirmed" for r in repro["cases"])
    matrix = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Independent source, integration counterexample and evidence audit. No runtime fixes.",
        "requirements": [{"id": r["id"], "title": r["title"], "audit": REQ_NOTES[r["id"]]} for r in plan["requirements"]],
        "tasks": [{"id": k, "title": v["title"], "claimed_state": v["state"], "audit": TASK_NOTES[k]} for k,v in task_doc["tasks"].items()],
        "cases": [{"id": k, "scenario": v["scenario"], "claimed_result": v["result"],
                   "recorded_observed": v.get("observed"), "audit": CASE_NOTES[k]} for k,v in card_doc["cases"].items()],
        "findings": [{"id": f[0], "priority": f[1], "title": f[2], "repros": f[3],
                      "locations": [{"path": str((ROOT / SRC / path).resolve()), "line": line} for path,line in f[4]],
                      "observed": f[5], "impact": f[6], "required_fix": f[7]} for f in FINDINGS]
    }
    (HERE / "audit-matrix.json").write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    baseline = json.loads((HERE / "baseline.json").read_text(encoding="utf-8"))
    changes = []
    for rel, digest in baseline["sha256"].items():
        path = ROOT / rel
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if actual != digest:
            changes.append({"path": rel, "before": digest, "after": actual})
    preservation = {"checked_files": len(baseline["sha256"]), "changes": changes,
                    "recorded_at": datetime.now(timezone.utc).isoformat()}
    (HERE / "preservation.json").write_text(json.dumps(preservation, ensure_ascii=False, indent=2), encoding="utf-8")
    assert not changes, "Audited source/report/ledger unexpectedly changed during audit"
    lines = [
      "# 实施结果独立审计 · 2026-11-14",
      "", "结论：当前不能接受实施报告中“40项全部落地、60项全部通过、无未完成项”的总体结论。源码有实质进展，现有测试和包一致性可以复核，但新链路存在原件保护、模型数值正确性、复核互通、版本绑定和正式发布方面的实质缺陷。",
      "", "本次记录 **21项审计发现**；新增 **23个合成反例全部复现，0个fixture错误**。编号F是本次发现，C是本次反例，与既有C01–C18历史修复编号不是同一套。没有修改生产代码、原实施报告、任务状态或验收状态；只新增本审计目录。",
      "", "## 已实际确认的结果", "",
      "| 检查 | 本次独立结果 |", "|---|---|",
      "| 完整现有回归 | 842 tests，524.348秒，OK，0跳过；日志 regression.log |",
      "| 新增反例 | reproduce_audit.py：23/23确认现有实现违反相应预期，0 fixture_error；repro-results.json保存值与源码哈希 |",
      "| 源码/安装包 | build_skill.py --check：74文件一致 |",
      "| 标准归档SHA256 | 4f6126982efebc62068f2592ddec2a0607450711d599ac916715a88ab04fb045，与sidecar一致 |",
      "| 隔离解包/导入 | install.log：74文件，不含tests/docs/pycache；独立进程导入和提供方探测rc=0 |",
      "| 验收结构校验 | validate：60张卡、0结构错误；不能据此推导60项能力正确 |",
      "| 验收漂移检查 | 0 errors、105 warnings，涉及60卡；详见card-drift.json |",
      f"| 审计现场保留 | baseline.json中{len(baseline['sha256'])}个文件审计前后SHA一致，详见preservation.json |",
      "", "源码与包一致也意味着本次发现的生产缺陷随当前包一同分发。隔离导入不是完整重建环境后对所有研究项目的复现证明。现有回归使用合成材料，本次也没有审计真实研究资料的真实性或形成实证结论。",
      "", "## 审计方法和解释边界", "",
      "逐项对照冻结方案、9项能力、40项任务、60张原场景，以及实施报告的具体完成声明；阅读关键生产者/消费者、已有测试和校验工具，并独立运行完整回归、包校验、隔离导入及23个反例。后文矩阵完整保留全部编号，不把“有代码/有测试/命令退出0”当成整项完成。",
      "", "反例均在临时目录构造，不使用真实材料。C08真实第二次读取合成CSV，并在机器prepare无错误后串联工作台→final。C19只用屏障安排真实提交时序。C21是合法来源复读事件的生产/消费隔离测试，没有冒充真实OCR识别或视觉阅览。已知答案来自简单解析解、独立fixture常量或明确契约；所有fixture异常单列，不计缺陷。",
      "", "本审计覆盖了全部需求/任务/验收编号及关键接口；这不等于证明所有15k余行新增代码、所有可能格式和所有研究问题均无其他缺陷。局部测试通过仅认可其实际变体。未获得充分证据的事项保留未核，不写成确定不存在或已经失败。",
      "", "## 发现与必要修复", "",
    ]
    for f in matrix["findings"]:
        lines += [f"### {f['id']} [{f['priority']}] {f['title']}", ""]
        lines += ["位置：" + "；".join(f"[{Path(x['path']).name}:{x['line']}]({Path(x['path']).as_posix()}:{x['line']})" for x in f["locations"]), ""]
        lines += ["实际观察：" + f["observed"], "", "影响：" + f["impact"], "", "修复验收要求：" + f["required_fix"], ""]
        lines += ["反例：" + ("、".join(f["repros"]) if f["repros"] else "逐卡内容对照及card-validation.json/card-drift.json；不虚构运行反例"), ""]
    lines += ["## 9项能力逐项结论", "", "| 编号 | 能力 | 审计结论 |", "|---|---|---|"]
    for r in matrix["requirements"]:
        lines.append(f"| {r['id']} | {r['title']} | {r['audit']} |")
    lines += ["", "## 40项任务逐项核对", "", "所有任务原台账均为implemented；下列是独立审计意见，没有擅自改原台账。", "", "| 编号 | 任务 | 审计意见 |", "|---|---|---|"]
    for t in matrix["tasks"]:
        lines.append(f"| {t['id']} | {t['title']} | {t['audit']} |")
    lines += ["", "## 60项验收逐项核对", "", "原记录60项均为passed。下面区分反例、记录错配、局部测试依据和整卡证据不足；不是另造一个60全失败的结论。完整原场景和observed原文保存在audit-matrix.json。", "", "| 编号 | 审计意见 |", "|---|---|"]
    for c in matrix["cases"]:
        lines.append(f"| {c['id']} | {c['audit']} |")
    lines += ["", "## 建议修复与重新验收顺序", "",
      "1. 先修F01原件写入、F02/F03错解、F04/F05/F06发布与当前证据绑定；这些问题会产生错误数据或错误就绪结论。",
      "2. 接通F07/F08工作台/来源复读→final和F18/F19模型→设计消费者；所有链路通过同一项目、同一数据版本、公开CLI验收。",
      "3. 修F09/F10/F11全资料检索和补数闭环，再修F12/F13全文数字和内容不丢失；增加尾部/未知章节/空集反例。",
      "4. 完成F14开放执行器和F20稳定性要求，修F15/F16/F17事务版本与并发；未实现项显式记录，不静默降级。",
      "5. 最后修F21：逐卡补齐真实证据、重新判定40任务/60场景，更新README/契约/实施报告，重跑受影响测试和最终完整回归后重新打包。不要删除本次反例、抬高容差、放松门禁或只改说明来获得通过。",
      "", "密集横轴标签与配色无需推翻已有实现：保留同图、完整文本/字号，实际测量后选旋转/扩边距/增宽；旋转后必须确认已达到可读要求，不能只因重叠数量下降就签收。配色仍是建议。当前测试证明30°旋转可减少60标签碰撞，并没有证明所有最终Word/PDF安置都已无重叠。",
      "", "实施报告还保留首轮69文件与第二轮74文件两种描述，应改清楚历史/当前口径。真实文献的来源、访问层次、撤稿更正和语义支持仍需按项目核验，不能由合成摘录测试代替。",
      "", "## 证据与复现", "",
      "- baseline.json / preservation.json：审计对象哈希与现场未被修改的检查。",
      "- regression.log：本次842项完整回归原始输出。",
      "- reproduce_audit.py / repro.log / repro-results.json：23反例、实际值、确认断言及源码哈希。",
      "- audit-matrix.json：9R/40T/60A及21发现的机器可读清单。",
      "- card-validation.json / card-drift.json：当前验收工具实际输出。",
      "- install.log：隔离解包导入与提供方探测。",
      "", "在仓库根目录运行 `python docs/audit-implementation-2026-11-14/reproduce_audit.py` 可重现。脚本正常退出表示审计运行完成；应阅读每项verdict，counterexample_confirmed表示确认现有缺陷，绝不是该能力通过。修复后应将相应契约转成生产测试，预期不再出现counterexample_confirmed。",
      "", "本报告没有修改已安装skill副本、第三方插件或原实施台账，也未代用户宣称研究成果已可用于正式论文发布。",
    ]
    (HERE / "AUDIT-REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"requirements": len(matrix["requirements"]), "tasks": len(matrix["tasks"]),
                      "acceptance_cases": len(matrix["cases"]), "findings": len(matrix["findings"]),
                      "confirmed_counterexamples": len(repro["cases"]), "preserved_files": preservation["checked_files"]}))


if __name__ == "__main__":
    main()
