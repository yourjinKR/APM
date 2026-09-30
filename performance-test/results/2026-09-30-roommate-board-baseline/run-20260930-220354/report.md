# 게시글 목록·검색 탐색 기준선

필터·페이지·검색 fixture를 실제 Agent에서 검증하고, 워밍업과 본 측정을 분리했다. 아래 결과는 현재 로컬 H2 환경의 탐색 기준선이다. 애플리케이션 성능 로직은 변경하지 않았다.

유효 본 측정 18회에서 성공 5,400건·오류 0건이며 검색 이력 증가 2,700건을 요청 수와 대조했다. 초기 worker 경쟁 조건 시험은 이 합계에서 제외한다.

## 조건과 fixture

- 이전 smoke와 동일 JAR SHA256, Java 21, `test`/H2, 시드 1,000건(게시글 1,002건), SQL 로그 비활성화, timeout 5초다. nGrinder Agent Java 11·`3.5.9-p1`을 사용한다.
- Controller/Agent와 백엔드가 같은 Windows 호스트의 자원을 공유한다. 다른 작업의 호스트 부하를 완전히 통제하지 못했으므로 운영 환경 성능으로 외삽하지 않는다.
- 지역/방 유형 fixture는 DB에서 조회했다. 전체 17개 프로필에 DB 기반 기대 count를 넣었다. 관심 시드 회원 3은 전체 부하 데이터 회원과 차단 관계여서 양성 fixture로 사용할 수 없었다. 시험 DB에 회원 2/게시글 3의 관심 관계 한 건을 추가했고, 토큰 풀에서 회원 3을 제외했다. 모든 반복에서 같은 관계를 유지했다.
- 검색 이력은 초기 1,005건을 보존하고 각 시험에서 신규 생성한 시험 회원의 행만 정리했다. 각 회차의 시작 행 수/분포는 동일하다. identity sequence와 DB 내부 물리 상태를 재생성하지는 않았다.
- fixture는 각각 1 VU×3회, 워밍업은 주 경로별 1 VU×30회, 본 측정은 1→3→5 VU×회원별 100회×3반복 계획이다. 요청 오류·계약 오류·표본 누락·검색 저장 증분 불일치 시 남은 반복과 상위 단계는 중단한다. 워밍업/fixture는 기준선 집계에서 제외한다.
- 매 실행마다 Agent worker를 새로 생성한다. 별도 워밍업은 서버/JIT 워밍업이며 첫 클라이언트 연결 비용은 본 요청에 포함될 수 있다.
- 최초 3 VU 시험 318은 worker의 출력 폴더 동시 생성 경쟁 조건으로 1개 worker만 동작했다. 원본을 보존하고 정상 기준선에서 제외했다. `Files.createDirectories`로 수정 후 두 경로를 3 VU×3회(각 9건)로 검증하고 3→5 VU 측정을 재개했다. 변경은 HTTP 실행/검증/측정 구간 밖의 worker 초기화에 한정되므로 완료된 1 VU 기준선은 유지했다. [원인과 판정](./harness-diagnosis.json), [당시 worker/Controller 증거](./baseline-list-anonymous-vu3-r1/controller-artifacts/).

## 프로필 검증

| 프로필 | 기대 count | 성공/오류 | 검색 이력 Δ | 판정 |
|---|---:|---:|---:|---|
| list-anonymous | 1002 | 3/0 | 0 | 통과 |
| list-authenticated | 1002 | 3/0 | 0 | 통과 |
| filter-region | 18 | 3/0 | 0 | 통과 |
| filter-room-type | 202 | 3/0 | 0 | 통과 |
| filter-budget | 252 | 3/0 | 0 | 통과 |
| filter-gender | 500 | 3/0 | 0 | 통과 |
| filter-combined | 4 | 3/0 | 0 | 통과 |
| liked-authenticated | 1 | 3/0 | 0 | 통과 |
| page-1 | 1002 | 3/0 | 0 | 통과 |
| page-deep | 1002 | 3/0 | 0 | 통과 |
| size-100 | 1002 | 3/0 | 0 | 통과 |
| sort-hits | 1002 | 3/0 | 0 | 통과 |
| search-frequent-anonymous | 1000 | 3/0 | 0 | 통과 |
| search-frequent-authenticated | 1000 | 3/0 | 3 | 통과 |
| search-rare-authenticated | 1 | 3/0 | 3 | 통과 |
| search-zero-authenticated | 0 | 3/0 | 3 | 통과 |
| search-combined-authenticated | 4 | 3/0 | 3 | 통과 |

## 반복 측정

평균/p95/p99/TPS는 **성공한 반복별 값의 중앙값(최소~최대)**다. 실패 실행을 제외한 숫자가 전체 정상 성능을 뜻하지 않으므로 완료/통과 회수와 오류를 함께 확인한다.

| 프로필 | VU | 완료/통과 반복 | 성공/오류 | 평균 ms | p95 ms | p99 ms | Controller TPS | 검색 이력 Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| list-anonymous | 1 | 3/3 | 300/0 | 40.72 (35.93~42.70) | 71.05 (62.24~74.98) | 115.97 (91.47~124.42) | 23.40 (23.22~24.42) | 0 |
| list-anonymous | 3 | 3/3 | 900/0 | 35.88 (29.44~71.09) | 65.03 (48.69~155.46) | 109.21 (63.29~258.68) | 71.60 (34.67~73.35) | 0 |
| list-anonymous | 5 | 3/3 | 1500/0 | 47.31 (17.68~57.56) | 84.76 (27.64~93.87) | 120.13 (44.95~121.17) | 79.76 (76.93~250.00) | 0 |
| search-frequent-authenticated | 1 | 3/3 | 300/0 | 809.86 (792.31~832.10) | 957.56 (956.08~989.96) | 1066.58 (1014.91~1118.44) | 1.24 (1.21~1.27) | 300 |
| search-frequent-authenticated | 3 | 3/3 | 900/0 | 998.69 (969.01~1041.12) | 1264.30 (1254.67~1429.22) | 1469.17 (1440.59~1611.42) | 2.99 (2.89~3.07) | 900 |
| search-frequent-authenticated | 5 | 3/3 | 1500/0 | 753.11 (721.45~1543.76) | 1919.45 (1677.99~2228.51) | 2406.84 (1889.16~2557.50) | 6.84 (3.26~7.06) | 1500 |

중단: 시험한 모든 예정 단계 완료.

## 실행별 자원 관측

CPU는 해당 구간 표본의 최대값, GC는 경계 밖 인접 표본 사이의 근사 증가량이다. 10초 간격에 scrape/stats 시간이 추가돼 순간 peak를 놓칠 수 있다. Docker CPU는 코어 기준 합산 비율이므로 JVM/system CPU와 수치 기준이 다르다.

| ID | 프로필/VU/회차 | 호스트 CPU max % | JVM CPU max % | Hikari active/pending max | GC pause 근사 초 | 오류 |
|---:|---|---:|---:|---:|---:|---:|
| 312 | list-anonymous/1/1 | — | — | —/— | 0.03 | 0 |
| 313 | search-frequent-authenticated/1/1 | 54.93 | 16.21 | 1.00/0.00 | 0.17 | 0 |
| 314 | list-anonymous/1/2 | 73.06 | 7.80 | 1.00/0.00 | 0.01 | 0 |
| 315 | search-frequent-authenticated/1/2 | 61.18 | 16.46 | 1.00/0.00 | 0.15 | 0 |
| 316 | list-anonymous/1/3 | — | — | —/— | 0.01 | 0 |
| 317 | search-frequent-authenticated/1/3 | 49.06 | 16.01 | 1.00/0.00 | 0.16 | 0 |
| 321 | list-anonymous/3/1 | 62.91 | 24.87 | 3.00/0.00 | 0.05 | 0 |
| 322 | search-frequent-authenticated/3/1 | 71.02 | 34.96 | 3.00/0.00 | 0.32 | 0 |
| 323 | list-anonymous/3/2 | 53.49 | 1.02 | 0.00/0.00 | 0.02 | 0 |
| 324 | search-frequent-authenticated/3/2 | 74.15 | 32.93 | 3.00/0.00 | 0.31 | 0 |
| 325 | list-anonymous/3/3 | 48.86 | 32.73 | 0.00/0.00 | 0.03 | 0 |
| 326 | search-frequent-authenticated/3/3 | 66.22 | 31.03 | 3.00/0.00 | 0.30 | 0 |
| 327 | list-anonymous/5/1 | 70.32 | 26.15 | 5.00/0.00 | 0.04 | 0 |
| 328 | search-frequent-authenticated/5/1 | 67.47 | 37.63 | 5.00/0.00 | 0.47 | 0 |
| 329 | list-anonymous/5/2 | 83.45 | 14.92 | 3.00/0.00 | 0.04 | 0 |
| 330 | search-frequent-authenticated/5/2 | 97.78 | 59.58 | 5.00/0.00 | 0.29 | 0 |
| 331 | list-anonymous/5/3 | — | — | —/— | 0.02 | 0 |
| 332 | search-frequent-authenticated/5/3 | 96.52 | 60.26 | 5.00/0.00 | 0.20 | 0 |

## 해석 범위와 다음 진단

반복 편차가 커 최적화 전후 비교의 확정 기준선으로는 추가 보강이 필요하다.
- list-anonymous의 5 VU TPS 범위는 76.93~250.00다. 실행 편차를 숨기고 중앙값만 확정 성능으로 사용하지 않는다.
- search-frequent-authenticated의 5 VU TPS 범위는 3.26~7.06다. 실행 편차를 숨기고 중앙값만 확정 성능으로 사용하지 않는다.
- list-anonymous의 실제 GET 표본 구간은 1.99~7.30초다. 짧은 기본 목록 시험은 자원 표본이 0~1개여서 자원과 지연의 연관성을 충분히 평가할 수 없다.
- search-frequent-authenticated의 실제 GET 표본 구간은 72.44~154.76초다. 짧은 기본 목록 시험은 자원 표본이 0~1개여서 자원과 지연의 연관성을 충분히 평가할 수 없다.
- 관측 호스트 CPU 최대 97.78%, Hikari pending 최대 0이다. 순간값 누락과 공유 호스트 영향이 있어 특정 SQL·검색 INSERT·CPU 중 하나를 원인으로 확정하지 않는다.

- 1 VU 회당 100건은 안정된 p99 평가에 부족하다. 기본 경로와 인증 검색은 조회 결과 범위 및 인증 조건도 달라 두 숫자의 차이를 검색 INSERT 비용으로 단정할 수 없다.
- 지연/처리량 포화가 관측되면 개별 content/count SQL과 실행계획을 별도 구간에서 수집하고, 익명 검색·키워드 없는 인증 조회 대조군을 동일 부하로 측정한다. H2 상관 서브쿼리·차단 조건·CPU/GC·Agent 자원 가설은 해당 증거와 대조한다.
- 오류 구간은 `request-samples/`의 실패 유형과 worker 로그를 대조한다. timeout 뒤 DB commit이 가능하므로 성공 요청 수만으로 이력 저장 여부를 추정하지 않는다.
- 정상 조건은 더 긴 정상 구간과 반복 표본으로 보강하고 실제 대상 DB의 고정 snapshot에서도 확인한 뒤 최적화 전후를 비교한다.

## 원본과 재실행

- [환경](./environment.json), [측정 계획](./measurement-plan.json), [fixture snapshot](./fixture-snapshot.json), [fixture 설정](./fixture-config.json), [배포](./deployment.json).
- [전체 실행 요약](./suite-summary.json), [CSV 요약](./summary.csv), [반복·자원 분석](./baseline-analysis.json), [자원 표본](./telemetry.jsonl).
- 각 조건 폴더의 `deployed-config.json`, `created.json`, `test.json`, `basic-report.json`, `request-samples/`에 요청별 원본과 실제 Controller 설정을 보관한다. `backend.out.log`/`backend.err.log`는 시험 서버 로그다.
- [측정 실행기](../../../tools/run-roommate-board-baseline.py), [이 집계기](../../../tools/summarize-roommate-board-baseline.py). 실행기는 전용 로컬 H2 seed1000 서버를 대상으로 하며 fixture INSERT·시험 이력 DELETE를 수행한다. 기존 운영 DB/외부 대상에서는 사용하지 않는다.
- [정리 확인](./cleanup.json)에 Agent 임시 토큰 파일 삭제·Controller 설정 템플릿 복원을 기록한다. 재개 시 직접 기동했던 백엔드 PID와 8080 리스너가 이미 종료된 것을 확인했고, 확인 시각을 환경 기록에 남겼다. 실제 종료 시각은 확인하지 못했다.
