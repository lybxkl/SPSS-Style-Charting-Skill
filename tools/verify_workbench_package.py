"""Run the packaged plugin's own regression and integration tests after extraction."""
from pathlib import Path
import hashlib
import json
import os
import shlex
import subprocess
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]
WORKBENCH=Path('F:/deepseek-data-analysis/dsh-data-analysis')
ARTIFACTS=WORKBENCH.parent/'docs/gate-report-implementation'
OUT=ROOT/'docs/gate-report-implementation/evidence'


def main():
    metadata=json.loads((ARTIFACTS/'workbench-package.json').read_text(encoding='utf-8-sig'))[0]
    archive=ARTIFACTS/metadata['filename']
    results=[]
    with tempfile.TemporaryDirectory(prefix='dsa-plugin-clean-') as temp:
        target=Path(temp)
        with tarfile.open(archive,'r:gz') as bundle:
            for member in bundle.getmembers():
                (target/member.name).resolve().relative_to(target.resolve())
                if not (member.isfile() or member.isdir()):raise ValueError('non-file package member')
                if member.isfile():
                    rel=Path(member.name).relative_to('package')
                    if bundle.extractfile(member).read()!=(WORKBENCH/rel).read_bytes():
                        raise ValueError('package/source mismatch: '+str(rel))
            bundle.extractall(target,filter='data')
        package=target/'package'
        scripts=json.loads((package/'package.json').read_text(encoding='utf-8'))['scripts']
        env={**os.environ,'DSA_SKILL_ROOT':str(Path.home()/'.agents/skills/empirical-research-pipeline'),'PYTHONUTF8':'1'}
        with (OUT/'workbench-clean-package.log').open('w',encoding='utf-8') as log:
            for group in ('test','test:gates:integration'):
                for command in scripts[group].split(' && '):
                    argv=shlex.split(command)
                    if argv[0]!='node':raise ValueError('unexpected package test launcher')
                    run=subprocess.run(argv,cwd=package,env=env,capture_output=True,text=True,encoding='utf-8',timeout=240)
                    log.write(f'\nCOMMAND {command}\n'+run.stdout+run.stderr)
                    log.flush()
                    results.append({'command':command,'exitCode':run.returncode})
                    if run.returncode:raise RuntimeError('packaged plugin test failed: '+command)
    record={'archive':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
            'sourceBytesMatched':True,'commands':results,'exitCode':0}
    (OUT/'workbench-package-verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'exitCode':0,'commands':len(results),'sourceBytesMatched':True}))


if __name__=='__main__':main()
