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
OUTPUT = PERF / 'results/2026-10-07-authenticated-search-block-index'
KST = timezone(timedelta(hours=9))
PROFILE = 'search-frequent-authenticated'
SCRIPT = 'RoommateBoardListKeywordGetTest.groovy'
KEYWORD = '부하 테스트 게시글'
TOKEN_FILE = '/tmp/knockin-block-index-20261007-' + str(int(time.time())) + '.txt'

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
    config['runId'] = 'block-index-20261007-' + label
    save(case / 'deployed-config.json', config)
    revision = deploy('resources/roommate-board-list.json', json.dumps(config, ensure_ascii=False, indent=2) + '\n')
    before = history()
    created = api('/perftest/api', method='POST', form=True, data={
        'testName': 'block-index-auth-search-' + label + '-' + str(int(time.time())),
        'description': 'Controlled Slice Block OR vs composite index/two NOT EXISTS AND; H2 seed1000; Java21 JAR; HTTP-only; SQL OFF',
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
    row['requestAccountingPassed'] = (row['status']=='FINISHED' and row['sampleComplete']
        and row['requests']==vu*count==row['controllerSuccesses']+row['controllerErrors']
        and row['successes']==row['controllerSuccesses'] and row['errors']==row['controllerErrors'])
    row['historyConsistentWithOutcomes'] = (row['historyDelta']==row['memberKeywordHistoryDelta']
        and row['successes']<=row['historyDelta']<=row['requests'])
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
        return {row['SQL_STATEMENT']: row for row in db.query(stats_sql.replace('SELECT ', 'SELECT /* block-index-' + str(time.time_ns()) + ' */ ', 1))}
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
        if data['contentExecutions'] != 10 or data['boardCountExecutions'] != EXPECTED_BOARD_COUNTS or data['historyDelta'] != 10:
            raise RuntimeError('Runtime SQL block-index evidence did not match expected executions')
        print('SQL CHECK content=10 count=' + str(data['boardCountExecutions']) + ' history+=10', flush=True)
    finally:
        db_execute('SET QUERY_STATISTICS FALSE')
        save(target / 'cleanup.json', {'queryStatisticsDisabled': not db.query('SELECT SQL_STATEMENT,EXECUTION_COUNT FROM INFORMATION_SCHEMA.QUERY_STATISTICS')})

