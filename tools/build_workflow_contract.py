"""Build structural workflow schema; workflow.json itself is the maintained spec."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'empirical-research-pipeline/contracts/workflow'

def build():
    text={'type':'string'}
    strings={'type':'array','items':text}
    ident={'type':'string','pattern':'^[a-z][a-z0-9-]{0,63}$'}
    def obj(properties,required=()):return {'type':'object','properties':properties,'required':list(required),'additionalProperties':False}
    option=obj({'flag':text,'file':text,'whenFile':text},['flag'])
    step_fields={'script':{'type':['string','null']},'args':strings,'whenFile':text,'produces':strings,'continueOnError':{'type':'boolean'},'optionalArgs':{'type':'array','items':option},'optionalFlags':{'type':'array','items':option}}
    admission=obj({'checkpoint':{'enum':['data-ready','analysis-ready','figures-ready','manuscript-ready','delivery-ready']},'reportStages':strings,'gates':strings,'waitingMessage':text,'whenFile':text,'requiredInStrict':{'type':'boolean'},'requireComplete':{'type':'boolean'}})
    ui=obj({'panels':strings,'draftTask':text,'requiredFiles':strings,'artifactPrefixes':strings,'legacySkipWhenMissing':text})
    stage=obj({**step_fields,'id':ident,'index':{'type':'integer','minimum':1},'name':{'type':'string','minLength':1},'short':text,'purpose':text,'dependsOn':{'type':'array','items':ident,'uniqueItems':True},'steps':{'type':'array','items':obj(step_fields,['script'])},'artifacts':strings,'admission':admission,'legacyAdmission':admission,'afterRun':admission,'inspectionStages':strings,'manualInstructions':strings,'ui':ui},['id','name','purpose','dependsOn','artifacts','admission','afterRun','inspectionStages','manualInstructions','ui'])
    action=obj({'id':ident,'tool':ident,'variant':text,'stage':ident,'label':text,'steps':{'type':'array','minItems':1,'items':obj(step_fields,['script'])},'outFile':text,'admission':admission},['id','stage','label','steps'])
    task=obj({'id':ident,'stage':ident,'label':text,'file':text,'brief':text,'need':strings,'contextFiles':strings},['id','stage','label','file','brief','need'])
    binding=obj({'token':text,'select':{'enum':['first-existing','latest-existing','directory-of']},'paths':{'type':'array','items':{'anyOf':[text,obj({'json':text,'array':text,'field':text},['json','array','field'])]}},'fallback':text,'from':text,'cases':{'type':'object','additionalProperties':text}},['token','select'])
    binding['allOf']=[{'if':{'properties':{'select':{'const':'directory-of'}},'required':['select']},'then':{'required':['from']},'else':{'required':['paths','fallback']}}]
    schema=obj({'schema':{'const':'dsa.workflow/1'},'id':ident,'version':{'type':'string','pattern':'^\\d+\\.\\d+\\.\\d+$'},'requiredFeatures':{'type':'array','items':text,'uniqueItems':True},'workspace':obj({'directories':strings},['directories']),'stages':{'type':'array','minItems':1,'items':stage},'actions':{'type':'array','items':action},'draftTasks':{'type':'array','items':task},'rerunRules':{'type':'array','items':obj({'match':{'enum':['exact','prefix']},'pattern':text,'stages':strings},['match','pattern','stages'])},'argumentBindings':{'type':'array','items':binding},'taskConstraints':strings,'agentInstructions':strings},['schema','id','version','requiredFeatures','workspace','stages','actions','draftTasks','rerunRules','argumentBindings','taskConstraints'])
    schema['$schema']='https://json-schema.org/draft/2020-12/schema'
    DEST.mkdir(parents=True,exist_ok=True)
    (DEST/'workflow.schema.json').write_text(json.dumps(schema,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':build()
