"""Verify the real archive and optionally synchronize the active installed skill.

Never alters a research project. Existing installed extras are preserved and a
complete backup precedes the explicit --install operation.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]
WORKBENCH=Path('F:/deepseek-data-analysis/dsh-data-analysis')
SKILL=ROOT/'empirical-research-pipeline'
ARCHIVE=ROOT/'dist/empirical-research-pipeline.skill'
OUT=ROOT/'docs/gate-report-implementation/evidence'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def acceptance(package,label):
    env={**os.environ,'DSA_SKILL_ROOT':str(package),'PYTHONUTF8':'1'}
    commands=[]
    with (OUT/f'{label}-acceptance.log').open('w',encoding='utf-8') as log:
        for script in ['tests/gate-report.test.mjs','tests/gate-workflow.test.mjs','tests/gate-audit.test.mjs']:
            result=subprocess.run(['node',script],cwd=WORKBENCH,env=env,capture_output=True,text=True,encoding='utf-8',timeout=240)
            log.write(result.stdout+result.stderr);log.flush()
            commands.append({'script':script,'exitCode':result.returncode})
            if result.returncode:raise RuntimeError(label+' acceptance failed; see evidence log')
    return {'exitCode':0,'log':f'{label}-acceptance.log','commands':commands}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    record={'archiveSha256':sha(ARCHIVE)}
    with tempfile.TemporaryDirectory(prefix='dsa-clean-package-') as temp:
        with zipfile.ZipFile(ARCHIVE) as archive:
            entries=archive.namelist()
            if len(entries)!=len(set(entries)):raise ValueError('duplicate archive member')
            for name in entries:
                (Path(temp)/name).resolve().relative_to(Path(temp).resolve())
                relative=Path(name).relative_to(SKILL.name)
                if archive.read(name)!=(SKILL/relative).read_bytes():raise ValueError('archive/source mismatch')
            archive.extractall(temp)
        clean=Path(temp)/SKILL.name
        record['archiveMembers']=len(entries)
        record['cleanExtract']=acceptance(clean,'clean-package')
        if args.install:
            installed=Path.home()/'.agents/skills'/SKILL.name
            if not installed.is_dir() or installed.is_symlink():raise ValueError('expected regular installed skill directory')
            backup=OUT/('installed-backup-'+uuid.uuid4().hex[:12])
            shutil.copytree(installed,backup,symlinks=True)
            record.update(installedPath=str(installed),backupPath=str(backup))
            for source in clean.rglob('*'):
                if not source.is_file():continue
                target=installed/source.relative_to(clean)
                target.resolve().relative_to(installed.resolve())
                target.parent.mkdir(parents=True,exist_ok=True)
                temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
                try:
                    shutil.copy2(source,temporary)
                    os.replace(temporary,target)
                finally:temporary.unlink(missing_ok=True)
                if sha(source)!=sha(target):raise ValueError('installed file digest mismatch')
            record['installed']=acceptance(installed,'installed-package')
            record['installedMembers']=[{'path':p.relative_to(clean).as_posix(),'sha256':sha(p)}
                                        for p in sorted(clean.rglob('*')) if p.is_file() and '__pycache__' not in p.parts]
    previous=OUT/'package-verification.json'
    if previous.is_file():
        shutil.copy2(previous,OUT/('package-verification-history-'+uuid.uuid4().hex[:12]+'.json'))
    previous.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k!='installedMembers'},ensure_ascii=False))


if __name__=='__main__':main()
