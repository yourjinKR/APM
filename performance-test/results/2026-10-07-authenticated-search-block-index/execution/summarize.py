from pathlib import Path
from datetime import datetime, timezone, timedelta
from statistics import median
import csv
import hashlib
import importlib.util
import json
import re
import shutil
import socket
import subprocess

OUT=Path(r'C:\dev\workspace\prography\APM\performance-test\results\2026-10-07-authenticated-search-block-index')
BACKEND=Path(r'C:\dev\workspace\KnockIn\back\11th-1team-BE')
VARIANTS=['before-or','after-index-and']
def read(path):
    return json.loads(path.read_text('utf-8-sig'))
def save(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def fmt(value):
    return f'{value:,.2f}'
rows=[]
steady_rows=[]
groups={}
verification={'verifiedAtKst':datetime.now(timezone(timedelta(hours=9))).isoformat(),'variants':{}}
for variant in VARIANTS:
    folder=OUT/'controlled-ab'/variant
    cases=read(folder/'suite-summary.json')
    loads=[row for row in cases if row['phase']=='load']
    cleanup=read(folder/'cleanup.json')
    sql=read(folder/'sql-diagnostics/summary.json')
    plan=read(folder/'sql-diagnostics/block-plan.json')
    schema=read(folder/'block-index-schema.json')
    if sql['contentExecutions']!=10 or sql['boardCountExecutions']!=0 or sql['historyDelta']!=10:
        raise RuntimeError('Unexpected count/content/history SQL execution evidence')
    if not read(folder/'sql-diagnostics/cleanup.json')['queryStatisticsDisabled']:
        raise RuntimeError('Query statistics remain enabled')
    if schema['newCompositeIndexExists']!=(variant=='after-index-and') or plan['blockNotExistsSubqueries']!=(1 if variant=='before-or' else 2):
        raise RuntimeError('Block schema/runtime SQL mismatch')
    if not cleanup['ownedBackendStopped'] or not cleanup['controllerIdle'] or not all(cleanup['controllerRestored'].values()) or not all(cleanup['tokensRemoved'].values()):
        raise RuntimeError('Incomplete cleanup')
    for row in cases:
        paths=list((folder/'raw'/row['label']/'request-samples').glob('*.csv'))
        samples=[]
        for path in paths:
            with path.open(encoding='utf-8-sig',newline='') as stream:
                samples.extend({'source':path.name,**sample} for sample in csv.DictReader(stream))
        success=sum(sample['success']=='true' for sample in samples)
        if len(paths)!=row['vu'] or len(samples)!=row['expectedRequests'] or success!=row['successes'] or len(samples)-success!=row['errors']:
            raise RuntimeError('Raw worker/CSV accounting mismatch')
        failures=[sample for sample in samples if sample['success']!='true']
        if failures:
            save(folder/'raw'/row['label']/'failure-analysis.json',{'testId':row['testId'],'failures':failures,
                'historyDelta':row['historyDelta'],'note':'Throwable cause names are from the script; exact timeout stage is not established by CSV alone.'})
        rows.append({'variant':variant,**row})
    groups[variant]={}
    for vu in [10,30]:
        runs=[row for row in loads if row['vu']==vu]
        if len(runs)!=3:
            raise RuntimeError('Did not complete the three planned repeats')
        groups[variant][vu]={'repetitions':3,'requests':sum(row['requests'] for row in runs),'errors':sum(row['errors'] for row in runs),
            'errorRatePercent':100*sum(row['errors'] for row in runs)/sum(row['requests'] for row in runs),
            'meanMsMedian':median(row['meanMs'] for row in runs),'p95MsMedian':median(row['p95Ms'] for row in runs),
            'p99MsMedian':median(row['p99Ms'] for row in runs),'tpsMedian':median(row['controllerTps'] for row in runs),
            'meanMsRange':[min(row['meanMs'] for row in runs),max(row['meanMs'] for row in runs)],
            'spanSecondsRange':[min(row['sampleSpanSeconds'] for row in runs),max(row['sampleSpanSeconds'] for row in runs)],
            'historyDelta':sum(row['historyDelta'] for row in runs),'testIds':[row['testId'] for row in runs]}
    verification['variants'][variant]={'runs':len(loads),'loadRequests':sum(row['requests'] for row in loads),
        'allRequestAccountingPassed':all(row['requestAccountingPassed'] for row in loads),
        'allStrictAccountingPassed':all(row['accountingPassed'] for row in loads),
        'historyConsistentWithOutcomes':all(row['historyConsistentWithOutcomes'] for row in loads),
        'historyDelta':sum(row['historyDelta'] for row in loads),'errors':sum(row['errors'] for row in loads),
        'contentExecutionsPer10Requests':sql['contentExecutions'],'countExecutionsPer10Requests':sql['boardCountExecutions'],
        'blockNotExistsSubqueries':plan['blockNotExistsSubqueries'],'newCompositeIndexExists':schema['newCompositeIndexExists'],
        'newCompositeIndexUsedByFocusedPlan':plan['newCompositeIndexUsedByFocusedPlan'],'cleanupVerified':True}
envs={variant:read(OUT/'controlled-ab'/variant/'environment.json') for variant in VARIANTS}
conditions=['actualCounts','memberIds','profile','keyword','query','agentCount','processes','vusers','requestsPerVu','repetitions',
            'cooldownSeconds','connectTimeoutMs','socketTimeoutMs','connectionReset','rampUp','responseValidator','sqlLogging',
            'javaOptions','defaultTieredCompilation','executionTimeAspectLogger','warmup']
if any(envs['before-or'][key]!=envs['after-index-and'][key] for key in conditions):
    raise RuntimeError('Runtime/data conditions differ')
responses={variant:read(OUT/'controlled-ab'/variant/'member-response-probes.json') for variant in VARIANTS}
extract=lambda values:[{key:row[key] for key in ['memberId','ids','first','last']} for row in values['members']]
if extract(responses['before-or'])!=extract(responses['after-index-and']):
    raise RuntimeError('Seeded member results differ')
verification['conditionsMatched']=True
verification['memberFirstPageResultsMatched']=30
verification['measurementComplete']=all(value['runs']==6 and value['loadRequests']==12000 and value['allRequestAccountingPassed'] and value['historyConsistentWithOutcomes'] for value in verification['variants'].values())
verification['allRunsErrorFree']=all(value['errors']==0 for value in verification['variants'].values())
save(OUT/'verification.json',verification)
comparison=[]
for vu in [10,30]:
    before=groups['before-or'][vu]
    after=groups['after-index-and'][vu]
    comparison.append({'vu':vu,'before':before,'after':after,
        'meanReductionPercent':100*(1-after['meanMsMedian']/before['meanMsMedian']),
        'p95ReductionPercent':100*(1-after['p95MsMedian']/before['p95MsMedian']),
        'p99ReductionPercent':100*(1-after['p99MsMedian']/before['p99MsMedian']),
        'tpsIncreasePercent':100*(after['tpsMedian']/before['tpsMedian']-1)})
save(OUT/'comparison.json',{'basis':'Median of per-run metrics; same code except Block entity index and repository predicate; both Slice/no count',
    'groups':comparison})
fields=['variant','phase','vu','repeat','testId','requests','successes','errors','errorRatePercent','controllerTps','meanMs','p95Ms','p99Ms',
        'sampleSpanSeconds','historyDelta','requestAccountingPassed','historyConsistentWithOutcomes','accountingPassed','passed']
with (OUT/'summary.csv').open('w',encoding='utf-8-sig',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
initial=read(OUT/'initial-environment.json')
save(OUT/'environment.json',{'measurement':'Block composite index and two NOT EXISTS AND combined improvement',
    'backendCommit':initial['backendCommit'],'startedAtKst':envs['before-or']['startedAtKst'],'finishedAtKst':envs['after-index-and']['finishedAtKst'],
    'sharedConditions':{key:envs['before-or'][key] for key in conditions},'loadRequests':24000,'memberResponseProbeRequests':60,
    'note':'Temporary JARs are removed after measurement; source snapshots, patch, build logs and hashes are retained.'})
sql_comparison={variant:{**read(OUT/'controlled-ab'/variant/'sql-diagnostics/block-plan.json'),
    'indexSchema':'controlled-ab/'+variant+'/block-index-schema.json'} for variant in VARIANTS}
save(OUT/'sql-comparison.json',sql_comparison)
steady_folder=OUT/'controlled-ab/current-steady'
if steady_folder.exists():
    steady_rows=read(steady_folder/'suite-summary.json')
    for row in steady_rows:
        paths=list((steady_folder/'raw'/row['label']/'request-samples').glob('*.csv'))
        total=0
        successes=0
        failures=[]
        for path in paths:
            with path.open(encoding='utf-8-sig',newline='') as stream:
                for sample in csv.DictReader(stream):
                    total+=1
                    successes+=sample['success']=='true'
                    if sample['success']!='true':
                        failures.append({'source':path.name,**sample})
        if total!=row['expectedRequests'] or successes!=row['successes'] or total-successes!=row['errors'] or len(paths)!=row['vu']:
            raise RuntimeError('Supplemental raw CSV accounting mismatch')
        if failures:
            save(steady_folder/'raw'/row['label']/'failure-analysis.json',{'testId':row['testId'],'failures':failures,
                'note':'Both timeout samples were iteration 1000 with HTTP status 0; exact timeout stage is not proved by Throwable cause names alone.'})
    steady_case=next(row for row in steady_rows if row['phase']=='steady-observation')
    if steady_case['sampleSpanSeconds']<60:
        raise RuntimeError('Supplemental observation was shorter than 60 seconds')
    steady_cleanup=read(steady_folder/'cleanup.json')
    if not steady_cleanup['ownedBackendStopped'] or not steady_cleanup['controllerIdle'] or not all(steady_cleanup['controllerRestored'].values()) or not all(steady_cleanup['tokensRemoved'].values()):
        raise RuntimeError('Supplemental cleanup failed')
    save(OUT/'current-steady.json',{'comparisonMedianIncluded':False,'case':steady_case,
        'sampleSuccessRps':steady_case['successes']/steady_case['sampleSpanSeconds'],
        'observedAtLeast60Seconds':steady_case['sampleSpanSeconds']>=60,
        'environment':read(steady_folder/'environment.json'),'cleanupVerified':True})
    with (OUT/'steady-summary.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
        writer.writeheader()
        writer.writerows({'variant':'current-steady',**row} for row in steady_rows)

lines=['# 인증 게시글 검색 — Block 인덱스·차단 조건 개선','',
    '대상: [RoommateBoardListKeywordGetTest.groovy](./execution/deployed-scripts/RoommateBoardListKeywordGetTest.groovy), 인증 `GET /roommate/boards`, 검색어 `부하 테스트 게시글`.','',
    '직전 Slice/count 제거 구현의 OR 조건과, 복합 인덱스를 추가하고 두 NOT EXISTS를 AND로 결합한 현재 구현을 같은 조건에서 비교했다. **평균·p95·p99·TPS는 실행 3회의 중간값**, 오류율은 해당 VU의 전체 요청 기준이다. 지연 통계는 성공 요청만 포함한다.','',
    '| VU | 평균 ms 전→후 | 평균 감소 | p95 ms 전→후 | p95 감소 | p99 ms 전→후 | TPS 전→후 | TPS 증가 | 오류율 % 전→후 |',
    '|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
for row in comparison:
    b,a=row['before'],row['after']
    lines.append(f'| {row["vu"]} | {fmt(b["meanMsMedian"])} → {fmt(a["meanMsMedian"])} | {fmt(row["meanReductionPercent"])}% | {fmt(b["p95MsMedian"])} → {fmt(a["p95MsMedian"])} | {fmt(row["p95ReductionPercent"])}% | {fmt(b["p99MsMedian"])} → {fmt(a["p99MsMedian"])} | {fmt(b["tpsMedian"])} → {fmt(a["tpsMedian"])} | {fmt(row["tpsIncreasePercent"])}% | {fmt(b["errorRatePercent"])} → {fmt(a["errorRatePercent"])} |')
lines+=['','## 측정 조건','',
    f'- 측정: `{envs["before-or"]["startedAtKst"]}` ~ `{envs["after-index-and"]["finishedAtKst"]}`. 기준 commit `{initial["backendCommit"][:12]}` + 현재 미커밋 수정본.',
    '- Java 21 JAR, 기본 tiered compilation, `-Xms512m -Xmx2g`, Spring test/H2, 포트 18080. Hibernate·datasource proxy·실행 시간 Aspect 로그 OFF. 각 버전에서 동일한 새 H2 seed 생성.',
    '- 회원 2,004·게시글 1,002·차단 1,001·초기 검색 이력 1,005건. 회원 ID 5~34를 VU별로 배정. page=0, size=20, sort=createdAt,DESC. 각 30회원의 첫 페이지 ID·first/last 결과 일치.',
    '- Agent 1·process 1, 10/30 VU × 각 100회 × 3반복 × 전후 2버전 = **24,000요청**. 워밍업은 각각 1 VU×20 + 10 VU×50, 단계 간 15초. connect/socket 설정 5/15초, ramp-up=false, connectionReset=false.',
    '- 응답 본문 형태 검증을 부하 경로에서 끄고 HTTP 200과 통신 성공을 판정했다. 검색 이력은 삭제 없이 누적하며 CSV worker 수·성공/오류·Controller 건수·이력 증가량을 검산했다.',
    '- 두 Java 파일 외 복사한 소스·빌드 설정은 동일하다. [변경 내용](./execution/block-index-source.patch), [소스 동일성](./controlled-ab/source-tree-comparison.json), [빌드 hash](./controlled-ab/builds.json), [검산](./verification.json).','',
    '## 반복별 결과','',
    '| 버전 | VU | 반복 | 테스트 | 요청 | 평균 ms | p95 ms | p99 ms | TPS | 오류 | 관측 초 | 이력 증가 |',
    '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
for row in rows:
    if row['phase']!='load':
        continue
    link=f'./controlled-ab/{row["variant"]}/raw/{row["label"]}/summary.json'
    lines.append(f'| {"OR / 새 복합 인덱스 없음" if row["variant"]=="before-or" else "복합 인덱스 + AND"} | {row["vu"]} | {row["repeat"]} | [{row["testId"]}]({link}) | {row["requests"]:,} | {fmt(row["meanMs"])} | {fmt(row["p95Ms"])} | {fmt(row["p99Ms"])} | {fmt(row["controllerTps"])} | {row["errors"]} | {fmt(row["sampleSpanSeconds"])} | {row["historyDelta"]:,} |')
lines+=['','## SQL·인덱스 증거','',
    '| 확인 항목 | OR / 새 복합 인덱스 없음 | 복합 인덱스 + AND |','|---|---:|---:|',
    '| 실제 content SQL의 Block NOT EXISTS 수 | 1 | 2 |',
    '| 별도 10요청의 content SELECT / 게시글 count SELECT | 10 / 0 | 10 / 0 |',
    '| 새 복합 인덱스 생성 | 없음 | 있음 |',
    '| Block 조건만 추출한 EXPLAIN ANALYZE에서 새 인덱스 사용 | 없음 | 확인 |',
    f'| 진단 content SELECT 평균 DB 시간 ms | {fmt(sql_comparison["before-or"]["contentSqlMeanMs"])} | {fmt(sql_comparison["after-index-and"]["contentSqlMeanMs"])} |','',
    '`idx_block_blocker_blocked_deleted(blocker_id, blocked_id, is_deleted)`를 H2 실제 스키마에서 확인했다. 기존 단일 FK 인덱스는 두 버전 모두 존재한다. OR를 분리해 각 방향의 존재 여부를 별도로 검사하고 두 NOT EXISTS를 AND로 묶었다. 위 실행 계획은 차단 조건을 추출한 읽기 전용 쿼리이며 API 전체 실행 계획과 구분한다. 진단 DB 시간은 HTTP 지연 전체와 같지 않다. Query statistics는 부하 종료 후 진단 때만 켜고 종료 후 껐다.',
    '[Before SQL·계획](./controlled-ab/before-or/sql-diagnostics/block-plan.json), [After SQL·계획](./controlled-ab/after-index-and/sql-diagnostics/block-plan.json), [After 인덱스 스키마](./controlled-ab/after-index-and/block-index-schema.json).','',
    '## 추가 지속 관측','',
    '개선 후 비교 실행은 약 2.7~9.4초로 짧아져 별도 새 seed/JVM에서 현재 버전을 길게 관측했다. 전후 개선율은 위 3회 반복 기준으로 유지했다. 추가 실행의 워밍업은 1 VU×20 + 30 VU×200이다.','',
    '| VU | 요청 | 관측 초 | 평균 ms | p95 ms | p99 ms | Controller TPS | 표본 성공 RPS | 오류 | 이력 증가 |',
    '|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
if steady_rows:
    row=next(item for item in steady_rows if item['phase']=='steady-observation')
    lines.append(f'| {row["vu"]} | {row["requests"]:,} | {fmt(row["sampleSpanSeconds"])} | {fmt(row["meanMs"])} | {fmt(row["p95Ms"])} | {fmt(row["p99Ms"])} | {fmt(row["controllerTps"])} | {fmt(row["successes"]/row["sampleSpanSeconds"])} | {row["errors"]} | {row["historyDelta"]:,} |')
    lines+=['','[지속 관측 원본](./current-steady.json), [추가 CSV](./steady-summary.csv).','']
    if row['errors']:
        lines+= [f'추가 실행에서 SocketTimeoutException {row["errors"]}건({row["errorRatePercent"]:.4f}%)이 발생했다. 두 worker 모두 iteration=1000에서 약 5.04/5.65초 후 HTTP status=0으로 실패했으며, 전체 검색 이력 증가는 {row["historyDelta"]:,}/{row["requests"]:,}건이다. 정확한 타임아웃 단계는 확인하지 못했다. 지연·처리율 통계는 성공 요청 기준이다. [오류 표본](./controlled-ab/current-steady/raw/steady-observation-vu30-r1/failure-analysis.json).','']
lines+=['## 해석과 기록','',
    '- 위 개선율은 인덱스 추가와 차단 조건 변경을 합친 효과다. 인덱스만/조건만 각각의 기여도는 분리 측정하지 않았다. 두 버전 모두 Slice/count 제거를 유지한다.',
    '- 동일 호스트의 H2·고정 seed·첫 페이지·폐쇄형 10/30 VU 결과다. 운영 DB의 실행 계획이나 최대 처리 용량을 나타내지 않는다. Before→After 실행 순서에 따른 JIT/캐시·호스트 점유 변화와 검색 이력 누적 영향이 남는다.',
    '- 특히 After 10 VU는 관측 2.69~9.44초, Controller TPS 109.37~499.75로 편차가 크다. TPS는 Controller 종료 통계값이며 초기 연결·JIT와 2초 샘플 간격의 영향을 함께 받는다. 현재 처리율 해석에는 30 VU 반복과 추가 지속 관측도 함께 사용한다.',
    '- 실제 DDL과 인덱스 사용은 H2 create-drop 환경에서 확인했다. 운영 DB에 이 인덱스가 적용됐는지는 이번 측정에 포함하지 않았다.','']
for row in rows:
    if row['phase']=='load' and row['errors']:
        link=f'./controlled-ab/{row["variant"]}/raw/{row["label"]}/failure-analysis.json'
        lines.append(f'- 테스트 {row["testId"]}: 오류 {row["errors"]}건, 원인 분류 `{row["transportFailureRoots"] or row["failures"]}`, 이력 증가 {row["historyDelta"]}/{row["requests"]}건. [오류 표본]({link}).')
if not any(row['errors'] for row in rows if row['phase']=='load'):
    lines.append('- 본 부하 24,000요청에서 오류 0건이며, 검색 이력 증가량도 모든 요청과 일치했다.')
lines+=['','일상 확인은 이 보고서와 [summary.csv](./summary.csv), [comparison.json](./comparison.json)으로 가능하다. 개별 요청 CSV·Controller JSON은 `controlled-ab/<버전>/raw/`, 서버 지표는 각 `telemetry.jsonl` 및 [지표 요약](./telemetry-summary.json), 재현 자료는 `execution/`에 보관했다. Controller 설정·측정 토큰·직접 띄운 서버 정리 결과는 각 `cleanup.json`에 기록했다. [직전 count 제거 보고서](../2026-10-07-authenticated-search-count-removal/report.md).','']
(OUT/'report.md').write_text('\n'.join(lines),encoding='utf-8')

spec=importlib.util.spec_from_file_location('focused_verify',OUT/'execution/focused_search_lib.py')
lib=importlib.util.module_from_spec(spec)
spec.loader.exec_module(lib)
originals=read(OUT/'execution/controlled-controller-originals.json')
restored={name:lib.api('/script/api/detail/'+name)['file']['content']==entry['content'] for name,entry in originals.items()}
token_checks={}
for variant in VARIANTS+(['current-steady'] if steady_rows else []):
    if variant=='current-steady':
        envs[variant]=read(steady_folder/'environment.json')
    token_file=envs[variant]['tokenFile']
    token_checks[variant]={container:subprocess.run(['docker','exec',container,'test','!','-e',token_file],capture_output=True).returncode==0
        for container in read(OUT/'controlled-ab'/variant/'cleanup.json')['tokensRemoved']}
def listening(port):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=1):
            return True
    except OSError:
        return False
build=next(row for row in read(OUT/'controlled-ab/builds.json') if row['variant']=='after-index-and')
source_match={name:hashlib.sha256((BACKEND/name).read_bytes()).hexdigest()==expected for name,expected in build['sourceHashes'].items()}
broken=[link for link in re.findall(r'\]\(([^)]+)\)',(OUT/'report.md').read_text('utf-8')) if not (OUT/link).exists()]
jwt=re.compile(rb'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}')
secrets=[str(path.relative_to(OUT)) for path in OUT.rglob('*') if path.is_file() and jwt.search(path.read_bytes())]
post={'controllerOriginalContentRestored':restored,'controllerIdle':lib.api('/perftest/api/status')['runningTestsCount']==0,
      'ownedTokenFilesAbsent':token_checks,'originalBackendListeningStatePreserved':listening(8080)==initial['existingBackend8080Listening'],
      'measurementBackend18080Stopped':not listening(18080),'sourceUnchanged':source_match,'brokenReportLinks':broken,'jwtBearingResultFiles':secrets,
      'supplementalRequestAccountingPassed':all(row['requestAccountingPassed'] and row['historyConsistentWithOutcomes'] for row in steady_rows)}
post['passed']=all(restored.values()) and post['controllerIdle'] and all(all(value.values()) for value in token_checks.values())
post['passed']=post['passed'] and post['originalBackendListeningStatePreserved'] and post['measurementBackend18080Stopped'] and all(source_match.values()) and not broken and not secrets and verification['measurementComplete'] and post['supplementalRequestAccountingPassed']
save(OUT/'post-verification.json',post)
if Path(__file__).resolve()!=(OUT/'execution/summarize.py').resolve():
    shutil.copyfile(__file__,OUT/'execution/summarize.py')
generator=Path(__file__).parent/'prepare_steady.py'
if generator.exists() and generator.resolve()!=(OUT/'execution/prepare_steady.py').resolve():
    shutil.copyfile(generator,OUT/'execution/prepare_steady.py')
print(json.dumps({'comparison':comparison,'verification':verification,'postVerificationPassed':post['passed']},ensure_ascii=False,indent=2))
if not post['passed']:
    raise SystemExit('Final verification failed')
