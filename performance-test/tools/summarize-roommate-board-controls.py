"""Compare four API paths over equal, fully contained 140-second windows."""
import argparse
import csv
import importlib.util
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, pstdev


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def stats(rows, seconds):
    errors=sum(r['success']!='true' for r in rows)
    times = sorted(float(r['elapsedMs']) for r in rows if r['success']=='true')
    if not times: return {'requests': 0, 'rps': 0}
    return {'requests': len(times), 'attempts':len(rows),'errors':errors,'errorRatePercent':errors/len(rows)*100,
            'rps': len(times)/seconds, 'meanMs': mean(times),
            **{f'p{n}Ms': times[math.ceil(len(times)*n/100)-1] for n in (50,95,99)}}


def spread(values):
    return {'median': median(values), 'min': min(values), 'max': max(values),
            'cvPercent': pstdev(values)/mean(values)*100 if mean(values) else 0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args(); directory=args.directory.resolve()
    cases=json.loads((directory/'suite-summary.json').read_text(encoding='utf-8'))
    telemetry=[json.loads(x) for x in (directory/'telemetry.jsonl').read_text(encoding='utf-8').splitlines() if x]
    spec=importlib.util.spec_from_file_location('baseline',Path(__file__).with_name('summarize-roommate-board-baseline.py'))
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    groups=defaultdict(list); runs=[]
    for case in cases:
        if case['phase']!='control' or not case.get('measurementComplete',case['passed']) or case.get('excludedFromControls'): continue
        rows=[]
        for path in (directory/case['label']/'request-samples').glob('*.csv'):
            with path.open(encoding='utf-8-sig',newline='') as source:rows.extend(csv.DictReader(source))
        if len(rows)!=case['expectedRequests'] or sum(r['success']!='true' for r in rows)!=case['errors']:
            raise RuntimeError('Unexpected raw count or failure: '+case['label'])
        first=min(float(r['startedAtEpochMs']) for r in rows)
        start=first+30000; end=first+170000
        full_end=max(float(r['startedAtEpochMs'])+float(r['elapsedMs']) for r in rows)
        if full_end-first<180000: raise RuntimeError('Short control: '+case['label'])
        contained=lambda r,a,b: float(r['startedAtEpochMs'])>=a and float(r['startedAtEpochMs'])+float(r['elapsedMs'])<=b
        selected=[r for r in rows if contained(r,start,end)]
        segments=[stats([r for r in rows if contained(r,start+20000*n,start+20000*(n+1))],20) for n in range(7)]
        run=dict(case,windowStartEpochMs=start,windowEndEpochMs=end,window=stats(selected,140),segments20Seconds=segments,
                 resources=baseline.resources(dict(case,startTime=start,finishTime=end),telemetry))
        runs.append(run);groups[case['profile']].append(run)
    aggregates=[]
    for profile,items in sorted(groups.items()):
        if len(items)!=3 or {r['repeat'] for r in items}!={1,2,3}:raise RuntimeError('Three repetitions required: '+profile)
        aggregates.append({'profile':profile,'repetitions':len(items),'fullRequests':sum(r['sampleRequests'] for r in items),
            'windowRequests':sum(r['window']['requests'] for r in items),'historyDelta':sum(r['historyDelta'] for r in items),
            'fullErrors':sum(r['errors'] for r in items),'windowErrors':sum(r['window']['errors'] for r in items),
            'errorFreeRepetitions':sum(r['passed'] for r in items),
            'testIds':[r['testId'] for r in items],
            **{key:spread([r['window'][key] for r in items]) for key in ('meanMs','p50Ms','p95Ms','p99Ms','rps')}})
    if len(aggregates)!=4:raise RuntimeError('All four controls must complete before comparison')
    contrasts=[];mapping={r['profile']:r for r in aggregates}
    for label,left,right in [('authentication without keyword','list-anonymous','list-authenticated'),
            ('keyword for anonymous','list-anonymous','search-frequent-anonymous'),
            ('keyword for authenticated','list-authenticated','search-frequent-authenticated')]:
        contrasts.append({'comparison':label,'reference':left,'compared':right,
            'p95MedianRatio':mapping[right]['p95Ms']['median']/mapping[left]['p95Ms']['median'],
            'meanMedianDeltaMs':mapping[right]['meanMs']['median']-mapping[left]['meanMs']['median']})
    analysis={'groups':aggregates,'runs':runs,'contrasts':contrasts,
        'fullRequests':sum(r['sampleRequests'] for r in runs),'windowRequests':sum(r['window']['requests'] for r in runs),
        'errors':sum(r['errors'] for r in runs),'historyDelta':sum(r['historyDelta'] for r in runs),
        'excludedRuns':[r for r in cases if r.get('excludedFromControls')],
        'notes':['Window is [first GET start+30s,first GET start+170s], requests must finish in window.',
                 'Closed workload: one Agent/process/thread, no pacing; throughput includes response validation and CSV overhead.',
                 'Quantiles are nearest rank; aggregate median/range are per-repetition, not pooled percentiles.',
                 'H2 and generator share host. This is a controlled local diagnostic, not a production capacity or SLO result.']}
    save(directory/'controls-analysis.json',analysis)
    fields=['profile','repeat','testId','sampleRequests','fullErrors','sampleSpanSeconds','historyDelta','requests','errors','errorRatePercent','meanMs','p50Ms','p95Ms','p99Ms','rps']
    with (directory/'controls-summary.csv').open('w',encoding='utf-8',newline='') as target:
        writer=csv.DictWriter(target,fieldnames=fields,extrasaction='ignore');writer.writeheader()
        writer.writerows(dict(r,fullErrors=r['errors'],**r['window']) for r in runs)
    fmt=lambda x:f"{x['median']:.2f} ({x['min']:.2f}~{x['max']:.2f})"
    lines=['# 게시글 목록·검색 네 경로 장시간 대조 측정','',
        f"네 경로를 1 VUser·3반복으로 측정했다. 집계와 구간 길이를 검증한 실행 {len(runs)}회, 전체 GET {analysis['fullRequests']:,}건, 오류 {analysis['errors']}건, 인증 검색 이력 증가 {analysis['historyDelta']:,}건이다. 오류 있는 실행도 비교에 포함하며 오류 없는 확정 기준선으로 판정하지 않는다. 개별 CSV·Controller 집계·DB 이력 증분을 대조했다.",'',
        '## 비교 결과','',
        '각 값은 동일한 140초 구간에서 구한 반복별 값의 중앙값(최소~최대)이다. 경계 요청은 시작과 완료가 모두 구간 안에 있는 경우만 포함한다. p99 표본 수와 반복 편차도 함께 확인한다.','',
        '| 경로 | 구간 성공/오류 | 오류 없는 반복 | 평균 ms | p95 ms | p99 ms | 성공 요청/s | p95 CV % |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for group in aggregates:
        lines.append(f"| {group['profile']} | {group['windowRequests']:,}/{group['windowErrors']} | {group['errorFreeRepetitions']}/3 | {fmt(group['meanMs'])} | {fmt(group['p95Ms'])} | {fmt(group['p99Ms'])} | {fmt(group['rps'])} | {group['p95Ms']['cvPercent']:.2f} |")
    lines+=['','## 실행별 검증과 변화','',
        '| ID | 경로/반복 | 전체 표본/오류 | 실제 구간 초 | 검색 이력 Δ | 140초 성공/오류 | 앞/뒤 20초 평균 ms | 호스트 CPU max % | Hikari pending max |',
        '|---:|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in runs:
        resource=r['resources'];system=resource.get('systemCpuPercent');pending=resource.get('hikariPending')
        segments=r['segments20Seconds']; trend=f"{segments[0].get('meanMs',0):.2f}/{segments[-1].get('meanMs',0):.2f}"
        system_text=f"{system['max']:.2f}" if system else '—'
        pending_text=f"{pending['max']:.0f}" if pending else '—'
        lines.append(f"| {r['testId']} | {r['profile']}/{r['repeat']} | {r['sampleRequests']:,}/{r['errors']} | {r['sampleSpanSeconds']:.2f} | {r['historyDelta']:,} | {r['window']['requests']:,}/{r['window']['errors']} | {trend} | {system_text} | {pending_text} |")
    lines+=['','## 실행 조건과 해석','',
        '- 기존 기준선과 같은 JAR·Java21·test/H2 seed1000(게시글1002, 초기 검색1005), SQL 로그·query statistics 비활성 상태다. 각 회차 전에 새 시험 이력만 정리했다. 시퀀스·DB 물리 상태는 재생성하지 않았다.',
        '- Controller/Agent3.5.9-p1·Agent Java11, Agent1/process1/thread1, 기본 page0/size20/sort createdAt DESC, 동일 timeout과 계약 검증을 적용했다. 실행 순서를 회차별 회전하고 회차 사이15초 휴식했다.',
        '- 네 경로별100건 워밍업 후 관측 속도로 횟수를 보정해 완료 요청 방식(R)으로 최소180초 표본을 확보했다. 비교에서는 처음30초와170초 이후를 제외한다. 새 Agent worker마다 초기화 비용이 있으므로 중앙 구간을 사용한다.',
        '- Controller 최대 반복10000회 제한은 관리 API로 측정 동안만1000000회로 높였다. 기존 한 반복/한 GET 실행 방식을 유지했다. 종료 시 원래 설정 전체와 상한을 복원하며 [변경·복원 증거](./controller-limit.json)에 확인 결과를 기록한다.',
        '- 시간 종료 사전 시험357은 Controller1086/CSV1100 불일치로 제외했다. 이후 생성 실패는 최대 반복 초과였으며 실제 HTTP 요청 없이 거부됐다. 여러 GET을 한 반복에 묶은 시험366도 Controller의 조기 종료로 표본 누락·ShutdownException이 있어 제외하고 변경을 철회했다. 짧은 보정 시험도 유효 비교에서 제외하고 원본을 보존했다.',
        '- 익명/인증 조회는 count1002, 빈번 검색은 count1000이다. 인증 조회에는 회원·차단·관심 조건이 추가되므로 인증 차이를 JWT 비용으로 단정하지 않는다. 인증 검색과 인증 조회의 차이도 검색 필터와 INSERT를 함께 포함하므로 순수 INSERT 비용이 아니다.',
        '- 자원은 약10초+scrape/docker stats 시간 간격의 관측이다. 순간 peak를 놓칠 수 있고 CPU는 동일 호스트의 다른 작업 영향을 받는다. DB pool 대기를 관측하지 못했어도 발생하지 않았다고 보장하지 않는다.',
        '- 첫 장시간 익명 실행368의 통신 실패2건은 서버 완료 counter 증가29163과 클라이언트 성공29163이 일치했다. 오류 시 서버5xx·DB pool 대기는 관측하지 못했다. 서버 도달 전 통신 문제를 의심해 동일1VU 독립 대조 조건을 계속 수집하되 모든 실패를 포함했다. 집계·DB 증분 불일치나 종료 상태 이상은 계속 중단 조건이다. timeout의5초 관측을 성공 응답 p95/p99에 섞지 않는다.',
        '- 반복 평균과 p95 범위/CV, 앞뒤20초 변화는 안정성 판단의 참고값이다. 공유 로컬 H2 결과로 운영 SLO·수용 VUser·확정 개선률을 선언하지 않는다.','',
        '## SQL 진단','',
        '[별도 SQL 통계·실행계획 진단](./sql-diagnostics/report.md)을 본 측정 종료 후 수집한다. SQL 진단의 HTTP 지연은 통계·로깅 비용을 포함할 수 있어 위 기준선과 혼합하지 않는다.','',
        '## 원본과 도구','',
        '- [환경](./environment.json), [계획](./measurement-plan.json), [fixture](./fixture-snapshot.json), [배포](./deployment.json), [전체 실행](./suite-summary.json).',
        '- [140초 분석과 20초 추세](./controls-analysis.json), [반복 요약 CSV](./controls-summary.csv), [자원 원본](./telemetry.jsonl), [시간 종료 제외 근거](./duration-accounting-preflight.json).',
        '- 각 실행 폴더에 `created.json`, `deployed-config.json`, `test.json`, `basic-report.json`, `request-samples/*.csv`와 요청 집계가 있다.',
        '- [실행기](../../../tools/run-roommate-board-baseline.py), [대조 집계기](../../../tools/summarize-roommate-board-controls.py), [정리 확인](./cleanup.json).','']
    (directory/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'runs':len(runs),'requests':analysis['fullRequests'],'windowRequests':analysis['windowRequests'],'errors':analysis['errors']},ensure_ascii=False))


if __name__=='__main__':main()
