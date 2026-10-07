from pathlib import Path
import hashlib
import json
import shutil
import socket
import subprocess
from datetime import datetime, timezone, timedelta

SCRATCH=Path(__file__).resolve().parent
PREVIOUS=Path(r'C:\dev\workspace\prography\APM\performance-test\results\2026-10-07-authenticated-search-count-removal')
OUT=PREVIOUS.parent/'2026-10-07-authenticated-search-block-index'
BACKEND=Path(r'C:\dev\workspace\KnockIn\back\11th-1team-BE')
FILES=['src/main/java/org/example/knockin/board/repository/impl/RoommateBoardRepositoryImpl.java',
       'src/main/java/org/example/knockin/member/entity/Block.java']
VARIANTS=['before-or','after-index-and']
if OUT.exists():
    raise RuntimeError('Refuse to overwrite an existing result directory')
(OUT/'execution').mkdir(parents=True)
def git(*args):
    return subprocess.check_output(['git','-C',str(BACKEND),*args]).decode('utf-8').strip()
def listening(port):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=1):
            return True
    except OSError:
        return False
metadata={'preparedAtKst':datetime.now(timezone(timedelta(hours=9))).isoformat(),
          'backendCommit':git('rev-parse','HEAD'),'backendOriginalStatus':git('status','--short').splitlines(),
          'existingBackend8080Listening':listening(8080),'measurementPort':18080,
          'comparison':'Current HEAD Slice with OR/no new Block composite index versus working-tree Slice with two NOT EXISTS AND and Block composite index',
          'previousReport':'../2026-10-07-authenticated-search-count-removal/report.md'}
(OUT/'initial-environment.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'execution/block-index-source.patch').write_bytes(subprocess.check_output(['git','-C',str(BACKEND),'diff','HEAD','--',*FILES]))
builds=[]
tree_hashes={}
for variant in VARIANTS:
    project=SCRATCH/variant
    if project.exists():
        raise RuntimeError('Isolated project already exists')
    project.mkdir()
    for name in ['src','gradle']:
        shutil.copytree(BACKEND/name,project/name,ignore=shutil.ignore_patterns('firebase*.json'))
    for name in ['build.gradle','settings.gradle','gradlew','gradlew.bat']:
        shutil.copyfile(BACKEND/name,project/name)
    if variant=='before-or':
        for name in FILES:
            (project/name).write_bytes(subprocess.check_output(['git','-C',str(BACKEND),'show','HEAD:'+name]))
    hashes={str(path.relative_to(project)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest()
            for path in project.rglob('*') if path.is_file()}
    tree_hashes[variant]=hashes
    target=OUT/'controlled-ab'/variant
    target.mkdir(parents=True)
    for name in FILES:
        saved=OUT/'execution/backend-source'/variant/name
        saved.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(project/name,saved)
    print('BUILD '+variant,flush=True)
    with (target/'build.log').open('wb') as log:
        result=subprocess.run(['cmd','/c','gradlew.bat','--offline','--no-daemon','--console=plain','bootJar','-x','test'],
                              cwd=project,stdout=log,stderr=subprocess.STDOUT,timeout=300,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        print((target/'build.log').read_text('utf-8',errors='replace')[-4500:])
        raise RuntimeError('Isolated build failed: '+variant)
    jar=project/'build/libs/KnockIn-0.0.1-SNAPSHOT.jar'
    builds.append({'variant':variant,'jarPath':str(jar),'jarSha256':hashlib.sha256(jar.read_bytes()).hexdigest(),
                   'sourceHashes':{name:hashes[name] for name in FILES}})
    print('BUILT '+variant,flush=True)
differences=[name for name in sorted(set(tree_hashes[VARIANTS[0]])|set(tree_hashes[VARIANTS[1]]))
             if tree_hashes[VARIANTS[0]].get(name)!=tree_hashes[VARIANTS[1]].get(name)]
if differences!=sorted(FILES):
    raise RuntimeError('Unexpected source/runtime file differences: '+str(differences))
(OUT/'controlled-ab/builds.json').write_text(json.dumps(builds,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'controlled-ab/source-tree-comparison.json').write_text(json.dumps({'changedFiles':differences,'allOtherCopiedFilesIdentical':True,
    'fileHashes':tree_hashes},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def replace(text,old,new):
    if old not in text:
        raise RuntimeError('Missing adaptation marker: '+old[:100])
    return text.replace(old,new)
library=(PREVIOUS/'execution/focused_search_lib.py').read_text('utf-8').replace('authenticated-search-count-removal','authenticated-search-block-index').replace('count-removal','block-index')
library=replace(library,"'description': 'Current IDE backend, H2 seed1000; authenticated frequent keyword; HTTP-only; SQL output configured ON',",
    "'description': 'Controlled Slice Block OR vs composite index/two NOT EXISTS AND; H2 seed1000; Java21 JAR; HTTP-only; SQL OFF',")
library=replace(library,"    row['passed'] = row['accountingPassed'] and row['errors'] == 0", """    row['requestAccountingPassed'] = (row['status']=='FINISHED' and row['sampleComplete']
        and row['requests']==vu*count==row['controllerSuccesses']+row['controllerErrors']
        and row['successes']==row['controllerSuccesses'] and row['errors']==row['controllerErrors'])
    row['historyConsistentWithOutcomes'] = (row['historyDelta']==row['memberKeywordHistoryDelta']
        and row['successes']<=row['historyDelta']<=row['requests'])
    row['passed'] = row['accountingPassed'] and row['errors'] == 0""")
(OUT/'execution/focused_search_lib.py').write_text(library,encoding='utf-8')

runner=(PREVIOUS/'execution/run_pair.py').read_text('utf-8')
runner=runner.replace('authenticated-search-count-removal','authenticated-search-block-index').replace('before-count','before-or').replace('after-slice','after-index-and').replace('count-ab','block-ab').replace('COUNT BEFORE/AFTER','BLOCK INDEX/AND BEFORE/AFTER')
runner=replace(runner,'lib.EXPECTED_BOARD_COUNTS=10 if variant==\'before-or\' else 0','lib.EXPECTED_BOARD_COUNTS=0')
runner=replace(runner,"if ('totalElements' in data)!=(variant=='before-or')", "if ('totalElements' in data)")
marker="        snapshot=target/'deployed-scripts'"
runner=replace(runner,marker,"""        index_rows=lib.db.query("SELECT * FROM INFORMATION_SCHEMA.INDEXES WHERE TABLE_NAME='BLOCK'")
        index_columns=lib.db.query("SELECT * FROM INFORMATION_SCHEMA.INDEX_COLUMNS WHERE TABLE_NAME='BLOCK' ORDER BY INDEX_NAME,ORDINAL_POSITION")
        has_index=any(row['INDEX_NAME'].upper()=='IDX_BLOCK_BLOCKER_BLOCKED_DELETED' for row in index_rows)
        lib.save(target/'block-index-schema.json',{'indexes':index_rows,'indexColumns':index_columns,'newCompositeIndexExists':has_index})
        if has_index!=(variant=='after-index-and'):
            raise RuntimeError('Actual Block schema does not match variant')
        member_responses=[]
        probe_history=lib.history()
        for member_id,token in zip(lib.ids,tokens):
            body,duration=lib.direct_search(token)
            member_responses.append({'memberId':member_id,'ids':[item['id'] for item in body['data']['content']],
                                     'first':body['data']['first'],'last':body['data']['last'],'elapsedMs':duration})
        lib.save(target/'member-response-probes.json',{'members':member_responses,'requests':30,
            'historyDelta':lib.history()['total']-probe_history['total']})
        if variant=='after-index-and':
            previous=json.loads((OUT/'controlled-ab/before-or/member-response-probes.json').read_text('utf-8'))['members']
            if [{k:row[k] for k in ['memberId','ids','first','last']} for row in previous]!=[{k:row[k] for k in ['memberId','ids','first','last']} for row in member_responses]:
                raise RuntimeError('Changed Block predicates returned different seeded first-page results')
        snapshot=target/'deployed-scripts'""")
runner=replace(runner,"if not row['accountingPassed'] or row['errorRatePercent']>5:","if not row['requestAccountingPassed'] or not row['historyConsistentWithOutcomes'] or row['errorRatePercent']>5:")
runner=replace(runner,"        environment['finishedAtKst']=lib.now()", """        from block_diagnostic import capture_block_plans
        capture_block_plans(lib,target,variant)
        environment['finishedAtKst']=lib.now()""")
runner=replace(runner,'"""Controlled count/Page vs Slice comparison with identical runtime and seeded DB."""','"""Controlled Slice OR versus Block index/two NOT EXISTS AND comparison."""')
(SCRATCH/'run_pair.py').write_text(runner,encoding='utf-8')
shutil.copyfile(SCRATCH/'block_diagnostic.py',OUT/'execution/block_diagnostic.py')
shutil.copyfile(__file__,OUT/'execution/bootstrap.py')
print('Ready: '+str(OUT),flush=True)
