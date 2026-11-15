"""One-time catalog evolution; no existing identifier is reused."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
FILE=ROOT/'empirical-research-pipeline/contracts/gates/catalog.json'


def main():
    value=json.loads(FILE.read_text(encoding='utf-8'))
    records={r['id']:r for r in value['gates']}
    additions=[
        ('scope-doc','scope','workbench','data-ready','范围文档存在且非空'),
        ('audit-flow','audit','skill','data-ready','审计样本流程完整且口径合法'),
        ('coding-sheet','coding','skill','data-ready','适用时编码表存在且非空'),
        ('manuscript-docx','manuscript','skill','manuscript-ready','实际成稿文件可读取'),
        ('fig-source-dpi','figures','skill','figures-ready','源图在计划宽度的有效分辨率'),
        ('fig-source-font','figures','skill','figures-ready','源图在计划宽度的可测字号'),
        ('v2.release-ready','qa','skill','delivery-ready','当前 v2 发布评估确实就绪'),
        ('qa-decision-facts','qa','skill','delivery-ready','判断台账机器检查无错误'),
        ('recheck.caption-n-present','recheck','skill','delivery-ready','实际图注含明确样本量'),
        ('recheck.caption-n-consistent','recheck','skill','delivery-ready','实际图注样本量与登记口径一致'),
    ]
    for ident,stage,owner,point,label in additions:
        records.setdefault(ident,dict(id=ident,definitionVersion='2.0',owner=owner,
            reportStage=stage,displayStage=stage,defaultLevel='error',blockingAt=point,
            label=label,migrationBatch='S2',implemented=False))
    for r in records.values():
        # These are declarations of executable coverage, not successful quality results.
        r['implemented']=True
        if r['id'] in ('sources-mounted','sources-outside'):r['displayStage']='scope'
        if r['reportStage'] in ('audit','coding','dataset'):r['blockingAt']='data-ready'
        if r['id'] in ('verification-final','verification-fresh','verification-cells','dataset-in-analysis'):r['blockingAt']='analysis-ready'
        if r['reportStage']=='stats':r['blockingAt']='figures-ready'
        if r['id'] in ('fig-files','fig-manifest','fig-status','fig-title','fig-paper'):r['blockingAt']='figures-ready'
        r['allowNa']=r['id'].startswith('coding-') or r['id'] in ('v2.release-ready','fig-paper','fig-palette','stats-fit-n','stats-flow','models-sweep','qa-vision','materials-provenance','materials-selection','materials-provenance-cover','recheck.caption-n-present','recheck.caption-n-consistent')
        r['required']=r['id'] not in ('stage-source','qa-decisions','qa-vision','artifacts-declared','fig-palette','qa-decision-facts','qa-review','methods-report','models-sweep','recheck-report')
    value['gates']=sorted(records.values(),key=lambda r:r['id'])
    value['version']='1.1'
    FILE.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
