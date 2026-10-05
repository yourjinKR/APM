# nGrinder UI 실행 준비 확인

확인: 2026-10-05T20:25:53.039149+09:00. 전체 부하 시험 결과와 구분하는 단건 실행 확인이다.

이전 수정은 Validate에 성능 테스트 ID가 없는 문제를 해결했다. 이후 인증 검색에 토큰 설정이 없는 오류와 다른 등록본의 만료된 토큰을 확인했다. 현재 로컬 H2 테스트 회원 30명의 새 토큰을 Controller/Agent 5개에 준비하고, Controller의 검색 JSON `tokenFile`과 다른 15개 등록본의 토큰 파일 경로·fixture ID·캘린더 날짜를 갱신했다.

- 토큰 만료: `2026-10-12T20:20:02+09:00` (KST), 토큰 파일: `/tmp/knockin-ngrinder-tokens.txt`.
- 회원 ID: 5~34, 캘린더 날짜: `2026-10-05`.
- 인증 검색 프로필: `search-frequent-authenticated`. 익명 검색으로 바꾸지 않고 확인했다.
- Agent 인증 검색 확인: 테스트 **449**, 1 Agent·1 process·1 thread·Run Count 1, **FINISHED / 성공 1 / 오류 0**.

| 등록 스크립트 | Validate 성공 | 오류 | 판정 |
|---|---:|---:|---|
| [ChatRoomDetailGetTest.groovy](../../../../script/chat/ChatRoomDetailGetTest.groovy) | 1 | 0 | 통과 |
| [ChatRoomListGetTest.groovy](../../../../script/chat/ChatRoomListGetTest.groovy) | 1 | 0 | 통과 |
| [RoommateBoardDetailGetTest.groovy](../../../../script/roommate/RoommateBoardDetailGetTest.groovy) | 1 | 0 | 통과 |
| [RoommateBoardEditFormGetTest.groovy](../../../../script/roommate/RoommateBoardEditFormGetTest.groovy) | 1 | 0 | 통과 |
| [RoommateBoardListGetTest.groovy](../../../../script/roommate/RoommateBoardListGetTest.groovy) | 1 | 0 | 통과 |
| [RoommateBoardListKeywordGetTest.groovy](../../../../script/roommate/RoommateBoardListKeywordGetTest.groovy) | 1 | 0 | 통과 |
| [RoommateMatchDetailGetTest.groovy](../../../../script/roommate/RoommateMatchDetailGetTest.groovy) | 1 | 0 | 통과 |
| [RoommateMatchListGetTest.groovy](../../../../script/roommate/RoommateMatchListGetTest.groovy) | 1 | 0 | 통과 |
| [CalendarCategoryGetTest.groovy](../../../../script/roommate-management/CalendarCategoryGetTest.groovy) | 1 | 0 | 통과 |
| [CalendarDayListGetTest.groovy](../../../../script/roommate-management/CalendarDayListGetTest.groovy) | 1 | 0 | 통과 |
| [CalendarEditFormGetTest.groovy](../../../../script/roommate-management/CalendarEditFormGetTest.groovy) | 1 | 0 | 통과 |
| [CalendarMonthListGetTest.groovy](../../../../script/roommate-management/CalendarMonthListGetTest.groovy) | 1 | 0 | 통과 |
| [HouseRuleDetailGetTest.groovy](../../../../script/roommate-management/HouseRuleDetailGetTest.groovy) | 1 | 0 | 통과 |
| [HouseRuleListGetTest.groovy](../../../../script/roommate-management/HouseRuleListGetTest.groovy) | 1 | 0 | 통과 |
| [MyRoommateGetTest.groovy](../../../../script/roommate-management/MyRoommateGetTest.groovy) | 1 | 0 | 통과 |
| [RoommateRequestListGetTest.groovy](../../../../script/roommate-request/RoommateRequestListGetTest.groovy) | 1 | 0 | 통과 |
| [UserBoardsGetTest.groovy](../../../../script/user/UserBoardsGetTest.groovy) | 1 | 0 | 통과 |

[원본 집계](./summary.json), 스크립트별 `.log`, [Agent 결과](./agent-test.json)를 같은 폴더에 보관했다. JWT/서명 키는 기록하지 않았다. 재발급 명령과 UI 화면 입력은 [실행 가이드](../../../../docs/ngrinder-ui-testing.md)를 따른다. Script 화면을 새로고침하고 최신 등록본/리비전을 선택한다.
