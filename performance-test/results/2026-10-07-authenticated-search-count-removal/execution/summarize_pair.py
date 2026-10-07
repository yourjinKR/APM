from pathlib import Path
import csv
from datetime import datetime, timedelta, timezone
import json
import re
import shutil
from statistics import median

OUT=Path(r'C:\dev\workspace\prography\APM\performance-test\results\2026-10-07-authenticated-search-count-removal')
VARIANTS=['before-count','after-slice']
def read(path):
    return json.loads(path.read_text('utf-8-sig'))
def save(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def fmt(value):
    return '—' if value is None else f'{value:,.2f}'
rows=[]
grouped={}
verdict={'verifiedAtKst':datetime.now(timezone(timedelta(hours=9))).isoformat(),'variants':{},'allPassed':True}
for variant in VARIANTS:
    directory=OUT/'controlled-ab'/variant
    cases=read(directory/'suite-summary.json')
    loads=[row for row in cases if row['phase']=='load']
    cleanup=read(directory/'cleanup.json')
    sql=read(directory/'sql-diagnostics/summary.json')
    expected_count=10 if variant=='before-count' else 0
    if sql['requests']!=10 or sql['contentExecutions']!=10 or sql['boardCountExecutions']!=expected_count:
        raise RuntimeError('SQL execution evidence mismatch')
    if not cleanup['ownedBackendStopped'] or not cleanup['controllerIdle'] or not all(cleanup['controllerRestored'].values()) or not all(cleanup['tokensRemoved'].values()):
        raise RuntimeError('Measurement resources not fully cleaned up')
    for row in cases:
        csv_files=list((directory/'raw'/row['label']/'request-samples').glob('*.csv'))
        samples=[]
        for path in csv_files:
            with path.open(encoding='utf-8-sig',newline='') as stream:
                samples.extend(csv.DictReader(stream))
        success=sum(sample['success']=='true' for sample in samples)
        if len(samples)!=row['requests'] or success!=row['successes'] or len(samples)-success!=row['errors']:
            raise RuntimeError('Raw CSV accounting mismatch: '+row['label'])
        if len(csv_files)!=row['vu']:
            raise RuntimeError('Worker CSV count mismatch')
        rows.append({'variant':variant,**row})
    grouped[variant]={}
    for vu in [10,30]:
        runs=[row for row in loads if row['vu']==vu]
        if not runs:
            continue
        grouped[variant][vu]={
            'repetitions':len(runs),'requests':sum(row['requests'] for row in runs),
            'errors':sum(row['errors'] for row in runs),
            'errorRatePercent':100*sum(row['errors'] for row in runs)/sum(row['requests'] for row in runs),
            'meanMsMedian':median(row['meanMs'] for row in runs),
            'p95MsMedian':median(row['p95Ms'] for row in runs),
            'p99MsMedian':median(row['p99Ms'] for row in runs),
            'controllerTpsMedian':median(row['controllerTps'] for row in runs),
            'meanMsRange':[min(row['meanMs'] for row in runs),max(row['meanMs'] for row in runs)],
            'p95MsRange':[min(row['p95Ms'] for row in runs),max(row['p95Ms'] for row in runs)],
            'sampleSpanSecondsRange':[min(row['sampleSpanSeconds'] for row in runs),max(row['sampleSpanSeconds'] for row in runs)],
            'historyDelta':sum(row['memberKeywordHistoryDelta'] for row in runs),
            'testIds':[row['testId'] for row in runs],
            'accountingPassed':all(row['accountingPassed'] for row in runs)}
    verdict['variants'][variant]={'measuredLoadRuns':len(loads),'fullThreeRepeats':len(loads)==6,
        'plannedLoadRequests':12000,'actualLoadRequests':sum(row['requests'] for row in loads),
        'errors':sum(row['errors'] for row in loads),'allStrictAccountingPassed':all(row['accountingPassed'] for row in loads),
        'allRequestCsvAccountingPassed':all(row['sampleComplete'] and row['status']=='FINISHED'
            and row['requests']==row['expectedRequests']==row['controllerSuccesses']+row['controllerErrors']
            and row['successes']==row['controllerSuccesses'] and row['errors']==row['controllerErrors'] for row in loads),
        'allHistoryEqualsPlanned':all(row['historyDelta']==row['memberKeywordHistoryDelta']==row['expectedRequests'] for row in loads),
        'searchHistoryDelta':sum(row['memberKeywordHistoryDelta'] for row in loads),
        'contentExecutionsPer10Requests':sql['contentExecutions'],'countExecutionsPer10Requests':sql['boardCountExecutions'],
        'cleanupVerified':True}
    verdict['allPassed']=verdict['allPassed'] and len(loads)==6 and all(row['passed'] for row in loads)
verdict['measurementComplete']=all(item['fullThreeRepeats'] and item['actualLoadRequests']==item['plannedLoadRequests']
    and item['allRequestCsvAccountingPassed'] and item['cleanupVerified'] for item in verdict['variants'].values())
verdict['allPassedMeaning']='Every planned load run completed with zero HTTP/transport errors; before-count timeout errors are retained as measured outcomes'
save(OUT/'verification.json',verdict)
before_env=read(OUT/'controlled-ab/before-count/environment.json')
after_env=read(OUT/'controlled-ab/after-slice/environment.json')
conditions=['actualCounts','memberIds','profile','keyword','query','agentCount','processes','vusers','requestsPerVu',
            'repetitions','cooldownSeconds','connectTimeoutMs','socketTimeoutMs','connectionReset','rampUp',
            'responseValidator','sqlLogging','javaOptions','defaultTieredCompilation','executionTimeAspectLogger','warmup']
differences={key:{'before':before_env[key],'after':after_env[key]} for key in conditions if before_env[key]!=after_env[key]}
if differences:
    raise RuntimeError('A/B runtime/data condition mismatch: '+str(list(differences)))
before_probe=read(OUT/'controlled-ab/before-count/preflight.json')
after_probe=read(OUT/'controlled-ab/after-slice/preflight.json')
if before_probe['firstIds']!=after_probe['firstIds']:
    raise RuntimeError('Page/Slice returned different first-page board IDs')
comparison=[]
for vu in [10,30]:
    if vu not in grouped['before-count'] or vu not in grouped['after-slice']:
        continue
    before=grouped['before-count'][vu]
    after=grouped['after-slice'][vu]
    comparison.append({'vu':vu,'before':before,'after':after,
        'meanReductionPercent':100*(1-after['meanMsMedian']/before['meanMsMedian']),
        'p95ReductionPercent':100*(1-after['p95MsMedian']/before['p95MsMedian']),
        'p99ReductionPercent':100*(1-after['p99MsMedian']/before['p99MsMedian']),
        'tpsIncreasePercent':100*(after['controllerTpsMedian']/before['controllerTpsMedian']-1)})
save(OUT/'comparison.json',{'comparisonBasis':'Same-code count/Page vs Slice, identical seeded DB/runtime; medians of per-run metrics',
    'conditionsMatched':conditions,'firstPageIdsMatched':True,'groups':comparison})
fields=['variant','phase','vu','repeat','testId','requests','successes','errors','errorRatePercent',
        'controllerTps','meanMs','p95Ms','p99Ms','sampleSpanSeconds','historyDelta','memberKeywordHistoryDelta','accountingPassed','passed']
with (OUT/'summary.csv').open('w',encoding='utf-8-sig',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
historical_root=OUT.parent/'2026-10-04-entire-test'
with (historical_root/'summary.csv').open(encoding='utf-8-sig',newline='') as stream:
    historical=[row for row in csv.DictReader(stream) if row['script']=='RoommateBoardListKeywordGetTest.groovy' and row['phase']=='load']
historical_compare=[]
for row in historical:
    vu=int(row['vusers'])
    if vu in grouped['after-slice']:
        after=grouped['after-slice'][vu]
        historical_compare.append({'vu':vu,'historicalTestId':int(row['testId']),
            'historicalMeanMs':float(row['meanMs']),'historicalP95Ms':float(row['p95Ms']),'historicalTps':float(row['tps']),
            'historicalErrorRatePercent':float(row['sampleErrorRatePct']),
            'currentMeanMsMedian':after['meanMsMedian'],'currentP95MsMedian':after['p95MsMedian'],'currentTpsMedian':after['controllerTpsMedian'],
            'meanReductionPercent':100*(1-after['meanMsMedian']/float(row['meanMs'])),
            'p95ReductionPercent':100*(1-after['p95MsMedian']/float(row['p95Ms'])),
            'tpsIncreasePercent':100*(after['controllerTpsMedian']/float(row['tps'])-1)})
save(OUT/'historical-comparison.json',{'causalComparison':False,'source':'../2026-10-04-entire-test/summary.csv',
    'reason':'Different date, backend artifact/version, heap/runtime, validation mode and warmup; reference only','groups':historical_compare})
metadata=read(OUT/'excluded-ide-preliminary/environment.json')
save(OUT/'environment.json',{'measurement':'Controlled count/Page vs Slice comparison',
    'startedAtKst':before_env['startedAtKst'],'finishedAtKst':after_env['finishedAtKst'],
    'backendCommit':metadata['backendCommit'],'apmCommit':metadata['apmCommit'],
    'sharedConditions':{key:before_env[key] for key in conditions},
    'variantEnvironments':{variant:f'controlled-ab/{variant}/environment.json' for variant in VARIANTS},
    'loadRequests':24000,'warmupRequests':1040,'sqlDiagnosticRequests':20,
    'artifactNote':'Temporary executable JARs were removed after measurement; source snapshots, patch, build logs and SHA-256 hashes are preserved'})
sql_before=read(OUT/'controlled-ab/before-count/sql-diagnostics/summary.json')
sql_after=read(OUT/'controlled-ab/after-slice/sql-diagnostics/summary.json')
sql_changes={'requestsPerVariant':10,
    'beforeContentMs':sum(row['totalMs'] for row in sql_before['statements'] if re.search(r'\bfrom roommate_board\b',row['sql'].lower()) and not re.match(r'select\s+count\(',row['sql'].lower())),
    'beforeCountMs':sum(row['totalMs'] for row in sql_before['statements'] if re.search(r'\bfrom roommate_board\b',row['sql'].lower()) and re.match(r'select\s+count\(',row['sql'].lower())),
    'afterContentMs':sum(row['totalMs'] for row in sql_after['statements'] if re.search(r'\bfrom roommate_board\b',row['sql'].lower()) and not re.match(r'select\s+count\(',row['sql'].lower())),
    'afterCountMs':0}
save(OUT/'sql-comparison.json',sql_changes)

lines=['# 인증 게시글 검색 — count 제거 전후 측정','',
    '대상: [RoommateBoardListKeywordGetTest.groovy](./execution/deployed-scripts/RoommateBoardListKeywordGetTest.groovy), `GET /roommate/boards?keyword=부하 테스트 게시글`, 인증 프로필 `search-frequent-authenticated`.','',
    '현재 소스의 count/Page 버전과 Slice 버전을 같은 조건에서 비교했다. 아래 평균·p95·p99·TPS는 **반복별 수치의 중간값**이며, p95를 여러 실행에 걸쳐 평균하거나 합친 값이 아니다. 오류율은 해당 VU의 전체 요청 기준이다.','',
    '| VU | 반복 전/후 | 평균 ms 전→후 | 평균 감소 | p95 ms 전→후 | p95 감소 | p99 ms 전→후 | TPS 전→후 | TPS 증가 | 오류율 % 전→후 |','|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
for row in comparison:
    b,a=row['before'],row['after']
    lines.append(f'| {row["vu"]} | {b["repetitions"]}/{a["repetitions"]} | {fmt(b["meanMsMedian"])} → {fmt(a["meanMsMedian"])} | {fmt(row["meanReductionPercent"])}% | {fmt(b["p95MsMedian"])} → {fmt(a["p95MsMedian"])} | {fmt(row["p95ReductionPercent"])}% | {fmt(b["p99MsMedian"])} → {fmt(a["p99MsMedian"])} | {fmt(b["controllerTpsMedian"])} → {fmt(a["controllerTpsMedian"])} | {fmt(row["tpsIncreasePercent"])}% | {fmt(b["errorRatePercent"])} → {fmt(a["errorRatePercent"])} |')
lines+=['','## 조건과 판정','',
    f'- 측정: `{before_env["startedAtKst"]}` ~ `{after_env.get("finishedAtKst","진행 중")}`. Java 21·기본 tiered compilation·`-Xms512m -Xmx2g`, Spring test/H2, 동일 호스트. 별도 측정 포트 18080. SQL 및 실행 시간 Aspect 출력 OFF.',
    '- count 유무에 따라 달라진 5개 Java 파일 외 소스/의존성은 같다. Before는 현재 HEAD의 Page/count 구현, After는 사용자의 미커밋 Slice 수정본이다. Slice는 21건을 조회하고 20건을 반환해 hasNext를 계산한다. [소스 변경](./execution/count-removal-source.patch), [빌드 hash](./controlled-ab/builds.json).',
    '- 각 버전에서 새 H2 seed1000을 생성했다. 회원 2,004·게시글 1,002·차단 1,001·초기 검색 이력 1,005건. 동일 회원 ID 5~34를 VU별로 배정하고 동일 검색어·첫 페이지(size 20, createdAt DESC)를 사용했다. 첫 페이지 게시글 ID도 일치했다.',
    '- Agent 1·process 1, 10/30 threads×100회, 각 3반복 완료(본 부하 총 24,000요청). 공통 워밍업은 1 VU×20회 + 10 VU×50회, 단계 간 15초. connect/socket 설정 5/15초, connectionReset=false, ramp-up=false.',
    '- 기본 부하 판정은 HTTP 200/통신 성공이다. 응답 형태 검증은 측정에서 끄고 Page/Slice 여부·반환 ID와 실행 SQL은 별도 확인했다. 지연은 성공한 개별 GET 종료까지이며 CSV 기록/검증 시간은 제외된다.',
    '- 표본·worker 수와 Controller 성공/오류 건수, 회원+검색어별 검색 이력 증가량을 대조했다. 기존 검색 이력은 삭제하지 않고 같은 순서로 누적했다. [검산](./verification.json), [전체 실행 CSV](./summary.csv).','',
    '## 반복별 원본 수치','',
    '| 버전 | VU | 반복 | 테스트 | 요청 | 평균 ms | p95 ms | p99 ms | TPS | 오류 | 관측 초 | 이력 증가 | 판정 |','|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|']
for row in rows:
    if row['phase']!='load':
        continue
    path=f'./controlled-ab/{row["variant"]}/raw/{row["label"]}/summary.json'
    lines.append(f'| {"Count 있음" if row["variant"]=="before-count" else "Slice"} | {row["vu"]} | {row["repeat"]} | [{row["testId"]}]({path}) | {row["requests"]:,} | {fmt(row["meanMs"])} | {fmt(row["p95Ms"])} | {fmt(row["p99Ms"])} | {fmt(row["controllerTps"])} | {row["errors"]} | {fmt(row["sampleSpanSeconds"])} | {row["memberKeywordHistoryDelta"]:,} | {"PASS" if row["passed"] else "오류 있음"} |')
lines+=['','## count 제거 실행 증거','',
    '| 별도 진단 10요청 | Count 있음 | Slice |','|---|---:|---:|',
    '| 게시글 content SELECT 실행 | 10 | 10 |','| 게시글 count SELECT 실행 | 10 | 0 |','| 검색 이력 INSERT 증가 | 10 | 10 |',
    f'| content SQL 누적 ms | {fmt(sql_changes["beforeContentMs"])} | {fmt(sql_changes["afterContentMs"])} |',
    f'| count SQL 누적 ms | {fmt(sql_changes["beforeCountMs"])} | 0 |','',
    'H2 query statistics는 부하 종료 후 진단 구간에서만 켰고 종료 후 껐다. content/count 실행 증분과 검색 저장 증분을 확인했다. 진단 SQL 시간은 DB 실행 시간이며 HTTP 지연 전체와 같지 않다. [Before SQL](./controlled-ab/before-count/sql-diagnostics/summary.json), [After SQL](./controlled-ab/after-slice/sql-diagnostics/summary.json).','',
    '## 과거 전체 시험과의 참고 비교','',
    '| VU | 2026-10-04 평균 ms | 현재 Slice 평균 ms | 관측 감소 | 과거 p95 ms | 현재 p95 ms | 과거 TPS | 현재 TPS |','|---:|---:|---:|---:|---:|---:|---:|---:|']
for row in historical_compare:
    lines.append(f'| {row["vu"]} | {fmt(row["historicalMeanMs"])} | {fmt(row["currentMeanMsMedian"])} | {fmt(row["meanReductionPercent"])}% | {fmt(row["historicalP95Ms"])} | {fmt(row["currentP95MsMedian"])} | {fmt(row["historicalTps"])} | {fmt(row["currentTpsMedian"])} |')
lines+=['','과거 시험은 1회 탐색이며 다른 시점의 빌드·워밍업·JVM/힙 조건을 사용했다. count 제거의 개선율은 위의 동일 조건 전후 비교를 기준으로 삼고, 이 표는 참고 자료로만 사용한다. [이전 보고서](../2026-10-04-entire-test/report.md), [비교 값](./historical-comparison.json).','',
    '## 한계와 기록','',
    '- 동일 호스트의 H2·고정 데이터·반복 3회의 결과다. 실제 운영 PostgreSQL의 용량이나 무한 스크롤 전체 페이지의 성능을 보증하지 않는다. 조회 content 비용·차단 조건·검색 이력 저장 비용은 여전히 포함된다.',
    '- Before 30 VU 1회차에 SocketTimeoutException 64건, Slice 30 VU 3회차에 1건이 발생했다. Before 이력 증가는 3,000/3,000건, 해당 Slice 실행은 2,999/3,000건이었다. Slice 오류는 한 worker의 첫 GET에서 약 5.14초 후 발생했으며, 연결/응답 중 정확한 타임아웃 단계는 로그만으로 확정할 수 없다. [Before 오류](./controlled-ab/before-count/raw/load-vu30-r1/failure-analysis.json), [Slice 오류](./controlled-ab/after-slice/raw/load-vu30-r3/failure-analysis.json).',
    '- 지연 통계는 성공 요청 기준이므로 오류율과 함께 봐야 한다. 전체 요청 CSV·Controller 건수는 검산 완료했지만 Slice 마지막 실행의 이력 전체 요청 일치 판정은 실패했다. verification.json에서 수집 완료(measurementComplete)와 모든 실행 무오류(allPassed), 이력 일치 여부를 구분한다.',
    '- 반복은 Before→After 순서로 실행했다. 통제한 코드/데이터/JVM/로그 조건 외 호스트 점유 변화, JIT/캐시, 새 worker 초기 연결 비용과 검색 이력 누적의 영향이 남아 있다. 실행별 편차와 관측 길이는 CSV에 남겼다.',
    '- IDE 예비 시험 513/514는 SQL 출력 ON·`TieredStopAtLevel=1`이라 개선율 계산에서 제외하고 `excluded-ide-preliminary/`에 보존했다. [당시 JVM 증거](./excluded-ide-preliminary/runtime-evidence.json), [예비 판정](./excluded-ide-preliminary/preliminary-verdict.json). 별도 SQL 로거가 켜진 준비 시도 515/516과 시드 사전 검증 보정 기록도 `controlled-ab/excluded-*`에 보존하고 본 측정에서 제외했다.',
    '- Controller 원래 설정을 복원하고 측정용 토큰 및 직접 띄운 서버를 정리했다. 기존 개발 서버는 측정 시점의 실행 상태를 유지했다. [Before 정리](./controlled-ab/before-count/cleanup.json), [After 정리](./controlled-ab/after-slice/cleanup.json).',
    '- 일상 확인은 이 보고서·`summary.csv`·`comparison.json`만 보면 된다. 개별 요청 CSV와 Controller JSON은 각 `controlled-ab/<버전>/raw/`, 서버 지표는 `telemetry.jsonl`과 [지표 요약](./telemetry-summary.json), 실행/빌드 재현 자료는 `execution/`에 있다. JWT·서명 키는 결과 자료에 포함하지 않았다.','']
(OUT/'report.md').write_text('\n'.join(lines),encoding='utf-8')
shutil.copyfile(__file__,OUT/'execution/summarize_pair.py')
print(json.dumps({'comparison':comparison,'verification':verdict},ensure_ascii=False,indent=2))
print('Report: '+str(OUT/'report.md'))
