# 별도 SQL 통계·실행계획 진단

장시간 부하 측정 종료 후 같은 시험 DB에서 경로별3건 워밍업·10건 순차 요청의 SQL 통계 증분을 수집했다. SQL/bind 로그는 그 다음 경로별1건씩 수집해 실제 바인딩 값을 SELECT 실행계획에 사용했다. 이 구간의 HTTP 시간은 본 측정 기준선에 포함하지 않는다.

| 경로 | 진단 요청 | HTTP 평균 ms | DB 명령 총시간/요청 ms | 업무 SQL/COMMIT 실행/요청 | 검색 이력 Δ |
|---|---:|---:|---:|---:|---:|
| list-anonymous | 10 | 18.833 | 7.443 | 5.0/2.0 | 0 |
| list-authenticated | 10 | 419.249 | 409.812 | 7.0/4.0 | 0 |
| search-frequent-anonymous | 10 | 12.900 | 7.587 | 5.0/2.0 | 0 |
| search-frequent-authenticated | 10 | 364.774 | 354.929 | 9.0/4.0 | 10 |

## 확인한 병목과 후보

인증 기본 조회의 content/count는 각각 실행당210.608ms/199.185ms, 인증 검색은184.971ms/169.903ms로 관측됐다. 두 SQL의 합계가 각 구간 DB 명령 시간의99.99%/99.98% 이상을 차지했다. 검색 INSERT는 실행당0.0231ms였다. 이 수치는 별도 진단의 관측이며 API 기준선 지연과 직접 빼지 않는다.

양방향 차단 OR 조건의 상관 서브쿼리가 BLOCK.tableScan을 사용한다. 같은 데이터에서 두 NOT EXISTS로 나눈 후보는 네 회원의 content/count를 유지했고 기존 FK 인덱스를 사용하며 SQL 실행 시간95.58~98.55% 감소를 보였다. [후보 SQL 검증과 다음 구현](./block-prototype/report.md). 실제 API 개선률은 소스 반영 후 재측정해야 한다.

## SQL별 비용

시간은10요청 구간의 누적 증분이다. `요청당`은 누적 시간을10으로 나눈 값이며 같은 SQL이 요청당 여러 번 실행되면 그 비용을 합친다. 쿼리 실행 시간에 네트워크·JSON 변환·전체 트랜잭션 commit 비용이 모두 포함되는 것은 아니다.

| 경로 | SQL 역할 | 실행 횟수 | 누적 ms | 실행당 ms | 요청당 ms | SQL 시간 비중 % |
|---|---|---:|---:|---:|---:|---:|
| list-anonymous | 게시글 content | 10 | 58.332 | 5.833 | 5.833 | 78.37 |
| list-anonymous | 게시글 count | 10 | 15.864 | 1.586 | 1.586 | 21.31 |
| list-anonymous | COMMIT 명령 | 20 | 0.124 | 0.006 | 0.012 | 0.17 |
| list-anonymous | 인증 정보 배치 조회 | 10 | 0.055 | 0.006 | 0.006 | 0.07 |
| list-anonymous | 이미지 배치 조회 | 10 | 0.038 | 0.004 | 0.004 | 0.05 |
| list-anonymous | 관심 배치 조회 | 10 | 0.021 | 0.002 | 0.002 | 0.03 |
| list-authenticated | 게시글 content | 10 | 2106.084 | 210.608 | 210.608 | 51.39 |
| list-authenticated | 게시글 count | 10 | 1991.846 | 199.185 | 199.185 | 48.60 |
| list-authenticated | COMMIT 명령 | 40 | 0.063 | 0.002 | 0.006 | 0.00 |
| list-authenticated | 이미지 배치 조회 | 10 | 0.047 | 0.005 | 0.005 | 0.00 |
| list-authenticated | 회원 조회 | 10 | 0.041 | 0.004 | 0.004 | 0.00 |
| list-authenticated | 인증 정보 배치 조회 | 10 | 0.016 | 0.002 | 0.002 | 0.00 |
| list-authenticated | 관심 배치 조회 | 10 | 0.012 | 0.001 | 0.001 | 0.00 |
| list-authenticated | 관심 배치 조회 | 10 | 0.010 | 0.001 | 0.001 | 0.00 |
| search-frequent-anonymous | 게시글 content | 10 | 55.167 | 5.517 | 5.517 | 72.72 |
| search-frequent-anonymous | 게시글 count | 10 | 20.598 | 2.060 | 2.060 | 27.15 |
| search-frequent-anonymous | 이미지 배치 조회 | 10 | 0.039 | 0.004 | 0.004 | 0.05 |
| search-frequent-anonymous | COMMIT 명령 | 20 | 0.026 | 0.001 | 0.003 | 0.03 |
| search-frequent-anonymous | 인증 정보 배치 조회 | 10 | 0.019 | 0.002 | 0.002 | 0.02 |
| search-frequent-anonymous | 관심 배치 조회 | 10 | 0.018 | 0.002 | 0.002 | 0.02 |
| search-frequent-authenticated | 게시글 content | 10 | 1849.713 | 184.971 | 184.971 | 52.12 |
| search-frequent-authenticated | 게시글 count | 10 | 1699.033 | 169.903 | 169.903 | 47.87 |
| search-frequent-authenticated | 검색 기록 INSERT | 10 | 0.231 | 0.023 | 0.023 | 0.01 |
| search-frequent-authenticated | COMMIT 명령 | 40 | 0.173 | 0.004 | 0.017 | 0.00 |
| search-frequent-authenticated | 이미지 배치 조회 | 10 | 0.046 | 0.005 | 0.005 | 0.00 |
| search-frequent-authenticated | 회원 조회 | 20 | 0.045 | 0.002 | 0.004 | 0.00 |
| search-frequent-authenticated | 인증 정보 배치 조회 | 10 | 0.019 | 0.002 | 0.002 | 0.00 |
| search-frequent-authenticated | 관심 배치 조회 | 10 | 0.015 | 0.002 | 0.002 | 0.00 |
| search-frequent-authenticated | 관심 배치 조회 | 10 | 0.010 | 0.001 | 0.001 | 0.00 |

## 실행계획 원본

SELECT에만 EXPLAIN ANALYZE를 실행했다. INSERT는 추가 저장을 피하기 위해 SQL 통계로만 확인했다. 각 계획은 수집한 prepared SQL과 bind 값을 기반으로 하며 원래 쿼리·바인딩·치환 SQL을 `diagnosis.json`에 보존했다.

| 경로 | SQL 역할 | 관측 노드 scanCount 최대 | 원본 |
|---|---|---:|---|
| list-anonymous | 게시글 content | 2,004 | [SQL/계획](./list-anonymous-select-00-plan.txt) |
| list-anonymous | 게시글 count | 2,004 | [SQL/계획](./list-anonymous-select-01-plan.txt) |
| list-anonymous | 이미지 배치 조회 | 40 | [SQL/계획](./list-anonymous-select-02-plan.txt) |
| list-anonymous | 인증 정보 배치 조회 | 21 | [SQL/계획](./list-anonymous-select-03-plan.txt) |
| list-anonymous | 관심 배치 조회 | 21 | [SQL/계획](./list-anonymous-select-04-plan.txt) |
| list-authenticated | 회원 조회 | 2 | [SQL/계획](./list-authenticated-select-00-plan.txt) |
| list-authenticated | 게시글 content | 2,004 | [SQL/계획](./list-authenticated-select-01-plan.txt) |
| list-authenticated | 게시글 count | 2,004 | [SQL/계획](./list-authenticated-select-02-plan.txt) |
| list-authenticated | 이미지 배치 조회 | 40 | [SQL/계획](./list-authenticated-select-03-plan.txt) |
| list-authenticated | 인증 정보 배치 조회 | 21 | [SQL/계획](./list-authenticated-select-04-plan.txt) |
| list-authenticated | 관심 배치 조회 | 21 | [SQL/계획](./list-authenticated-select-05-plan.txt) |
| list-authenticated | 관심 배치 조회 | 21 | [SQL/계획](./list-authenticated-select-06-plan.txt) |
| search-frequent-anonymous | 게시글 content | 2,004 | [SQL/계획](./search-frequent-anonymous-select-00-plan.txt) |
| search-frequent-anonymous | 게시글 count | 2,004 | [SQL/계획](./search-frequent-anonymous-select-01-plan.txt) |
| search-frequent-anonymous | 이미지 배치 조회 | 40 | [SQL/계획](./search-frequent-anonymous-select-02-plan.txt) |
| search-frequent-anonymous | 인증 정보 배치 조회 | 21 | [SQL/계획](./search-frequent-anonymous-select-03-plan.txt) |
| search-frequent-anonymous | 관심 배치 조회 | 21 | [SQL/계획](./search-frequent-anonymous-select-04-plan.txt) |
| search-frequent-authenticated | 회원 조회 | 2 | [SQL/계획](./search-frequent-authenticated-select-00-plan.txt) |
| search-frequent-authenticated | 회원 조회 | 2 | [SQL/계획](./search-frequent-authenticated-select-01-plan.txt) |
| search-frequent-authenticated | 게시글 content | 2,004 | [SQL/계획](./search-frequent-authenticated-select-03-plan.txt) |
| search-frequent-authenticated | 게시글 count | 2,004 | [SQL/계획](./search-frequent-authenticated-select-04-plan.txt) |
| search-frequent-authenticated | 이미지 배치 조회 | 40 | [SQL/계획](./search-frequent-authenticated-select-05-plan.txt) |
| search-frequent-authenticated | 인증 정보 배치 조회 | 21 | [SQL/계획](./search-frequent-authenticated-select-06-plan.txt) |
| search-frequent-authenticated | 관심 배치 조회 | 21 | [SQL/계획](./search-frequent-authenticated-select-07-plan.txt) |
| search-frequent-authenticated | 관심 배치 조회 | 21 | [SQL/계획](./search-frequent-authenticated-select-08-plan.txt) |

## 해석 범위

- H2 query statistics 시간 단위는 ms다. EXPLAIN ANALYZE는 쿼리를 실제 실행해 scan count를 보여준다. [H2 System Tables](https://h2database.com/html/systemtables.html), [H2 Commands](https://h2database.com/html/commands.html).
- 같은 로컬H2·시험 회원2·seed1000 조건의 원인 진단이다. 다른 회원의 차단 분포, 선택도, 실제 PostgreSQL의 인덱스·최적화기·대기는 별도로 확인해야 한다.
- SQL 자체 실행 시간과 API 전체 지연은 측정 범위가 다르다. 검색 기록 INSERT 통계가 작아도 모든 저장/commit/네트워크 비용이 그 수치와 같다고 단정하지 않는다.
- H2 통계는 COMMIT 명령도 수집한다. 표의 업무 SQL 횟수와 분리했으며 명령 수를 그대로 트랜잭션 수로 환산하지 않는다.
- 첫 수집은 동적 통계 테이블을 같은 SELECT로 읽어 일부 경로의 증분이0이 되었다. 해당 시도는 `excluded-cached-statistics/`에 보존하고 제외했다. 조회마다 고유 주석을 사용해 새 메타 테이블 조회를 생성한 후 content/count 실행이 각10회이고 검색 SQL에 LIKE 조건이 있는 것을 검증했다. 본 API의 쿼리 캐시 설정은 바꾸지 않았다. [스냅샷](./list-authenticated-statistics-snapshots.json).
- `scanCount` 최대값은 개별 계획 노드의 관측 값이다. 중첩 노드 값을 임의 합산해 실제 전체 스캔 행 수로 제시하지 않는다.
- JWT·서명 키·예외 메시지는 결과에 남기지 않았다. SQL/bind 로그에는 전용 시험 데이터 값만 있다. SQL 로그/통계 원상 복원은 아래 확인 자료에 기록했다.

## 자료

- [SQL 통계·바인딩·실행계획 JSON](./diagnosis.json), [진단 정리 확인](./cleanup.json).
- [장시간 대조 측정](../report.md), [SQL 수집기](../../../../tools/diagnose-roommate-board-sql.py), [이 집계기](../../../../tools/summarize-roommate-board-sql.py).
