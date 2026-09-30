"""Summarize fixture and repeated local baseline measurements with resource evidence."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import re
from statistics import median


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def metric(row, name, labels=None):
    values = []
    for line in row.get('metrics', []):
        match = re.match(r'^' + re.escape(name) + r'(\{[^}]*\})?\s+([-+0-9.eE]+)$', line)
        if match and (not labels or all(label in (match.group(1) or '') for label in labels)):
            values.append(float(match.group(2)))
    return sum(values) if values else None


def describe(values):
    values = [value for value in values if value is not None]
    return {'median': median(values), 'min': min(values), 'max': max(values)} if values else None


def resources(case, telemetry):
    start = case.get('startTime'); end = case.get('finishTime')
    if not start or not end: return {'points': 0}
    points = [row for row in telemetry if start <= row['epochMs'] <= end]
    before = [row for row in telemetry if row['epochMs'] <= start and row.get('metrics')]
    after = [row for row in telemetry if row['epochMs'] >= end and row.get('metrics')]
    def delta(name):
        if not before or not after: return None
        a = metric(after[0], name); b = metric(before[-1], name)
        return a-b if a is not None and b is not None else None
    containers = defaultdict(list)
    for point in points:
        for raw in point.get('containers', []):
            row = json.loads(raw)
            containers[row['Name']].append(float(row['CPUPerc'].rstrip('%')))
    return {'points': len(points),
        'systemCpuPercent': describe([value*100 if (value:=metric(row,'system_cpu_usage')) is not None else None for row in points]),
        'backendCpuPercent': describe([value*100 if (value:=metric(row,'process_cpu_usage')) is not None else None for row in points]),
        'heapMiB': describe([value/1024**2 if (value:=metric(row,'jvm_memory_used_bytes',['area="heap"'])) is not None else None for row in points]),
        'hikariActive': describe([metric(row,'hikaricp_connections_active') for row in points]),
        'hikariPending': describe([metric(row,'hikaricp_connections_pending') for row in points]),
        'hikariTimeoutDelta': delta('hikaricp_connections_timeout_total'),
        'gcPauseSecondsDeltaApprox': delta('jvm_gc_pause_seconds_sum'),
        'gcPauseCountDeltaApprox': delta('jvm_gc_pause_seconds_count'),
        'hikariAcquireSecondsDeltaApprox': delta('hikaricp_connections_acquire_seconds_sum'),
        'containerCpuPercent': {name: describe(values) for name,values in containers.items()},
        'scrapeElapsedMs': describe([row.get('scrapeElapsedMs') for row in points])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args(); directory=args.directory.resolve()
    cases=json.loads((directory/'suite-summary.json').read_text(encoding='utf-8'))
    telemetry=[json.loads(line) for line in (directory/'telemetry.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    excluded=[row for row in cases if row['phase']=='baseline' and row.get('excludedFromBaseline')]
    baseline=[row for row in cases if row['phase']=='baseline' and not row.get('excludedFromBaseline')]
    groups=defaultdict(list)
    for row in baseline:
        row['resources']=resources(row,telemetry)
        groups[(row['profile'],row['vu'])].append(row)
    aggregated=[]
    for (profile,vu),rows in sorted(groups.items()):
        passed=[row for row in rows if row['passed']]
        aggregated.append({'profile':profile,'vu':vu,'completedRepetitions':len(rows),'passedRepetitions':len(passed),
            'requests':sum(row.get('sampleRequests',0) for row in rows),'successes':sum(row['successes'] for row in rows),
            'errors':sum(row['errors'] for row in rows),'historyDelta':sum(row['historyDelta'] for row in rows),
            'meanMs':describe([row.get('meanMs') for row in passed]),'p95Ms':describe([row.get('p95Ms') for row in passed]),
            'p99Ms':describe([row.get('p99Ms') for row in passed]),'controllerTps':describe([row.get('controllerTps') for row in passed]),
            'testIds':[row['testId'] for row in rows]})
    save(directory/'baseline-analysis.json',{'groups':aggregated,'runs':baseline,'excludedHarnessRuns':excluded,
        'telemetryPoints':len(telemetry),'telemetryErrors':sum(bool(row.get('errorType')) for row in telemetry),
        'notes':['Resources use roughly 10s polling plus scrape/docker-stats overhead; missed peaks are possible.',
            'GC/acquire counter deltas use nearest outside points and can include a few seconds before/after a run.',
            'Each successful run has individual request quantiles. Repetition median/range is not a pooled percentile.',
            'This is exploration. Three short repetitions do not certify SLO, safe capacity or production performance.']})
    fields=['phase','profile','vu','repeat','testId','status','successes','errors','sampleRequests','sampleComplete','meanMs','p95Ms','p99Ms','controllerTps','historyDelta','expectedHistoryDelta','passed','excludedFromBaseline','excludedReason']
    with (directory/'summary.csv').open('w',encoding='utf-8',newline='') as target:
        writer=csv.DictWriter(target,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(cases)
    def show(value):return '—' if value is None else f'{value:.2f}'
    def range_text(value):
        return '—' if not value else f"{show(value['median'])} ({show(value['min'])}~{show(value['max'])})"
    spans=defaultdict(list)
    for row in baseline:
        sample=json.loads((directory/row['label']/'request-samples/request-summary.json').read_text(encoding='utf-8'))
        spans[row['profile']].append(sample['sampleSpanSeconds'])
    lines=['# 게시글 목록·검색 탐색 기준선','',
        '필터·페이지·검색 fixture를 실제 Agent에서 검증하고, 워밍업과 본 측정을 분리했다. 아래 결과는 현재 로컬 H2 환경의 탐색 기준선이다. 애플리케이션 성능 로직은 변경하지 않았다.','',
        f"유효 본 측정 {len(baseline)}회에서 성공 {sum(row['successes'] for row in baseline):,}건·오류 {sum(row['errors'] for row in baseline)}건이며 검색 이력 증가 {sum(row['historyDelta'] for row in baseline):,}건을 요청 수와 대조했다. 초기 worker 경쟁 조건 시험은 이 합계에서 제외한다.",'',
        '## 조건과 fixture','',
        '- 이전 smoke와 동일 JAR SHA256, Java 21, `test`/H2, 시드 1,000건(게시글 1,002건), SQL 로그 비활성화, timeout 5초다. nGrinder Agent Java 11·`3.5.9-p1`을 사용한다.',
        '- Controller/Agent와 백엔드가 같은 Windows 호스트의 자원을 공유한다. 다른 작업의 호스트 부하를 완전히 통제하지 못했으므로 운영 환경 성능으로 외삽하지 않는다.',
        '- 지역/방 유형 fixture는 DB에서 조회했다. 전체 17개 프로필에 DB 기반 기대 count를 넣었다. 관심 시드 회원 3은 전체 부하 데이터 회원과 차단 관계여서 양성 fixture로 사용할 수 없었다. 시험 DB에 회원 2/게시글 3의 관심 관계 한 건을 추가했고, 토큰 풀에서 회원 3을 제외했다. 모든 반복에서 같은 관계를 유지했다.',
        '- 검색 이력은 초기 1,005건을 보존하고 각 시험에서 신규 생성한 시험 회원의 행만 정리했다. 각 회차의 시작 행 수/분포는 동일하다. identity sequence와 DB 내부 물리 상태를 재생성하지는 않았다.',
        '- fixture는 각각 1 VU×3회, 워밍업은 주 경로별 1 VU×30회, 본 측정은 1→3→5 VU×회원별 100회×3반복 계획이다. 요청 오류·계약 오류·표본 누락·검색 저장 증분 불일치 시 남은 반복과 상위 단계는 중단한다. 워밍업/fixture는 기준선 집계에서 제외한다.',
        '- 매 실행마다 Agent worker를 새로 생성한다. 별도 워밍업은 서버/JIT 워밍업이며 첫 클라이언트 연결 비용은 본 요청에 포함될 수 있다.',
        '- 최초 3 VU 시험 318은 worker의 출력 폴더 동시 생성 경쟁 조건으로 1개 worker만 동작했다. 원본을 보존하고 정상 기준선에서 제외했다. `Files.createDirectories`로 수정 후 두 경로를 3 VU×3회(각 9건)로 검증하고 3→5 VU 측정을 재개했다. 변경은 HTTP 실행/검증/측정 구간 밖의 worker 초기화에 한정되므로 완료된 1 VU 기준선은 유지했다. [원인과 판정](./harness-diagnosis.json), [당시 worker/Controller 증거](./baseline-list-anonymous-vu3-r1/controller-artifacts/).',
        '', '## 프로필 검증','', '| 프로필 | 기대 count | 성공/오류 | 검색 이력 Δ | 판정 |','|---|---:|---:|---:|---|']
    fixture=json.loads((directory/'fixture-snapshot.json').read_text(encoding='utf-8'))
    for row in cases:
        if row['phase']=='fixture':lines.append(f"| {row['profile']} | {fixture['expectedCounts'][row['profile']]} | {row['successes']}/{row['errors']} | {row['historyDelta']} | {'통과' if row['passed'] else '실패'} |")
    lines+=['','## 반복 측정','',
        '평균/p95/p99/TPS는 **성공한 반복별 값의 중앙값(최소~최대)**다. 실패 실행을 제외한 숫자가 전체 정상 성능을 뜻하지 않으므로 완료/통과 회수와 오류를 함께 확인한다.','',
        '| 프로필 | VU | 완료/통과 반복 | 성공/오류 | 평균 ms | p95 ms | p99 ms | Controller TPS | 검색 이력 Δ |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in aggregated:
        lines.append(f"| {row['profile']} | {row['vu']} | {row['completedRepetitions']}/{row['passedRepetitions']} | {row['successes']}/{row['errors']} | {range_text(row['meanMs'])} | {range_text(row['p95Ms'])} | {range_text(row['p99Ms'])} | {range_text(row['controllerTps'])} | {row['historyDelta']} |")
    stop_path=directory/'stop-reason.json'
    lines+=['','중단: ' + (json.loads(stop_path.read_text(encoding='utf-8'))['case'] if stop_path.exists() else '시험한 모든 예정 단계 완료') + '.','',
        '## 실행별 자원 관측','',
        'CPU는 해당 구간 표본의 최대값, GC는 경계 밖 인접 표본 사이의 근사 증가량이다. 10초 간격에 scrape/stats 시간이 추가돼 순간 peak를 놓칠 수 있다. Docker CPU는 코어 기준 합산 비율이므로 JVM/system CPU와 수치 기준이 다르다.','',
        '| ID | 프로필/VU/회차 | 호스트 CPU max % | JVM CPU max % | Hikari active/pending max | GC pause 근사 초 | 오류 |','|---:|---|---:|---:|---:|---:|---:|']
    for row in baseline:
        resource=row['resources']
        maximum=lambda key: resource.get(key,{}).get('max') if resource.get(key) else None
        lines.append(f"| {row['testId']} | {row['profile']}/{row['vu']}/{row['repeat']} | {show(maximum('systemCpuPercent'))} | {show(maximum('backendCpuPercent'))} | {show(maximum('hikariActive'))}/{show(maximum('hikariPending'))} | {show(resource.get('gcPauseSecondsDeltaApprox'))} | {row['errors']} |")
    lines+=['','## 해석 범위와 다음 진단','',
        '- 1 VU 회당 100건은 안정된 p99 평가에 부족하다. 기본 경로와 인증 검색은 조회 결과 범위 및 인증 조건도 달라 두 숫자의 차이를 검색 INSERT 비용으로 단정할 수 없다.',
        '- 지연/처리량 포화가 관측되면 개별 content/count SQL과 실행계획을 별도 구간에서 수집하고, 익명 검색·키워드 없는 인증 조회 대조군을 동일 부하로 측정한다. H2 상관 서브쿼리·차단 조건·CPU/GC·Agent 자원 가설은 해당 증거와 대조한다.',
        '- 오류 구간은 `request-samples/`의 실패 유형과 worker 로그를 대조한다. timeout 뒤 DB commit이 가능하므로 성공 요청 수만으로 이력 저장 여부를 추정하지 않는다.',
        '- 정상 조건은 더 긴 정상 구간과 반복 표본으로 보강하고 실제 대상 DB의 고정 snapshot에서도 확인한 뒤 최적화 전후를 비교한다.',
        '', '## 원본과 재실행','',
        '- [환경](./environment.json), [측정 계획](./measurement-plan.json), [fixture snapshot](./fixture-snapshot.json), [fixture 설정](./fixture-config.json), [배포](./deployment.json).',
        '- [전체 실행 요약](./suite-summary.json), [CSV 요약](./summary.csv), [반복·자원 분석](./baseline-analysis.json), [자원 표본](./telemetry.jsonl).',
        '- 각 조건 폴더의 `deployed-config.json`, `created.json`, `test.json`, `basic-report.json`, `request-samples/`에 요청별 원본과 실제 Controller 설정을 보관한다. `backend.out.log`/`backend.err.log`는 시험 서버 로그다.',
        '- [측정 실행기](../../../tools/run-roommate-board-baseline.py), [이 집계기](../../../tools/summarize-roommate-board-baseline.py). 실행기는 전용 로컬 H2 seed1000 서버를 대상으로 하며 fixture INSERT·시험 이력 DELETE를 수행한다. 기존 운영 DB/외부 대상에서는 사용하지 않는다.',
        '- [정리 확인](./cleanup.json)에 Agent 임시 토큰 파일 삭제·Controller 설정 템플릿 복원을 기록한다. 직접 기동한 백엔드 종료 시각은 환경 기록에 추가한다.','']
    observations=['반복 편차가 커 최적화 전후 비교의 확정 기준선으로는 추가 보강이 필요하다.']
    for row in aggregated:
        if row['vu']==5 and row['controllerTps']:
            value=row['controllerTps']
            observations.append(f"- {row['profile']}의 5 VU TPS 범위는 {value['min']:.2f}~{value['max']:.2f}다. 실행 편차를 숨기고 중앙값만 확정 성능으로 사용하지 않는다.")
    for profile,values in spans.items():
        observations.append(f'- {profile}의 실제 GET 표본 구간은 {min(values):.2f}~{max(values):.2f}초다. 짧은 기본 목록 시험은 자원 표본이 0~1개여서 자원과 지연의 연관성을 충분히 평가할 수 없다.')
    system=[row['resources']['systemCpuPercent']['max'] for row in baseline if row['resources'].get('systemCpuPercent')]
    pending=[row['resources']['hikariPending']['max'] for row in baseline if row['resources'].get('hikariPending')]
    if system and pending:
        observations.append(f'- 관측 호스트 CPU 최대 {max(system):.2f}%, Hikari pending 최대 {max(pending):.0f}이다. 순간값 누락과 공유 호스트 영향이 있어 특정 SQL·검색 INSERT·CPU 중 하나를 원인으로 확정하지 않는다.')
    position=lines.index('## 해석 범위와 다음 진단')+2
    lines[position:position]=observations+['']
    (directory/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    print('Baseline groups:',len(aggregated),'runs:',len(baseline),'errors:',sum(row['errors'] for row in baseline),'telemetry points:',len(telemetry))


if __name__=='__main__':main()
