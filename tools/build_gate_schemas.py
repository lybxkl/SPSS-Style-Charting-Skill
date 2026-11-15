"""Build self-contained offline schemas consumed by Python and JavaScript."""
import copy
import json
from pathlib import Path

DEST=Path(__file__).resolve().parents[1]/'empirical-research-pipeline/contracts/gates'
STRING={'type':'string','minLength':1}
HASH={'type':'string','pattern':'^[a-f0-9]{64}$'}
PATH={'type':'string','minLength':1,'pattern':r'^(?!/)(?!.*\\)(?!.*:)(?!.*(?:^|/)\.\.(?:/|$))[^\u0000]+$'}
INTEGER={'type':'integer','minimum':0}
STAGES=['scope','audit','coding','dataset','verify','stats','figures','manuscript','qa','recheck']
POINTS=['data-ready','analysis-ready','figures-ready','manuscript-ready','delivery-ready']


def obj(properties,required=None):
    return {'type':'object','properties':properties,'required':list(properties) if required is None else required}


def array(item):return {'type':'array','items':item}


def write(name,value):
    value={'$schema':'https://json-schema.org/draft/2020-12/schema','$id':f'urn:dsa:{name}:1',**value}
    (DEST/f'{name}.schema.json').write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')


def build():
    evidence=obj({'kind':{'enum':['structure','measurement','table','text','record','applicability']},
                  'resourceRef':STRING,'locator':{'type':'object'},'expected':{},'actual':{}},['kind','resourceRef'])
    evidence['allOf']=[{'if':{'properties':{'kind':{'const':'structure'}}},
                        'then':{'required':['locator','expected','actual']}},
                       {'if':{'properties':{'kind':{'const':'text'}}},
                        'then':{'required':['locator','quote']}}]
    write('evidence',evidence)
    requirement=obj({'gateId':STRING,'definitionVersion':STRING,'reportStage':{'enum':STAGES},
                     'displayStage':{'enum':STAGES},'blockingAt':{'enum':POINTS},
                     'source':{'enum':['skill','workbench','legacy']},'allowNa':{'type':'boolean'},'required':{'type':'boolean'}},
                    ['gateId','definitionVersion','reportStage','displayStage','blockingAt','source','allowNa'])
    thresholds=obj({k:{'type':'number','exclusiveMinimum':0} for k in ['minEffectiveDpi','minFontPt','figureWidthCm']})
    policy=obj({'schema':{'const':'dsa.gate-policy/1'},'mode':{'enum':['legacy','shadow','compare','skill']},
                'scopeKey':STRING,'catalogSha256':HASH,'researchContract':{'enum':['v1','v2']},
                'thresholds':thresholds,'requirements':{**array(requirement),'minItems':1}},
               ['schema','mode','scopeKey','catalogSha256','thresholds','requirements'])
    write('policy',policy)
    common={'attemptId':{'type':'string','pattern':'^attempt-[a-f0-9]+$'},'generation':{'type':'integer','minimum':1},'stage':{'enum':STAGES}}
    request=obj({'schema':{'const':'dsa.gate-attempt/1'},**common,'checkpoint':{'enum':POINTS},'scopeKey':STRING,
                 'requestedAt':STRING,'requestedGateIds':{**array(STRING),'uniqueItems':True},'catalogSha256':HASH,'policySha256':HASH,'producerContext':array(STRING)})
    state=obj({'schema':{'const':'dsa.gate-state/1'},**common,
               'phase':{'enum':['requested','running','production-running','completed','crashed','cancelled','interrupted','conflict']},
               'requestPath':PATH,'requestSha256':HASH,'resultPath':PATH,'resultSha256':HASH},
              ['schema',*common,'phase','requestPath','requestSha256'])
    state['allOf']=[{'if':{'properties':{'phase':{'const':'completed'}}},'then':{'required':['resultPath','resultSha256']}}]
    result=obj({'schema':{'const':'dsa.gate-result/1'},'attemptId':common['attemptId'],'generation':common['generation'],
                'outcome':{'enum':['completed','crashed','cancelled','interrupted','conflict']},'finishedAt':STRING,
                'checkerExitCode':{'type':['integer','null']},'reportPath':PATH,'reportSha256':HASH,'reason':STRING},
               ['schema','attemptId','generation','outcome','finishedAt','checkerExitCode'])
    result['allOf']=[{'if':{'properties':{'outcome':{'const':'completed'}}},'then':{'required':['reportPath','reportSha256']},'else':{'required':['reason']}}]
    error=obj({'schema':{'const':'dsa.gate-error/1'},'attemptId':common['attemptId'],'generation':common['generation'],'reason':STRING,'detail':STRING,'finishedAt':STRING})
    write('attempt',{'oneOf':[request,state,result,error]})
    report=json.loads((DEST/'report.schema.json').read_text(encoding='utf-8'))
    report['$defs']['evidence']=evidence
    report['$defs']['gate']['properties']['evidence']={**array({'$ref':'#/$defs/evidence'}),'minItems':1}
    report['properties']['thresholds']=thresholds
    report['properties']['collections']=array(obj({'id':STRING,'rootId':STRING,'basePath':PATH,'selector':obj({'recursive':{'const':True}}),'members':{**array(PATH),'uniqueItems':True},'complete':{'const':True}}))
    report['properties']['stage']={'enum':STAGES}
    report['properties']['requiredFeatures']['items']={'enum':['coverage-v1','relative-roots-v1','project-aliases-v1','package-closure-v1']}
    report['properties']['resources']['items']['properties']['path']=PATH
    report['properties']['resources']['items']['properties']['projectPaths']={**array(PATH),'uniqueItems':True,'minItems':1}
    report['properties']['resources']['items']['properties']['rootId']={'type':'string','pattern':'^(project|skill|material:[A-Za-z0-9_.-]+)$'}
    (DEST/'report.schema.json').write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':build()
