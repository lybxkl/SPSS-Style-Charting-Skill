"""Capture a test's real exit status and exact source bindings before and after it."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from gate_progress import source_bindings,sha,ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',required=True)
    parser.add_argument('--cwd',default=str(ROOT))
    parser.add_argument('--log',required=True)
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    command=args.command[1:] if args.command[:1]==['--'] else args.command
    if not command:parser.error('a test command is required')
    before=source_bindings();started=datetime.now(timezone.utc).isoformat()
    log=Path(args.log);log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w',encoding='utf-8') as stream:
        result=subprocess.run(command,cwd=args.cwd,env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'},stdout=stream,stderr=subprocess.STDOUT)
    record={'command':command,'cwd':args.cwd,'startedAt':started,'finishedAt':datetime.now(timezone.utc).isoformat(),
            'exitCode':result.returncode,'sourceBindings':before,'sourcesUnchanged':before==source_bindings(),'log':str(log.resolve()),'logSha256':sha(log)}
    out=ROOT/'docs/gate-report-implementation/evidence/executions';out.mkdir(parents=True,exist_ok=True)
    (out/(args.name+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k!='sourceBindings'},ensure_ascii=False))
    return result.returncode or (0 if record['sourcesUnchanged'] else 1)


if __name__=='__main__':sys.exit(main())
