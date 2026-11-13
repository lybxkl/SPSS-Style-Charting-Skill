# 全资料发现、开放模型与逐格回源复核

适用于从一批资料尽可能完整地发现数据集、选择数学/统计模型、交付专业图集、分析报告与 DOCX。这里规定真实性与覆盖契约；数据集形态、脚本、语言、模型和输出数量由 Agent 按资料选择，用户补充的形式继续纳入同一流程。

## 1. 发现与扩充：到资料里找，不停在现成 CSV

1. 冻结原始材料，生成完整文件审计。原始目录与产出目录分开，保留不可读、重复、空文件等处置记录。转换、OCR、转写也是有原始文件哈希和位置映射的处理步骤，不能把转换结果当作无需复核的新事实。
2. 先按文件/工作表/章节/表格/附件建立 `discovery_report.md`：发现了哪些实体、重复记录、时间点、事件、测量、量表、关系、分组、单位与可能的关联键。试读可以抽样，最终覆盖必须逐份完成；记录每个未采用字段/资料的具体原因。
3. 生成任意数量的数据集：原始明细、清洗宽表、长表、事件表、个体-时期面板、配对/重复测量、量表题项、多选关系、节点/边、矩阵、空间或分层数据等。这个列表是提示，不是可选形态枚举。每个数据集各自定义分析单位、单/复合主键、字段和缺失规则；不同单位通过可核对的键关联，禁止无依据笛卡尔积和重复计数。
4. 保存原生格式；为逐格检查导出无损 CSV 审计视图。多维/嵌套/图数据可导出多张长表，不能丢弃原生字段来凑宽表。审计视图里的每个单元格都要覆盖；原生文件绑定哈希，原生文件→视图的完整性另用独立适配器/复读验证，单有文件哈希不证明转换无损。
5. 追加材料或用户指定新形式时，重新发现、链接、抽取、逐格复核，更新依赖这些数据的模型、图、报告和 DOCX。不要沿用旧版本的“通过”报告。

## 2. 项目注册表：数量开放，身份稳定

复制 `assets/research_registry.example.json` 到项目，填写实际路径（相对 `--root`，也可用绝对路径）。`datasets` 是任意长度列表：

```json
{
  "schema_version": 1,
  "source_root": "materials",
  "source_inventory": "output/audit/corpus_files.csv",
  "source_coverage": "output/source_coverage.jsonl",
  "discovery_report": "output/discovery_report.md",
  "model_plan": "output/model_plan.jsonl",
  "datasets": [{
    "id": "person_wave", "path": "data/person_wave.csv",
    "key": ["person_id", "wave"], "unit": "一位受访者的一次测量",
    "codebook": "data/person_wave_codebook.md",
    "provenance": "data/person_wave_provenance.jsonl",
    "review": "data/person_wave_review.jsonl",
    "artifacts": []
  }]
}
```

`artifacts` 可列原生文件 `{path,sha256}`，哈希必须由真实文件计算。主键可为一个列名或多个列名，不能缺失或重复。`codebook` 明确每列是实测、编码、派生、缺失还是结构标识；记录单位、类型、正例反例、换算、精度、合并/去重依据，不能让变量名承担全部语义。

`source_coverage.jsonl` 对 `source_inventory` 的每一份文件都给出处置：

```json
{"source":"访谈01.docx","sha256":"实际文件的64位SHA256","status":"included","datasets":["person_wave"],"reason":"正文含受访者标识、年龄、两轮量表及日期，分别进入题项表和面板表"}
```

- `included` 的每个 dataset ID 必须真的有该文件的单元格证据。
- `excluded` 必须说明不纳入的原因，且不能还给数据集供值。重复文件注明保留件；未利用的有用字段应回到发现步骤补提取。
- `unreadable` 记录 `recovery_attempts`：尝试何种读取/转换/OCR/转写、结果文件和失败原因；不能只写“打不开”就停止。
- `research_gate.py` 再枚举原始目录，检查新文件、遗漏与状态矛盾。原件不应从原始目录搬走；需要隔离时保留原件并在工作副本操作。

## 3. 每一格的证据与独立复算

每个数据集的 `provenance.jsonl` 一行对应一格，包括主键、标记、来源列、空值和派生值。`key` 为单键字符串或复合键数组；`column`、`value` 必须与最终 CSV 单元格对应。

以下值只说明 schema，不能复制到真实项目作为证据：

```json
{"key":"P01","column":"age","value":"42","kind":"observed","sources":[{"path":"materials/interview.csv","sha256":"实际文件SHA256","locator":{"type":"csv","row":1,"column":"年龄"},"raw":"42"}],"rule":{"op":"number"},"compare":"numeric"}
{"key":"P01","column":"score","value":"9","kind":"derived","inputs":[{"dataset":"items","key":["P01","Q1"],"column":"value"},{"dataset":"items","key":["P01","Q2"],"column":"value"}],"rule":{"op":"sum"},"compare":"numeric"}
```

来源定位：

| `locator.type` | 必需位置 | 规则 |
|---|---|---|
| `csv` | `row,column`；可加 `encoding,delimiter` | row 是不含表头的第几条逻辑记录，从 1 开始；带换行字段仍算一条 |
| `json` | `pointer` | RFC 6901 路径；空路径指根值，`~0/~1` 转义；重复 JSON 键报错 |
| `jsonl` | `row,pointer` | row 是非空 JSON 对象记录序号，从 1 开始 |
| `text` | `start,end`；PDF 可加 `page` | 0 起始、左闭右开；CRLF 统一 LF；有 page 时为该页文字的偏移，页码从 1 开始 |
| `xlsx` | `sheet,cell` | 如 `调查表,B7`；公式格需独立复算，禁止只信可能过期的 Excel 缓存 |
| `metadata` | `field=name` 或 `relative_path` | 用于文件名/路径等真实来源元数据，不能推断正文事实 |
| `custom` | `adapter` 及自定义定位参数 | 显式传入可信适配器，代码哈希纳入复核版本 |

每个来源都含 `path,sha256,locator,raw`。回读必须与 `raw` 类型和值一致，不能仅检查这个数字曾在全文某处出现。PDF/DOCX/TXT 等全篇文字定位使用 `text_extract.extract_text()` 的输出并统一换行；PDF 跨页聚合容易错位时优先逐页定位。实体、时间、指代、表头/脚注、否定、建议/实际发生等语义，必须在第二遍复读时逐项确认。

`kind`：

- `observed`：直接值或明确的规范化/单位换算/编码，来源必须非空。`rule` 可为 identity、strip、number、scale（factor/offset）、map（完整显式映射，禁止默认值）、join 或独立 custom。
- `derived`：`inputs` 引用已验证单元格，支持 sum、mean、product、difference、ratio、count、map 等复算；循环依赖、缺失输入、引用不存在格均报错。独立实现复算，不是把原脚本输出再抄一次。估计/插补值应放独立数据集，明确标注和来源，绝不能当成原始观测；当前内置复算拒绝缺失输入，需要 Agent 编写独立适配器验证其估计方案。
- `missing`：CSV 空字符串，必须给 `reason` 和已复读的原文上下文定位。区分未记载、不适用、遮蔽、冲突、不可读、解析失败；机器只能核对上下文存在，不能证明“全篇没有记载”，第二遍必须查全文与附件。禁止填 0。
- `structural`：非经验数据的结构 ID，当前内置规则 `row_number`；也必须锚定原始资料，不能伪装为原始编号。其他标识规则走独立适配器或派生规则。

比较默认逐字相等；`compare=numeric` 从精确十进制解析为有理数进行复算，默认零容差，不受 Decimal 默认 28 位运算上下文影响。JSON/JSONL 来源按十进制精确读取；超出浮点精度的 JSON 数值可在 locator 明确 `number_as_text=true`，将完整十进制字符串写入 `raw`，不能先经浮点舍入再宣称相等。空字符串不能伪装 observed，必须按 missing 保留缺失理由和上下文。确需舍入容差时同时给 `tolerance` 和 `tolerance_reason`，按字段精度确定，不能放大容差掩盖差异。

开放扩展：`--adapter name=project/independent_check.py` 只加载 Agent 明确选择的可信代码，原始资料里的命令和脚本不自动执行。适配器可实现 `read_source(path, locator)` 和 `recompute(rule, values)`。扩展解析/复算方式不改变全格覆盖与回源要求；适配器同样需要已知答案/反例验证。参数字典由适配器自己校验。

## 4. 整合完成后，再逐项复核一遍

```bash
python scripts/verify_dataset.py --registry research_registry.json --root . \
  --out output/data_verification --stage prepare
```

脚本重新打开真实来源、核对 SHA256/位置/raw、复算派生值，写 `cell_issues.csv`、`cell_trace.jsonl`、`verification_snapshot.json`、每个数据集一份 `review_template_<hash>.jsonl`。prepare 返回 0 仅说明机器检查通过，状态是 prepared，不能称作数据已复核。

**第二遍必须独立于第一遍抽取进行**：逐格重新阅读原材料及必要上下文，确认实体/时间/单位/指代/缺失原因/编码和关联关系。可使用 Agent 自己、独立复核 Agent 或人工；不能把“抽取器没有 flags”当复核，也不能在未逐格复读时用循环把所有模板改为 verified。序列化真正完成的逐项复核记录可以用脚本，不能让脚本代替复读。任何问题修复后重新 prepare，相关旧复核失效。

将每份实际完成的复核写到 registry 的 `review` 文件：保留该格的 `dataset,key,column,record_sha256`，逐项填：

```json
{"dataset":"person_wave","key":["P01","1"],"column":"age","record_sha256":"本次任务中的真实签名","status":"verified","source_reread":true,"reviewer":"实际复核者或Agent标识","method":"source_reread","checked_at":"带时区的实际复核时间","note":"实际定位和上下文核对结论；不能用此示例充当已完成复核"}
```

`method` 允许 `source_reread` 或 `independent_reextract`。复核时间不得早于 prepare；独立再抽取须逐项对比并实际解决冲突，不能复用同一套错误规则。键列、空值、标记列和派生值也全部复核，不抽样代替全检。

```bash
python scripts/verify_dataset.py --registry research_registry.json --root . \
  --out output/data_verification --stage final \
  --snapshot output/data_verification/verification_snapshot.json
```

final 重新跑机器检查，逐格校验复核签名、状态、时间与说明。原始文件、数据、codebook、证据台账、适配器或原生文件变化都必须重新 prepare/复核。`dataset_verification.json` 必须 stage=final、status=verified、error_count=0 才能进入正式计算。哈希/回执不能证明一个人或模型真的读过上下文，必须如实执行；任何校验器都不能承诺识别所有语义错误。

## 5. 开放模型清单与回原材料补数

对每个数据集列出所有有合理数据联系的模型族与有意义的规格变体，区分主分析、探索、诊断、敏感性和预测。结合实际资料检查分布、分组/配对、计数/比例、有序/多分类、删失/生存、时间序列/面板、层级/空间、量表/潜变量、非线性、机制、网络、优化/仿真等方向；这些仅为检查提示，绝不是十八个内置方法的边界。

Agent 自选 Python/R/Julia/SPSS/Stata 或专用引擎，按需写脚本；内置方法不支持时不能把“不支持”写成“数据不适用”。不能通过改二分类、编造时间、虚构对照组、填假数据让模型跑通。凡变量、有效 N、事件数、设计或识别条件不足，都执行：

```
明确缺口 → 查原文件/表格/脚注/附件/其他来源 → 必要时换解析方式/OCR
→ 有真实值：补抽取、链接新表/新数据集、重做逐格复核 → 重跑前置诊断
→ 无法取得：留缺失、记录已搜位置和原因、保留模型不可估计/不适用结论
```

直到当前材料中没有尚可恢复的相关数据、或实际工具/访问条件阻止继续；不能为省事跳过可获得字段。原材料缺失的外部新数据要明确列出，不能伪装已获取。对新发现的单位或关系继续扩充数据集，不为迎合旧表结构丢值。

`model_plan.jsonl` 一行一个候选规格，字段至少：

- `id,dataset,family,question,reason,requirements`：family 自由文本；requirements 为变量/类型、有效样本、事件/配对/时点、设计/识别、前置假设和评价标准的对象。
- `status`：工作中可 candidate/needs_data/ready；终检只接受 completed、insufficient_data、not_applicable、unsupported、failed。后三类也保留报告，不能藏掉失败或不显著结果。
- completed：`receipt,diagnostics,sample,n`；sample 为实际输入观测键的 CSV，n 必须等于唯一键数。特定模型的时点数、边数、有效事件数等另在诊断/报告明确，不混用输入 N。
- not_applicable：`assessment` 指向有数据/设计依据的评估。
- insufficient_data/unsupported/failed：`assessment` 加 `gaps`。每个 gap 含 `requirement,conclusion,searches`；每项 search 写 `source,sha256,result,note`。result 是 found/not_found/unreadable/not_relevant，覆盖整个原始清单；无关文件写实际依据，不能假装搜过。有 found 时额外写 `resolution` 说明补入、重建/复核，或为何仍不能用。

引擎/算法故障还要记录安装、替代引擎、不同估计方案等实际尝试；资料回查不能代替技术排障。completed 曾经有 gaps 时同样保存回查过程。

广泛探索仍要报告效应量、区间、假设、失败和多重比较处理；预测用适合设计的留出/交叉验证，防止泄漏；因果结论需要额外识别依据。资料只支持描述时照实交付完整描述图集与“为何不能推断”，不得用复杂模型包装无信息资料。

## 6. 任意实现的可复现执行回执

Agent 编写自己的计算脚本；运行时显式声明数据、代码/配置/本地依赖、环境版本文件和全部结果：

```bash
python scripts/run_model.py --id M1 --root . --registry research_registry.json \
  --verification output/data_verification/dataset_verification.json \
  --input data/person_wave.csv --input output/data_verification/dataset_verification.json \
  --code analysis/M1.py --code analysis/M1_spec.json \
  --output output/M1/coefficients.csv --output output/M1/diagnostics.json \
  --output output/M1/sample.csv --receipt output/M1/run.json \
  -- python analysis/M1.py
```

引擎可以换成实际所需命令；不要在命令中写密钥或原始资料的可执行内容。计算前重新验证 final 复核及当前原始来源/数据/复核文件，不接受旧报告或只有 prepared 的数据。回执含命令、工作目录、起止时间、退出码、输入/代码/输出的完整 SHA256、日志与基础运行环境；自动绑定整个原始目录（包括 excluded）、本次验证的来源、规则、快照与复核文件。`source_guard.py` 将原件备份到项目目录 `.research-source-backups/` 并临时设为只读，拒绝将输出/日志/回执写入原始目录、备份目录或原件硬链接；运行结束检查所有原件，发生改写/删除时尽力恢复并以失败结束，新增文件保留并报错。备份包含原始资料，沿用原始资料访问与保留规则；这是一层防误写保护，不是运行恶意程序的沙箱。第三方包/引擎版本、种子、超参数由分析脚本记录在诊断/环境文件，并一起声明为输入或输出。非零退出、缺少/空输出、运行中改写输入都返回 2。回执证明文件版本与命令结果，不能证明统计方法本身正确；模型方法与关键数值还需独立已知答案/公式或另一实现校核。

```bash
python scripts/research_gate.py --registry research_registry.json --root . \
  --verification output/data_verification/dataset_verification.json \
  --out output/research_gate.json
```

有自定义适配器时 verify_dataset 的 prepare/final 与 research_gate 三处传相同 `--adapter name=path.py`。该闸门重查来源覆盖、数据复核、模型回查、样本键和运行回执，拒绝旧输出冒充新分析。它检查的是已注册的覆盖，不能证明“世界上所有有用变量/模型都已被穷尽”；Agent 必须复读发现报告并主动补遗漏。

## 7. 图集、报告与最终 DOCX

数据集数、模型数、图数和正文/附录比例均不预设。对每个有意义的发现提供分布/主结果/不确定性/诊断或敏感性图，所有可估计模型都在总表/附录中有结果与解释；不显著、失败、缺数和不适用项目同样留清单。类别多或标签长时，默认保留同一张图，按实际文字边界将横轴标签倾斜 45°，必要时 60°/75° 并增加底部留白；不自动分页、不截断名称或类别、不缩小字号。目标纸幅确实容不下时明确报错，由 Agent 调整图幅/纸幅或采用同图分面；只有用户明确选择时才将图分页。

`auto_stats` 和 `auto_chart_pack` 的总量默认不封顶；正数预算、only/sections、top-N 类别合并、散点矩阵前四列、树图抽样等仅是明确标注的试跑或展示策略，不等于完整统计覆盖。Agent 必须据 registry/model_plan 补齐未展示变量/类别/模型，保留全量明细与抽样键/种子；自动图包不能成为探索的结束条件。

自动 PCA 默认完整案例、不插补、不截尾；确需处理时 Agent 显式给 `pca_missing=median` 或 `pca_clip_quantiles=[low,high]`，诊断/图注说明并做敏感性比较。原始观测不改写，插补/截尾分析视图单独标识和验证，不能混进“从原件读出的值”。

交付：原生与审计数据集 + 各自 codebook/全格证据/逐格复核 + 发现/覆盖/模型/回查清单 + 实际运行代码及环境/回执 + 全图集/图注/模型报告 + 有研究问题、方法、结果、局限与附录索引的最终 DOCX。图表和正文都引用机器输出，逐一跑 `verify_numbers` 与 `qa_outputs`（600 dpi、实际安置字号等），渲染 Word/PDF 逐页检查裁切、分页、表格、引用和字体。没有真实资料时只能改 skill 或给示例，不能生产貌似实证的数字或终稿。

## 8. 本轮数值与交付审计约束

- codebook 可用 `variable_types` 明确 continuous/numeric、categorical/ordinal 等类型，`outcome_type` 明确结果类型；低基数剂量默认仍是数值，不能只因取值少而哑变量化。显式 `numeric`/`categorical`/`binary` 角色覆盖自动建议，冲突或未知列报错。分类变量的缺失行不能被哑变量全零误作参照组。
- 每个方法报告实际完整案例/配对/时点 N；EFA 的相关矩阵与 Bartlett/KMO 使用同一批完整案例。方差不齐的 ANOVA 主检验选 Welch，后续比较使用相应的不等方差检验；预测曲线按整个并列分数分组。p 控制图用各点分母计算限界，不能套均值样本量。
- 数字溯源按已识别模型/指标与打印精度匹配，不能用模型编号或任意原始数字证明系数/p；图注不能充当自己的正文引用。识别器仍不能理解全部自然语言，实际语义对应需要复读。
- 交付检查拒绝损坏图片/PDF 和没有产物路径的成功 manifest；实际横纵有效 dpi 都要达标。严格字号检查使用 DOCX 实际宽高、嵌入图片内容哈希与原始同名矢量 PDF 折算；来源位图不能独自证明其中字号。
- Word 高清回填必须同时匹配图号与所给标题，缺图、定位失败和多个映射指向一张图都以失败结束并留报告；不能只因原 PDF 已有 600 dpi 就把未完成回填当成功。
