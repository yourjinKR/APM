# 게시글 목록·검색 실제 smoke 결과

2026-09-30에 APM 기준 스크립트를 Controller에 배포하고 기본 조회·검색의 익명/인증 네 조건을 실제 Agent에서 검증했다. 네 조건 모두 1 Agent × 1 process × 1 thread × 3회 요청으로 완료됐다. 오류 0건, 누락 0건이며 인증 검색에서만 검색 기록이 3건 증가했다.

| 프로필 | Controller ID | 설정 리비전 | 성공 | 오류 | CSV 표본 | 검색 이력 Δ | GET 평균 ms | 판정 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| list-anonymous | 289 | 38 | 3 | 0 | 3 | 0 | 128.178 | 통과 |
| list-authenticated | 290 | 39 | 3 | 0 | 3 | 0 | 771.979 | 통과 |
| search-frequent-anonymous | 291 | 40 | 3 | 0 | 3 | 0 | 383.647 | 통과 |
| search-frequent-authenticated | 292 | 41 | 3 | 0 | 3 | 3 | 917.737 | 통과 |

3개 표본의 평균은 이번 실행의 참고값이다. 워밍업과 반복 기준선·자원 계측을 수행하지 않았으므로 p95/p99·처리량 한계나 성능 개선률을 판단하지 않는다. 과거 측정과 SQL 로그·빌드·호스트 부하 등의 조건이 같지 않아 직접 비교할 수 없다.

## 환경과 수행 내용

- 현재 백엔드 소스를 Java 21로 새로 빌드했다. `test` 프로필, H2 메모리 DB, `seed.load-test.records-per-entity=1000`, `spring.jpa.show-sql=false`로 기동했다. 게시글 총 1,002건이다.
- 백엔드 커밋은 `9dbc58399c83ee7679d8d00b17c97048ec66b324`다. 기존 사용자의 test.properties 변경은 유지했고 시드/SQL 로그는 기동 인자로 지정했다. JAR SHA256과 실행 설정은 [환경 원본](./run-20260930-213025/environment.json)에 기록했다.
- nGrinder Controller/Agent `3.5.9-p1`, Agent Java 11을 사용했다. Agent에서 `http://host.docker.internal:8080`으로 요청하며 connect/socket timeout은 각각 5초다.
- 회원 ID 2~11의 로컬 시험 토큰을 메모리에서 발급하고 Agent 전용 파일로 임시 전달했다. 토큰·서명 키는 결과/저장소에 기록하지 않았다. Agent 환경 변수를 바꾸지 않도록 공통 helper에 JSON `tokenFile` 경로 대체 설정을 추가했다.
- `search-frequent-*`는 `부하 테스트 게시글` 검색어를 사용했다. 시험 전후 읽기 전용 SQL로 전체 SEARCH 수와 시험 회원·검색어의 수를 확인했다. 전체 SEARCH가 1,005→1,008건으로 증가했고 해당 회원·검색어는 0→3건이다. 앞선 세 조건에서는 두 값 모두 변하지 않았다.
- 각 worker CSV 3건과 manifest를 수집했다. 집계기는 기대 3요청·1worker와 Controller 성공/오류 수를 대조했다.

## 배포와 원본

- [스크립트·helper 배포 리비전과 SHA256](./run-20260930-213025/deployment.json): 기본 조회 35, 검색 36, helper 37.
- [네 조건의 완료 상태·DB 증분·누락 판정](./run-20260930-213025/smoke-summary.json), [회원·데이터 사전 확인](./run-20260930-213025/preflight.json).
- 조건별 폴더에는 `deployed-config.json`, `created.json`, `test.json`, `basic-report.json`, `request-samples/`를 보관했다. 설정 리비전은 38~41이다. `execution/run-roommate-smoke.py`는 이번 실행에 사용한 조정 코드의 증거본이며 새 관리용 실행기는 아니다.
- [정리 확인](./run-20260930-213025/cleanup.json): 모든 Agent의 임시 토큰 파일 삭제를 확인했고, Controller JSON은 APM의 `CHANGE-ME` 기준 템플릿으로 복원했다. 재실행 전 runId·프로필·토큰 경로를 새로 설정해야 한다. 이번에 직접 기동한 백엔드는 종료했으며 종료 시각은 환경 원본에 기록했다.

## 다음 단계

1. 고정 데이터에서 지역·방 유형·예산·페이지 등 나머지 프로필 fixture를 확보하고 1 VU로 계약을 확인한다. 이번 네 조건 통과가 17개 프로필의 정합성을 대신하지 않는다.
2. 워밍업을 분리하고 1→3→5 VU 기준선을 동일 조건 3회씩 탐색한다. 오류 발생 시 상위 부하는 중단한다. 검색 조건은 각 회차의 초기 검색 이력도 맞춘다.
3. 개별 요청 지연·Controller TPS·서버/Agent CPU·GC·DB 대기·쿼리를 함께 기록해 병목을 찾는다. 안정된 조건에서 표본/정상 구간을 늘린 후 개선 전후를 비교한다.

실행 절차는 [게시글 목록·검색 측정 가이드](../../docs/roommate-board-list-testing.md)를 따른다. 이번에 백엔드 성능 로직은 변경하지 않았다. 기존 Python 집계기 테스트 4개도 통과했다.
