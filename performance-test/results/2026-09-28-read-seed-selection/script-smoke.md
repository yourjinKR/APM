# nGrinder 조회 스크립트 단일 실행 검증

- 실행일: 2026-09-28
- 대상: 실행 중인 로컬 백엔드 (`http://host.docker.internal:8080`, H2)
- 데이터: `GET /roommate/boards?page=0&size=1`의 `totalElements=1252` (기본 데이터 포함)
- 방법: nGrinder Controller에 등록된 Groovy 스크립트 16개를 각각 1 Agent, 1 process, 1 thread, 1 run으로 순차 실행
- 판정: nGrinder 성공 1건·오류 0건 및 스크립트의 HTTP 200 검증

| 스크립트 | 테스트 ID | 성공/오류 | 결과 |
|---|---:|---:|---|
| CalendarCategoryGetTest | 164 | 1/0 | 통과 |
| CalendarDayListGetTest | 165 | 1/0 | 통과 |
| CalendarEditFormGetTest | 166 | 1/0 | 통과 |
| CalendarMonthListGetTest | 167 | 1/0 | 통과 |
| ChatRoomDetailGetTest | 168 | 0/1 | 실패: `GET /chats/1` → 404 `ROOM_MEMBER_NOT_FOUND` |
| ChatRoomListGetTest | 169 | 1/0 | 통과 |
| HouseRuleDetailGetTest | 170 | 0/1 | 실패: `GET /roommates/me/house-rule/1` → 403 `HOUSE_RULE_ACCESS_DENIED` |
| HouseRuleListGetTest | 171 | 1/0 | 통과 |
| MyRoommateGetTest | 172 | 1/0 | 통과 |
| RoommateBoardDetailGetTest | 173 | 1/0 | 통과 |
| RoommateBoardEditFormGetTest | 174 | 1/0 | 통과 |
| RoommateBoardListGetTest | 162 | 1/0 | 통과 |
| RoommateMatchDetailGetTest | 175 | 1/0 | 통과 |
| RoommateMatchListGetTest | 176 | 1/0 | 통과 |
| RoommateRequestListGetTest | 177 | 1/0 | 통과 |
| UserBoardsGetTest | 178 | 1/0 | 통과 |

## 후속 조치

1. 채팅방 상세 스크립트의 토큰 계정이 참여하는 채팅방 ID를 사용한다. 현재 실행은 ID 1에 대해 `ROOM_MEMBER_NOT_FOUND`를 반환했다.
2. 하우스룰 상세 스크립트의 토큰 계정이 접근 가능한 하우스룰 ID를 사용한다. 현재 실행은 ID 1에 대해 `HOUSE_RULE_ACCESS_DENIED`를 반환했다.
3. 두 스크립트를 다시 1회 실행해 성공을 확인한 다음 반복 측정 대상으로 포함한다.

이 검증은 각 스크립트의 단일 요청과 HTTP 상태만 확인했다. 응답 본문 계약, 다중 VUser, 반복 실행 및 지연 분포를 검증한 결과가 아니다. 보고된 nGrinder 평균 응답시간도 표본이 1건이므로 성능 비교에 사용하지 않는다.
