"""Controlled Slice OR versus Block index/two NOT EXISTS AND comparison."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import copy
import importlib.util
import json
import re
import shutil
import socket
import subprocess
import threading
import time

OUT = Path(r'C:\dev\workspace\prography\APM\performance-test\results\2026-10-07-authenticated-search-block-index')
PORT = 18080
JAVA = r'C:\Program Files\Java\jdk-21\bin\java.exe'
KST = timezone(timedelta(hours=9))
builds = [dict(row,variant='current-steady') for row in json.loads((OUT/'controlled-ab/builds.json').read_text('utf-8')) if row['variant']=='after-index-and']
STEADY_COUNT=1165
library_path = OUT/'execution/focused_search_lib.py'
text = library_path.read_text('utf-8').replace("data['boardCountExecutions'] != 0", "data['boardCountExecutions'] != EXPECTED_BOARD_COUNTS")
text = text.replace("print('SQL CHECK content=10 count=0 history+=10', flush=True)",
                    "print('SQL CHECK content=10 count=' + str(data['boardCountExecutions']) + ' history+=10', flush=True)")
library_path.write_text(text,encoding='utf-8')
spec = importlib.util.spec_from_file_location('focused',library_path)
lib = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lib)
if lib.api('/perftest/api/status')['runningTestsCount'] != 0:
    raise RuntimeError('Controller must be idle')
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port_probe:
    port_probe.bind(('127.0.0.1', PORT))
originals = {name: lib.api('/script/api/detail/'+name)['file'] for name in [lib.SCRIPT,'resources/RoommateBoardListSupport.txt','resources/roommate-board-list.json']}
lib.save(OUT/'execution/steady-controller-originals.json',originals)
source = lib.PERF/'script/roommate'
shutil.copyfile(__file__,OUT/'execution/run_steady.py')
variant_summaries=[]

for build in builds:
    variant=build['variant']
    target=OUT/'controlled-ab'/variant
    lib.OUTPUT=target
    lib.base.BACKEND='http://localhost:'+str(PORT)
    lib.EXPECTED_BOARD_COUNTS=0
    lib.results=[]
    lib.active_id=None
    lib.originals=originals
    lib.stop_monitor=threading.Event()
    args=[JAVA,'-Xms512m','-Xmx2g','-jar',build['jarPath'],
          '--server.port='+str(PORT),'--spring.profiles.active=test','--spring.jpa.show-sql=false',
          '--logging.level.org.hibernate.SQL=OFF','--logging.level.org.hibernate.orm.jdbc.bind=OFF',
          '--logging.level.org.example.knockin.query=OFF',
          '--logging.level.org.example.knockin.global.aspect.MethodExecuteAspect=OFF']
    stdout=(target/'backend.out.log').open('wb')
    stderr=(target/'backend.err.log').open('wb')
    server=subprocess.Popen(args,cwd=Path(build['jarPath']).parents[2],stdout=stdout,stderr=stderr,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    lib.save(target/'server.json',{'pid':server.pid,'startedAtKst':datetime.now(KST).isoformat(),
        'args':args,'jarSha256':build['jarSha256'],'noTieredStopAtLevelOverride':True})
    monitor=None
    containers=[]
    changed=[]
    cleanup={'controllerRestored':{},'tokensRemoved':{}}
    try:
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            if server.poll() is not None:
                raise RuntimeError('Isolated backend exited during startup; see backend.err/out logs')
            try:
                health=lib.base.request(lib.base.BACKEND+'/actuator/health')
                if health.get('status')=='UP':
                    break
            except Exception:
                pass
            time.sleep(2)
        else:
            raise RuntimeError('Isolated backend startup timed out')
        lib.db=lib.base.H2()
        members=lib.db.query("SELECT ID,PROVIDER_ID FROM MEMBER WHERE ROLE='USER' AND IS_DELETE=FALSE AND PROVIDER_ID LIKE 'load_test_user_%' ORDER BY ID LIMIT 30")
        lib.ids=[int(row['ID']) for row in members]
        if len(lib.ids)!=30 or len(set(lib.ids))!=30:
            raise RuntimeError('Need 30 distinct seeded test members')
        lib.agents=lib.prep.docker('ps','--filter','ancestor=ngrinder/agent:3.5.9-p1','--format','{{.Names}}').splitlines()
        containers=['ngrinder-controller']+lib.agents
        lib.TOKEN_FILE='/tmp/knockin-block-ab-'+variant+'-'+str(int(time.time()))+'.txt'
        tokens,expires=lib.prep.issue_tokens(Path(build['jarPath']).parents[2],members,2)
        lib.measurement_config=json.loads(originals['resources/roommate-board-list.json']['content'])
        lib.measurement_config.update(baseUrl='http://host.docker.internal:'+str(PORT),connectTimeoutMs=5000,
            socketTimeoutMs=15000,activeKeywordProfile=lib.PROFILE,responseValidator=None,expectedStatusCodes=[200],tokenFile=lib.TOKEN_FILE)
        lib.measurement_config['profiles'][lib.PROFILE]={'auth':'authenticated','responseValidator':None,
            'expectedStatusCodes':[200],'inputs':[{'query':{'page':0,'size':20,'sort':'createdAt,DESC'},'keyword':lib.KEYWORD}]}
        counts={table:int(lib.db.query('SELECT COUNT(*) AS TOTAL FROM '+table)[0]['TOTAL'])
                for table in ['MEMBER','ROOMMATE_BOARD','BLOCK','SEARCH','STATE']}
        if counts != {'MEMBER':2004,'ROOMMATE_BOARD':1002,'BLOCK':1001,'SEARCH':1005,'STATE':2003}:
            raise RuntimeError('Fresh seed did not match the expected comparison snapshot')
        startup_log=(target/'backend.out.log').read_text('utf-8',errors='replace')
        if 'org.example.knockin.query' in startup_log or 'Hibernate:' in startup_log:
            raise RuntimeError('SQL output remains enabled; do not use this run for comparison')
        environment={'variant':variant,'startedAtKst':lib.now(),'backendUrl':lib.base.BACKEND,
            'launch':'Owned isolated Java 21 executable JAR','javaOptions':['-Xms512m','-Xmx2g'],
            'sqlLogging':False,'executionTimeAspectLogger':'OFF','defaultTieredCompilation':True,
            'jarSha256':build['jarSha256'],'sourceHashes':build['sourceHashes'],
            'actualCounts':counts,'memberIds':lib.ids,'profile':lib.PROFILE,'keyword':lib.KEYWORD,
            'query':{'page':0,'size':20,'sort':'createdAt,DESC'},'agentCount':1,'processes':1,
            'vusers':[30],'requestsPerVu':STEADY_COUNT,'repetitions':1,'cooldownSeconds':15,
            'connectTimeoutMs':5000,'socketTimeoutMs':15000,'connectionReset':False,'rampUp':False,
            'responseValidator':None,'historyPolicy':'Append-only, fresh same seed for each variant',
            'warmup':'1 VU x20 then 30 VU x200 (6000 requests); supplemental current-version observation',
            'tokenExpiresAt':datetime.fromtimestamp(expires,KST).isoformat(),'tokenFile':lib.TOKEN_FILE}
        lib.save(target/'environment.json',environment)
        for container in containers:
            lib.prep.docker('exec',container,'sh','-c','test -z "$ROOMMATE_BOARD_TOKENS" && test -z "$ROOMMATE_BOARD_TOKEN_FILE"')
            lib.prep.docker('exec','-i',container,'sh','-c','umask 077; cat > '+lib.TOKEN_FILE,
                            data=('\n'.join(tokens)+'\n').encode())
        for name in [lib.SCRIPT,'resources/RoommateBoardListSupport.txt']:
            content=(source/name).read_text('utf-8')
            if content!=originals[name]['content']:
                changed.append(name)
                lib.deploy(name,content)
        changed.append('resources/roommate-board-list.json')
        history_before=lib.history()
        response,elapsed=lib.direct_search(tokens[0])
        history_after=lib.history()
        data=response['data']
        lib.save(target/'preflight.json',{'responseDataKeys':sorted(data.keys()),'contentSize':len(data['content']),
            'firstIds':[row['id'] for row in data['content']], 'totalElements':data.get('totalElements'),
            'httpStatus':200,'elapsedMs':elapsed,'historyDelta':history_after['total']-history_before['total']})
        if ('totalElements' in data) or len(data['content'])!=20 or history_after['total']-history_before['total']!=1:
            raise RuntimeError('Preflight did not match Page/Slice variant or expected history insert')
        index_rows=lib.db.query("SELECT * FROM INFORMATION_SCHEMA.INDEXES WHERE TABLE_NAME='BLOCK'")
        index_columns=lib.db.query("SELECT * FROM INFORMATION_SCHEMA.INDEX_COLUMNS WHERE TABLE_NAME='BLOCK' ORDER BY INDEX_NAME,ORDINAL_POSITION")
        has_index=any(row['INDEX_NAME'].upper()=='IDX_BLOCK_BLOCKER_BLOCKED_DELETED' for row in index_rows)
        lib.save(target/'block-index-schema.json',{'indexes':index_rows,'indexColumns':index_columns,'newCompositeIndexExists':has_index})
        if has_index!=(variant=='current-steady'):
            raise RuntimeError('Actual Block schema does not match variant')
        member_responses=[]
        probe_history=lib.history()
        for member_id,token in zip(lib.ids,tokens):
            body,duration=lib.direct_search(token)
            member_responses.append({'memberId':member_id,'ids':[item['id'] for item in body['data']['content']],
                                     'first':body['data']['first'],'last':body['data']['last'],'elapsedMs':duration})
        lib.save(target/'member-response-probes.json',{'members':member_responses,'requests':30,
            'historyDelta':lib.history()['total']-probe_history['total']})
        if variant=='current-steady':
            previous=json.loads((OUT/'controlled-ab/before-or/member-response-probes.json').read_text('utf-8'))['members']
            if [{k:row[k] for k in ['memberId','ids','first','last']} for row in previous]!=[{k:row[k] for k in ['memberId','ids','first','last']} for row in member_responses]:
                raise RuntimeError('Changed Block predicates returned different seeded first-page results')
        snapshot=target/'deployed-scripts'
        (snapshot/'resources').mkdir(parents=True)
        for name in [lib.SCRIPT,'resources/RoommateBoardListSupport.txt']:
            shutil.copyfile(source/name,snapshot/name)
        monitor=threading.Thread(target=lib.telemetry,daemon=True)
        monitor.start()
        print('VARIANT '+variant+' STARTED',flush=True)
        if not lib.run_case('smoke-warmup',1,20,1)['passed']:
            raise RuntimeError('Variant smoke failed')
        if not lib.run_case('jit-warmup',30,200,1)['passed']:
            raise RuntimeError('Variant warmup failed')
        time.sleep(15)
        stop_variant=False
        for repeat in [1]:
            for vu in [30]:
                row=lib.run_case('steady-observation',vu,STEADY_COUNT,repeat)
                if not row['requestAccountingPassed'] or not row['historyConsistentWithOutcomes'] or row['errorRatePercent']>5:
                    lib.save(target/'stop-reason.json',{'case':row['label'],
                        'reason':'Accounting incomplete or error rate >5%; higher/repeated stages cancelled'})
                    stop_variant=True
                    break
                time.sleep(15)
            if stop_variant:
                break
        lib.stop_monitor.set()
        monitor.join(timeout=45)
        lib.sql_diagnostic(tokens[0])
        from block_diagnostic import capture_block_plans
        capture_block_plans(lib,target,'after-index-and')
        environment['finishedAtKst']=lib.now()
        lib.save(target/'environment.json',environment)
        variant_summaries.append({'variant':variant,'runs':lib.results,'stoppedEarly':stop_variant})
        lib.save(OUT/'controlled-ab/steady-summary.json',variant_summaries)
        print('VARIANT '+variant+' COMPLETE',flush=True)
    except BaseException as error:
        lib.save(target/'execution-error.json',{'atKst':lib.now(),'errorType':type(error).__name__,
            'message':re.sub(lib.prep.JWT_PATTERN,'[REDACTED_JWT]',str(error))})
        raise
    finally:
        if lib.active_id is not None:
            try:
                lib.api('/perftest/api/'+str(lib.active_id)+'?action=stop',method='PUT')
                cleanup['stoppedOwnTestId']=lib.active_id
            except Exception as error:
                cleanup['stopErrorType']=type(error).__name__
        lib.stop_monitor.set()
        if monitor and monitor.is_alive():
            monitor.join(timeout=45)
        for name in reversed(changed):
            try:
                lib.deploy(name,originals[name]['content'])
                cleanup['controllerRestored'][name]=lib.api('/script/api/detail/'+name)['file']['content']==originals[name]['content']
            except Exception as error:
                cleanup['controllerRestored'][name]=False
        for container in containers:
            try:
                lib.prep.docker('exec',container,'rm','-f',lib.TOKEN_FILE)
                cleanup['tokensRemoved'][container]=subprocess.run(['docker','exec',container,'test','!','-e',lib.TOKEN_FILE],capture_output=True).returncode==0
            except Exception:
                cleanup['tokensRemoved'][container]=False
        # Stop only the exact child process started above.
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        stdout.close()
        stderr.close()
        cleanup['ownedBackendStopped']=server.poll() is not None
        cleanup['controllerIdle']=lib.api('/perftest/api/status')['runningTestsCount']==0
        cleanup['finishedAtKst']=lib.now()
        lib.save(target/'cleanup.json',cleanup)
        print('CLEANUP '+variant+' '+json.dumps(cleanup),flush=True)

print('SUPPLEMENTAL CURRENT STEADY OBSERVATION COMPLETE',flush=True)
