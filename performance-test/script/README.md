# nGrinder 스크립트 인덱스

`performance-test/script`에서 관리하는 실행 가능한 nGrinder 스크립트의 협업 인덱스다. 스크립트는 작성자별 폴더가 아니라 **도메인 폴더**에 배치하고, 추가·이동·삭제할 때 이 문서의 해당 표를 같은 변경에서 갱신한다.

- 최종 갱신: 2026-10-07 — 목록·검색의 HTTP 부하 판정과 선택 응답 계약 분리
- 기준 환경: nGrinder Controller/Agent `3.5.9-p1`, The Grinder `3.9.1`, Groovy `3.0.5`, JDK `11`
- 공통 대상 주소: `http://host.docker.internal:8080`
- 현재 범위: 조회 REST API
- 현재 제외: SSE, WebSocket, 이미지 업로드, deprecated `/chat-requests/**`, 빈 DTO를 반환하는 `/roommate/matches/score`, `/roommates/me/calendar/{id}`

목록·검색의 현재 기본 실행은 HTTP 상태/통신을 판정한다. 응답 검증은 JSON의 `responseValidator`로 선택한다. 기존 Page 검증 기록은 당시 응답 계약에 대한 결과이며 현재 Slice의 업무 정합성을 뜻하지 않는다. [설정·UI 실행 안내](../docs/ngrinder-ui-testing.md), [2026-10-07 변경 검증](../results/2026-10-07-ui-readiness/http-response-decoupling/report.md).

## 검증 상태 표기

- **런타임 검증 완료**: Controller의 `/script/api/validate`에서 초기화, 1회 HTTP 실행, 통계 종료까지 스크립트 예외 없이 완료했다.
- **계약 검증 완료**: 정상 토큰과 정상 fixture를 사용해 기대 HTTP 상태와 응답 계약까지 확인했다.
- 2026-09-23 최초 16개 스크립트는 placeholder 토큰으로 런타임 검증했다. 이후 정상 fixture로 수행한 기록은 [측정 결과](../results/2026-09-28-read-seed-selection/report.md)를 참조한다.
- 2026-09-30 갱신한 목록·검색 스크립트는 실제 Agent 라이브러리 오프라인 검증과 Controller 계약 smoke를 통과했다. 기본 조회/빈번 검색 × 익명/인증 네 조건에서 각각 3회 요청과 검색 이력 증분을 확인했다. [결과](../results/2026-09-30-roommate-board-list-smoke/report.md). 이후 H2 fixture에서 17개 프로필의 실제 계약 검증과 반복 기준선을 수행했다. [후속 측정](../results/2026-09-30-roommate-board-baseline/report.md). 다른 snapshot은 별도 검증이 필요하다.

## 룸메이트 게시글

| 시나리오 | 메서드 | 라우터 | GTest ID | 스크립트 경로 | 작성자 | 인증·fixture | 조회 부작용 | 검증 상태 |
|---|---|---|---:|---|---|---|---|---|
| S01 · 게시글 기본·필터·페이지 조회 | GET | `/roommate/boards` | 4101 | [RoommateBoardListGetTest.groovy](./roommate/RoommateBoardListGetTest.groovy) | `yourjin` | JSON 프로필, 익명/인증 선택, 실측 fixture | 검색어 없음 | H2 fixture의 12개 조회 프로필 계약 검증 완료 |
| S01 · 게시글 검색 조회 | GET | `/roommate/boards?keyword=...` | 4104 | [RoommateBoardListKeywordGetTest.groovy](./roommate/RoommateBoardListKeywordGetTest.groovy) | 미지정 | JSON 프로필, 익명 대조군/인증 검색, Agent 토큰 | 인증 검색마다 검색 이력 INSERT | H2 fixture의 5개 검색 프로필 계약 검증 완료 |
| S01 · 게시글 상세 조회 | GET | `/roommate/boards/{boardId}` | 4102 | [`script/roommate/RoommateBoardDetailGetTest.groovy`](./roommate/RoommateBoardDetailGetTest.groovy) | `yourjin` | JWT, 공개·미삭제 `BOARD_ID_POOL` | 요청마다 조회수 UPDATE | 런타임 검증 완료 |
| S12 준비 · 게시글 편집 폼 조회 | GET | `/roommate/boards/{boardId}/edit` | 4103 | [`script/roommate/RoommateBoardEditFormGetTest.groovy`](./roommate/RoommateBoardEditFormGetTest.groovy) | `yourjin` | JWT, 토큰 사용자가 작성한 `OWNED_BOARD_ID_POOL` | 없음 | 런타임 검증 완료 |

## 룸메이트 매칭

| 시나리오 | 메서드 | 라우터 | GTest ID | 스크립트 경로 | 작성자 | 인증·fixture | 조회 부작용 | 검증 상태 |
|---|---|---|---:|---|---|---|---|---|
| S02 · 추천 목록 조회 | GET | `/roommate/matches?size=20` | 4201 | [`script/roommate/RoommateMatchListGetTest.groovy`](./roommate/RoommateMatchListGetTest.groovy) | `yourjin` | JWT 사용. 라우터는 익명 허용. 온보딩 완료 후보 필요 | 없음 | 런타임 검증 완료 |
| S02 · 추천 회원 상세 조회 | GET | `/roommate/matches/{memberId}` | 4202 | [`script/roommate/RoommateMatchDetailGetTest.groovy`](./roommate/RoommateMatchDetailGetTest.groovy) | `yourjin` | JWT, 조회 가능한 다른 회원 `TARGET_MEMBER_ID_POOL` | 없음 | 런타임 검증 완료 |

## 채팅

| 시나리오 | 메서드 | 라우터 | GTest ID | 스크립트 경로 | 작성자 | 인증·fixture | 조회 부작용 | 검증 상태 |
|---|---|---|---:|---|---|---|---|---|
| S05 · 채팅방 목록 조회 | GET | `/chats` | 5101 | [`script/chat/ChatRoomListGetTest.groovy`](./chat/ChatRoomListGetTest.groovy) | `yourjin` | JWT, 채팅방 참여 사용자 | 없음 | 런타임 검증 완료 |
| S05 · 채팅방 상세·이력 조회 | GET | `/chats/{chatRoomId}` | 5102 | [`script/chat/ChatRoomDetailGetTest.groovy`](./chat/ChatRoomDetailGetTest.groovy) | `yourjin` | JWT와 같은 인덱스의 참여 방 `CHAT_ROOM_ID_POOL` | 상대방의 안 읽은 메시지를 읽음 처리 | 런타임 검증 완료 |

## 룸메이트 요청

| 시나리오 | 메서드 | 라우터 | GTest ID | 스크립트 경로 | 작성자 | 인증·fixture | 조회 부작용 | 검증 상태 |
|---|---|---|---:|---|---|---|---|---|
| S07 · 룸메이트 요청 목록 조회 | GET | `/roommate-requests?page=0&size=20&sort=createdAt,DESC` | 6205 | [`script/roommate-request/RoommateRequestListGetTest.groovy`](./roommate-request/RoommateRequestListGetTest.groovy) | `yourjin` | JWT, 요청 송수신 이력이 있는 사용자 권장 | 없음 | 런타임 검증 완료 |

## 룸메이트 생활 관리

| 시나리오 | 메서드 | 라우터 | GTest ID | 스크립트 경로 | 작성자 | 인증·fixture | 조회 부작용 | 검증 상태 |
|---|---|---|---:|---|---|---|---|---|
| S09 전제 · 내 룸메이트 조회 | GET | `/roommates/me` | 7001 | [`script/roommate-management/MyRoommateGetTest.groovy`](./roommate-management/MyRoommateGetTest.groovy) | `yourjin` | JWT, 수락 완료된 룸메이트 관계 | 없음 | 런타임 검증 완료 |
| 생활 관리 · 하우스룰 목록 조회 | GET | `/roommates/me/house-rule` | 7101 | [`script/roommate-management/HouseRuleListGetTest.groovy`](./roommate-management/HouseRuleListGetTest.groovy) | `yourjin` | JWT, 룸메이트 관계 | 없음 | 런타임 검증 완료 |
| 생활 관리 · 하우스룰 상세 조회 | GET | `/roommates/me/house-rule/{id}` | 7102 | [`script/roommate-management/HouseRuleDetailGetTest.groovy`](./roommate-management/HouseRuleDetailGetTest.groovy) | `yourjin` | JWT와 같은 인덱스의 `HOUSE_RULE_ID_POOL` | 없음 | 런타임 검증 완료 |
| S09 · 캘린더 월별 조회 | GET | `/roommates/me/calendar?year={year}&month={month}` | 7201 | [`script/roommate-management/CalendarMonthListGetTest.groovy`](./roommate-management/CalendarMonthListGetTest.groovy) | `yourjin` | JWT, 룸메이트 관계, `YEAR`, `MONTH` | 없음 | 런타임 검증 완료 |
| S09 · 캘린더 일별 조회 | GET | `/roommates/me/calendar?year={year}&month={month}&day={day}` | 7202 | [`script/roommate-management/CalendarDayListGetTest.groovy`](./roommate-management/CalendarDayListGetTest.groovy) | `yourjin` | JWT, 룸메이트 관계, `YEAR`, `MONTH`, `DAY` | 없음 | 런타임 검증 완료 |
| S09 보조 · 캘린더 카테고리 조회 | GET | `/roommates/me/calendar/categories` | 7203 | [`script/roommate-management/CalendarCategoryGetTest.groovy`](./roommate-management/CalendarCategoryGetTest.groovy) | `yourjin` | JWT | 없음 | 런타임 검증 완료 |
| S09 준비 · 캘린더 편집 폼 조회 | GET | `/roommates/me/calendar/edit` | 7204 | [`script/roommate-management/CalendarEditFormGetTest.groovy`](./roommate-management/CalendarEditFormGetTest.groovy) | `yourjin` | JWT, 룸메이트 관계 | 없음 | 런타임 검증 완료 |

## 사용자 연계 게시글

| 시나리오 | 메서드 | 라우터 | GTest ID | 스크립트 경로 | 작성자 | 인증·fixture | 조회 부작용 | 검증 상태 |
|---|---|---|---:|---|---|---|---|---|
| S12 준비 · 내가 쓴 게시글 조회 | GET | `/users/me/boards?page=0&size=20&sort=createdAt,DESC` | 3020 | [`script/user/UserBoardsGetTest.groovy`](./user/UserBoardsGetTest.groovy) | `yourjin` | JWT, 게시글 작성 이력이 있는 사용자 권장 | 없음 | 런타임 검증 완료 |

## UI에서 직접 실행

[UI 실행 가이드](../docs/ngrinder-ui-testing.md)에서 Script 설정, Controller/Agent 토큰 준비, Validate 오류 해결과 성능 테스트 화면 입력값을 확인한다.

## 게시글 목록·검색 설정

목록·검색 두 스크립트는 [전용 실행 가이드](../docs/roommate-board-list-testing.md)를 따른다. `roommate/resources/roommate-board-list.json`에서 대상 주소·runId·프로필·fixture를 관리하고 인증 토큰은 Controller(Validate)·Agent(성능 테스트) 환경/로컬 파일로 제공한다. 공통 txt 리소스도 함께 배포한다. GTest 4102는 기존 상세 조회이며 새 검색은 4104다.

## 나머지 조회 스크립트 실행 전 설정

1. `targetHost`를 Agent에서 접근 가능한 백엔드 주소로 변경한다.
2. `TOKEN_POOL`의 `TOKEN_USER_*`를 실제 access token으로 교체한다. `Bearer ` 접두사는 넣지 않는다.
3. 상세 조회 스크립트의 ID 풀을 해당 토큰이 접근 가능한 정상 데이터 ID로 교체한다.
4. 월·일 캘린더 스크립트는 데이터가 존재하는 `YEAR`, `MONTH`, `DAY`로 변경한다.
5. 스크립트별 1 VU, 1회 실행에서 `200`과 응답 계약을 확인한 후 부하를 올리고 검증 상태를 **계약 검증 완료**로 변경한다.

목록·검색을 제외한 기존 조회 스크립트의 토큰 선택 방식은 `grinder.threadNumber % TOKEN_POOL.size()`다. 여러 process·Agent에서 계정을 완전히 분리해야 하는 본 시험 전에는 Agent/process/thread shard 기반 배정으로 교체한다.

## 실행·집계 도구

- [단계별 VUser 실행기](../tools/run-ngrinder-load-stages.sh): 등록된 스크립트를 순차 실행하고 결과를 `performance-test/results/`에 저장한다.
- [H2 시드별 조회 실행기](../tools/run-read-sequential.ps1): 빌드 시 `-BackendProject`를 명시하거나 `-JarPath`를 사용한다.
- [개별 요청 집계기](../tools/summarize-roommate-board-samples.py): 목록·검색 CSV의 p95/p99와 오류·누락을 집계한다.

## 기존 테스트 ID 반복 실행

nGrinder UI에서 테스트를 최초 1회 등록·검증한 뒤 저장소 루트에서 `./run_test.sh <TEST_ID> [반복횟수] [실행간격초]`로 반복 실행한다. 예: `./run_test.sh 97 5 120`. 여기서 `TEST_ID`는 Controller가 발급한 성능 테스트 ID이며 위 표의 `GTest ID`와는 다르다.

## 협업 규칙

1. 스크립트는 `script/<도메인>/`에 추가하며 작성자 이름으로 상위 폴더를 만들지 않는다.
2. 새 스크립트의 `GTest ID`는 이 문서의 기존 ID와 중복되지 않게 배정한다.
3. 스크립트 추가·이동·삭제와 도메인 표 갱신을 같은 커밋 또는 PR에 포함한다.
4. 작성자는 Git author의 식별 가능한 이름 또는 팀에서 합의한 핸들을 기록한다.
5. 정상·거절 시나리오는 성공 상태가 다르므로 별도 스크립트 또는 별도 행으로 관리한다.
6. 검증 상태는 실제로 수행한 수준만 기록한다. placeholder 토큰의 401 실행을 `계약 검증 완료`로 표시하지 않는다.
