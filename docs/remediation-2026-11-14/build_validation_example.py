"""Persistent synthetic validation artifact. Not real research data or findings.

Run prepare before compose; compose requires Word/LibreOffice. All source
values are generated here, then reopened through the normal second-pass gate.
"""
from pathlib import Path
import csv
from decimal import Decimal
import json
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO/"tests"), str(REPO/"empirical-research-pipeline/scripts")]
from _research_fixture import known_project, final_review, csv_write
import contract_v2 as C
import models as M
import validation as V
import designcheck as DC
import discovery as D
import source_units as SU
import manuscript as MS
import claims as CL
import support_review as SR

ROOT = Path(__file__).resolve().parent/"validation-example-v3"


def prepare():
    if ROOT.exists():
        raise RuntimeError("Example already exists; preserve previous evidence and choose a fresh directory.")
    p = known_project(ROOT, n=20, fit=False)
    source = ROOT/"materials/raw.csv"
    with source.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rename = {r["id"]:f"合成项目 {r['id']} 原始记录" for r in rows}
    for row in rows:
        row["id"] = rename[row["id"]]
    for path in (source, ROOT/"data/person.csv"):
        csv_write(path, ["id","treatment","y"], [[r[k] for k in ("id","treatment","y")] for r in rows])
    proof_path = ROOT/"data/person.prov.jsonl"
    proofs = [json.loads(line) for line in proof_path.read_text(encoding="utf-8").splitlines()]
    for item in proofs:
        item["key"] = rename[item["key"]]
        if item["column"] == "id":
            item["value"] = rename[item["value"]]
            item["sources"][0]["raw"] = item["value"]
        item["sources"][0]["sha256"] = C.file_sha256(source)
    proof_path.write_text("".join(json.dumps(r,ensure_ascii=False)+"\n" for r in proofs), encoding="utf-8")
    coverage = ROOT/"output/source_coverage.jsonl"
    entry = json.loads(coverage.read_text(encoding="utf-8")); entry["sha256"] = C.file_sha256(source)
    coverage.write_text(json.dumps(entry,ensure_ascii=False)+"\n",encoding="utf-8")
    units = SU.SourceUnits(p, root=ROOT); units.build(ROOT/"materials")
    discovery = D.Discovery(p,units); discovery.from_materials()
    for ident in {r["id"] for r in p.read("discovery_candidate")}:
        discovery.dispose(ident,"adopted",dataset="person",reason="Synthetic source columns are all in the reviewed dataset.")
    (ROOT/"output/discovery_report.json").write_text(json.dumps(discovery.report()),encoding="utf-8")
    final_review(ROOT)
    spec = {"id":"M1","family":"ols","purpose":"known synthetic arithmetic only",
            "variables":{"y":"y","x":["treatment"]},
            "inputs":[{"role":"fit","dataset":"data/person.csv","sha256":C.file_sha256(ROOT/"data/person.csv"),"keys":["id"]}],
            "n_semantics":{"kind":"observation","unit":"one synthetic participant"},
            "result":{"type":"coefficient_table","target_parameter":"treatment","unit":"score points","scale":"linear"}}
    M.register(p,spec); assert M.fit(p,"M1")["status"] == "estimated"
    assert V.independent_ols(p,"M1")["status"] == "passed"
    assert DC.record_linkage(p,M.load_spec(p,"M1")["data"])["status"] == "passed"
    # Independent source arithmetic after integration, before the support review.
    with source.open(encoding="utf-8",newline="") as stream: reread = list(csv.DictReader(stream))
    means = {g:sum(Decimal(r["y"]) for r in reread if r["treatment"]==g)/sum(r["treatment"]==g for r in reread) for g in ("0","1")}
    assert means["1"]-means["0"] == Decimal("0.42")
    sentence = "在合成数据中，处理指标与得分的线性关联为 0.42 分。"
    claim = CL.register_claim(p,claim_id="effect",claim_type="result",text=sentence,block_id="results",section="results",support=[{"kind":"result","id":"M1"}])
    SR.review(p,claim["id"],decision="supported",reviewer="synthetic-formula-check",
              note="Reopened every source record; treatment mean minus control mean equals 0.42 exactly. This is an association in generated data, with no population inference.",
              reread_scopes=[{"path":str(source),"sha256":C.file_sha256(source),"locator":"all original rows and treatment/y columns"}])
    bodies = {
      "abstract":"本稿是研究流水线的合成验证示例。全部资料由验证脚本生成，共包含 {n} 条合成记录。研究目的是检验来源复核、独立计算、密集标签制图和成稿输出是否能保持一致。结果仅用于软件校验，不代表真实人群或现实干预的发现。",
      "keywords":"合成验证；数据溯源；逐格复核；科研图表",
      "introduction":"研究资料整理需要同时控制来源、口径和输出一致性。本示例用可独立计算的合成值建立最小完整链路，观察从原件到最终文稿是否发生数据替换、遗漏或未声明的变换。它验证具体软件行为，不评估研究问题的现实价值。",
      "methods":"原始材料为脚本生成的 CSV。每条记录有独立主键、处理指标和得分；数据集每一格保留原始行列定位。整合后重新打开原始文件逐格比较，再执行 final 核验。模型采用含截距的最小二乘回归，随后使用独立线性代数实现校验。原始得分没有随机误差，因此不把标准误或显著性当作实质研究证据。",
      "results":sentence+"模型所用记录数为 {n}。图中的每根柱对应原始记录得分；横轴保留全部项目标签，使用斜排和底部留白保持同图呈现。附表完整列出核验后的记录。",
      "discussion":"模型计算与源数据的组间差值一致，说明这份合成样本中的数值传递保持了预设关系。图表可读性需要在最终纸面尺寸继续检查，单独查看高分辨率源图不能替代这一步。这个结果不构成对任意材料、任意语言和任意模型正确性的普遍证明。",
      "limitations":"本示例没有真实调查、文献证据或观察误差，也未建立因果识别设计。软件检查可以发现版本或数值矛盾，无法代替对原始材料语境的理解。实际研究仍须逐项审阅实体、时间、单位、缺失、抽取与方法适用性。",
      "conclusion":"合成验证链路保留了原始定位、整合后的复核记录和模型校核依据，并输出可阅读的文稿与同图完整标签。正式研究交付应以当前项目的证据和实际版面检查为准。",
      "appendix":"本稿的全部数据均为合成。复现材料、来源映射、逐格复核、模型版本与独立校核随示例工程一并保存。没有引用外部文章，也不声称完成任何未实际执行的外部查核。"
    }
    for section,text in bodies.items():
        CL.register_block(p,block_id=section,section=section,text=text,claims=["effect"] if section=="results" else [])
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import figsemantics as FS
    plt.rcParams.update({"font.family":"Microsoft YaHei","font.size":12,"axes.unicode_minus":False,"pdf.fonttype":42})
    data = pd.read_csv(ROOT/"data/person.csv")
    fig,ax = plt.subplots(figsize=(8,6),dpi=120)
    ax.bar(data["id"],data["y"],color="#1C4E7B",width=0.7)
    ax.set_ylabel("合成得分（分）");ax.set_ylim(0,0.65)
    plt.setp(ax.get_xticklabels(),rotation=45,ha="right",rotation_mode="anchor",fontsize=12)
    fig.subplots_adjust(left=.12,right=.98,top=.96,bottom=.47)
    mapping={"type":"bar","x":"id","y":"y","unit":"score points"}
    directory=ROOT/"output/figures";directory.mkdir(parents=True,exist_ok=True)
    png,pdf=directory/"dense-labels.png",directory/"dense-labels.pdf"
    fig.savefig(png,dpi=600);fig.savefig(pdf)
    checks=FS.check_figure(fig,data,mapping);geometry=FS.label_geometry(fig)
    record=FS.record_figure(p,"F1",fig,mapping,"data/person.csv",C.file_sha256(ROOT/"data/person.csv"),checks,geometry,FS.palette_report(fig),png_path=str(png),pdf_path=str(pdf),dpi=600,caption="合成记录得分与完整项目标签")
    (ROOT/"figure-qa.json").write_text(json.dumps({"checks":checks,"geometry":geometry,"record_status":record["status"]},ensure_ascii=False,indent=2),encoding="utf-8")
    assert record["status"]=="checked", (checks,geometry)
    plt.close(fig)
    print(json.dumps({"prepared":str(ROOT),"figure_status":record["status"],"overlaps":geometry["overlaps"]},ensure_ascii=False))


def refresh():
    """Reopen/review/refit after a verification-code version change."""
    p=C.Project(ROOT)
    units=SU.SourceUnits(p,root=ROOT);units.build(ROOT/"materials")
    discovery=D.Discovery(p,units);discovery.from_materials()
    for ident in discovery._active_candidates():
        discovery.dispose(ident,"adopted",dataset="person",reason="Reopened synthetic CSV: all source columns are present in the reviewed person dataset.")
    (ROOT/"output/discovery_report.json").write_text(json.dumps(discovery.report()),encoding="utf-8")
    final_review(ROOT)
    assert M.fit(p,"M1")["status"]=="estimated"
    assert V.independent_ols(p,"M1")["status"]=="passed"
    assert DC.record_linkage(p,M.load_spec(p,"M1")["data"])["status"]=="passed"
    source=ROOT/"materials/raw.csv"
    with source.open(encoding="utf-8",newline="") as stream: rows=list(csv.DictReader(stream))
    means={g:sum(Decimal(r["y"]) for r in rows if r["treatment"]==g)/sum(r["treatment"]==g for r in rows) for g in ("0","1")}
    assert means["1"]-means["0"]==Decimal("0.42")
    SR.review(p,"effect",decision="supported",reviewer="synthetic-formula-recheck",
              note="After reopening every original row, the treatment difference remains exactly 0.42; the new fit is an association only in generated data.",
              reread_scopes=[{"path":str(source),"sha256":C.file_sha256(source),"locator":"all original rows, treatment and y columns"}])
    compose()


def compose():
    import layout_check as LC
    import release as R
    p=C.Project(ROOT)
    numbers={"n":20,"effect":"0.42"}
    trace={"n":{"model":"M1","field":"n"},"effect":{"model":"M1","parameter":"treatment","format":".2f"}}
    figure={"figure_id":"F1","png":str(ROOT/"output/figures/dense-labels.png"),"pdf":str(ROOT/"output/figures/dense-labels.pdf"),"width_cm":15,"caption":"合成记录得分与完整项目标签"}
    info=MS.build_docx(p,docx_path=ROOT/"manuscript.docx",title="合成数据溯源与科研图表验证",authors="软件验证示例",numbers=numbers,trace=trace,
                       figures=[figure],tables=[{"table_id":"raw","csv":"data/person.csv","caption":"逐格复核后的合成记录"}],
                       outline=["abstract","keywords","introduction","methods","results","discussion","limitations","conclusion",{"id":"appendix","title":"附录"}])
    export=MS.export_pdf(ROOT/"manuscript.docx",ROOT/"manuscript.pdf",figures=[figure])
    verification=MS.verify_printed(p,docx_path=ROOT/"manuscript.docx",pdf_path=ROOT/"manuscript.pdf",spans=info["spans"],numbers=numbers,trace=trace)
    assert verification["ok"],verification
    layout=LC.check_placement(ROOT/"manuscript.docx",ROOT/"manuscript.pdf",figures=[{**figure,"figure_record":p.latest("figure_spec","F1")}])
    LC.record_check(p,layout,docx_rel="manuscript.docx",pdf_rel="manuscript.pdf")
    (ROOT/"layout-qa.json").write_text(json.dumps(layout,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    assert layout["ok"], layout
    result=p.latest("model_result","M1")["data"]["payload"]
    report=("# 合成验证分析报告\n\n全部数据由示例脚本生成，只用于验证软件行为。\n\n"
            f"当前 OLS 实际使用 {result['n']} 条记录；处理指标系数为 {result['coefficients']['treatment']['estimate']:.2f} 分。"
            "该数值已用独立线性代数与回读原始 CSV 的组间差值分别校验。没有随机误差，不将标准误、置信区间或显著性作为实质研究证据。\n\n"
            "原始材料、逐格来源、整合后的第二遍复核和模型版本均保留在示例工程。图保留全部项目标签并斜排；DOCX/PDF 实际安置后的分辨率、字号、图像身份和图注由 layout-qa.json 记录。实际逐页目视检查另存 visual-review.json。\n\n"
            "这是已知答案的合成测试，不代表真实人群、因果识别或任意资料均可自动恢复。\n")
    (ROOT/"analysis-report.md").write_text(report,encoding="utf-8")
    scope={"deliverable_type":"full_research","analysis_report":"analysis-report.md",
           "datasets":["person"],"models":["M1"],"claims":["effect"],"figures":["F1"],"sections":info["outline"],"pdf":"manuscript.pdf",
           "artifacts":["analysis-report.md","manuscript.docx","manuscript.pdf","output/figures/dense-labels.png","output/figures/dense-labels.pdf"]}
    release=R.build(p,scope,label="synthetic-validation")
    (ROOT/"example-summary.json").write_text(json.dumps({"export":export,"printed":verification,"release":release},ensure_ascii=False,indent=2),encoding="utf-8")
    assert release["status"]=="complete",release
    assert release["project_ready"] and R.current(p)["status"]=="complete",release
    print(json.dumps(release,ensure_ascii=False))


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation",choices=("prepare","compose","refresh"))
    parser.add_argument("--root",type=Path,default=ROOT,help="choose a new directory for a clean reproducible example; prepare never overwrites an existing one")
    args=parser.parse_args();ROOT=args.root.resolve()
    {"prepare":prepare,"compose":compose,"refresh":refresh}[args.operation]()
