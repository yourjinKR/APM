# nGrinder 스크립트 인덱스

`performance-test/script`에서 관리하는 실행 가능한 nGrinder 스크립트의 협업 인덱스다. 스크립트는 작성자별 폴더가 아니라 **도메인 폴더**에 배치하고, 추가·이동·삭제할 때 이 문서의 해당 표를 같은 변경에서 갱신한다.

- 최종 갱신: 2026-09-23
- 기준 환경: nGrinder Controller/Agent `3.5.9-p1`, The Grinder `3.9.1`, Groovy `3.0.5`, JDK `11`
- 공통 대상 주소: `http://host.docker.internal:8080`
- 현재 범위: 조회 REST API
- 현재 제외: SSE, WebSocket, 이미지 업로드, deprecated `/chat-requests/**`, 빈 DTO를 반환하는 `/roommate/matches/score`, `/roommates/me/calendar/{id}`

## 검증 상태 표기

- **런타임 검증 완료**: Controller의 `/script/api/validate`에서 초기화, 1회 HTTP 실행, 통계 종료까지 스크립트 예외 없이 완료했다.
- **계약 검증 완료**: 정상 토큰과 정상 fixture를 사용해 기대 HTTP 상태와 응답 계약까지 확인했다.
- 현재 16개 스크립트는 placeholder 토큰으로 런타임 검증했으므로 실제 API 응답은 `401 TOKEN_INVALID`였다. 즉, nGrinder 호환성과 HTTP 호출 경로는 확인했지만 정상 데이터의 `200` 계약은 아직 검증 전이다.

## 룸메이트 게시글

| 시나리오 | 메서드 | 라우터 | GTest ID | 스크립트 경로 | 작성자 | 인증·fixture | 조회 부작용 | 검증 상태 |
|---|---|---|---:|---|---|---|---|---|
| S01 · 게시글 첫 페이지 조회 | GET | `/roommate/boards?page=0&size=20&sort=createdAt,DESC` | 4101 | [`script/roommate/RoommateBoardListGetTest.groovy`](./roommate/RoommateBoardListGetTest.groovy) | `yourjin` | JWT 사용. 라우터는 익명 허용. `KEYWORD` 선택 설정 | 로그인 상태에서 `KEYWORD` 사용 시 검색 이력 INSERT | 런타임 검증 완료 |
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

## 실행 전 설정

1. `targetHost`를 Agent에서 접근 가능한 백엔드 주소로 변경한다.
2. `TOKEN_POOL`의 `TOKEN_USER_*`를 실제 access token으로 교체한다. `Bearer ` 접두사는 넣지 않는다.
3. 상세 조회 스크립트의 ID 풀을 해당 토큰이 접근 가능한 정상 데이터 ID로 교체한다.
4. 월·일 캘린더 스크립트는 데이터가 존재하는 `YEAR`, `MONTH`, `DAY`로 변경한다.
5. 스크립트별 1 VU, 1회 실행에서 `200`과 응답 계약을 확인한 후 부하를 올리고 검증 상태를 **계약 검증 완료**로 변경한다.

현재 토큰 선택 방식은 `grinder.threadNumber % TOKEN_POOL.size()`다. 여러 process·Agent에서 계정을 완전히 분리해야 하는 본 시험 전에는 Agent/process/thread shard 기반 배정으로 교체한다.

## 반복 실행

nGrinder UI에서 테스트를 최초 1회 등록·검증한 뒤 저장소 루트에서 `./run_test.sh <TEST_ID> [반복횟수] [실행간격초]`로 반복 실행한다. 예: `./run_test.sh 97 5 120`. 여기서 `TEST_ID`는 Controller가 발급한 성능 테스트 ID이며 위 표의 `GTest ID`와는 다르다.

## 협업 규칙

1. 스크립트는 `script/<도메인>/`에 추가하며 작성자 이름으로 상위 폴더를 만들지 않는다.
2. 새 스크립트의 `GTest ID`는 이 문서의 기존 ID와 중복되지 않게 배정한다.
3. 스크립트 추가·이동·삭제와 도메인 표 갱신을 같은 커밋 또는 PR에 포함한다.
4. 작성자는 Git author의 식별 가능한 이름 또는 팀에서 합의한 핸들을 기록한다.
5. 정상·거절 시나리오는 성공 상태가 다르므로 별도 스크립트 또는 별도 행으로 관리한다.
6. 검증 상태는 실제로 수행한 수준만 기록한다. placeholder 토큰의 401 실행을 `계약 검증 완료`로 표시하지 않는다.
