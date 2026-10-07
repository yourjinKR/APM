# 인증 게시글 검색 — Block 인덱스·차단 조건 개선

대상: [RoommateBoardListKeywordGetTest.groovy](./execution/deployed-scripts/RoommateBoardListKeywordGetTest.groovy), 인증 `GET /roommate/boards`, 검색어 `부하 테스트 게시글`.

직전 Slice/count 제거 구현의 OR 조건과, 복합 인덱스를 추가하고 두 NOT EXISTS를 AND로 결합한 현재 구현을 같은 조건에서 비교했다. **평균·p95·p99·TPS는 실행 3회의 중간값**, 오류율은 해당 VU의 전체 요청 기준이다. 지연 통계는 성공 요청만 포함한다.

| VU | 평균 ms 전→후 | 평균 감소 | p95 ms 전→후 | p95 감소 | p99 ms 전→후 | TPS 전→후 | TPS 증가 | 오류율 % 전→후 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 554.04 → 30.17 | 94.55% | 644.98 → 46.54 | 92.78% | 698.49 → 73.55 | 17.86 → 235.13 | 1,216.52% | 0.00 → 0.00 |
| 30 | 1,620.60 → 83.35 | 94.86% | 2,134.40 → 130.13 | 93.90% | 2,390.04 → 180.89 | 18.36 → 340.44 | 1,754.25% | 0.00 → 0.00 |

## 측정 조건

- 측정: `2026-10-07T19:09:08.557591+09:00` ~ `2026-10-07T19:29:42.982351+09:00`. 기준 commit `0525d702e26f` + 현재 미커밋 수정본.
- Java 21 JAR, 기본 tiered compilation, `-Xms512m -Xmx2g`, Spring test/H2, 포트 18080. Hibernate·datasource proxy·실행 시간 Aspect 로그 OFF. 각 버전에서 동일한 새 H2 seed 생성.
- 회원 2,004·게시글 1,002·차단 1,001·초기 검색 이력 1,005건. 회원 ID 5~34를 VU별로 배정. page=0, size=20, sort=createdAt,DESC. 각 30회원의 첫 페이지 ID·first/last 결과 일치.
- Agent 1·process 1, 10/30 VU × 각 100회 × 3반복 × 전후 2버전 = **24,000요청**. 워밍업은 각각 1 VU×20 + 10 VU×50, 단계 간 15초. connect/socket 설정 5/15초, ramp-up=false, connectionReset=false.
- 응답 본문 형태 검증을 부하 경로에서 끄고 HTTP 200과 통신 성공을 판정했다. 검색 이력은 삭제 없이 누적하며 CSV worker 수·성공/오류·Controller 건수·이력 증가량을 검산했다.
- 두 Java 파일 외 복사한 소스·빌드 설정은 동일하다. [변경 내용](./execution/block-index-source.patch), [소스 동일성](./controlled-ab/source-tree-comparison.json), [빌드 hash](./controlled-ab/builds.json), [검산](./verification.json).

## 반복별 결과

| 버전 | VU | 반복 | 테스트 | 요청 | 평균 ms | p95 ms | p99 ms | TPS | 오류 | 관측 초 | 이력 증가 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| OR / 새 복합 인덱스 없음 | 10 | 1 | [535](./controlled-ab/before-or/raw/load-vu10-r1/summary.json) | 1,000 | 598.37 | 753.97 | 863.02 | 16.73 | 0 | 60.06 | 1,000 |
| OR / 새 복합 인덱스 없음 | 30 | 1 | [536](./controlled-ab/before-or/raw/load-vu30-r1/summary.json) | 3,000 | 1,650.80 | 2,159.80 | 2,390.04 | 18.06 | 0 | 166.84 | 3,000 |
| OR / 새 복합 인덱스 없음 | 10 | 2 | [537](./controlled-ab/before-or/raw/load-vu10-r2/summary.json) | 1,000 | 554.04 | 644.98 | 698.49 | 17.98 | 0 | 55.57 | 1,000 |
| OR / 새 복합 인덱스 없음 | 30 | 2 | [538](./controlled-ab/before-or/raw/load-vu30-r2/summary.json) | 3,000 | 1,580.60 | 2,100.36 | 2,279.86 | 18.79 | 0 | 160.01 | 3,000 |
| OR / 새 복합 인덱스 없음 | 10 | 3 | [539](./controlled-ab/before-or/raw/load-vu10-r3/summary.json) | 1,000 | 546.53 | 633.88 | 683.12 | 17.86 | 0 | 54.75 | 1,000 |
| OR / 새 복합 인덱스 없음 | 30 | 3 | [540](./controlled-ab/before-or/raw/load-vu30-r3/summary.json) | 3,000 | 1,620.60 | 2,134.40 | 2,451.51 | 18.36 | 0 | 163.46 | 3,000 |
| 복합 인덱스 + AND | 10 | 1 | [543](./controlled-ab/after-index-and/raw/load-vu10-r1/summary.json) | 1,000 | 93.26 | 206.82 | 311.52 | 109.37 | 0 | 9.44 | 1,000 |
| 복합 인덱스 + AND | 30 | 1 | [544](./controlled-ab/after-index-and/raw/load-vu30-r1/summary.json) | 3,000 | 90.29 | 141.76 | 190.32 | 340.44 | 0 | 9.23 | 3,000 |
| 복합 인덱스 + AND | 10 | 2 | [545](./controlled-ab/after-index-and/raw/load-vu10-r2/summary.json) | 1,000 | 30.17 | 46.54 | 73.55 | 235.13 | 0 | 3.14 | 1,000 |
| 복합 인덱스 + AND | 30 | 2 | [546](./controlled-ab/after-index-and/raw/load-vu30-r2/summary.json) | 3,000 | 83.35 | 130.13 | 180.89 | 344.47 | 0 | 8.49 | 3,000 |
| 복합 인덱스 + AND | 10 | 3 | [547](./controlled-ab/after-index-and/raw/load-vu10-r3/summary.json) | 1,000 | 25.97 | 37.92 | 50.36 | 499.75 | 0 | 2.69 | 1,000 |
| 복합 인덱스 + AND | 30 | 3 | [548](./controlled-ab/after-index-and/raw/load-vu30-r3/summary.json) | 3,000 | 75.41 | 119.78 | 143.26 | 336.36 | 0 | 7.73 | 3,000 |

## SQL·인덱스 증거

| 확인 항목 | OR / 새 복합 인덱스 없음 | 복합 인덱스 + AND |
|---|---:|---:|
| 실제 content SQL의 Block NOT EXISTS 수 | 1 | 2 |
| 별도 10요청의 content SELECT / 게시글 count SELECT | 10 / 0 | 10 / 0 |
| 새 복합 인덱스 생성 | 없음 | 있음 |
| Block 조건만 추출한 EXPLAIN ANALYZE에서 새 인덱스 사용 | 없음 | 확인 |
| 진단 content SELECT 평균 DB 시간 ms | 175.07 | 9.95 |

`idx_block_blocker_blocked_deleted(blocker_id, blocked_id, is_deleted)`를 H2 실제 스키마에서 확인했다. 기존 단일 FK 인덱스는 두 버전 모두 존재한다. OR를 분리해 각 방향의 존재 여부를 별도로 검사하고 두 NOT EXISTS를 AND로 묶었다. 위 실행 계획은 차단 조건을 추출한 읽기 전용 쿼리이며 API 전체 실행 계획과 구분한다. 진단 DB 시간은 HTTP 지연 전체와 같지 않다. Query statistics는 부하 종료 후 진단 때만 켜고 종료 후 껐다.
[Before SQL·계획](./controlled-ab/before-or/sql-diagnostics/block-plan.json), [After SQL·계획](./controlled-ab/after-index-and/sql-diagnostics/block-plan.json), [After 인덱스 스키마](./controlled-ab/after-index-and/block-index-schema.json).

## 추가 지속 관측

개선 후 비교 실행은 약 2.7~9.4초로 짧아져 별도 새 seed/JVM에서 현재 버전을 길게 관측했다. 전후 개선율은 위 3회 반복 기준으로 유지했다. 추가 실행의 워밍업은 1 VU×20 + 30 VU×200이다.

| VU | 요청 | 관측 초 | 평균 ms | p95 ms | p99 ms | Controller TPS | 표본 성공 RPS | 오류 | 이력 증가 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 | 34,950 | 97.84 | 82.35 | 123.78 | 171.07 | 358.07 | 357.18 | 2 | 34,948 |

[지속 관측 원본](./current-steady.json), [추가 CSV](./steady-summary.csv).

추가 실행에서 SocketTimeoutException 2건(0.0057%)이 발생했다. 두 worker 모두 iteration=1000에서 약 5.04/5.65초 후 HTTP status=0으로 실패했으며, 전체 검색 이력 증가는 34,948/34,950건이다. 정확한 타임아웃 단계는 확인하지 못했다. 지연·처리율 통계는 성공 요청 기준이다. [오류 표본](./controlled-ab/current-steady/raw/steady-observation-vu30-r1/failure-analysis.json).

## 해석과 기록

- 위 개선율은 인덱스 추가와 차단 조건 변경을 합친 효과다. 인덱스만/조건만 각각의 기여도는 분리 측정하지 않았다. 두 버전 모두 Slice/count 제거를 유지한다.
- 동일 호스트의 H2·고정 seed·첫 페이지·폐쇄형 10/30 VU 결과다. 운영 DB의 실행 계획이나 최대 처리 용량을 나타내지 않는다. Before→After 실행 순서에 따른 JIT/캐시·호스트 점유 변화와 검색 이력 누적 영향이 남는다.
- 특히 After 10 VU는 관측 2.69~9.44초, Controller TPS 109.37~499.75로 편차가 크다. TPS는 Controller 종료 통계값이며 초기 연결·JIT와 2초 샘플 간격의 영향을 함께 받는다. 현재 처리율 해석에는 30 VU 반복과 추가 지속 관측도 함께 사용한다.
- 실제 DDL과 인덱스 사용은 H2 create-drop 환경에서 확인했다. 운영 DB에 이 인덱스가 적용됐는지는 이번 측정에 포함하지 않았다.

- 본 부하 24,000요청에서 오류 0건이며, 검색 이력 증가량도 모든 요청과 일치했다.

일상 확인은 이 보고서와 [summary.csv](./summary.csv), [comparison.json](./comparison.json)으로 가능하다. 개별 요청 CSV·Controller JSON은 `controlled-ab/<버전>/raw/`, 서버 지표는 각 `telemetry.jsonl` 및 [지표 요약](./telemetry-summary.json), 재현 자료는 `execution/`에 보관했다. Controller 설정·측정 토큰·직접 띄운 서버 정리 결과는 각 `cleanup.json`에 기록했다. [직전 count 제거 보고서](../2026-10-07-authenticated-search-count-removal/report.md).
