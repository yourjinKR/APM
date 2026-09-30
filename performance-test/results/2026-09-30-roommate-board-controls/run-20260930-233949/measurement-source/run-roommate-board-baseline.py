import argparse
import base64
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import copy
import csv
import threading
from datetime import datetime, timezone
from statistics import median
from html.parser import HTMLParser

PERF = Path(__file__).resolve().parents[1]
SOURCE = PERF / 'script/roommate'
CONTROLLER = 'http://localhost'
BACKEND = 'http://localhost:8080'

def request(url, method='GET', data=None, headers=None, form=False):
    headers = dict(headers or {})
    if data is not None:
        if form:
            data = urllib.parse.urlencode(data).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        else:
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
            headers['Content-Type'] = 'application/json;charset=UTF-8'
    with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=30) as response:
        text = response.read().decode('utf-8')
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text

class ResultTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.rows = []
        self.row = None
        self.cell = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table' and ('resultSet' in attrs.get('class', '') or 'resultSet' in attrs.get('id', '')):
            self.active = True
        if self.active and tag == 'tr': self.row = []
        if self.active and tag in ('th', 'td'): self.cell = ''
    def handle_data(self, data):
        if self.cell is not None: self.cell += data
    def handle_endtag(self, tag):
        if self.active and tag in ('td', 'th') and self.cell is not None:
            self.row.append(self.cell.strip()); self.cell = None
        if self.active and tag == 'tr' and self.row:
            self.rows.append(self.row); self.row = None
        if tag == 'table': self.active = False

class H2:
    def __init__(self):
        html = request(BACKEND + '/h2-console/')
        self.sid = re.search(r'jsessionid=([a-z0-9]+)', html).group(1)
        login = request(BACKEND + '/h2-console/login.do?jsessionid=' + self.sid, 'POST',
            {'driver': 'org.h2.Driver', 'url': 'jdbc:h2:mem:testdb;MODE=PostgreSQL', 'user': 'sa', 'password': ''}, form=True)
        if 'query.jsp' not in login and 'frame.jsp' not in login:
            raise RuntimeError('H2 console login did not succeed')
    def query(self, sql):
        if not sql.strip().upper().startswith('SELECT '): raise ValueError('Only read-only SQL allowed')
        html = request(BACKEND + '/h2-console/query.do?jsessionid=' + self.sid, 'POST', {'sql': sql, 'maxrows': '0'}, form=True)
        table = ResultTable(); table.feed(html)
        if not table.rows: raise RuntimeError('No H2 result table: ' + re.sub('<[^>]+>', '', html)[:400])
        return [dict(zip(table.rows[0], row)) for row in table.rows[1:]]
    def snapshot(self, ids):
        clause = ','.join(str(int(value)) for value in ids)
        return {'total': int(self.query('SELECT COUNT(*) AS TOTAL FROM SEARCH')[0]['TOTAL']),
            'keyword': int(self.query("SELECT COUNT(*) AS TOTAL FROM SEARCH WHERE KEYWORD='부하 테스트 게시글' AND MEMBER_ID IN (" + clause + ')')[0]['TOTAL'])}

def docker(*args, input=None):
    done = subprocess.run(['docker', *args], input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if done.returncode: raise RuntimeError('Docker operation failed: ' + done.stderr.decode(errors='replace')[:300])
    return done.stdout.decode(errors='replace')

def jwt_tokens(jar, members):
    with zipfile.ZipFile(jar) as archive:
        key = None
        for entry in archive.namelist():
            if entry.startswith('BOOT-INF/classes/application') and entry.endswith('.properties'):
                for line in archive.read(entry).decode('utf-8').splitlines():
                    if re.match(r'^\s*jwt\.key\s*[=:]', line): key = re.split(r'[=:]', line, maxsplit=1)[1].strip()
        if not key or key.startswith('${'): raise RuntimeError('Cannot resolve local test JWT signing key from built JAR')
    def encode(value): return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).rstrip(b'=').decode()
    now = int(time.time())
    tokens = []
    for member in members:
        message = encode({'alg': 'HS512'}) + '.' + encode({'sub': member['PROVIDER_ID'], 'memberId': int(member['ID']),
            'role': 'USER', 'iat': now, 'exp': now + 3600})
        signature = base64.urlsafe_b64encode(hmac.new(key.encode(), message.encode(), hashlib.sha512).digest()).rstrip(b'=').decode()
        tokens.append(message + '.' + signature)
    return tokens


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


class Suite:
    def __init__(self, args):
        self.args = args
        self.output = args.output_directory.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.auth = 'Basic ' + base64.b64encode((os.getenv('NGRINDER_USERNAME', 'admin') + ':' + os.getenv('NGRINDER_PASSWORD', 'admin')).encode()).decode()
        self.active_id = None
        self.agents = [line.split()[0] for line in docker('ps', '--format', '{{.Names}} {{.Image}}').splitlines() if 'ngrinder/agent:' in line]
        self.token_file = '/tmp/knockin-board-baseline-' + self.output.name + '.txt'
        self.results = []
        if args.resume_controls:
            self.results = json.loads((self.output / 'suite-summary.json').read_text(encoding='utf-8'))
            for row in self.results:
                if row['phase']=='duration-check':
                    row['excludedFromControls']=True
                    row['excludedReason']='Controller duration shutdown cuts final statistics/CSV tail; fixed-count complete runs used instead'
                if row['testId']==366:
                    row['excludedFromControls']=True
                    row['excludedReason']='Multiple GET per iteration reaches Controller request threshold early; reverted batching'
                if row['phase']=='control' and not row.get('excludedFromControls'):
                    row['accountingPassed']=(row['status']=='FINISHED' and row['sampleComplete'] and
                        row['sampleRequests']==row['expectedRequests']==row['successes']+row['errors'] and
                        row['sampleErrors']==row['errors'] and row['historyDelta']==row['expectedHistoryDelta'])
                    row['measurementComplete']=row['accountingPassed'] and row.get('durationSufficient',False)
        if args.resume_baseline:
            self.results = json.loads((self.output / 'suite-summary.json').read_text(encoding='utf-8'))
            for row in self.results:
                if row['status'] == 'STOP_BY_ERROR' and row['testId'] == 318:
                    row['excludedFromBaseline'] = True
                    row['excludedReason'] = 'Worker sample directory creation race; not an API load result'
        self.stop_monitor = threading.Event()

    def api(self, path, **kw):
        return request(CONTROLLER + path, headers={'Authorization': self.auth}, **kw)

    def deploy(self, path, content, file_type):
        self.api('/script/api/save/' + path, method='POST', data={'fileEntry': {'path': path, 'fileType': file_type,
            'content': content, 'description': 'APM board list fixed H2 measurement', 'encoding': 'UTF-8'},
            'targetHosts': 'host.docker.internal', 'validated': '0', 'createLibAndResource': False})
        file = self.api('/script/api/detail/' + path)['file']
        if file['content'] != content: raise RuntimeError('Deployment content differs: ' + path)
        return {'path': path, 'revision': file['revision'], 'sha256': hashlib.sha256(content.encode()).hexdigest()}

    def prepare(self):
        if self.api('/perftest/api/status')['runningTestsCount'] != 0: raise RuntimeError('Controller is busy')
        health = request(BACKEND + '/actuator/health')
        if health['status'] != 'UP' or health['components']['db']['details']['database'] != 'H2':
            raise RuntimeError('Only local H2 test backend is supported')
        if not self.agents: raise RuntimeError('No running nGrinder Agents')
        self.max_runs = int(self.api('/perftest/api/create')['config']['maxRunCount'])
        self.database = H2()
        self.members = self.database.query("SELECT ID,ROLE,PROVIDER_ID FROM MEMBER WHERE ROLE='USER' AND IS_DELETE=FALSE ORDER BY ID LIMIT 30")
        self.members = [member for member in self.members if int(member['ID']) != 3]
        liker = int(self.members[0]['ID'])
        self.ids = [int(member['ID']) for member in self.members]
        self.search_floor = int(self.database.query('SELECT MAX(ID) AS MAX_ID FROM SEARCH')[0]['MAX_ID'])
        self.initial_history = self.history()
        self.base_config = json.loads((SOURCE / 'resources/roommate-board-list.json').read_text(encoding='utf-8'))
        self.config = copy.deepcopy(self.base_config)
        self.config['tokenFile'] = self.token_file
        regions = self.database.query('SELECT ID,NAME,PARENTS_ID FROM REGION')
        room_types = self.database.query('SELECT ID,NAME FROM ROOM_TYPE')
        boards = []
        # Chunked reads avoid the H2 console's result row cap.
        for offset in range(0, 2000, 400):
            part = self.database.query("SELECT b.ID,b.TITLE,b.REGION_ID,b.ROOM_TYPE_ID,b.DEPOSIT,b.MONTHLY_RENT,b.MEMBER_ID,b.HITS,bi.GENDER FROM ROOMMATE_BOARD b JOIN BASIC_INFORMATION bi ON bi.MEMBER_ID=b.MEMBER_ID AND bi.ID=(SELECT MAX(x.ID) FROM BASIC_INFORMATION x WHERE x.MEMBER_ID=b.MEMBER_ID) WHERE b.IS_DELETED=FALSE AND EXISTS(SELECT 1 FROM STATE s WHERE s.MEMBER_ID=b.MEMBER_ID AND s.STATE='ACTIVE') AND (b.COMEABLE_DATE_NEGOTIABLE=TRUE OR b.COMEABLE_DATE>=CURRENT_TIMESTAMP) ORDER BY b.ID LIMIT 400 OFFSET " + str(offset))
            boards.extend(part)
            if len(part) < 400: break
        if len(boards) != 1002: raise RuntimeError('Expected unchanged seed1000 / 1002 boards')
        region_map = {int(row['ID']): row for row in regions}
        type_map = {int(row['ID']): row['NAME'] for row in room_types}
        # Seed support member 3 is blocked by every bulk member. Its likes cannot
        # provide a positive likedOnly fixture; create one local test-only relation.
        liked_board_id = int(next(row['ID'] for row in boards if row['TITLE'].startswith('부하 테스트 게시글 ')))
        existing_like = self.database.query('SELECT ID FROM ROOMMATE_BOARD_INTEREST WHERE MEMBER_ID=' + str(liker) + ' AND ROOMMATE_BOARD_ID=' + str(liked_board_id))
        if not existing_like:
            sql = 'INSERT INTO ROOMMATE_BOARD_INTEREST(MEMBER_ID,ROOMMATE_BOARD_ID,IS_DELETED) VALUES(' + str(liker) + ',' + str(liked_board_id) + ',FALSE)'
            html = request(BACKEND + '/h2-console/query.do?jsessionid=' + self.database.sid,'POST',{'sql':sql},form=True)
            if 'class="error"' in html: raise RuntimeError('Local liked fixture setup failed')
        fixture = next(row for row in boards if row['GENDER'] == 'MALE' and 300 <= int(row['DEPOSIT']) <= 600 and 30 <= int(row['MONTHLY_RENT']) <= 50 and row['TITLE'].startswith('부하 테스트 게시글 '))
        region_id = int(fixture['REGION_ID']); type_id = int(fixture['ROOM_TYPE_ID'])
        for name in ['filter-region', 'filter-combined', 'search-combined-authenticated']:
            item = self.config['profiles'][name]['inputs'][0]
            item['query']['regionIds'] = [region_id]
            item['expect']['regionFragments'] = [region_map[region_id]['NAME']]
        for name in ['filter-room-type', 'filter-combined', 'search-combined-authenticated']:
            item = self.config['profiles'][name]['inputs'][0]
            item['query']['roomTypeIds'] = [type_id]
            item['expect']['roomTypeNames'] = [type_map[type_id]]
        def ancestors(value):
            result = []
            while value in region_map and value not in result:
                result.append(value)
                parent = region_map[value]['PARENTS_ID']
                value = int(parent) if parent not in ('null', 'NULL', '') else -1
            return result
        likes = {int(row['ROOMMATE_BOARD_ID']) for row in self.database.query('SELECT ROOMMATE_BOARD_ID FROM ROOMMATE_BOARD_INTEREST WHERE IS_DELETED=FALSE AND MEMBER_ID=' + str(liker) + ' ORDER BY ROOMMATE_BOARD_ID LIMIT 400')}
        # Liked set can exceed console row cap; read in chunks.
        for offset in range(400, 1600, 400):
            rows = self.database.query('SELECT ROOMMATE_BOARD_ID FROM ROOMMATE_BOARD_INTEREST WHERE IS_DELETED=FALSE AND MEMBER_ID=' + str(liker) + ' ORDER BY ROOMMATE_BOARD_ID LIMIT 400 OFFSET ' + str(offset))
            likes.update(int(row['ROOMMATE_BOARD_ID']) for row in rows)
            if len(rows) < 400: break
        blocks = self.database.query('SELECT BLOCKER_ID,BLOCKED_ID FROM BLOCK WHERE IS_DELETED=FALSE')
        blocked = {int(row['BLOCKED_ID']) for row in blocks if int(row['BLOCKER_ID']) == liker} | {int(row['BLOCKER_ID']) for row in blocks if int(row['BLOCKED_ID']) == liker}
        for name, profile in self.config['profiles'].items():
            item = profile['inputs'][0]; q = item['query']; keyword = item.get('keyword', '').lower()
            matched = []
            for row in boards:
                if profile['auth'] == 'authenticated' and int(row['MEMBER_ID']) in blocked: continue
                if q.get('gender') and row['GENDER'] != q['gender']: continue
                if q.get('regionIds') and not set(q['regionIds']).intersection(ancestors(int(row['REGION_ID']))): continue
                if q.get('roomTypeIds') and int(row['ROOM_TYPE_ID']) not in q['roomTypeIds']: continue
                if q.get('likedOnly') and int(row['ID']) not in likes: continue
                if any(key in q and (int(row[col]) < q[key] if minimum else int(row[col]) > q[key]) for key, col, minimum in [('minDeposit','DEPOSIT',True),('maxDeposit','DEPOSIT',False),('minMounthRent','MONTHLY_RENT',True),('maxMounthRent','MONTHLY_RENT',False)]): continue
                searchable = [row['TITLE'], type_map[int(row['ROOM_TYPE_ID'])]] + [region_map[value]['NAME'] for value in ancestors(int(row['REGION_ID']))]
                if keyword and not any(keyword in value.lower() for value in searchable): continue
                matched.append(int(row['ID']))
            item['expect']['totalElements'] = len(matched)
            if len(matched) < item['expect']['minTotalElements']: raise RuntimeError('Insufficient fixture: ' + name)
        save(self.output / 'fixture-snapshot.json', {'regionId': region_id, 'regionName': region_map[region_id]['NAME'],
            'roomTypeId': type_id, 'roomTypeName': type_map[type_id], 'likedMemberId': liker, 'memberIds': self.ids,
            'boardCount': len(boards), 'initialHistory': self.initial_history, 'searchIdFloor': self.search_floor,
            'localFixtureNote': 'Added liked relation for member ' + str(liker) + ' / board ' + str(liked_board_id) + '; excluded mass-blocked member 3 from token pool',
            'expectedCounts': {name: profile['inputs'][0]['expect']['totalElements'] for name, profile in self.config['profiles'].items()}})
        save(self.output / 'fixture-config.json', self.config)
        print('Fixtures prepared:', {name: value['inputs'][0]['expect']['totalElements'] for name,value in self.config['profiles'].items()}, flush=True)

    def history(self):
        clause = ','.join(str(value) for value in self.ids)
        return {'total': int(self.database.query('SELECT COUNT(*) AS TOTAL FROM SEARCH')[0]['TOTAL']),
            'newTestRows': int(self.database.query('SELECT COUNT(*) AS TOTAL FROM SEARCH WHERE ID>' + str(self.search_floor) + ' AND MEMBER_ID IN (' + clause + ')')[0]['TOTAL'])}

    def reset_history(self):
        # Fresh, owned, local memory DB only; preserve every pre-existing seed row.
        clause = ','.join(str(value) for value in self.ids)
        sql = 'DELETE FROM SEARCH WHERE ID>' + str(self.search_floor) + ' AND MEMBER_ID IN (' + clause + ')'
        html = request(BACKEND + '/h2-console/query.do?jsessionid=' + self.database.sid, 'POST', {'sql': sql}, form=True)
        if 'class="error"' in html: raise RuntimeError('Local test history reset failed')
        after = self.history()
        if after != self.initial_history: raise RuntimeError('History did not return to initial seed row count')
        return after

    def supply_tokens(self):
        tokens = jwt_tokens(self.args.jar, self.members)
        for agent in self.agents:
            docker('exec', '-i', agent, 'sh', '-c', 'umask 077; cat > ' + self.token_file, input=('\n'.join(tokens) + '\n').encode())

    def monitor(self):
        prefixes = ('process_cpu_', 'system_cpu_', 'jvm_gc_', 'jvm_memory_used_', 'hikaricp_', 'jvm_threads_live', 'http_server_requests_seconds')
        with (self.output / 'telemetry.jsonl').open('a', encoding='utf-8', buffering=1) as target:
            while not self.stop_monitor.is_set():
                row = {'epochMs': int(time.time()*1000), 'activeTestId': self.active_id}
                try:
                    start = time.monotonic()
                    row['metrics'] = [line for line in request(BACKEND + '/actuator/prometheus').splitlines() if line.startswith(prefixes)]
                    row['scrapeElapsedMs'] = round((time.monotonic()-start)*1000, 3)
                    row['containers'] = docker('stats', '--no-stream', '--format', '{{json .}}', *self.agents, 'ngrinder-controller').splitlines()
                except Exception as error:
                    row['errorType'] = type(error).__name__
                target.write(json.dumps(row, ensure_ascii=False) + '\n')
                self.stop_monitor.wait(10)

    def run_case(self, profile, phase, vu, count, repeat, duration_seconds=None, minimum_sample_seconds=None, attempt=1):
        self.reset_history(); self.supply_tokens()
        label = f'{phase}-{profile}-vu{vu}-r{repeat}'
        if phase=='control': label += '-attempt'+str(attempt)
        if self.args.resume_baseline: label += '-retry1'
        case = self.output / label; case.mkdir()
        config = copy.deepcopy(self.config)
        config['runId'] = self.output.name + '-' + label
        keyword = profile.startswith('search-')
        config['activeReadProfile'] = 'list-anonymous' if keyword else profile
        config['activeKeywordProfile'] = profile if keyword else 'search-frequent-authenticated'
        content = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
        save(case / 'deployed-config.json', config)
        revision = self.deploy('resources/roommate-board-list.json', content, 'JSON')
        before = self.history()
        created = self.api('/perftest/api', method='POST', form=True, data={'testName': label + '-' + str(int(time.time())),
            'description': 'H2 seed1000; SQL logging false; fixed seed history; APM canonical',
            'scriptName': 'RoommateBoardListKeywordGetTest.groovy' if keyword else 'RoommateBoardListGetTest.groovy',
            'status': 'READY', 'threshold': 'D' if duration_seconds else 'R', 'duration': (duration_seconds or 60)*1000,
            'runCount': 0 if duration_seconds else count, 'agentCount': 1, 'processes': 1, 'threads': vu,
            'vuserPerAgent': vu, 'targetHosts': 'host.docker.internal', 'samplingInterval': 2, 'useRampUp': 'false',
            'connectionReset': 'false', 'ignoreTooManyError': 'false', 'ignoreSampleCount': 0})
        self.active_id = created['id']; test_id = self.active_id
        save(case / 'created.json', created)
        if created['threads'] != vu or created['threshold'] != ('D' if duration_seconds else 'R'):
            raise RuntimeError('Controller execution settings differ from requested settings')
        print('START', label, 'test', test_id, flush=True)
        deadline = time.monotonic() + self.args.timeout_seconds
        while time.monotonic() < deadline:
            time.sleep(3)
            state = self.api('/perftest/api/' + str(test_id))
            if state.get('finishTime') and not state['status'].get('stoppable', True): break
        else:
            self.api('/perftest/api/' + str(test_id) + '?action=stop', method='PUT')
            raise RuntimeError('Test completion timeout: ' + label)
        save(case / 'test.json', state)
        self.active_id = None
        # Wait for outstanding timed-out requests/transactions before DB accounting.
        time.sleep(6 if state.get('errors', 0) else 1)
        after = self.history()
        expected = (state.get('tests', 0) + state.get('errors', 0)) if duration_seconds else vu * count
        expected_history = expected if keyword and config['profiles'][profile]['auth'] == 'authenticated' else 0
        record = {'label': label, 'phase': phase, 'profile': profile, 'vu': vu, 'repeat': repeat, 'requestsPerVu': count,
            'testId': test_id, 'configRevision': revision['revision'], 'status': state['status']['name'],
            'durationSeconds': duration_seconds, 'expectedRequests': expected,
            'successes': state.get('tests', 0), 'errors': state.get('errors', 0), 'controllerTps': state.get('tps'),
            'controllerMeanMs': state.get('meanTestTime'), 'startTime': state.get('startTime'), 'finishTime': state.get('finishTime'),
            'historyBefore': before, 'historyAfter': after, 'historyDelta': after['total']-before['total'], 'expectedHistoryDelta': expected_history}
        save(case / 'basic-report.json', self.api('/perftest/api/' + str(test_id) + '/basic_report'))
        samples = case / 'request-samples'; samples.mkdir()
        collected = []
        source = config['outputDir'].rstrip('/') + '/' + config['runId'] + '-test_' + str(test_id)
        for agent in self.agents:
            exists = subprocess.run(['docker','exec',agent,'test','-d',source], capture_output=True)
            if exists.returncode == 0:
                docker('cp', agent + ':' + source + '/.', str(samples)); collected.append(agent)
        record['sampleAgents'] = collected
        if collected:
            spec = importlib.util.spec_from_file_location('samples', PERF / 'tools/summarize-roommate-board-samples.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            summary = module.summarize(samples, expected, vu)
            save(samples / 'request-summary.json', summary)
            record.update({'sampleComplete': summary['sampleComplete'], 'sampleRequests': summary['requests'], 'sampleErrors': summary['errors'],
                'sampleSpanSeconds':summary['sampleSpanSeconds'],
                'failures': summary['failures'], 'meanMs': summary['successMeanMs'], 'p95Ms': summary['successP95Ms'], 'p99Ms': summary['successP99Ms']})
        else: record['sampleComplete'] = False
        record['passed'] = state['status']['name'] == 'FINISHED' and expected > 0 and record['successes'] == expected and record['errors'] == 0 and record['sampleComplete'] and record.get('sampleErrors', -1) == 0 and record['historyDelta'] == expected_history and after['newTestRows'] == expected_history
        if duration_seconds:
            span = summary.get('sampleSpanSeconds', 0) if collected else 0
            record['sampleSpanSeconds'] = span
            record['passed'] = record['passed'] and span >= duration_seconds - 15
        record['integrityPassed']=record['passed']
        record['accountingPassed']=(state['status']['name']=='FINISHED' and record['sampleComplete'] and
            record.get('sampleRequests')==expected==record['successes']+record['errors'] and
            record.get('sampleErrors')==record['errors'] and record['historyDelta']==expected_history)
        if minimum_sample_seconds:
            record['minimumSampleSeconds']=minimum_sample_seconds
            record['durationSufficient']=record.get('sampleSpanSeconds',0)>=minimum_sample_seconds
            if not record['durationSufficient'] and record['integrityPassed']:
                record['excludedFromControls']=True
                record['excludedReason']='Calibration attempt shorter than minimum observation window'
            record['passed']=record['passed'] and record['durationSufficient']
            record['measurementComplete']=record['accountingPassed'] and record['durationSufficient']
        self.results.append(record)
        save(self.output / 'suite-summary.json', self.results)
        print('END', label, 'test', test_id, 'success',record['successes'],'errors',record['errors'],'history+',record['historyDelta'],'p95',record.get('p95Ms'),'passed',record['passed'], flush=True)
        self.reset_history()
        time.sleep(self.args.cooldown_seconds if phase in ('baseline','control') else 1)
        return record['passed']

    def execute(self):
        self.prepare()
        if self.args.prepare_only: return
        self.supply_tokens()
        monitor = threading.Thread(target=self.monitor, daemon=True)
        monitor.start()
        original_system_config = None
        try:
            if self.args.mode=='controls':
                original_system_config=self.api('/operation/system_config/api')
                if not isinstance(original_system_config,str):raise RuntimeError('Unexpected Controller system config')
                changed=re.sub(r'(?m)^\s*controller\.max_run_count\s*=.*$', 'controller.max_run_count=1000000', original_system_config)
                if changed==original_system_config:changed=original_system_config+'\ncontroller.max_run_count=1000000\n'
                self.api('/operation/system_config/api',method='POST',form=True,data={'content':changed})
                for _ in range(20):
                    if self.api('/perftest/api/create')['config']['maxRunCount']==1000000:break
                    time.sleep(3)
                else:raise RuntimeError('Temporary Controller max run count did not reload')
                save(self.output/'controller-limit.json',{'originalMaxRunCount':self.max_runs,'temporaryMaxRunCount':1000000,
                    'originalConfigSha256':hashlib.sha256(original_system_config.encode()).hexdigest(),'restored':False})
            deployments = [self.deploy(name, (SOURCE / name).read_text(encoding='utf-8'), 'GROOVY_SCRIPT') for name in ['RoommateBoardListGetTest.groovy','RoommateBoardListKeywordGetTest.groovy']]
            deployments.append(self.deploy('resources/RoommateBoardListSupport.txt',(SOURCE/'resources/RoommateBoardListSupport.txt').read_text(encoding='utf-8'),'TXT'))
            save(self.output/('deployment-after-helper-fix.json' if self.args.resume_baseline else 'deployment.json'), deployments)
            if self.args.mode == 'controls':
                selected = ['list-anonymous','list-authenticated','search-frequent-anonymous','search-frequent-authenticated']
                if not self.args.resume_controls:
                    for profile in selected:
                        if not self.run_case(profile,'fixture',1,3,1): raise RuntimeError('Control fixture failed')
                counts={}
                for profile in selected:
                    existing=[r for r in self.results if r['phase']=='warmup' and r['profile']==profile and r['passed']]
                    if not existing:
                        if not self.run_case(profile,'warmup',1,100,1): raise RuntimeError('Control warmup failed')
                        measured=self.results[-1]
                    else: measured=existing[-1]
                    counts[profile]=max(100,int(measured['sampleRequests']/measured['sampleSpanSeconds']*self.args.duration_seconds*1.35)+1)
                for repeat in range(1,self.args.repetitions+1):
                    offset=(repeat-1)%len(selected)
                    order=selected[offset:]+selected[:offset]
                    for profile in order:
                        completed=[r for r in self.results if r['phase']=='control' and r['profile']==profile and r['repeat']==repeat and r.get('measurementComplete') and not r.get('excludedFromControls')]
                        if completed:
                            counts[profile]=max(counts[profile],completed[-1]['requestsPerVu'])
                            continue
                        counts[profile]=max([counts[profile]]+[r['requestsPerVu'] for r in self.results if r['phase']=='control' and r['profile']==profile and not r.get('excludedFromControls')])
                        first_attempt=max([r.get('attempt',int(r['label'].rsplit('attempt',1)[-1])) for r in self.results if r['phase']=='control' and r['profile']==profile and r['repeat']==repeat]+[0])+1
                        for attempt in range(first_attempt,first_attempt+4):
                            passed=self.run_case(profile,'control',1,counts[profile],repeat,minimum_sample_seconds=self.args.duration_seconds,attempt=attempt)
                            measured=self.results[-1]
                            if measured.get('measurementComplete'): break
                            if not measured['accountingPassed']:
                                save(self.output/'stop-reason.json',{'reason':'Control integrity failed; remaining measurements stopped','case':measured['label']})
                                return
                            counts[profile]=int(counts[profile]*self.args.duration_seconds/max(measured['sampleSpanSeconds'],1)*1.25)+1
                        else: raise RuntimeError('Could not establish minimum control window')
                print('Four-path complete-count sustained controls complete',flush=True)
                return
            fixture_pass = {}
            selected = ['list-anonymous','search-frequent-authenticated']
            if self.args.resume_baseline:
                for profile in selected:
                    if not self.run_case(profile,'concurrency-check',3,3,1): raise RuntimeError('Concurrent worker check failed')
                if (self.output/'stop-reason.json').exists():
                    (self.output/'stop-reason.json').rename(self.output/'harness-stop-reason.json')
            else:
                for profile in self.config['profiles']:
                    fixture_pass[profile] = self.run_case(profile,'fixture',1,3,1)
                save(self.output/'fixture-verdicts.json', fixture_pass)
                if not all(fixture_pass[name] for name in selected): raise RuntimeError('Primary baseline profiles failed fixture validation')
                for profile in selected:
                    if not self.run_case(profile,'warmup',1,30,1): raise RuntimeError('Warmup failed')
            stop = False
            for vu in [1,3,5]:
                if vu < self.args.start_vu: continue
                for repeat in range(1,4):
                    for profile in selected:
                        if not self.run_case(profile,'baseline',vu,self.args.requests_per_vu,repeat):
                            save(self.output/'stop-reason.json', {'reason':'Failed case: remaining repetitions and higher VUser stages stopped','case':self.results[-1]['label']})
                            stop = True; break
                    if stop: break
                if stop: break
            print('Suite measurements complete; inspect suite-summary.json', flush=True)
        finally:
            if original_system_config is not None:
                self.api('/operation/system_config/api',method='POST',form=True,data={'content':original_system_config})
                for _ in range(20):
                    if self.api('/perftest/api/create')['config']['maxRunCount']==self.max_runs:break
                    time.sleep(3)
                limit_path=self.output/'controller-limit.json'
                limit=json.loads(limit_path.read_text(encoding='utf-8')) if limit_path.exists() else {}
                limit['restored']=self.api('/perftest/api/create')['config']['maxRunCount']==self.max_runs
                limit['restoredContentMatches']=self.api('/operation/system_config/api')==original_system_config
                save(limit_path,limit)
            if self.active_id is not None:
                try: self.api('/perftest/api/' + str(self.active_id) + '?action=stop', method='PUT')
                except Exception: pass
            self.stop_monitor.set(); monitor.join(timeout=45)
            cleanup = {'agentTokenFileAbsent': {}, 'controllerConfigRestored': False}
            for agent in self.agents:
                docker('exec',agent,'rm','-f',self.token_file)
                exists = subprocess.run(['docker','exec',agent,'test','!','-e',self.token_file],capture_output=True)
                cleanup['agentTokenFileAbsent'][agent] = exists.returncode == 0
            self.deploy('resources/roommate-board-list.json',(SOURCE/'resources/roommate-board-list.json').read_text(encoding='utf-8'),'JSON')
            cleanup['controllerConfigRestored'] = True
            save(self.output/'cleanup.json',cleanup)


def main():
    parser = argparse.ArgumentParser(description='Local H2 seed1000 fixture and 1/3/5 VUser exploratory baseline. Backend must already be running with SQL logging disabled. No production targets.')
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--jar', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--mode', choices=['baseline','controls'], default='baseline')
    parser.add_argument('--resume-controls',action='store_true')
    parser.add_argument('--duration-seconds',type=int,default=180)
    parser.add_argument('--warmup-seconds',type=int,default=60)
    parser.add_argument('--repetitions',type=int,default=3)
    parser.add_argument('--resume-baseline', action='store_true', help='Resume the recorded helper-race run after fixing worker initialization; preserves completed 1 VU results')
    parser.add_argument('--start-vu', type=int, choices=[1,3,5], default=1)
    parser.add_argument('--requests-per-vu', type=int, default=100)
    parser.add_argument('--cooldown-seconds', type=int, default=15)
    parser.add_argument('--timeout-seconds', type=int, default=1200)
    args = parser.parse_args()
    if not re.fullmatch('[A-Za-z0-9_-]+', args.output_directory.name): parser.error('Use a safe output directory name')
    if args.requests_per_vu < 1: parser.error('Positive request count required')
    if min(args.duration_seconds,args.warmup_seconds,args.repetitions,args.timeout_seconds)<1 or args.cooldown_seconds<0: parser.error('Invalid duration/repetition/cooldown')
    Suite(args).execute()


if __name__ == '__main__': main()

