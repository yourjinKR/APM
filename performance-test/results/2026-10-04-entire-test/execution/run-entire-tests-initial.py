"""Sequential exploratory load survey of every canonical APM Groovy script.

Uses an already running, local H2 test server. Credentials stay in memory and
temporary Agent files. Controller scripts are restored in finally.
"""
import argparse
import base64
import copy
import csv
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import time

APM = Path(r'C:\dev\workspace\prography\APM')
PERF = APM / 'performance-test'
SOURCE = PERF / 'script'
spec = importlib.util.spec_from_file_location('baseline', PERF / 'tools/run-roommate-board-baseline.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
KST = timezone(timedelta(hours=9))
ROOT = '/tmp/knockin-entire-20261004'
TOKEN_FILE = ROOT + '/tokens.txt'
LABELS = {
 'RoommateBoardListGetTest': '게시글 목록(익명)',
 'RoommateBoardListKeywordGetTest': '게시글 검색(인증)',
 'RoommateBoardDetailGetTest': '게시글 상세',
 'RoommateBoardEditFormGetTest': '게시글 편집 폼',
 'RoommateMatchListGetTest': '추천 회원 목록',
 'RoommateMatchDetailGetTest': '추천 회원 상세',
 'ChatRoomListGetTest': '채팅방 목록',
 'ChatRoomDetailGetTest': '채팅방 상세·이력',
 'RoommateRequestListGetTest': '룸메이트 요청 목록',
 'MyRoommateGetTest': '내 룸메이트',
 'HouseRuleListGetTest': '하우스룰 목록',
 'HouseRuleDetailGetTest': '하우스룰 상세',
 'CalendarMonthListGetTest': '캘린더 월별',
 'CalendarDayListGetTest': '캘린더 일별',
 'CalendarCategoryGetTest': '캘린더 카테고리',
 'CalendarEditFormGetTest': '캘린더 편집 폼',
 'UserBoardsGetTest': '내 게시글',
}

def save(path, value):
    base.save(path, value)

def sha(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def now():
    return datetime.now(KST).isoformat()

def command(*args, input=None):
    result = subprocess.run(args, input=input, capture_output=True)
    if result.returncode:
        raise RuntimeError(f'{args[0]} operation failed: ' + result.stderr.decode(errors='replace')[:300])
    return result.stdout.decode(errors='replace')

def percentile(values, fraction):
    if not values: return None
    values = sorted(values)
    return values[max(0, math.ceil(len(values) * fraction) - 1)]

class Survey:
    def __init__(self, args):
        self.args = args
        self.out = args.output.resolve()
        self.out.mkdir(parents=True, exist_ok=True)
        self.auth = 'Basic ' + base64.b64encode(b'admin:admin').decode()
        self.agents = [line.split()[0] for line in command('docker', 'ps', '--format', '{{.Names}} {{.Image}}').splitlines() if 'ngrinder/agent:' in line]
        self.originals = {}
        self.deployments = []
        self.rows = []
        self.active_id = None
        self.paths = [next(SOURCE.rglob(name + '.groovy')) for name in LABELS]
        actual = {p.stem for p in SOURCE.rglob('*.groovy')}
        if actual != set(LABELS): raise RuntimeError('Script inventory changed; update labels before testing')

    def api(self, path, **kwargs):
        return base.request(base.CONTROLLER + path, headers={'Authorization': self.auth}, **kwargs)

    def deploy(self, path, content, file_type):
        if path not in self.originals:
            self.originals[path] = self.api('/script/api/detail/' + path)['file']
        self.api('/script/api/save/' + path, method='POST', data={'fileEntry': {
            'path': path, 'fileType': file_type, 'content': content,
            'description': '2026-10-04 entire API exploratory survey', 'encoding': 'UTF-8'},
            'targetHosts': 'host.docker.internal', 'validated': '0', 'createLibAndResource': False})
        deployed = self.api('/script/api/detail/' + path)['file']
        if deployed['content'] != content: raise RuntimeError('Deployment mismatch: ' + path)
        self.deployments.append({'path': path, 'revision': deployed['revision'], 'sha256': sha(content)})

    def tokens(self):
        tokens = base.jwt_tokens(self.args.jar, self.members)
        for agent in self.agents:
            command('docker', 'exec', '-i', agent, 'sh', '-c',
                'umask 077; mkdir -p ' + ROOT + '; cat > ' + TOKEN_FILE,
                input=('\n'.join(tokens) + '\n').encode())

    def prepare(self):
        if self.api('/perftest/api/status')['runningTestsCount'] != 0: raise RuntimeError('Controller is busy')
        health = base.request(base.BACKEND + '/actuator/health')
        if health['status'] != 'UP' or health['components']['db']['details']['database'] != 'H2':
            raise RuntimeError('Only local healthy H2 test backend supported')
        self.db = base.H2()
        self.members = self.db.query("SELECT m.ID,m.PROVIDER_ID,b.ID AS BOARD_ID,c.CHATTING_ROOM_ID,h.ID AS HOUSE_RULE_ID,cal.START_DATE FROM MEMBER m JOIN ROOMMATE_BOARD b ON b.MEMBER_ID=m.ID AND b.IS_DELETED=FALSE JOIN CHAT_ROOM_MEMBER c ON c.MEMBER_ID=m.ID AND c.IS_LEFT=FALSE JOIN ROOMMATE_HOUSE_RULE h ON h.MEMBER_ID=m.ID AND h.IS_DELETED=FALSE JOIN ROOMMATE_CALENDAR cal ON cal.MEMBER_ID=m.ID AND cal.IS_DELETED=FALSE WHERE m.PROVIDER_ID LIKE 'load_test_user_%' ORDER BY m.ID LIMIT 30")
        if len(self.members) != 30 or len({x['ID'] for x in self.members}) != 30:
            raise RuntimeError('Expected 30 distinct fixture members')
        self.date = datetime.fromisoformat(self.members[0]['START_DATE']).date()
        self.initial_history = int(self.db.query('SELECT COUNT(*) AS N FROM SEARCH')[0]['N'])
        self.counts = {table: int(self.db.query('SELECT COUNT(*) AS N FROM ' + table)[0]['N']) for table in
            ['MEMBER', 'ROOMMATE_BOARD', 'CHATTING_ROOM', 'CHAT_ROOM_MESSAGE', 'ROOMMATE_HOUSE_RULE', 'ROOMMATE_CALENDAR']}
        config = json.loads((SOURCE / 'roommate/resources/roommate-board-list.json').read_text(encoding='utf-8'))
        config.update(runId='entire-20261004', outputDir=ROOT, tokenFile=TOKEN_FILE,
            activeReadProfile='list-anonymous', activeKeywordProfile='search-frequent-authenticated')
        # Match the 5s/15s connection/socket settings of the other 15 scripts.
        config['connectTimeoutMs'] = 5000
        config['socketTimeoutMs'] = 15000
        for path in self.paths:
            original = path.read_text(encoding='utf-8')
            content = original if path.stem in ('RoommateBoardListGetTest', 'RoommateBoardListKeywordGetTest') else self.instrument(original)
            self.deploy(path.name, content, 'GROOVY_SCRIPT')
            (self.out / 'execution' / 'deployed-scripts').mkdir(parents=True, exist_ok=True)
            (self.out / 'execution' / 'deployed-scripts' / path.name).write_text(content, encoding='utf-8')
        self.deploy('resources/RoommateBoardListSupport.txt', (SOURCE / 'roommate/resources/RoommateBoardListSupport.txt').read_text(encoding='utf-8'), 'TXT')
        self.deploy('resources/roommate-board-list.json', json.dumps(config, ensure_ascii=False, indent=2) + '\n', 'JSON')
        save(self.out / 'execution' / 'deployed-config.json', config)
        self.tokens()
        self.environment = {'startedAtKst': now(), 'backendUrl': base.BACKEND, 'controllerUrl': base.CONTROLLER,
            'profile': 'test', 'database': 'H2 in-memory, PostgreSQL mode', 'recordsPerEntity': 1000,
            'actualCounts': self.counts, 'jarPath': str(self.args.jar),
            'jarSha256': hashlib.file_digest(self.args.jar.open('rb'), 'sha256').hexdigest(),
            'backendCommit': command('git', '-C', r'C:\dev\workspace\KnockIn\back\11th-1team-BE', 'rev-parse', 'HEAD').strip(),
            'apmCommit': command('git', '-C', str(APM), 'rev-parse', 'HEAD').strip(),
            'agents': self.agents, 'agentCountPerRun': 1, 'processesPerRun': 1,
            'vusers': self.args.vus, 'iterationsPerVu': self.args.iterations,
            'smokeWarmupIterations': 20, 'connectTimeoutMs': 5000, 'socketTimeoutMs': 15000,
            'cooldownSeconds': 5, 'calendarDate': self.date.isoformat(),
            'fixture': self.members, 'sourceSha256': {str(p.relative_to(SOURCE)): sha(p.read_text(encoding='utf-8')) for p in self.paths},
            'sqlLogging': False, 'controllerAgentVersion': '3.5.9-p1', 'backendJavaVersion': '21',
            'sourceConfigPreexistingUserChangePreserved': True}
        save(self.out / 'environment.json', self.environment)
        save(self.out / 'execution' / 'deployment.json', self.deployments)
        self.report()
        print('PREPARED 17 scripts; distinct fixture members=30; counts=' + json.dumps(self.counts), flush=True)

    def instrument(self, content):
        content = 'import groovy.json.JsonSlurper\nimport java.nio.file.Files\nimport net.grinder.scriptengine.groovy.junit.annotation.AfterThread\n' + content
        content = re.sub(r'(static final List<String> TOKEN_POOL = )\[[^\n]+\]', r"\1new File('" + TOKEN_FILE + "').readLines('UTF-8')", content)
        ids = {'BOARD_ID_POOL': 'BOARD_ID', 'OWNED_BOARD_ID_POOL': 'BOARD_ID',
            'CHAT_ROOM_ID_POOL': 'CHATTING_ROOM_ID', 'HOUSE_RULE_ID_POOL': 'HOUSE_RULE_ID'}
        for pool, field in ids.items():
            content = re.sub(r'(static final List<Long> ' + pool + r' = )\[[^\n]+\]',
                lambda match: match.group(1) + '[' + ','.join(x[field] + 'L' for x in self.members) + ']', content)
        other_ids = self.members[1:] + self.members[:1]
        content = re.sub(r'(static final List<Long> TARGET_MEMBER_ID_POOL = )\[[^\n]+\]',
            lambda match: match.group(1) + '[' + ','.join(x['ID'] + 'L' for x in other_ids) + ']', content)
        for key, value in [('YEAR', self.date.year), ('MONTH', self.date.month), ('DAY', self.date.day)]:
            content = re.sub(r'(static final int ' + key + r' = )\d+', lambda match: match.group(1) + str(value), content)
        content = content.replace('private String userToken', 'private BufferedWriter samples\n    private long sampleIteration = 0\n    private String userToken')
        init = """grinder.statistics.delayReports = true
        File sampleDir = new File('""" + ROOT + """', grinder.properties.getProperty('grinder.test.id'))
        Files.createDirectories(sampleDir.toPath())
        File sampleFile = new File(sampleDir, "a${grinder.agentNumber}-p${grinder.processNumber}-t${grinder.threadNumber}.csv")
        if (!sampleFile.createNewFile()) throw new IllegalStateException('Duplicate sample file')
        samples = sampleFile.newWriter('UTF-8')
        samples.write('iteration,startedAtEpochMs,elapsedMs,httpStatus,success,failure\\n')
        samples.flush()"""
        content = content.replace('grinder.statistics.delayReports = true', init)
        match = re.search(r'        HTTPResponse response = (request\.GET[^\n]+)', content)
        if not match: raise RuntimeError('Cannot instrument HTTP request')
        replacement = """        long startedAt = System.currentTimeMillis()
        long startedNs = System.nanoTime()
        HTTPResponse response
        try {
            response = """ + match.group(1) + """
        } catch (Exception error) {
            writeSample(startedAt, (System.nanoTime()-startedNs)/1000000d, 0, false, error.class.simpleName)
            throw error
        }
        double elapsedMs = (System.nanoTime()-startedNs)/1000000d
        boolean contractOk = response.statusCode == 200
        if (contractOk) {
            try {
                def json = new JsonSlurper().parseText(response.bodyText)
                contractOk = json.status == 200 && json.data != null
            } catch (Exception ignored) { contractOk = false }
        }
        if (!contractOk) grinder.statistics.forLastTest.success = false
        writeSample(startedAt, elapsedMs, response.statusCode, contractOk, contractOk ? '' : 'HTTP_OR_CONTRACT')"""
        content = content[:match.start()] + replacement + content[match.end():]
        extra = """
    private void writeSample(long startedAt, double elapsedMs, int status, boolean success, String failure) {
        samples.write("${++sampleIteration},${startedAt},${elapsedMs},${status},${success},${failure}\\n")
    }
    @AfterThread
    void closeSamples() { samples?.close() }
"""
        index = content.rfind('}')
        return content[:index] + extra + content[index:]

    def collect(self, test_id, keyword, is_list, directory):
        source = ROOT + ('/entire-20261004-test_' + str(test_id) if is_list else '/' + str(test_id))
        destination = directory / 'samples'
        destination.mkdir()
        for agent in self.agents:
            exists = subprocess.run(['docker', 'exec', agent, 'test', '-d', source], capture_output=True)
            if exists.returncode == 0:
                command('docker', 'cp', agent + ':' + source + '/.', str(destination))
        samples = []
        workers = []
        for path in sorted(destination.glob('*.csv')):
            with path.open(encoding='utf-8', newline='') as stream:
                part = list(csv.DictReader(stream))
            workers.append({'file': path.name, 'samples': len(part)})
            samples.extend(part)
        ok = [float(x['elapsedMs']) for x in samples if x['success'].lower() == 'true']
        all_values = [float(x['elapsedMs']) for x in samples]
        start = min([int(x['startedAtEpochMs']) for x in samples], default=0)
        end = max([int(x['startedAtEpochMs']) + float(x['elapsedMs']) for x in samples], default=0)
        return {'samples': len(samples), 'sampleErrors': len(samples)-len(ok), 'workers': workers,
            'meanMs': round(statistics.mean(ok), 3) if ok else None,
            'p95Ms': round(percentile(ok, .95), 3) if ok else None,
            'allRequestP95Ms': round(percentile(all_values, .95), 3) if all_values else None,
            'sampleSpanSeconds': round((end-start)/1000, 3) if samples else 0,
            'httpStatuses': {str(status): sum(1 for x in samples if x['httpStatus'] == str(status)) for status in sorted({int(x['httpStatus']) for x in samples})}}

    def run(self, path, phase, vu, iterations):
        if self.api('/perftest/api/status')['runningTestsCount'] != 0: raise RuntimeError('Controller became busy')
        if base.request(base.BACKEND + '/actuator/health')['status'] != 'UP': raise RuntimeError('Backend became unhealthy')
        self.tokens()
        history_before = int(self.db.query('SELECT COUNT(*) AS N FROM SEARCH')[0]['N'])
        is_list = path.stem in ('RoommateBoardListGetTest', 'RoommateBoardListKeywordGetTest')
        keyword = path.stem == 'RoommateBoardListKeywordGetTest'
        label = f'{phase}-{path.stem}-vu{vu}'
        directory = self.out / 'raw' / label
        directory.mkdir()
        created = self.api('/perftest/api', method='POST', form=True, data={
            'testName': 'entire-20261004-' + label + '-' + str(int(time.time())),
            'description': 'All read scripts survey; test/H2 seed1000; one agent/process; SQL logging off',
            'scriptName': path.name, 'status': 'READY', 'threshold': 'R', 'runCount': iterations,
            'agentCount': 1, 'processes': 1, 'threads': vu, 'vuserPerAgent': vu,
            'targetHosts': 'host.docker.internal', 'samplingInterval': 2, 'useRampUp': 'false',
            'connectionReset': 'false', 'ignoreTooManyError': 'false', 'ignoreSampleCount': 0})
        self.active_id = test_id = created['id']
        save(directory / 'created.json', created)
        if created['threads'] != vu or created['runCount'] != iterations:
            raise RuntimeError('Controller execution settings differ')
        print(f'START {label} id={test_id} planned={vu*iterations}', flush=True)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            time.sleep(3)
            state = self.api('/perftest/api/' + str(test_id))
            if state.get('finishTime') and not state['status'].get('stoppable', True): break
        else:
            self.api('/perftest/api/' + str(test_id) + '?action=stop', method='PUT')
            raise RuntimeError('Per-test completion timeout')
        self.active_id = None
        save(directory / 'test.json', state)
        save(directory / 'basic-report.json', self.api('/perftest/api/' + str(test_id) + '/basic_report'))
        time.sleep(2)
        summary = self.collect(test_id, keyword, is_list, directory)
        history_after = int(self.db.query('SELECT COUNT(*) AS N FROM SEARCH')[0]['N'])
        requests = (state.get('tests') or 0) + (state.get('errors') or 0)
        accounting = (summary['samples'] == requests == vu*iterations and summary['sampleErrors'] == (state.get('errors') or 0)
            and len(summary['workers']) == vu and all(x['samples'] == iterations for x in summary['workers']))
        history_ok = history_after-history_before == requests if keyword else history_after == history_before
        row = {'script': path.name, 'domain': path.parent.name, 'scenario': LABELS[path.stem],
            'phase': phase, 'vusers': vu, 'iterationsPerVu': iterations, 'testId': test_id,
            'status': state['status']['name'], 'scriptRevision': state.get('scriptRevision'),
            'plannedRequests': vu*iterations, 'requests': requests, 'successes': state.get('tests') or 0,
            'errors': state.get('errors') or 0, 'errorRatePct': round(100*(state.get('errors') or 0)/requests, 3) if requests else None,
            'tps': state.get('tps'), 'controllerMeanMs': state.get('meanTestTime'),
            'startTime': state.get('startTime'), 'finishTime': state.get('finishTime'),
            'historyDelta': history_after-history_before, 'accountingPassed': accounting, 'historyPassed': history_ok,
            **summary}
        row['result'] = 'PASS' if state['status']['name'] == 'FINISHED' and accounting and history_ok and row['errors'] == 0 else 'FAIL'
        self.rows.append(row)
        save(directory / 'summary.json', row)
        self.report()
        print(f"END {label} id={test_id} {row['result']} requests={requests} errors={row['errors']} TPS={row['tps']} mean={row['meanMs']} p95={row['p95Ms']} sampleSpan={row['sampleSpanSeconds']}s", flush=True)
        time.sleep(5)
        return row['result'] == 'PASS'

    def report(self):
        save(self.out / 'summary.json', self.rows)
        fields = ['domain','scenario','script','phase','vusers','iterationsPerVu','testId','status','plannedRequests','requests','successes','errors','errorRatePct','tps','meanMs','p95Ms','allRequestP95Ms','controllerMeanMs','samples','sampleErrors','sampleSpanSeconds','accountingPassed','historyDelta','historyPassed','result']
        with (self.out / 'summary.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
            writer.writeheader(); writer.writerows(self.rows)
        loads = [x for x in self.rows if x['phase'] == 'load']
        completed = len({x['script'] for x in loads})
        def pair(rows, field):
            return ' / '.join('—' if row is None or row.get(field) is None else f'{row[field]:,.2f}' for row in rows)
        lines = ['# 전체 조회 API 부하 테스트 — 2026-10-04', '',
            f"- 진행: {completed}/17개 API 부하 측정, {len(loads)}회 완료. 갱신: {now()}.",
            '- 환경: 로컬 Java21·test/H2 seed1000, 게시글 1,002건, nGrinder 3.5.9-p1. Agent 1개·process 1개, 계정 30명 분리, SQL 로그 OFF.',
            '- 각 API 1 VU·20회 사전 검증/워밍업 후 10 VU·30 VU를 순차 실행. 부하 단계당 VU별 100회(총 1,000/3,000회), 단계 사이 5초 휴식.',
            '- 아래 두 값의 순서는 **10 VU / 30 VU**. 평균·p95는 성공 GET 개별 CSV, TPS는 Controller 완료 집계. p95는 nearest-rank 방식.',
            '', '| 도메인 | API | 요청 수 | TPS | 평균 ms | p95 ms | 오류율 % | 판정 |',
            '|---|---|---:|---:|---:|---:|---:|---|']
        for path in self.paths:
            rows = [next((x for x in loads if x['script'] == path.name and x['vusers'] == vu), None) for vu in self.args.vus]
            verdict = ' / '.join(x['result'] if x else '대기/미실행' for x in rows)
            lines.append(f"| {path.parent.name} | {LABELS[path.stem]} | {pair(rows,'requests')} | {pair(rows,'tps')} | {pair(rows,'meanMs')} | {pair(rows,'p95Ms')} | {pair(rows,'errorRatePct')} | {verdict} |")
        lines += ['', '## 판정과 해석', '',
            '- PASS: FINISHED, 예정 요청 수와 CSV·Controller 성공/오류 수 일치, worker별 표본 수 일치, 오류 0건, 검색 이력 증분 일치. 지연 SLO는 정하지 않았으므로 성능 목표 충족을 뜻하지 않는다.',
            '- 실패 시 해당 API의 상위 부하는 생략하고 다음 API를 진행한다. 실패 실행도 표와 원본에 보존한다.',
            '- 전체 기능의 첫 탐색 측정이다. API별 1회 실행이며 빠른 API는 관측 구간이 짧다. 같은 Windows 호스트에 서버·Agent가 있어 운영 처리 용량이나 PostgreSQL 성능으로 해석하지 않는다.',
            '- 게시글 목록은 설정의 익명 기본 목록, 검색은 인증 빈번 검색 1개 프로필만 대표 측정했다. 목록·검색의 17개 세부 필터 프로필, SSE/WebSocket·업로드·쓰기 API는 이번 범위에 포함하지 않는다.',
            '- 상세 게시글은 조회수 UPDATE, 채팅 상세는 읽음 처리, 인증 검색은 검색 이력 INSERT가 포함된다. 상세 fixture는 계정별로 분리했고 채팅은 읽음 상태가 워밍업 후 유지된다. 검색 이력은 실행 순서대로 누적된다.',
            '', '## 기록', '',
            '- [전체 실행 표(CSV)](./summary.csv): 사전 검증과 부하 단계의 정확한 요청 수·관측 구간·Controller ID.',
            '- [환경·fixture](./environment.json), [배포 리비전](./execution/deployment.json), [정리 확인](./cleanup.json).',
            '- `raw/<단계-스크립트-VU>/`: Controller 원본, 요약, worker별 개별 요청 CSV. `execution/`: 실행기·토큰 없는 배포본.']
        (self.out / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    def cleanup(self):
        cleanup = {'timeKst': now(), 'controllerRestored': [], 'agentTemporaryFilesRemoved': [], 'errors': []}
        if self.active_id:
            try:
                self.api('/perftest/api/' + str(self.active_id) + '?action=stop', method='PUT')
                for _ in range(60):
                    if self.api('/perftest/api/status')['runningTestsCount'] == 0: break
                    time.sleep(1)
            except Exception as error: cleanup['errors'].append('active test stop: ' + type(error).__name__)
        for path, original in reversed(list(self.originals.items())):
            try:
                entry = {key: original.get(key) for key in ['path', 'fileType', 'content', 'description', 'encoding']}
                self.api('/script/api/save/' + path, method='POST', data={'fileEntry': entry,
                    'targetHosts': 'host.docker.internal', 'validated': '0', 'createLibAndResource': False})
                restored = self.api('/script/api/detail/' + path)['file']
                if restored['content'] != original['content']: raise RuntimeError('Restore mismatch')
                cleanup['controllerRestored'].append({'path': path, 'revision': restored['revision'], 'sha256': sha(restored['content'])})
            except Exception as error: cleanup['errors'].append(path + ': ' + type(error).__name__)
        for agent in self.agents:
            try:
                command('docker', 'exec', agent, 'rm', '-rf', ROOT)
                probe = subprocess.run(['docker', 'exec', agent, 'test', '-e', ROOT], capture_output=True)
                if probe.returncode != 1: raise RuntimeError('Temporary files remain')
                cleanup['agentTemporaryFilesRemoved'].append(agent)
            except Exception as error: cleanup['errors'].append(agent + ': ' + type(error).__name__)
        cleanup['controllerStatus'] = self.api('/perftest/api/status')
        save(self.out / 'cleanup.json', cleanup)
        print('CLEANUP ' + json.dumps({'restored': len(cleanup['controllerRestored']), 'agents': len(cleanup['agentTemporaryFilesRemoved']), 'errors': cleanup['errors']}), flush=True)

    def execute(self):
        try:
            self.prepare()
            for path in self.paths:
                if not self.run(path, 'smoke-warmup', 1, 20):
                    print('SKIP LOAD after smoke failure: ' + path.name, flush=True)
                    continue
                for vu in self.args.vus:
                    if not self.run(path, 'load', vu, self.args.iterations):
                        print('SKIP HIGHER LOAD after failed stage: ' + path.name, flush=True)
                        break
            self.environment['finishedAtKst'] = now()
            save(self.out / 'environment.json', self.environment)
        finally:
            self.cleanup()
            self.report()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jar', type=Path, required=True)
    parser.add_argument('--vus', type=int, nargs='+', default=[10,30])
    parser.add_argument('--iterations', type=int, default=100)
    args = parser.parse_args()
    Survey(args).execute()
