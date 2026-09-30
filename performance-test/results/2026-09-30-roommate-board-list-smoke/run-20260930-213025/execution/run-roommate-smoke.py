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
from html.parser import HTMLParser

APM = Path(r'C:\dev\workspace\prography\APM')
PERF = APM / 'performance-test'
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
        html = request(BACKEND + '/h2-console/query.do?jsessionid=' + self.sid, 'POST', {'sql': sql}, form=True)
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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--jar', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    output = args.directory.resolve()
    output.mkdir(parents=True, exist_ok=True)
    auth = 'Basic ' + base64.b64encode((os.getenv('NGRINDER_USERNAME', 'admin') + ':' + os.getenv('NGRINDER_PASSWORD', 'admin')).encode()).decode()
    def api(path, **kw): return request(CONTROLLER + path, headers={'Authorization': auth}, **kw)
    if api('/perftest/api/status')['runningTestsCount'] != 0: raise RuntimeError('Controller is busy')
    if request(BACKEND + '/actuator/health')['status'] != 'UP': raise RuntimeError('Backend not ready')
    database = H2()
    members = database.query("SELECT ID,ROLE,PROVIDER_ID FROM MEMBER WHERE ROLE='USER' AND IS_DELETE=FALSE ORDER BY ID LIMIT 10")
    tokens = jwt_tokens(args.jar, members)
    ids = [int(member['ID']) for member in members]
    proof = request(BACKEND + '/roommate/boards?page=0&size=1', headers={'Authorization': 'Bearer ' + tokens[0]})
    if proof['status'] != 200: raise RuntimeError('Test authentication failed')
    save = lambda name, value: (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    save('preflight.json', {'memberIds': ids, 'anonymousBoardTotal': request(BACKEND + '/roommate/boards?page=0&size=1')['data']['totalElements'],
        'authenticatedBoardTotal': proof['data']['totalElements'], 'initialSearch': database.snapshot(ids)})
    if args.prepare_only:
        print('Read-only DB and local fixture authentication preflight passed', flush=True)
        return
    agents = [line.split()[0] for line in docker('ps', '--format', '{{.Names}} {{.Image}}').splitlines() if 'ngrinder/agent:' in line]
    if not agents: raise RuntimeError('No running Agents')
    token_file = '/tmp/knockin-roommate-smoke-tokens-20260930.txt'
    for agent in agents:
        docker('exec', '-i', agent, 'sh', '-c', 'umask 077; cat > ' + token_file, input=('\n'.join(tokens) + '\n').encode())
    active_id = None
    results = []
    def deploy(path, content, file_type):
        api('/script/api/save/' + path, method='POST', data={'fileEntry': {'path': path, 'fileType': file_type,
            'content': content, 'description': 'APM canonical board list smoke', 'encoding': 'UTF-8'},
            'targetHosts': 'host.docker.internal', 'validated': '0', 'createLibAndResource': False})
        deployed = api('/script/api/detail/' + path)['file']
        if deployed['content'] != content: raise RuntimeError('Controller deployment differs: ' + path)
        return {'path': path, 'revision': deployed['revision'], 'sha256': hashlib.sha256(content.encode()).hexdigest()}
    try:
        deployed = []
        for name in ['RoommateBoardListGetTest.groovy', 'RoommateBoardListKeywordGetTest.groovy']:
            deployed.append(deploy(name, (SOURCE / name).read_text(encoding='utf-8'), 'GROOVY_SCRIPT'))
        deployed.append(deploy('resources/RoommateBoardListSupport.txt', (SOURCE / 'resources/RoommateBoardListSupport.txt').read_text(encoding='utf-8'), 'TXT'))
        save('deployment.json', deployed)
        for profile in ['list-anonymous', 'list-authenticated', 'search-frequent-anonymous', 'search-frequent-authenticated']:
            case = output / profile; case.mkdir(exist_ok=True)
            config = json.loads((SOURCE / 'resources/roommate-board-list.json').read_text(encoding='utf-8'))
            config['runId'] = output.name + '-' + profile
            config['tokenFile'] = token_file
            config['activeReadProfile'] = profile if profile.startswith('list-') else 'list-anonymous'
            config['activeKeywordProfile'] = profile if profile.startswith('search-') else 'search-frequent-authenticated'
            content = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
            (case / 'deployed-config.json').write_text(content, encoding='utf-8')
            revision = deploy('resources/roommate-board-list.json', content, 'JSON')
            before = database.snapshot(ids)
            script = 'RoommateBoardListKeywordGetTest.groovy' if profile.startswith('search-') else 'RoommateBoardListGetTest.groovy'
            created = api('/perftest/api', method='POST', form=True, data={'testName': 'board-smoke-' + profile + '-' + str(int(time.time())),
                'description': 'contract smoke; local H2 seed1000; 1 VUser x 3 requests', 'scriptName': script,
                'status': 'READY', 'threshold': 'R', 'runCount': 3, 'agentCount': 1, 'processes': 1, 'threads': 1,
                'vuserPerAgent': 1, 'targetHosts': 'host.docker.internal', 'samplingInterval': 2, 'useRampUp': 'false',
                'connectionReset': 'false', 'ignoreTooManyError': 'false', 'ignoreSampleCount': 0})
            active_id = created['id']
            print('Started', profile, 'test', active_id, flush=True)
            (case / 'created.json').write_text(json.dumps(created, ensure_ascii=False, indent=2), encoding='utf-8')
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                time.sleep(3)
                state = api('/perftest/api/' + str(active_id))
                if state.get('finishTime') and not state['status'].get('stoppable', True): break
            else: raise RuntimeError('Test did not finish within 180 seconds')
            (case / 'test.json').write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
            test_id = active_id; active_id = None
            after = database.snapshot(ids)
            expected_delta = 3 if profile == 'search-frequent-authenticated' else 0
            record = {'profile': profile, 'testId': test_id, 'configRevision': revision['revision'],
                'status': state['status']['name'], 'successes': state.get('tests', 0), 'errors': state.get('errors', 0),
                'searchBefore': before, 'searchAfter': after, 'expectedHistoryDelta': expected_delta,
                'historyDelta': after['keyword'] - before['keyword']}
            record['passed'] = record['status'] == 'FINISHED' and record['successes'] == 3 and record['errors'] == 0 and record['historyDelta'] == expected_delta and after['total'] - before['total'] == expected_delta
            samples = case / 'request-samples'; samples.mkdir(exist_ok=True)
            run_id = config['runId'] + '-test_' + str(test_id)
            collected = 0
            for agent in agents:
                source = config['outputDir'].rstrip('/') + '/' + run_id
                exists = subprocess.run(['docker', 'exec', agent, 'test', '-d', source], capture_output=True)
                if exists.returncode == 0:
                    docker('cp', agent + ':' + source + '/.', str(samples)); collected += 1
            if collected:
                spec = importlib.util.spec_from_file_location('samples', PERF / 'tools/summarize-roommate-board-samples.py')
                module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
                summary = module.summarize(samples, 3, 1)
                (samples / 'request-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
                record['samplesComplete'] = summary['sampleComplete']
                record['passed'] = record['passed'] and summary['sampleComplete'] and summary['errors'] == 0
            else:
                record['samplesComplete'] = False; record['passed'] = False
            results.append(record); save('smoke-summary.json', results)
            print('Finished', profile, 'successes=', record['successes'], 'errors=', record['errors'], 'historyDelta=', record['historyDelta'], 'passed=', record['passed'], flush=True)
            if not record['passed']: raise RuntimeError('Smoke failed; inspect test ' + str(test_id))
    finally:
        if active_id is not None:
            try: api('/perftest/api/' + str(active_id) + '?action=stop', method='PUT')
            except Exception: pass
        for agent in agents:
            docker('exec', agent, 'rm', '-f', token_file)
    print('All four contract smoke cases passed', flush=True)

if __name__ == '__main__': main()
