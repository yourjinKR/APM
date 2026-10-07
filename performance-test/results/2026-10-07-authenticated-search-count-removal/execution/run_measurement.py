"""Focused authenticated search measurement on the already-running local backend."""
from pathlib import Path
import base64
import copy
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
import re
import shutil
from statistics import median
import subprocess
import threading
import time
import urllib.parse
import urllib.request

PERF = Path(r'C:\dev\workspace\prography\APM\performance-test')
BACKEND_PROJECT = Path(r'C:\dev\workspace\KnockIn\back\11th-1team-BE')
OUTPUT = PERF / 'results/2026-10-07-authenticated-search-count-removal'
KST = timezone(timedelta(hours=9))
PROFILE = 'search-frequent-authenticated'
SCRIPT = 'RoommateBoardListKeywordGetTest.groovy'
KEYWORD = '부하 테스트 게시글'
TOKEN_FILE = '/tmp/knockin-count-removal-20261007-' + str(int(time.time())) + '.txt'

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

base = load('baseline', PERF / 'tools/run-roommate-board-baseline.py')
prep = load('prepare_ui', PERF / 'tools/prepare-ngrinder-ui.py')
samples_module = load('samples', PERF / 'tools/summarize-roommate-board-samples.py')
auth = 'Basic ' + base64.b64encode((os.getenv('NGRINDER_USERNAME','admin') + ':' + os.getenv('NGRINDER_PASSWORD','admin')).encode()).decode()

def now():
    return datetime.now(KST).isoformat()

def save(path, value):
    base.save(path, value)

def api(path, **kwargs):
    return base.request(base.CONTROLLER + path, headers={'Authorization': auth}, **kwargs)

def command(*args):
    result = subprocess.run(args, capture_output=True, encoding='utf-8', errors='replace', timeout=90)
    if result.returncode:
        raise RuntimeError('Command failed: ' + str(args[:2]) + ': ' + result.stderr[:250])
    return result.stdout.strip()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def db_execute(sql):
    response = base.request(base.BACKEND + '/h2-console/query.do?jsessionid=' + db.sid,
                            'POST', {'sql': sql, 'maxrows': '0'}, form=True)
    if 'class="error"' in response:
        raise RuntimeError('H2 diagnostic setting command failed')

def history():
    return {
        'total': int(db.query('SELECT COUNT(*) AS TOTAL FROM SEARCH')[0]['TOTAL']),
        'testMembersKeyword': int(db.query("SELECT COUNT(*) AS TOTAL FROM SEARCH WHERE MEMBER_ID IN (" +
            ','.join(str(value) for value in ids) + ") AND KEYWORD='" + KEYWORD.replace("'", "''") + "'")[0]['TOTAL'])}

def deploy(path, content):
    entry = originals[path]
    api('/script/api/save/' + path, method='POST', data={'fileEntry': {'path': path,
        'fileType': entry['fileType'], 'content': content, 'description': entry.get('description') or '',
        'encoding': entry.get('encoding') or 'UTF-8'}, 'targetHosts': 'host.docker.internal',
        'validated': '0', 'createLibAndResource': False})
    current = api('/script/api/detail/' + path)['file']
    if current['content'] != content:
        raise RuntimeError('Controller deployment content mismatch')
    return {'path': path, 'revision': current['revision'], 'sha256': hashlib.sha256(content.encode()).hexdigest()}

def direct_search(token):
    query = {'page': 0, 'size': 20, 'sort': 'createdAt,DESC', 'keyword': KEYWORD}
    request = urllib.request.Request(base.BACKEND + '/roommate/boards?' + urllib.parse.urlencode(query),
                                     headers={'Authorization': 'Bearer ' + token})
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=30) as response:
        status = response.status
        data = json.loads(response.read())
    if status != 200:
        raise RuntimeError('Authenticated search probe failed')
    return data, (time.perf_counter() - started) * 1000

def telemetry():
    prefixes = ('process_cpu_', 'system_cpu_', 'jvm_gc_', 'jvm_memory_used_', 'hikaricp_',
                'jvm_threads_live', 'http_server_requests_seconds')
    iteration = 0
    with (OUTPUT / 'telemetry.jsonl').open('a', encoding='utf-8', buffering=1) as target:
        while not stop_monitor.is_set():
            row = {'atKst': now(), 'epochMs': int(time.time()*1000), 'activeTestId': active_id}
            try:
                row['metrics'] = [line for line in base.request(base.BACKEND + '/actuator/prometheus').splitlines()
                                  if line.startswith(prefixes)]
                if iteration % 3 == 0:
                    row['containers'] = command('docker', 'stats', '--no-stream', '--format', '{{json .}}',
                                                 'ngrinder-controller', *agents).splitlines()
            except Exception as error:
                row['errorType'] = type(error).__name__
            target.write(json.dumps(row, ensure_ascii=False) + '\n')
            iteration += 1
            stop_monitor.wait(5)

def run_case(phase, vu, count, repeat):
    global active_id
    label = f'{phase}-vu{vu}-r{repeat}'
    case = OUTPUT / 'raw' / label
    case.mkdir(parents=True)
    config = copy.deepcopy(measurement_config)
    config['runId'] = 'count-removal-20261007-' + label
    save(case / 'deployed-config.json', config)
    revision = deploy('resources/roommate-board-list.json', json.dumps(config, ensure_ascii=False, indent=2) + '\n')
    before = history()
    created = api('/perftest/api', method='POST', form=True, data={
        'testName': 'count-removal-auth-search-' + label + '-' + str(int(time.time())),
        'description': 'Current IDE backend, H2 seed1000; authenticated frequent keyword; HTTP-only; SQL output configured ON',
        'scriptName': SCRIPT, 'status': 'READY', 'threshold': 'R', 'runCount': count,
        'agentCount': 1, 'processes': 1, 'threads': vu, 'vuserPerAgent': vu,
        'targetHosts': 'host.docker.internal', 'samplingInterval': 2, 'useRampUp': 'false',
        'connectionReset': 'false', 'ignoreTooManyError': 'false', 'ignoreSampleCount': 0})
    active_id = int(created['id'])
    test_id = active_id
    save(case / 'created.json', created)
    if created['threads'] != vu or created['runCount'] != count or created['threshold'] != 'R':
        raise RuntimeError('Controller settings differ from requested settings')
    print(f'START {label} test={test_id} requests={vu*count}', flush=True)
    deadline = time.monotonic() + 1200
    last_progress = 0
    while time.monotonic() < deadline:
        time.sleep(3)
        state = api('/perftest/api/' + str(test_id))
        if time.monotonic() - last_progress > 30:
            print(f'PROGRESS {label} status={state["status"]["name"]} successes={state.get("tests")} errors={state.get("errors")}', flush=True)
            last_progress = time.monotonic()
        if state.get('finishTime') and not state['status'].get('stoppable', True):
            break
    else:
        api('/perftest/api/' + str(test_id) + '?action=stop', method='PUT')
        raise RuntimeError('Measurement timed out')
    active_id = None
    save(case / 'test.json', state)
    save(case / 'basic-report.json', api('/perftest/api/' + str(test_id) + '/basic_report'))
    time.sleep(6 if state.get('errors') else 1)
    after = history()
    sample_directory = case / 'request-samples'
    sample_directory.mkdir()
    collected = []
    remote = config['outputDir'].rstrip('/') + '/' + config['runId'] + '-test_' + str(test_id)
    for agent in agents:
        exists = subprocess.run(['docker','exec',agent,'test','-d',remote], capture_output=True)
        if exists.returncode == 0:
            prep.docker('cp', agent + ':' + remote + '/.', str(sample_directory))
            collected.append(agent)
    if len(collected) != 1:
        raise RuntimeError('Expected samples from exactly one Agent')
    summary = samples_module.summarize(sample_directory, vu*count, vu)
    save(sample_directory / 'request-summary.json', summary)
    row = {'label': label, 'phase': phase, 'vu': vu, 'repeat': repeat, 'testId': test_id,
           'requestsPerVu': count, 'expectedRequests': vu*count, 'status': state['status']['name'],
           'controllerSuccesses': state.get('tests'), 'controllerErrors': state.get('errors'),
           'controllerTps': state.get('tps'), 'controllerMeanMs': state.get('meanTestTime'),
           'configRevision': revision['revision'], 'sampleAgents': collected,
           'historyBefore': before, 'historyAfter': after,
           'historyDelta': after['total']-before['total'],
           'memberKeywordHistoryDelta': after['testMembersKeyword']-before['testMembersKeyword'],
           'requests': summary['requests'], 'successes': summary['successes'], 'errors': summary['errors'],
           'errorRatePercent': summary['errorRatePercent'], 'meanMs': summary['successMeanMs'],
           'p95Ms': summary['successP95Ms'], 'p99Ms': summary['successP99Ms'],
           'sampleSpanSeconds': summary['sampleSpanSeconds'], 'sampleComplete': summary['sampleComplete'],
           'failures': summary['failures'], 'transportFailureRoots': summary['transportFailureRoots'],
           'startTime': state.get('startTime'), 'finishTime': state.get('finishTime')}
    row['accountingPassed'] = (row['status'] == 'FINISHED' and row['sampleComplete'] and
        row['requests'] == vu*count == row['controllerSuccesses'] + row['controllerErrors'] and
        row['successes'] == row['controllerSuccesses'] and row['errors'] == row['controllerErrors'] and
        row['memberKeywordHistoryDelta'] == vu*count and row['historyDelta'] == vu*count)
    row['passed'] = row['accountingPassed'] and row['errors'] == 0
    results.append(row)
    save(OUTPUT / 'suite-summary.json', results)
    save(case / 'summary.json', row)
    print(f'END {label} success={row["successes"]} errors={row["errors"]} mean={row["meanMs"]:.2f} p95={row["p95Ms"]:.2f} TPS={row["controllerTps"]} history+={row["historyDelta"]} passed={row["passed"]}', flush=True)
    return row

def sql_diagnostic(token):
    target = OUTPUT / 'sql-diagnostics'
    target.mkdir()
    initial = db.query('SELECT SQL_STATEMENT,EXECUTION_COUNT FROM INFORMATION_SCHEMA.QUERY_STATISTICS')
    if initial:
        save(target / 'skipped.json', {'reason': 'Pre-existing H2 query statistics preserved; not changed'})
        return
    stats_sql = 'SELECT SQL_STATEMENT,EXECUTION_COUNT,CUMULATIVE_EXECUTION_TIME FROM INFORMATION_SCHEMA.QUERY_STATISTICS'
    def snapshot():
        return {row['SQL_STATEMENT']: row for row in db.query(stats_sql.replace('SELECT ', 'SELECT /* count-removal-' + str(time.time_ns()) + ' */ ', 1))}
    try:
        db_execute('SET QUERY_STATISTICS TRUE')
        direct_search(token)
        before = snapshot()
        history_before = history()
        elapsed = [direct_search(token)[1] for _ in range(10)]
        after = snapshot()
        history_after = history()
        statements = []
        for sql, row in after.items():
            previous = before.get(sql, {})
            count = int(row['EXECUTION_COUNT']) - int(previous.get('EXECUTION_COUNT',0))
            duration = float(row['CUMULATIVE_EXECUTION_TIME']) - float(previous.get('CUMULATIVE_EXECUTION_TIME',0))
            if count > 0 and 'INFORMATION_SCHEMA' not in sql.upper() and not sql.upper().startswith(('SET ', 'SELECT COUNT(*) AS TOTAL')):
                statements.append({'sql': sql, 'executions': count, 'totalMs': duration, 'meanMs': duration/count})
        content = [row for row in statements if re.search(r'\bfrom roommate_board\b',row['sql'].lower()) and not re.match(r'select\s+count\(',row['sql'].lower())]
        counts = [row for row in statements if re.search(r'\bfrom roommate_board\b',row['sql'].lower()) and re.match(r'select\s+count\(',row['sql'].lower())]
        data = {'requests': 10, 'httpDurationsMs': elapsed, 'statements': sorted(statements,key=lambda row: row['totalMs'],reverse=True),
                'contentExecutions': sum(row['executions'] for row in content),
                'boardCountExecutions': sum(row['executions'] for row in counts),
                'historyDelta': history_after['total'] - history_before['total']}
        save(target / 'statistics-snapshots.json', {'before': before, 'after': after})
        save(target / 'summary.json', data)
        if data['contentExecutions'] != 10 or data['boardCountExecutions'] != 0 or data['historyDelta'] != 10:
            raise RuntimeError('Runtime SQL count-removal evidence did not match expected executions')
        print('SQL CHECK content=10 count=0 history+=10', flush=True)
    finally:
        db_execute('SET QUERY_STATISTICS FALSE')
        save(target / 'cleanup.json', {'queryStatisticsDisabled': not db.query('SELECT SQL_STATEMENT,EXECUTION_COUNT FROM INFORMATION_SCHEMA.QUERY_STATISTICS')})

if OUTPUT.exists():
    raise RuntimeError('Refuse to reuse an existing result directory')
OUTPUT.mkdir(parents=True)
shutil.copyfile(__file__, OUTPUT / 'execution/run_measurement.py') if (OUTPUT / 'execution').exists() else None
(OUTPUT / 'execution').mkdir(exist_ok=True)
shutil.copyfile(__file__, OUTPUT / 'execution/run_measurement.py')
if api('/perftest/api/status')['runningTestsCount'] != 0:
    raise RuntimeError('Controller already running a performance test')
health = base.request(base.BACKEND + '/actuator/health')
if health.get('status') != 'UP' or health['components']['db']['details']['database'] != 'H2':
    raise RuntimeError('Only the healthy existing local H2 backend is supported')
db = base.H2()
members = db.query("SELECT ID,PROVIDER_ID FROM MEMBER WHERE ROLE='USER' AND IS_DELETE=FALSE AND PROVIDER_ID LIKE 'load_test_user_%' ORDER BY ID LIMIT 30")
ids = [int(row['ID']) for row in members]
if len(ids) != 30 or len(set(ids)) != 30:
    raise RuntimeError('Need 30 distinct local fixture members')
agents = prep.docker('ps','--filter','ancestor=ngrinder/agent:3.5.9-p1','--format','{{.Names}}').splitlines()
if not agents:
    raise RuntimeError('No available Agents')
containers = ['ngrinder-controller'] + agents
originals = {name: api('/script/api/detail/' + name)['file'] for name in [SCRIPT, 'resources/RoommateBoardListSupport.txt', 'resources/roommate-board-list.json']}
measurement_config = json.loads(originals['resources/roommate-board-list.json']['content'])
measurement_config.update(baseUrl='http://host.docker.internal:8080', connectTimeoutMs=5000, socketTimeoutMs=15000,
                          activeKeywordProfile=PROFILE, responseValidator=None, expectedStatusCodes=[200], tokenFile=TOKEN_FILE)
measurement_config['profiles'][PROFILE] = {'auth':'authenticated', 'responseValidator':None,
    'expectedStatusCodes':[200], 'inputs':[{'query':{'page':0,'size':20,'sort':'createdAt,DESC'},'keyword':KEYWORD}]}
tokens, expires = prep.issue_tokens(BACKEND_PROJECT, members, 2)
source = PERF / 'script/roommate'
snapshot = OUTPUT / 'execution/deployed-scripts'
(snapshot / 'resources').mkdir(parents=True)
for name in [SCRIPT, 'resources/RoommateBoardListSupport.txt']:
    shutil.copyfile(source / name, snapshot / name)
environment = {'startedAtKst': now(), 'backendHealth':health, 'backendLaunch':'Existing IDE Java 21 process, no backend restart/build',
    'backendCommit':command('git','-C',str(BACKEND_PROJECT),'rev-parse','HEAD'),
    'backendDirtyFiles':command('git','-C',str(BACKEND_PROJECT),'status','--short').splitlines(),
    'apmCommit':command('git','-C',str(PERF.parent),'rev-parse','HEAD'),
    'actualCounts':{table:int(db.query('SELECT COUNT(*) AS TOTAL FROM ' + table)[0]['TOTAL']) for table in ['MEMBER','ROOMMATE_BOARD','BLOCK','SEARCH','STATE']},
    'memberIds':ids, 'agents':agents, 'agentCountPerRun':1, 'processesPerRun':1,
    'profile':PROFILE, 'keyword':KEYWORD, 'query':{'page':0,'size':20,'sort':'createdAt,DESC'},
    'vusers':[10,30], 'requestsPerVu':100, 'repetitions':3, 'smokeWarmupRequests':20, 'cooldownSeconds':15,
    'connectTimeoutMs':5000, 'socketTimeoutMs':15000, 'connectionReset':False,'rampUp':False,
    'responseValidator':None,'expectedStatusCodes':[200], 'sqlOutputSetting':True,
    'sqlOutputEvidence': 'Source application-test.properties has spring.jpa.show-sql=true; IDE argument-file resource path captured separately',
    'tokenExpiresAt':datetime.fromtimestamp(expires,KST).isoformat(), 'tokenFile':TOKEN_FILE,
    'historyPolicy':'Append-only; preserve pre-existing rows and record before/after member+keyword counts',
    'comparison':'Historical 2026-10-04 tests 389/390; different backend commit and SQL output settings, observational comparison',
    'sourceHashes':{name:sha(source/name) for name in [SCRIPT,'resources/RoommateBoardListSupport.txt']}}
source_files = ['src/main/java/org/example/knockin/board/controller/RoomMateController.java',
                'src/main/java/org/example/knockin/board/repository/RoommateBoardRepositoryCustom.java',
                'src/main/java/org/example/knockin/board/repository/impl/RoommateBoardRepositoryImpl.java',
                'src/main/java/org/example/knockin/board/service/RoommateBoardService.java',
                'src/main/java/org/example/knockin/board/service/impl/RoommateBoardServiceImpl.java']
environment['backendSourceHashes'] = {name:sha(BACKEND_PROJECT/name) for name in source_files}
patch = command('git','-C',str(BACKEND_PROJECT),'diff','--',*source_files)
(OUTPUT / 'execution/count-removal-source.patch').write_text(patch+'\n',encoding='utf-8')
save(OUTPUT / 'environment.json', environment)
results = []
active_id = None
stop_monitor = threading.Event()
monitor = threading.Thread(target=telemetry, daemon=True)
changed = []
cleanup = {'startedAtKst':None, 'controllerRestored':{}, 'tokensRemoved':{}}
try:
    for container in containers:
        prep.docker('exec',container,'sh','-c','test -z "$ROOMMATE_BOARD_TOKENS" && test -z "$ROOMMATE_BOARD_TOKEN_FILE"')
        prep.docker('exec','-i',container,'sh','-c','umask 077; cat > '+TOKEN_FILE,
                    data=('\n'.join(tokens)+'\n').encode())
    for name in [SCRIPT,'resources/RoommateBoardListSupport.txt']:
        content = (source/name).read_text('utf-8')
        if content != originals[name]['content']:
            changed.append(name)
            deploy(name,content)
    changed.append('resources/roommate-board-list.json')
    probe_before = history()
    response, elapsed = direct_search(tokens[0])
    probe_after = history()
    data = response.get('data', {})
    save(OUTPUT / 'preflight.json', {'httpStatus':200, 'elapsedMs':elapsed, 'envelopeStatus':response.get('status'),
        'responseDataKeys': sorted(data.keys()), 'contentSize':len(data.get('content',[])),
        'hasTotalElements':'totalElements' in data, 'firstPage':data.get('first'), 'lastPage':data.get('last'),
        'historyDelta':probe_after['total']-probe_before['total']})
    if 'totalElements' in data or not data.get('content') or probe_after['total']-probe_before['total'] != 1:
        raise RuntimeError('Expected current Slice response and authenticated search history insert')
    monitor.start()
    smoke = run_case('smoke-warmup',1,20,1)
    if not smoke['passed']:
        raise RuntimeError('Smoke/warmup failed; load stages cancelled')
    time.sleep(15)
    for repeat in [1,2,3]:
        for vu in [10,30]:
            row = run_case('load',vu,100,repeat)
            if not row['passed']:
                save(OUTPUT / 'stop-reason.json', {'case':row['label'],'reason':'Failed or incomplete run; remaining load stages stopped'})
                raise RuntimeError('Load stage failed; evidence preserved')
            time.sleep(15)
    stop_monitor.set()
    monitor.join(timeout=45)
    sql_diagnostic(tokens[0])
    environment['finishedAtKst'] = now()
    save(OUTPUT / 'environment.json',environment)
    print('MEASUREMENTS COMPLETE', flush=True)
except Exception as error:
    save(OUTPUT / 'execution-error.json', {'atKst':now(), 'errorType':type(error).__name__,
                                          'message':re.sub(prep.JWT_PATTERN,'[REDACTED_JWT]',str(error))})
    raise
finally:
    cleanup['startedAtKst'] = now()
    if active_id is not None:
        try:
            api('/perftest/api/' + str(active_id) + '?action=stop', method='PUT')
            cleanup['stoppedOwnTestId'] = active_id
        except Exception as error:
            cleanup['stopErrorType'] = type(error).__name__
    stop_monitor.set()
    if monitor.is_alive():
        monitor.join(timeout=45)
    for name in reversed(changed):
        try:
            deploy(name,originals[name]['content'])
            cleanup['controllerRestored'][name] = api('/script/api/detail/'+name)['file']['content'] == originals[name]['content']
        except Exception as error:
            cleanup['controllerRestored'][name] = False
            cleanup['restoreErrorType'] = type(error).__name__
    for container in containers:
        try:
            prep.docker('exec',container,'rm','-f',TOKEN_FILE)
            absent = subprocess.run(['docker','exec',container,'test','!','-e',TOKEN_FILE],capture_output=True).returncode == 0
            cleanup['tokensRemoved'][container] = absent
        except Exception as error:
            cleanup['tokensRemoved'][container] = False
    cleanup['finishedAtKst'] = now()
    cleanup['controllerIdle'] = api('/perftest/api/status')['runningTestsCount'] == 0
    save(OUTPUT / 'cleanup.json',cleanup)
    print('CLEANUP ' + json.dumps(cleanup),flush=True)
