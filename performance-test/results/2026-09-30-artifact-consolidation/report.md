# 성능 테스트 산출물 APM 통합

2026-09-30에 KnockIn의 `doc/test/perf/`에서 관리하던 산출물 105개를 APM 저장소 `performance-test/`로 통합했다. 모든 복사본의 SHA-256을 확인한 뒤 원본 중복을 제거했다. Python bytecode cache는 산출물에서 제외했다.

- 실행 스크립트/리소스 → `script/roommate/`, `script/roommate/resources/`
- 실행·집계·검증 도구 → `tools/`, `tools/tests/`
- 계획·시나리오·환경·작업 일지·게시글 측정 가이드 → `docs/`
- 측정 결과와 원본 → `results/` (날짜별 하위 구조 유지)
- KnockIn → 안내 README만 유지

기존 APM 목록 파일은 [통합 전 기록용 txt](./RoommateBoardListGetTest.before-consolidation.txt)로 보존했다. 새 목록 파일은 현재 관리 위치에서 갱신했다. 검색의 GTest ID는 기존 상세 조회 4102와 중복되지 않도록 4104로 바꿨다. PowerShell 실행기는 백엔드 소스 경로를 명시적으로 받으며 결과와 서버 로그는 APM에서 관리한다.

[이동 manifest](./migration-manifest.json)는 문서 경로 및 코드 수정 **전**의 복사 일치 해시를 기록한다. 측정 JSON/CSV/로그/zip 원본은 유지했고 문서의 재실행 경로와 링크만 새 위치에 맞췄다. 새 부하 테스트 측정은 이 통합 작업에 포함하지 않았다.

## 이동 후 검증

- 관리 문서 20개의 로컬 Markdown 링크 확인 완료.
- 기존 측정 원본 81개(JSON/CSV/로그/zip/분석 코드 등)의 SHA-256 유지 확인.
- 실행 스크립트 17개의 GTest ID 중복 없음.
- 기존 nGrinder Agent의 Java 11·실제 라이브러리로 기준본 컴파일 및 오프라인 smoke 통과.
- 개별 요청 집계기 테스트 4개 통과.
- Bash 실행기 구문·help, PowerShell 실행기 구문 확인 완료.

컨테이너 설정 변경이나 실제 부하 재실행은 수행하지 않았다.
