# 인증 게시글 검색 — count 제거 전후 측정

대상: [RoommateBoardListKeywordGetTest.groovy](./execution/deployed-scripts/RoommateBoardListKeywordGetTest.groovy), `GET /roommate/boards?keyword=부하 테스트 게시글`, 인증 프로필 `search-frequent-authenticated`.

현재 소스의 count/Page 버전과 Slice 버전을 같은 조건에서 비교했다. 아래 평균·p95·p99·TPS는 **반복별 수치의 중간값**이며, p95를 여러 실행에 걸쳐 평균하거나 합친 값이 아니다. 오류율은 해당 VU의 전체 요청 기준이다.

| VU | 반복 전/후 | 평균 ms 전→후 | 평균 감소 | p95 ms 전→후 | p95 감소 | p99 ms 전→후 | TPS 전→후 | TPS 증가 | 오류율 % 전→후 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 3/3 | 751.62 → 318.32 | 57.65% | 1,082.75 → 441.34 | 59.24% | 1,304.59 → 597.47 | 12.89 → 30.31 | 135.14% | 0.00 → 0.00 |
| 30 | 3/3 | 2,168.31 → 885.24 | 59.17% | 3,498.41 → 1,453.30 | 58.46% | 4,054.72 → 2,040.05 | 13.54 → 31.37 | 131.68% | 0.71 → 0.01 |

## 조건과 판정

- 측정: `2026-10-07T17:36:09.182942+09:00` ~ `2026-10-07T18:09:49.669323+09:00`. Java 21·기본 tiered compilation·`-Xms512m -Xmx2g`, Spring test/H2, 동일 호스트. 별도 측정 포트 18080. SQL 및 실행 시간 Aspect 출력 OFF.
- count 유무에 따라 달라진 5개 Java 파일 외 소스/의존성은 같다. Before는 현재 HEAD의 Page/count 구현, After는 사용자의 미커밋 Slice 수정본이다. Slice는 21건을 조회하고 20건을 반환해 hasNext를 계산한다. [소스 변경](./execution/count-removal-source.patch), [빌드 hash](./controlled-ab/builds.json).
- 각 버전에서 새 H2 seed1000을 생성했다. 회원 2,004·게시글 1,002·차단 1,001·초기 검색 이력 1,005건. 동일 회원 ID 5~34를 VU별로 배정하고 동일 검색어·첫 페이지(size 20, createdAt DESC)를 사용했다. 첫 페이지 게시글 ID도 일치했다.
- Agent 1·process 1, 10/30 threads×100회, 각 3반복 완료(본 부하 총 24,000요청). 공통 워밍업은 1 VU×20회 + 10 VU×50회, 단계 간 15초. connect/socket 설정 5/15초, connectionReset=false, ramp-up=false.
- 기본 부하 판정은 HTTP 200/통신 성공이다. 응답 형태 검증은 측정에서 끄고 Page/Slice 여부·반환 ID와 실행 SQL은 별도 확인했다. 지연은 성공한 개별 GET 종료까지이며 CSV 기록/검증 시간은 제외된다.
- 표본·worker 수와 Controller 성공/오류 건수, 회원+검색어별 검색 이력 증가량을 대조했다. 기존 검색 이력은 삭제하지 않고 같은 순서로 누적했다. [검산](./verification.json), [전체 실행 CSV](./summary.csv).

## 반복별 원본 수치

| 버전 | VU | 반복 | 테스트 | 요청 | 평균 ms | p95 ms | p99 ms | TPS | 오류 | 관측 초 | 이력 증가 | 판정 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Count 있음 | 10 | 1 | [519](./controlled-ab/before-count/raw/load-vu10-r1/summary.json) | 1,000 | 1,124.52 | 1,361.29 | 1,437.38 | 8.85 | 0 | 112.61 | 1,000 | PASS |
| Count 있음 | 30 | 1 | [520](./controlled-ab/before-count/raw/load-vu30-r1/summary.json) | 3,000 | 3,519.71 | 4,552.95 | 5,152.53 | 8.17 | 64 | 359.14 | 3,000 | 오류 있음 |
| Count 있음 | 10 | 2 | [521](./controlled-ab/before-count/raw/load-vu10-r2/summary.json) | 1,000 | 751.62 | 1,082.75 | 1,304.59 | 12.89 | 0 | 77.67 | 1,000 | PASS |
| Count 있음 | 30 | 2 | [522](./controlled-ab/before-count/raw/load-vu30-r2/summary.json) | 3,000 | 2,141.00 | 3,498.41 | 4,036.19 | 13.72 | 0 | 218.72 | 3,000 | PASS |
| Count 있음 | 10 | 3 | [523](./controlled-ab/before-count/raw/load-vu10-r3/summary.json) | 1,000 | 714.75 | 979.39 | 1,150.68 | 13.93 | 0 | 72.60 | 1,000 | PASS |
| Count 있음 | 30 | 3 | [524](./controlled-ab/before-count/raw/load-vu30-r3/summary.json) | 3,000 | 2,168.31 | 3,423.34 | 4,054.72 | 13.54 | 0 | 221.10 | 3,000 | PASS |
| Slice | 10 | 1 | [527](./controlled-ab/after-slice/raw/load-vu10-r1/summary.json) | 1,000 | 324.37 | 463.95 | 643.95 | 29.83 | 0 | 32.87 | 1,000 | PASS |
| Slice | 30 | 1 | [528](./controlled-ab/after-slice/raw/load-vu30-r1/summary.json) | 3,000 | 927.75 | 1,453.30 | 2,526.09 | 30.98 | 0 | 97.13 | 3,000 | PASS |
| Slice | 10 | 2 | [529](./controlled-ab/after-slice/raw/load-vu10-r2/summary.json) | 1,000 | 300.67 | 424.22 | 597.47 | 32.30 | 0 | 30.37 | 1,000 | PASS |
| Slice | 30 | 2 | [530](./controlled-ab/after-slice/raw/load-vu30-r2/summary.json) | 3,000 | 872.04 | 1,352.24 | 1,957.52 | 32.97 | 0 | 89.86 | 3,000 | PASS |
| Slice | 10 | 3 | [531](./controlled-ab/after-slice/raw/load-vu10-r3/summary.json) | 1,000 | 318.32 | 441.34 | 579.64 | 30.31 | 0 | 32.44 | 1,000 | PASS |
| Slice | 30 | 3 | [532](./controlled-ab/after-slice/raw/load-vu30-r3/summary.json) | 3,000 | 885.24 | 1,518.65 | 2,040.05 | 31.37 | 1 | 95.06 | 2,999 | 오류 있음 |

## count 제거 실행 증거

| 별도 진단 10요청 | Count 있음 | Slice |
|---|---:|---:|
| 게시글 content SELECT 실행 | 10 | 10 |
| 게시글 count SELECT 실행 | 10 | 0 |
| 검색 이력 INSERT 증가 | 10 | 10 |
| content SQL 누적 ms | 1,337.41 | 1,266.89 |
| count SQL 누적 ms | 1,255.90 | 0 |

H2 query statistics는 부하 종료 후 진단 구간에서만 켰고 종료 후 껐다. content/count 실행 증분과 검색 저장 증분을 확인했다. 진단 SQL 시간은 DB 실행 시간이며 HTTP 지연 전체와 같지 않다. [Before SQL](./controlled-ab/before-count/sql-diagnostics/summary.json), [After SQL](./controlled-ab/after-slice/sql-diagnostics/summary.json).

## 과거 전체 시험과의 참고 비교

| VU | 2026-10-04 평균 ms | 현재 Slice 평균 ms | 관측 감소 | 과거 p95 ms | 현재 p95 ms | 과거 TPS | 현재 TPS |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 1,179.26 | 318.32 | 73.01% | 1,375.17 | 441.34 | 8.48 | 30.31 |
| 30 | 3,341.59 | 885.24 | 73.51% | 4,528.11 | 1,453.30 | 8.54 | 31.37 |

과거 시험은 1회 탐색이며 다른 시점의 빌드·워밍업·JVM/힙 조건을 사용했다. count 제거의 개선율은 위의 동일 조건 전후 비교를 기준으로 삼고, 이 표는 참고 자료로만 사용한다. [이전 보고서](../2026-10-04-entire-test/report.md), [비교 값](./historical-comparison.json).

## 한계와 기록

- 동일 호스트의 H2·고정 데이터·반복 3회의 결과다. 실제 운영 PostgreSQL의 용량이나 무한 스크롤 전체 페이지의 성능을 보증하지 않는다. 조회 content 비용·차단 조건·검색 이력 저장 비용은 여전히 포함된다.
- Before 30 VU 1회차에 SocketTimeoutException 64건, Slice 30 VU 3회차에 1건이 발생했다. Before 이력 증가는 3,000/3,000건, 해당 Slice 실행은 2,999/3,000건이었다. Slice 오류는 한 worker의 첫 GET에서 약 5.14초 후 발생했으며, 연결/응답 중 정확한 타임아웃 단계는 로그만으로 확정할 수 없다. [Before 오류](./controlled-ab/before-count/raw/load-vu30-r1/failure-analysis.json), [Slice 오류](./controlled-ab/after-slice/raw/load-vu30-r3/failure-analysis.json).
- 지연 통계는 성공 요청 기준이므로 오류율과 함께 봐야 한다. 전체 요청 CSV·Controller 건수는 검산 완료했지만 Slice 마지막 실행의 이력 전체 요청 일치 판정은 실패했다. verification.json에서 수집 완료(measurementComplete)와 모든 실행 무오류(allPassed), 이력 일치 여부를 구분한다.
- 반복은 Before→After 순서로 실행했다. 통제한 코드/데이터/JVM/로그 조건 외 호스트 점유 변화, JIT/캐시, 새 worker 초기 연결 비용과 검색 이력 누적의 영향이 남아 있다. 실행별 편차와 관측 길이는 CSV에 남겼다.
- IDE 예비 시험 513/514는 SQL 출력 ON·`TieredStopAtLevel=1`이라 개선율 계산에서 제외하고 `excluded-ide-preliminary/`에 보존했다. [당시 JVM 증거](./excluded-ide-preliminary/runtime-evidence.json), [예비 판정](./excluded-ide-preliminary/preliminary-verdict.json). 별도 SQL 로거가 켜진 준비 시도 515/516과 시드 사전 검증 보정 기록도 `controlled-ab/excluded-*`에 보존하고 본 측정에서 제외했다.
- Controller 원래 설정을 복원하고 측정용 토큰 및 직접 띄운 서버를 정리했다. 기존 개발 서버는 측정 시점의 실행 상태를 유지했다. [Before 정리](./controlled-ab/before-count/cleanup.json), [After 정리](./controlled-ab/after-slice/cleanup.json).
- 일상 확인은 이 보고서·`summary.csv`·`comparison.json`만 보면 된다. 개별 요청 CSV와 Controller JSON은 각 `controlled-ab/<버전>/raw/`, 서버 지표는 `telemetry.jsonl`과 [지표 요약](./telemetry-summary.json), 실행/빌드 재현 자료는 `execution/`에 있다. JWT·서명 키는 결과 자료에 포함하지 않았다.
