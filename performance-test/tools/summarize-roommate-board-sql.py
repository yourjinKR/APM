"""Render the isolated H2 SQL evidence separately from load-test latency."""
import argparse
import json
from pathlib import Path
import re


def category(sql):
    sql=sql.lower()
    if sql=='commit':return 'COMMIT 명령'
    if re.search(r'insert into search\b',sql):return '검색 기록 INSERT'
    if re.search(r'from roommate_board\b',sql):return '게시글 count' if sql.startswith('select count(') else '게시글 content'
    if re.search(r'from member\b',sql):return '회원 조회'
    if 'roommate_board_interest' in sql:return '관심 배치 조회'
    if 'roommate_board_file' in sql:return '이미지 배치 조회'
    if 'authentication' in sql:return '인증 정보 배치 조회'
    return '기타 조회'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    args=parser.parse_args();directory=args.directory.resolve()
    data=json.loads((directory/'diagnosis.json').read_text(encoding='utf-8'))
    lines=['# 별도 SQL 통계·실행계획 진단','',
        '장시간 부하 측정 종료 후 같은 시험 DB에서 경로별3건 워밍업·10건 순차 요청의 SQL 통계 증분을 수집했다. SQL/bind 로그는 그 다음 경로별1건씩 수집해 실제 바인딩 값을 SELECT 실행계획에 사용했다. 이 구간의 HTTP 시간은 본 측정 기준선에 포함하지 않는다.','',
        '| 경로 | 진단 요청 | HTTP 평균 ms | DB 명령 총시간/요청 ms | 업무 SQL/COMMIT 실행/요청 | 검색 이력 Δ |','|---|---:|---:|---:|---:|---:|']
    for g in data['groups']:
        commits=sum(s['executions'] for s in g['statements'] if s['sql'].upper()=='COMMIT')
        queries=sum(s['executions'] for s in g['statements'] if s['sql'].upper()!='COMMIT')
        lines.append(f"| {g['profile']} | {g['requests']} | {g['httpMeanMs']:.3f} | {g['sqlTotalMs']/g['requests']:.3f} | {queries/g['requests']:.1f}/{commits/g['requests']:.1f} | {g['historyDelta']} |")
    lines+=['','## SQL별 비용','',
        '시간은10요청 구간의 누적 증분이다. `요청당`은 누적 시간을10으로 나눈 값이며 같은 SQL이 요청당 여러 번 실행되면 그 비용을 합친다. 쿼리 실행 시간에 네트워크·JSON 변환·전체 트랜잭션 commit 비용이 모두 포함되는 것은 아니다.','',
        '| 경로 | SQL 역할 | 실행 횟수 | 누적 ms | 실행당 ms | 요청당 ms | SQL 시간 비중 % |','|---|---|---:|---:|---:|---:|---:|']
    for g in data['groups']:
        for s in g['statements']:
            share=s['totalMs']/g['sqlTotalMs']*100 if g['sqlTotalMs'] else 0
            lines.append(f"| {g['profile']} | {category(s['sql'])} | {s['executions']} | {s['totalMs']:.3f} | {s['meanMs']:.3f} | {s['totalMs']/g['requests']:.3f} | {share:.2f} |")
    lines+=['','## 실행계획 원본','',
        'SELECT에만 EXPLAIN ANALYZE를 실행했다. INSERT는 추가 저장을 피하기 위해 SQL 통계로만 확인했다. 각 계획은 수집한 prepared SQL과 bind 값을 기반으로 하며 원래 쿼리·바인딩·치환 SQL을 `diagnosis.json`에 보존했다.','',
        '| 경로 | SQL 역할 | 관측 노드 scanCount 최대 | 원본 |','|---|---|---:|---|']
    for c in data['captures']:
        for p in c['plans']:
            maximum=max(p.get('scanCounts',[]),default=0)
            filename=f"{c['profile']}-select-{p['statementIndex']:02d}-plan.txt"
            link='계획 미수집: '+p['error'] if p.get('error') else f'[SQL/계획](./{filename})'
            lines.append(f"| {c['profile']} | {category(p['sql'])} | {maximum:,} | {link} |")
    lines+=['','## 해석 범위','',
        '- H2 query statistics 시간 단위는 ms다. EXPLAIN ANALYZE는 쿼리를 실제 실행해 scan count를 보여준다. [H2 System Tables](https://h2database.com/html/systemtables.html), [H2 Commands](https://h2database.com/html/commands.html).',
        '- 같은 로컬H2·시험 회원2·seed1000 조건의 원인 진단이다. 다른 회원의 차단 분포, 선택도, 실제 PostgreSQL의 인덱스·최적화기·대기는 별도로 확인해야 한다.',
        '- SQL 자체 실행 시간과 API 전체 지연은 측정 범위가 다르다. 검색 기록 INSERT 통계가 작아도 모든 저장/commit/네트워크 비용이 그 수치와 같다고 단정하지 않는다.',
        '- H2 통계는 COMMIT 명령도 수집한다. 표의 업무 SQL 횟수와 분리했으며 명령 수를 그대로 트랜잭션 수로 환산하지 않는다.',
        '- 첫 수집은 동적 통계 테이블을 같은 SELECT로 읽어 일부 경로의 증분이0이 되었다. 해당 시도는 `excluded-cached-statistics/`에 보존하고 제외했다. 조회마다 고유 주석을 사용해 새 메타 테이블 조회를 생성한 후 content/count 실행이 각10회이고 검색 SQL에 LIKE 조건이 있는 것을 검증했다. 본 API의 쿼리 캐시 설정은 바꾸지 않았다. [스냅샷](./list-authenticated-statistics-snapshots.json).',
        '- `scanCount` 최대값은 개별 계획 노드의 관측 값이다. 중첩 노드 값을 임의 합산해 실제 전체 스캔 행 수로 제시하지 않는다.',
        '- JWT·서명 키·예외 메시지는 결과에 남기지 않았다. SQL/bind 로그에는 전용 시험 데이터 값만 있다. SQL 로그/통계 원상 복원은 아래 확인 자료에 기록했다.','',
        '## 자료','',
        '- [SQL 통계·바인딩·실행계획 JSON](./diagnosis.json), [진단 정리 확인](./cleanup.json).',
        '- [장시간 대조 측정](../report.md), [SQL 수집기](../../../../tools/diagnose-roommate-board-sql.py), [이 집계기](../../../../tools/summarize-roommate-board-sql.py).','']
    (directory/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    print('SQL report written:',len(data['groups']),'paths')


if __name__=='__main__':main()
