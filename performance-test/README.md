# 성능 테스트 산출물 인덱스

APM 저장소가 성능 테스트 산출물의 관리 기준이다. 모든 명령 예시는 APM 저장소 루트에서 실행한다. KnockIn의 `doc/test/perf/README.md`는 이곳으로 연결하는 안내만 유지한다.

| 관리 대상 | 위치 | 시작 문서 |
|---|---|---|
| 실행 가능한 nGrinder 스크립트 | `script/<도메인>/` | [스크립트 인덱스](./script/README.md) |
| 게시글 목록·검색 프로필과 공통 코드 | `script/roommate/resources/` | [측정 가이드](./docs/roommate-board-list-testing.md) |
| 실행·집계·검증 도구 | `tools/`, `tools/tests/` | 아래 도구 안내 |
| 계획·시나리오·환경·작업 기록 | `docs/` | [계획](./docs/plan.md), [시나리오](./docs/scenarios.md), [환경](./docs/apm-environment.md), [작업 일지](./docs/load-test-journal.md) |
| 측정 원본·분석·레포트 | `results/<측정일-주제>/` | 아래 측정 기록 |

## 게시글 목록·검색

- [기본·필터 조회](./script/roommate/RoommateBoardListGetTest.groovy), GTest 4101.
- [검색 조회](./script/roommate/RoommateBoardListKeywordGetTest.groovy), GTest 4104. 인증 검색은 검색 기록 저장을 포함한다.
- [17개 조건별 프로필](./script/roommate/resources/roommate-board-list.json), [설정·측정·전후 비교 가이드](./docs/roommate-board-list-testing.md).

목록·검색은 기본적으로 HTTP 상태/통신만 판정한다. 응답 계약은 `responseValidator`로 선택하며, 설정과 UI 준비 명령은 [UI 가이드](./docs/ngrinder-ui-testing.md)를 따른다.

Controller에 실행 스크립트와 같은 폴더의 resources를 함께 등록한다. 코드/설정 변경은 이 저장소에서 수행한 후 Controller에 반영하고 리비전을 기록한다. Controller runtime volume과 KnockIn에 수정용 복사본을 별도로 관리하지 않는다.

## 실행·집계·검증

```bash
bash performance-test/tools/run-ngrinder-load-stages.sh --help
python performance-test/tools/summarize-roommate-board-samples.py --help
python performance-test/tools/run-roommate-board-baseline.py --help
python performance-test/tools/summarize-roommate-board-baseline.py --help
python -B -m unittest discover -s performance-test/tools/tests -p "test_*.py"
```

H2 시드별 자동 기동·측정은 `performance-test/tools/run-read-sequential.ps1`을 사용한다. 소스 빌드가 필요하면 `-BackendProject C:/dev/workspace/KnockIn/back/11th-1team-BE`를 명시하고, 기존 JAR은 `-JarPath`로 지정한다. 기존 서버에 대한 측정에는 백엔드 소스 경로가 필요 없다. 생성 결과와 관리형 서버 로그는 `results/` 아래로 모인다.

Groovy 오프라인 smoke는 `performance-test/script/roommate/`를 작업 디렉터리로 하고 `../../tools/tests/roommate-board-support-smoke.groovy <새 임시 결과 경로>`를 실행한다. 실제 Agent 라이브러리를 classpath에 넣고 `ROOMMATE_BOARD_RUN_ID=offline-smoke`, 테스트용 `ROOMMATE_BOARD_TOKENS=fake0,fake1,fake2,fake3`를 제공한다. 이 토큰은 오프라인 검증 전용이며 실제 API 부하에는 사용할 수 없다.

`run_test.sh`는 저장된 Controller 테스트 ID를 복제하는 기존 편의 도구다. 신규 단계별 측정과 결과 기록은 `tools/run-ngrinder-load-stages.sh`를 사용한다.

## 측정 기록

- [2026-09-21 연결 오류 조사](./results/2026-09-21-terms-investigation/report.md)
- [2026-09-28 H2 시드 선정](./results/2026-09-28-read-seed-selection/report.md)
- [2026-09-28 목록 단계별 탐색](./results/2026-09-28-roommate-board-list-load/report.md)
- [2026-09-28 목록 반복 측정](./results/2026-09-28-roommate-board-list-repeats/report.md)
- [2026-09-30 산출물 통합 기록](./results/2026-09-30-artifact-consolidation/report.md)
- [2026-09-30 목록·검색 실제 smoke](./results/2026-09-30-roommate-board-list-smoke/report.md)
- [2026-09-30 필터·페이지 검증과 반복 기준선](./results/2026-09-30-roommate-board-baseline/report.md)

- [2026-09-30~10-01 네 경로 장시간 대조와 SQL 진단](./results/2026-09-30-roommate-board-controls/report.md)

과거 측정 원본의 커밋·리비전·경로·환경 값은 당시 증거이므로 유지한다. 재실행 명령과 문서 링크는 현재 위치로 갱신했다. 기존 `ngrinder-performance-testing-*.md`는 초기 설계 참고 자료이며 실행 가능한 코드와 검증 상태는 `script/README.md`를 기준으로 확인한다.
