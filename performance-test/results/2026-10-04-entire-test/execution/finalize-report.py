"""Verify persisted individual samples and render the concise final survey report."""
import csv
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

root = Path(sys.argv[1]).resolve()
kst = timezone(timedelta(hours=9))
rows = json.loads((root / 'summary.json').read_text(encoding='utf-8'))
environment = json.loads((root / 'environment.json').read_text(encoding='utf-8'))
loads = [x for x in rows if x['phase'] == 'load']
smokes = [x for x in rows if x['phase'] == 'smoke-warmup']
expected_coverage = {(x['script'],vu) for x in smokes for vu in [10,30]}
actual_coverage = {(x['script'],x['vusers']) for x in loads}
if len(smokes) != 17 or actual_coverage != expected_coverage:
    raise RuntimeError('Entire 17-script / 10-and-30-VU survey is incomplete')
checks = []
failure_types = []
for row in rows:
    folder = root / 'raw' / f"{row['phase']}-{Path(row['script']).stem}-vu{row['vusers']}"
    files = list((folder / 'samples').glob('*.csv'))
    samples = []
    worker_counts = []
    for path in files:
        with path.open(encoding='utf-8', newline='') as stream:
            worker = list(csv.DictReader(stream))
        worker_counts.append(len(worker))
        samples.extend(worker)
    successes = [float(x['elapsedMs']) for x in samples if x['success'].lower() == 'true']
    p95 = sorted(successes)[math.ceil(.95 * len(successes))-1] if successes else None
    controller_accounting = len(samples) == row['requests'] and len(samples)-len(successes) == row['errors']
    valid = (len(samples) == row['samples'] and
        len(samples)-len(successes) == row['sampleErrors'] and
        (p95 is None and row['p95Ms'] is None or p95 is not None and abs(round(p95, 3)-row['p95Ms']) < .001) and
        (not successes and row['meanMs'] is None or successes and abs(round(statistics.mean(successes), 3)-row['meanMs']) < .001))
    if row['result'] == 'PASS':
        valid = valid and len(files) == row['vusers'] and all(n == row['iterationsPerVu'] for n in worker_counts)
        valid = valid and all(x['httpStatus'] == '200' for x in samples)
    if row['status'] == 'FINISHED': valid = valid and controller_accounting
    checks.append({'testId': row['testId'], 'script': row['script'], 'phase': row['phase'],
        'sampleFiles': len(files), 'samples': len(samples), 'controllerAccounting': controller_accounting, 'metricsRecalculated': valid})
    row['sampleErrorRatePct'] = 100 * row['sampleErrors'] / row['samples'] if row['samples'] else None
    failed = [x for x in samples if x['success'].lower() != 'true']
    if failed:
        failure_types.append({'testId': row['testId'], 'scenario': row['scenario'], 'vusers': row['vusers'],
            'failures': dict(Counter(x.get('failureRoot') or x.get('failure') or 'unknown' for x in failed))})
if not all(x['metricsRecalculated'] for x in checks):
    raise RuntimeError('Persisted raw sample verification failed')

old_environment = root.parents[0] / '2026-09-30-roommate-board-list-smoke/run-20260930-213025/environment.json'
old = json.loads(old_environment.read_text(encoding='utf-8'))
environment['backendCheckoutCommit'] = environment.pop('backendCommit', environment.get('backendCheckoutCommit'))
if old['jarSha256'].lower() != environment['jarSha256'].lower():
    raise RuntimeError('JAR artifact attribution changed; check provenance manually')
environment['backendArtifactCommit'] = old['backendCommit']
environment['backendArtifactEvidence'] = str(old_environment)
environment['backendJarRebuiltForSurvey'] = False
jar = Path(environment['jarPath'])
environment['backendArtifactModifiedAtKst'] = datetime.fromtimestamp(jar.stat().st_mtime, kst).isoformat()
(root / 'environment.json').write_text(json.dumps(environment, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
(root / 'summary.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
fields = ['domain','scenario','script','phase','vusers','iterationsPerVu','testId','status','plannedRequests','samples','sampleErrors','sampleErrorRatePct','tps','meanMs','p95Ms','allRequestP95Ms','requests','errors','errorRatePct','controllerMeanMs','sampleSpanSeconds','accountingPassed','historyDelta','historyPassed','result']
with (root / 'summary.csv').open('w', encoding='utf-8-sig', newline='') as stream:
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
    writer.writeheader(); writer.writerows(rows)

verification = {'verifiedAtKst': datetime.now(kst).isoformat(), 'runs': len(rows),
    'loadRuns': len(loads), 'smokeRuns': len(smokes), 'scenarios': len({x['script'] for x in smokes}),
    'requests': sum(x['samples'] for x in rows), 'loadRequests': sum(x['samples'] for x in loads),
    'errors': sum(x['sampleErrors'] for x in rows), 'controllerRequests': sum(x['requests'] for x in rows),
    'controllerErrors': sum(x['errors'] for x in rows), 'allMetricsVerified': True,
    'entireScriptCoverage': True, 'failureTypes': failure_types, 'checks': checks}
(root / 'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def number(value, digits=2):
    return '—' if value is None else f'{value:,.{digits}f}'

def pair(group, field):
    return ' / '.join(number(x.get(field) if x else None, 0 if field in ('requests','samples') else 2) for x in group)

start = datetime.fromtimestamp(min(x['startTime'] for x in rows)/1000, kst)
end = datetime.fromtimestamp(max(x['finishTime'] for x in rows)/1000, kst)
passed = sum(x['result'] == 'PASS' for x in loads)
smoke_passed = sum(x['result'] == 'PASS' for x in smokes)
lines = ['# 전체 조회 API 부하 테스트 — 2026-10-04', '',
    f"**조회 스크립트 {len(smokes)}개 사전 검증 {smoke_passed}/{len(smokes)} 통과, 부하 {len(loads)}회 중 {passed}회 통과. 총 요청 {verification['requests']:,}건, 오류 {verification['errors']:,}건.**", '',
    f"- 측정: {start:%Y-%m-%d %H:%M:%S}~{end:%H:%M:%S} KST.",
    '- 환경: 로컬 Java 21·test/H2 seed1000, 회원 2,004명·게시글 1,002건. nGrinder Controller/Agent 3.5.9-p1.',
    '- API별 1 VU·20회 사전 검증/워밍업 → 10 VU·1,000회 → 30 VU·3,000회. Agent 1개·process 1개, VU별 계정·상세 fixture 분리, 단계 사이 5초 휴식.',
    '- HTTP connect/socket timeout 설정값 5/15초, connectionReset=false, ramp-up=false, SQL 로그 OFF. 실제 타임아웃 경과 시간은 아래 관찰과 함께 확인한다.',
    '- 표의 두 값은 **10 VU / 30 VU** 순서다. 요청 수·오류율·평균·p95는 개별 CSV, TPS는 Controller 집계다. 평균·p95는 성공 GET 기준이다.', '',
    '| 도메인 | API | 요청 수 | TPS | 평균 ms | p95 ms | 오류율 % | 판정 |',
    '|---|---|---:|---:|---:|---:|---:|---|']
for smoke in smokes:
    group = [next((x for x in loads if x['script'] == smoke['script'] and x['vusers'] == vu), None) for vu in [10,30]]
    verdict = ' / '.join(x['result'] if x else '미실행' for x in group)
    lines.append(f"| {smoke['domain']} | {smoke['scenario']} | {pair(group,'samples')} | {pair(group,'tps')} | {pair(group,'meanMs')} | {pair(group,'p95Ms')} | {pair(group,'sampleErrorRatePct')} | {verdict} |")

lines += ['', '## 주요 관찰', '']
for row in loads:
    if row['errors']:
        failures = next(x['failures'] for x in failure_types if x['testId'] == row['testId'])
        detail = ', '.join(f'{name} {count}건' for name,count in failures.items())
        lines.append(f"- **{row['scenario']} {row['vusers']} VU 실패:** CSV {row['samples']:,}건 중 오류 {row['sampleErrors']}건({row['sampleErrorRatePct']:.2f}%). 원본 오류 유형: {detail}.")
for row in loads:
    if row['status'] != 'FINISHED':
        lines.append(f"- {row['scenario']} {row['vusers']} VU는 `{row['status']}`로 중단됐다. Controller는 {row['requests']:,}건/오류 {row['errors']}건, CSV는 {row['samples']:,}건/오류 {row['sampleErrors']}건이다. 종료 시 집계 꼬리 차이를 보존했으며 표는 CSV 기준이다. 예정 {row['plannedRequests']:,}건을 완료한 시험으로 판정하지 않는다.")
recovery = root / 'execution/backend-recovery.json'
if recovery.exists():
    lines.append('- 추천 목록에서 JDBC 연결 획득 30초 타임아웃과 건강 확인 응답 실패를 확인했다. 같은 JAR·H2 seed1000으로 재기동 후 남은 12개 API를 20회씩 재워밍업하고 측정했다.')
timeout_observation = root / 'raw/timeout-observation.json'
if timeout_observation.exists():
    observed = json.loads(timeout_observation.read_text(encoding='utf-8'))
    lines.append(f"- 검색 타임아웃은 실제 {observed['failureElapsedMinMs']/1000:.2f}~{observed['failureElapsedMaxMs']/1000:.2f}초에 발생했다. 소켓 설정값 15초와 구분해 기록했다.")
ranked = sorted([x for x in loads if x['vusers'] == 30 and x.get('p95Ms') is not None], key=lambda x:x['p95Ms'], reverse=True)
lines.append('- 지연 점검 우선 대상(30 VU 성공 p95): ' + ' → '.join(f"{x['scenario']} {x['p95Ms']:,.0f}ms" for x in ranked[:3]) + '.')
observation_path = root / 'raw/observations.jsonl'
if observation_path.exists():
    observations = [json.loads(x) for x in observation_path.read_text(encoding='utf-8-sig').splitlines() if x]
    if any(any('hikaricp_connections_pending' in m and m.rstrip().endswith('20.0') for m in x['metrics']) for x in observations):
        lines.append('- 인증 검색 30 VU에서 Hikari 연결 10개 사용·20개 대기를 관측했다. 쿼리 비용 등 근본 원인은 별도 분석 대상이다.')
shortest = min(x['sampleSpanSeconds'] for x in loads)
longest = max(x['sampleSpanSeconds'] for x in loads)
lines += ['', '## 판정·측정 범위', '',
    '- PASS는 실행 완료·예정 요청 수 일치·worker별 CSV/Controller 성공·오류 수 일치·오류 0건·검색 이력 증분 일치를 뜻한다. 지연 SLO는 정하지 않았으므로 성능 목표 충족을 뜻하지 않는다.',
    f'- API마다 각 부하를 1회 실행한 탐색 시험이다. 실제 요청 관측 구간은 {shortest:.2f}~{longest:.2f}초이며 빠른 API는 짧다. CSV의 `sampleSpanSeconds`로 각 구간을 확인한다. 워밍업 이후 새 worker의 초기 연결 비용도 본 측정에 포함된다.',
    '- 서버·Agent가 같은 호스트에서 실행된다. H2 결과를 운영 PostgreSQL의 처리 용량으로 해석하지 않는다. 우선 대상 API를 같은 조건에서 더 긴 구간·반복 실행으로 재측정하는 데 사용한다.',
    '- 목록은 익명 기본 목록, 검색은 인증 빈번 검색 프로필을 대표 측정했다. 목록·검색의 모든 필터 조합, SSE/WebSocket·이미지 업로드·쓰기 API는 이번 스크립트 범위에 포함하지 않는다.',
    '- 게시글 상세는 조회수 UPDATE, 채팅 상세는 읽음 처리, 인증 검색은 검색 이력 INSERT가 포함된다. 계정별 상세 fixture를 분리했고 채팅은 워밍업 후 읽음 상태를 유지했다. 검색 이력은 순서대로 누적했다.',
    '- **빌드 기준:** 2026-09-30 시험 JAR(`9dbc583`)을 재사용했다. SHA256이 당시 시험 기록과 일치한다. 현재 checkout(`355bff4`, 실행 시간 Aspect 추가)과 구분하며 현재 소스를 새로 빌드한 결과는 아니다.',
    '', '## 기록 관리', '',
    '- 일상 확인은 이 레포트와 [summary.csv](./summary.csv)로 한다. CSV에는 사전 검증, 실행 ID, 정확한 요청 수, 관측 구간이 있다.',
    '- [환경·fixture](./environment.json), [원본 재검산](./verification.json), [복원·정리](./cleanup.json). 토큰과 서명 키는 결과에 저장하지 않았다.',
    '- `raw/<단계-스크립트-VU>/`: Controller 원본 JSON·worker별 요청 CSV. `execution/`: 실행기·토큰 없는 시험 배포본·리비전.']
(root / 'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
print(json.dumps({k:v for k,v in verification.items() if k != 'checks'}, ensure_ascii=False))
