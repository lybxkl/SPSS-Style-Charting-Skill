"""Materialise reviewed acceptance-card DESIGNS, not test execution results."""
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent

# Each row specifies a fixture/procedure, an independent expected result, and a
# negative control. All fixtures remain to be authored and executed in T39.
SPECS = [
    ("A01", "已知哈希原件，注入写入/删除/硬链接/输出重叠", "真实错误与原件恢复范围明确，失败不发布成功回执", "只查目录存在，恢复后仍称本次成功"),
    ("A02", "合法v1、必需视觉语义v2及其迁移副本", "旧能力不能消费新语义，迁移后重新核对", "剥关键字段或续用旧verified"),
    ("A03", "长十进制、大整数、重复JSON键、空值/0/非法值", "按独立原值/有理数真值核对，非法容差拒绝", "先转float舍入或缺失转0"),
    ("A04", "同页PDF有文字层与扫描表格，预先列两区域", "两区读取范围真实，未恢复不称全页已读", "有文字层即跳过扫描区"),
    ("A05", "原页90度旋转/缩放裁片，并加入错误页号", "几何真值可回原页，错页/越界拒绝", "仅有bbox或图片即通过"),
    ("A06", "原图18，故障注入OCR文本81且候选81", "实际回看能更正并使旧81失效", "文本相等或高confidence就verified"),
    ("A07", "两页续表、多级单位、重复表头和分母脚注", "独立观察/表头/脚注真值对账，不丢合法重复", "第二页全删或表头当观察"),
    ("A08", "合并表头/空格/过期公式缓存/不同日期纪元", "独立复算和日期真值一致，空格保留", "填满合并格或直接信缓存"),
    ("A09", "有原稿/时间段的短音频，模糊身份和缺引擎变体", "真实引擎运行与回听有证据，未知身份留疑", "mock当ASR或臆认身份"),
    ("A10", "合成图有标尺，另给多维原生文件及审计视图", "近似精度单列，原生结构/内容独立对账", "近似充实测或哈希证明无损"),
    ("A11", "表/脚注/附件/同义句埋字段，另指定长表", "预先人工真值中的候选有真实处置，新形态保留", "只分析CSV或仅做指定表"),
    ("A12", "真实查询后改原件保留旧索引，另设无命中查询", "执行/来源/上下文可追，旧索引重建", "假搜索日志或无命中当不存在"),
    ("A13", "模型缺字段而附件真实有值，执行回查闭环", "实际补表/整表重核/重评均可追", "只把gap改found"),
    ("A14", "字段未提供，但不同实体有同名字段值", "真实缺失及搜索范围保留", "填0或借另实体数值"),
    ("A15", "两个实体同为42，但有否定/建议/日期/单位冲突", "独立语义真值区分并裁决", "只匹配42或多数投票"),
    ("A16", "已核表含键/空值/派生，更新后保留旧页面", "新整表逐格复核，旧补丁/签名拒绝", "只查变化格或自动盖章"),
    ("A17", "正文无值但附件有值，另设真正未记载字段", "真实全范围回查区分两者", "只看片段或无关键词即缺失"),
    ("A18", "同名异编号、别名同体、重复脱敏名", "已知匹配与未匹配按证据核对", "字符串相似即合并"),
    ("A19", "合法重复测量及多对多缺关联键的连接", "独立关系真值/行数/分母对账", "机械去重或无依据扩行"),
    ("A20", "0.5万元/5000元、不同分母及不重叠有效期", "精确换算正确，不相容量明确冲突", "数值同型相加或未知时区补时刻"),
    ("A21", "内置目录外数学/统计脚本，规模超过旧展示限", "实际执行接入、不封顶，仅宣称实测引擎", "只有family名字而不能运行"),
    ("A22", "同人多时点/多表，真实n=5且n_dropna=2", "按角色计数且n=5，独立个体不膨胀", "跨表累加或优先取剔除数"),
    ("A23", "退出0且写系数，但无数值/方法校核", "execution完成，其余未核，不能正式推断", "completed等于ready"),
    ("A24", "min(x-2)^2,x>=0；互斥约束；秩不足逆问题", "解析真值x=2，不可行/不可识别如实记录", "有数字解即现实有效"),
    ("A25", "完全分离、不收敛、聚类相关、不同缺失策略", "实际设计相应诊断及结论范围正确", "空diagnostics或统一N阈值放行"),
    ("A26", "预列合理正/负/未显著/失败/未运行规格", "全量保留，差异来源及待办可追", "只留显著或同向规格"),
    ("A27", "同人跨组/有时间顺序，注入全样本预处理", "训练内拟合、设计留出、多重比较真实", "训练分数当样本外或预处理泄漏"),
    ("A28", "独立公式与引擎一致/真错及符号等价变体", "按预设标准接受等价、拒绝真实差异", "抄结果或事后放宽容差"),
    ("A29", "改供值文件，再单独增加含缺失字段的附件", "正向/否定/发现/适用性均按依赖失效", "新增材料不触发复评"),
    ("A30", "表有未改格、未知依赖与旧缓存/复核", "受影响整表重核，未知保守失效", "只改格或旧签名绑新快照"),
    ("A31", "分开只改图例/正文/环境并隔离重跑", "影响解释明确，环境前后绑定，适当标准比较", "只查文件名或事后收集版本"),
    ("A32", "A=10/B=20但正文称A最高，关联改写导致", "语义错被实际复核处置，数字相同不豁免", "数字出现过即支持论断"),
    ("A33", "真实元数据配错误观点，另有仅摘要访问", "观点支持/访问范围/更正状态分开核", "DOI存在即全文支持"),
    ("A34", "完整合成研究稿，更新一个结果版本", "各部分可读且版本支持一致，测试身份明确", "空标题或技术日志当论文"),
    ("A35", "图注入漏系列、错误差、矩阵列或分母", "实际绘图数据/图元与结果的差异可定位", "只验图片存在或图元数量"),
    ("A36", "长中文标签/多行图例/标题/数值标注实渲染", "真实边界与目视核查，同图全项不缩字", "自动分页/截字/删类"),
    ("A37", "分类/连续/透明/点边色及旧用途清单", "实际用途和未核范围真实，建议不默认阻断", "默认色环填补实际色或分类阈值验连续图"),
    ("A38", "同源图最终放双栏、窄图、长图", "按实际宽高/哈希/矢量字核dpi与字号", "统一15cm或只看像素"),
    ("A39", "真实Word稿含续表/图题/公式/引用并高清回填", "真实DOCX/PDF逐页核，缺字/缺图/错回填拒绝", "替代导出冒充Word已验"),
    ("A40", "完整/受限/未就绪/失败及源码包失配变体", "范围/状态/SHA分别核，阶段成功不等完整", "zero-error或包存在即全完成"),
    ("A41", "预声明递增表/格/候选/模型及计数真值", "全范围对账，到限留恢复点，不称语义复读已验", "隐形top-N或超时写成功"),
    ("A42", "最终源码重跑C01-C18/V-05及既有回归", "新实际结果与历史585记录分开，失败保留", "删反例或以旧日志冒充新增验收"),
    ("A43", "嵌套压缩/Office/PDF附件含可读与不可读成员", "父子/hash/范围对账，三种计数分开", "仅记容器或副本当新样本"),
    ("A44", "数组/嵌套对象含长整数/前导零/Unicode/有序轴", "独立解析/重建核路径类型维度顺序内容", "丢轴/字段仍以hash称无损"),
    ("A45", "拟合/参数/约束/训练/验证/测试及重复时点多表", "角色独立核算与泄漏检查，消费者同步支持", "所有表行数相加成N"),
    ("A46", "原件明确观察10人0事件与空表；只含约束的模型", "空表有范围依据，格率不适用，无N记录维度", "无命中当0、0/0=100%或补虚构行"),
    ("A47", "非法状态/未知必需特性/旧读取器/自报ready", "维护入口及新闸门拒绝不支持，扩展无损保留", "忽略新语义或信自报版本"),
    ("A48", "写文件/校核/提交清单/发布指针各点注入失败", "旧完整版本可读，半成品不发布，本次失败真实", "逐个覆盖正式文件后completed"),
    ("A49", "两运行或复核同父版本并发提交并重放操作ID", "锁/父版本/幂等防丢失覆盖，冲突明确", "最后写覆盖或重复应用"),
    ("A50", "取消/超时/崩溃后保持或更改原件代码再恢复", "只恢复匹配上下文，只处理本运行资源", "失配检查点verified或关闭其他用户任务"),
    ("A51", "两计算共享错误单位换算，另有预先独立真值", "分层校核发现预处理错，期望不来自待测程序", "错误结果一致即正确"),
    ("A52", "真实完整验收卡与仅编号/mock/skip卡比较", "真实执行与判定后才可集成passed，设计仍待执行", "字段齐全或skip当真提供方已验"),
    ("A53", "后加图文节点换来源/改句子/重排/改图注", "依赖注册且旧审阅失效，实印内容匹配", "框架存在即自动接入或只看句子ID"),
    ("A54", "缺ASR产品/无音频项目/生成器成功/partial未核稿", "产品项目阶段发布分开，partial不绕事实硬条件", "项目不适用证明产品或部分稿豁免真实性"),
    ("A55", "缓存有原回执，再改输入/环境/时间戳/签名", "复用与执行分开，依赖失配或伪造拒绝", "touch旧文件称新计算"),
    ("A56", "OR/风险差/标准化系数/不同时间分母混比较", "按参数尺度分组，图文支持范围一致", "最小p排名或ready授权所有结论"),
    ("A57", "无界max x/互斥约束/(x²-1)²驻点0/超时可行解", "独立真值区分解质量，证据充分才认证全局", "超时当不可行或KKT/残差证全局"),
    ("A58", "实测旁有插补/估计/模拟/图读数并删除标记", "原层不覆盖，方法不确定性用途可追", "生成链验证冒充来源直接观测"),
    ("A59", "预声明三档具体规模/计数/资源，中档故障", "各档实测耗时内存/范围，到限有继续点", "小样例称大规模或预算变数量上限"),
    ("A60", "每批注入错生产/消费方，查前置期望与执行", "本批门检拒错，M7综合，必要集成齐才关任务", "只等M7测或文档完成即发布"),
]

PRIMARY = (
    "T01 T02 T02 T05 T05 T13 T06 T06 T07 T38 "
    "T08 T09 T10 T10 T12 T13 T12 T14 T15 T15 "
    "T17 T18 T18 T19 T20 T21 T21 T22 T23 T24 "
    "T25 T26 T27 T28 T29 T30 T30 T31 T31 T32 "
    "T34 T34 T04 T38 T17 T38 T02 T37 T37 T37 "
    "T22 T39 T23 T32 T24 T21 T19 T38 T34 T39"
).split()


def main():
    task_file = DOCS / "research-pipeline-enhancement-2026-11-14.json"
    task_list = json.loads(task_file.read_text(encoding="utf-8"))
    plan = (DOCS / "RESEARCH-PIPELINE-ENHANCEMENT-PLAN-2026-11-14.md").read_text(encoding="utf-8")
    scenarios = dict(re.findall(r"^\| (A\d{2}) \| (.*?) \|$", plan, re.M))
    owners = {c: [] for c in scenarios}
    for task in task_list["tasks"]:
        for case in task["acceptance_cases"]:
            owners[case].append(task["id"])
    cards = []
    assert len(SPECS) == len(PRIMARY) == len(scenarios) == 60
    for (case, fixture, expected, negative), primary in zip(SPECS, PRIMARY):
        assert primary in owners[case], (case, primary, owners[case])
        profiles = ["local_core"]
        if case in {"A04", "A05", "A06", "A07"}:
            profiles.append("selected_ocr_or_table_provider")
        if case == "A09":
            profiles.append("selected_asr_provider")
        if case in {"A21", "A24", "A25", "A27", "A28", "A57"}:
            profiles.append("selected_model_engine")
        if case == "A33":
            profiles.append("metadata_and_source_access")
        if case in {"A38", "A39"}:
            profiles.append("word_pdf_actual_integration")
        cards.append({"id": case, "status": "planned", "scenario": scenarios[case],
                      "primary_acceptance_task": primary, "linked_tasks": owners[case],
                      "fixture_and_procedure_spec": fixture,
                      "independent_expected_observation": expected, "negative_control": negative,
                      "oracle_requirement": "Freeze actual fixture and independent oracle before implementation; this card is not an executed oracle.",
                      "environment_profiles": profiles,
                      "required_evidence": ["fixture_and_oracle_hashes", "actual_program_config_environment", "execution_receipt", "observed_values_states_differences", "actual_semantic_or_visual_review_when_applicable"],
                      "skip_policy": "Unavailable, not run, timeout, mock or skip is not actual integration passed.",
                      "actual_evidence": []})
    by_id = {t["id"]: t for t in task_list["tasks"]}
    phases = {p["id"]: i for i, p in enumerate(task_list["phases"])}
    order = []
    while len(order) < len(by_id):
        ready = [t for t in by_id.values() if t["id"] not in order
                 and set(t["depends_on"] + t["integration_dependencies"]) <= set(order)]
        assert ready, "Combined dependency cycle"
        order.append(min(ready, key=lambda t: (phases[t["phase"]], int(t["id"][1:])))["id"])
    task_list["suggested_acceptance_order"] = order
    task_list["acceptance_cards"] = "plan-audit-2026-11-14/acceptance_cards.json"
    payload = {"schema_version": 1, "plan_revision": "1.1",
               "scope": "Acceptance designs only. No fixture, capability or test is claimed executed by creating this file.", "cases": cards}
    (HERE / "acceptance_cards.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_file.write_text(json.dumps(task_list, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cards": len(cards), "tasks": len(order), "actual_acceptance_runs": 0}))


if __name__ == "__main__":
    main()
