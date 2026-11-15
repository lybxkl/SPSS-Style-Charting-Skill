"""Close the delivery record only when captured tests and exact packages agree."""
from pathlib import Path
import hashlib
import json
import platform
import re
import subprocess
import sys
import zipfile
import tarfile
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/gate-report-implementation'
EVIDENCE=OUT/'evidence'
WB=Path('F:/deepseek-data-analysis/dsh-data-analysis')
WBOUT=WB.parent/'docs/gate-report-implementation'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):return path.read_text(encoding='utf-8-sig')


def entry(command,log_path,**details):
    if not log_path.is_file():raise ValueError('missing evidence: '+str(log_path))
    return {'command':command,'exitCode':0,'log':str(log_path),'logSha256':sha(log_path),**details}


def unittest(path):
    text=read(path)
    matches=list(re.finditer(r'^Ran (\d+) tests in ([\d.]+)s\s+OK(?: \(skipped=(\d+)\))?',text,re.M))
    if not matches:raise ValueError('unittest did not complete successfully')
    match=matches[-1]
    if re.search(r'^FAILED \(',text[match.end():],re.M):raise ValueError('unittest failed')
    return {'testsRun':int(match[1]),'seconds':float(match[2]),'skipped':int(match[3] or 0),'failures':0}


def main():
    from gate_progress import source_bindings
    current_sources=source_bindings()
    for name in ['skill-full','skill-targeted','workbench-full','cross-runtime']:
        record=json.loads(read(EVIDENCE/'executions'/f'{name}.json'))
        if record['exitCode'] or not record['sourcesUnchanged'] or record['sourceBindings']!=current_sources or sha(Path(record['log']))!=record['logSha256']:
            raise ValueError('test execution does not validate current sources: '+name)
    full=unittest(EVIDENCE/'skill-release-full.log')
    targeted=unittest(EVIDENCE/'gates-release-last.log')
    if full['testsRun']<973 or targeted['testsRun']<49:raise ValueError('incomplete test discovery')
    workflow=read(WBOUT/'release-integration.log')
    cases=re.search(r'gate workflow acceptance: (\d+) passed',workflow)
    audit_cases=re.search(r'audit regressions: (\d+) passed, 0 failed',workflow)
    if not cases or int(cases[1])<23 or 'cross-runtime gate report tests passed' not in workflow:
        raise ValueError('cross-runtime acceptance incomplete')
    if not audit_cases or int(audit_cases[1])<16:raise ValueError('audit counterexamples incomplete')
    if '✓ 视觉回归全部通过' not in read(WBOUT/'release-full.log'):raise ValueError('workbench regression incomplete')
    package=json.loads(read(EVIDENCE/'package-verification.json'))
    archive=ROOT/'dist/empirical-research-pipeline.skill'
    if package['archiveSha256']!=sha(archive):raise ValueError('verified skill archive changed')
    from build_skill import iter_files,SKILL_DIR
    with zipfile.ZipFile(archive) as bundle:
        expected={SKILL_DIR.name+'/'+p.relative_to(SKILL_DIR).as_posix():p for p in iter_files()}
        if set(bundle.namelist())!=set(expected):raise ValueError('archive member closure changed')
        for name,file in expected.items():
            if bundle.read(name)!=file.read_bytes():raise ValueError('source changed after archive verification')
    installed=Path(package['installedPath'])
    for member in package['installedMembers']:
        if sha(installed/member['path'])!=member['sha256']:raise ValueError('installed implementation changed')
    for label in ('clean-package','installed-package'):
        if f"gate workflow acceptance: {cases[1]} passed" not in read(EVIDENCE/f'{label}-acceptance.log'):
            raise ValueError('package acceptance does not cover latest workflow cases')
        if f"audit regressions: {audit_cases[1]} passed, 0 failed" not in read(EVIDENCE/f'{label}-acceptance.log'):raise ValueError('package audit cases incomplete')
    plugin=json.loads(read(EVIDENCE/'workbench-package-verification.json'))
    if plugin['exitCode'] or sha(Path(plugin['archive']))!=plugin['sha256'] or not plugin['sourceBytesMatched'] or any(r['exitCode'] for r in plugin['commands']):
        raise ValueError('verified plugin artifact changed or tests failed')
    with tarfile.open(plugin['archive'],'r:gz') as bundle:
        for member in bundle.getmembers():
            if member.isfile():
                relative=Path(member.name).relative_to('package')
                if bundle.extractfile(member).read()!=(WB/relative).read_bytes():raise ValueError('plugin source changed after verification')
    if 'matches the source tree' not in read(EVIDENCE/'archive-check.log'):raise ValueError('archive source check missing')
    if 'Skill is valid!' not in read(EVIDENCE/'skill-validation.log'):raise ValueError('skill validation missing')
    fixtures=json.loads(read(EVIDENCE/'fixture-check.log'))
    if fixtures.get('accepted')!=1 or fixtures.get('rejected')!=6 or not fixtures.get('movedProjectValidated'):
        raise ValueError('protocol fixtures incomplete')
    records={
      'skillFull':entry('python -m unittest discover -s tests -v',EVIDENCE/'skill-release-full.log',**full),
      'skillTargeted':entry('python -m unittest discover -s tests -p test_gate*.py -q',EVIDENCE/'gates-release-last.log',**targeted),
      'workbenchFull':entry('npm test',WBOUT/'release-full.log'),
      'crossRuntime':entry('npm run test:gates:integration',WBOUT/'release-integration.log',workflowCases=int(cases[1]),auditCases=int(audit_cases[1])),
      'archiveBuild':entry('python tools/build_skill.py --check',EVIDENCE/'archive-check.log',archiveSha256=sha(archive),members=package['archiveMembers']),
      'cleanPackage':entry('clean skill extraction + cross-runtime acceptance',EVIDENCE/'clean-package-acceptance.log',workflowCases=int(cases[1])),
      'installedPackage':entry('installed skill + cross-runtime acceptance',EVIDENCE/'installed-package-acceptance.log',workflowCases=int(cases[1]),path=str(installed),backupPath=package['backupPath']),
      'skillValidate':entry('quick_validate.py empirical-research-pipeline',EVIDENCE/'skill-validation.log'),
      'pluginPackage':entry('python tools/verify_workbench_package.py',EVIDENCE/'workbench-clean-package.log',archiveSha256=plugin['sha256'],commands=len(plugin['commands'])),
      'protocolFixtures':entry('python tools/build_gate_fixtures.py',EVIDENCE/'fixture-check.log',accepted=1,rejected=6,movedProjectValidated=True),
      'environment':{'python':sys.version,'platform':platform.platform(),'node':subprocess.check_output(['node','--version'],text=True).strip()},
      'nonGatingDiagnostics':[
        {'command':'python -m pip check','exitCode':1,'log':str(EVIDENCE/'global-pip-check.log'),'scope':'global environment; unrelated packages; not counted as project validation'},
        {'command':'impeccable detect --json client.js','exitCode':1,'log':str(WBOUT/'ui-detect.json'),'scope':'advisory for an existing accent border; no new CSS added; visual regression passed'}],
      'recordedAt':datetime.now(timezone.utc).isoformat(),
    }
    sys.path.insert(0,str(ROOT/'empirical-research-pipeline/scripts'))
    import gates
    records['environment']['modules']=gates.environment()['modules']
    (OUT/'verification-results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    result=subprocess.run([sys.executable,str(ROOT/'tools/gate_progress.py')],cwd=ROOT)
    if result.returncode:raise RuntimeError('delivery state not recorded')
    summary=f'''# 判定下沉完成与验收报告

本次完成两个项目的判定下沉代码、工作台消费与准入、迁移和打包安装验证。技术交付状态为 completed；不代表任何真实研究已经被批准或签收。

## 实现结果

- 目录共 76 个稳定 ID：实际历史运行时 70 个，加 6 个必要的新事实。61 个技能判据均有实际检查入口，15 个宿主判据保留在工作台。逐项函数位置见 source-map.json 和 gate-inventory.csv；implemented 不等于项目通过。
- 技能复用现有 final 复核、ResearchGate、QA/版面测量、开放引擎回执与 v2 当前发布。检查数据集复合主键、真实纳入样本、模型实际使用的行号/键、审计集合、真实 DOCX/PDF 安置、正文题注、数字与结论。数学模型只有当前无观测 N 证据成立时才允许不适用。
- report / evidence / policy / attempt 使用共享 schema。当前指针校验 request→result→report 的字节哈希、generation、完整判据范围、当前策略/目录、发布 manifest、Python/依赖版本及全部资源/集合。Python 独立验证与 JavaScript 消费均拒绝被改写的兼容副本和漏项。
- 生产和 checker 共用项目锁，绑定成功执行步骤的输出与实际执行代码；可选步骤不会把旧输出冒充本轮产物。收尾单独记录 gateCheck，不篡改生产退出码。取消等真实子进程退出，恢复不抢存活/外机锁；控制输出不能通过 junction 写到项目外。
- 正式 skill 路径不再运行旧研究业务判据。面板、工具和自动链共享准入。prepare 等真实 final，QA 可生成复核材料，正式交付仍受全部到期硬要求约束。R1–R12 复用技能事实和真实阅读记录，checked 与人工按钮不能覆盖机器失败/未判。
- 新项目消费唯一 policy-template，默认 skill；已有项目保留原模式，初始化默认 compare。迁移保留策略和技能 pin 的前后记录；legacy 可显式回滚，shadow 只记新报告，compare 并列展示并打开正确的新证据。已接入项目有持久 required 标记，策略文件丢失也不能退回旧判据；缺报告、过期、损坏和未知能力均不回退。

## 实际验证

| 验证 | 结果 |
| --- | --- |
| 技能完整回归 | {full['testsRun']} 项，0 失败，{full['skipped']} 跳过 |
| 最终门禁专项 | {targeted['testsRun']} 项全部通过 |
| 工作台 npm test | 全部通过，包含真实 Chrome 视觉回归 |
| 跨语言流程验收 | {cases[1]} 项通过，另有报告契约集成通过 |
| 技能干净解包 / 安装副本 | 分别通过相同 {cases[1]} 项验收；{package['archiveMembers']} 个发布文件逐项一致 |
| 插件干净解包 | {len(plugin['commands'])} 个测试命令全部通过，与源码逐字节一致 |
| 协议样例 | 1 个合法、6 类非法；移动整个合成项目后仍能核验 |
| 确定性包与技能格式 | source check、SHA256 sidecar、quick_validate 均通过 |

三个跳过均为原有 ASR 用例，缺 VOSK_MODEL，记录为未评估，不计入通过。回归包含真实图片/DOCX/PDF、任意引擎执行、实际样本身份、Windows junction、内容同大小同时间变更、代码变化、失败/取消/恢复、漏项策略、比较模式证据和完整链路。

视觉检查覆盖并列对照、失效说明、证据展开、窄屏暗色体检中/停止和恢复状态；已查看真实浏览器截图。检测器的一个原有侧边强调边框建议保留在诊断日志，未借本任务重做原有设计。

## 发布与安装

技能包：`{archive}`，SHA256 `{sha(archive)}`。

安装副本：`{installed}`。安装前完整备份见 `{package['backupPath']}`；更早安装历史与首次备份同在 evidence 下，原有额外文件保留。插件包：`{plugin['archive']}`，SHA256 `{plugin['sha256']}`。工作台现有 skillRoot 指向源码仓库，源码与安装副本均已验证。没有清理或回退原有工作区改动，也未代替用户提交 Git 或发布到远端。

## 使用与后续开发

已有项目先初始化 compare，体检后处理真实缺口，再显式 migrate 到 skill；不能把旧空问题表当新凭据。旧生产没有内容绑定时重跑相应阶段，体检不补造历史成功回执。面板与 data_analysis_gates 支持体检、迁移、停止、恢复和证据定位。兼容细节见 COMPATIBILITY.md；统一开发与打包步骤见 DEVELOPMENT.md。

技术验收使用明确标记的合成项目，未自动迁移既有真实研究，未生成真实复读批准或人工签收。当前采用项目级串行和保守输入绑定；大项目刷新可能较慢，不相关配置变化也可能要求额外重跑。无法解析的证据保持未判，有限 v2 发布不等于完整研究。没有自动历史删除。

全局 `pip check` 另报 cnki-mcp 缺 scikit-image，以及 fastapi/starlette、mitmproxy/typing-extensions、streamlit/Pillow 的约束冲突；与新增门禁协议依赖无关，本次未修改这些依赖。原始结果保存在 evidence/global-pip-check.log，未计为项目通过，也未据此改动其他项目环境。本次实际运行环境与全部命令、日志哈希见 verification-results.json。

先前只完成四条首批判据的记录已保留为 IMPLEMENTATION-REPORT.pilot.md 与 pilot-state.json。最终任务状态、源码指纹、Git 工作区快照与发布证据分别见 implementation-state.json、delivery-snapshot.json 和 evidence/package-verification.json，不以文件存在替代验收。
'''
    (OUT/'IMPLEMENTATION-REPORT.md').write_text(summary,encoding='utf-8')
    print(json.dumps({'completed':True,'skillTests':full['testsRun'],'targetedTests':targeted['testsRun'],'workflowCases':int(cases[1]),'report':str(OUT/'IMPLEMENTATION-REPORT.md')},ensure_ascii=False))


if __name__=='__main__':main()
