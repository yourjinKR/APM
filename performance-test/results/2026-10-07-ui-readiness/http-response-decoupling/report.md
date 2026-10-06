# HTTP 부하 판정과 응답 계약 분리

2026-10-07. 기본 실행은 HTTP 상태/통신만 판정하도록 변경했다. 현재 Slice 응답으로 목록·검색 UI Validate와 인증 검색 Agent 단건 실행이 통과했다. 업무 응답의 정확성은 선택 검증기로 별도 확인한다.

| 변경 | 현재 동작 |
|---|---|
| [공통 실행기](../../../script/roommate/resources/RoommateBoardListSupport.txt) | 기본 `[200]`, 응답 본문 파싱 없음, `expect` 불필요 |
| [설정](../../../script/roommate/resources/roommate-board-list.json) | `expectedStatusCodes: [200]`, `responseValidator: null`; 프로필별 덮어쓰기 가능 |
| [선택 Page 검증](../../../script/roommate/resources/RoommateBoardPageContract.txt) | 기존 count·페이지·필터·정렬·노출/제외 검증 보존; Page 계약을 선택했을 때만 실행 |
| [UI 준비 도구](../../../tools/prepare-ngrinder-ui.py) | 공통/검증 리소스 자동 반영, 토큰 확인은 HTTP 상태만 판정; 설정·HTTP·전송·계약·수집 실패 구분 |
| [집계기](../../../tools/summarize-roommate-board-samples.py) | 계약 오류 코드를 전송 오류의 뿌리 예외로 집계하지 않음; CSV schema2 유지 |

| 확인 | 결과 | 증거 |
|---|---|---|
| Python 회귀 | 16개 통과; 실패 유형·상관 로그·표본 집계 | [로그](python-tests.log) |
| 실제 Agent 라이브러리 오프라인 회귀 | Page/Slice/비JSON 기본 통과, 선택 Page 불일치 실패, 상태·타임아웃·설정·토큰 배정 검증 | [로그](groovy-offline.log) |
| [기본 목록](../../../script/roommate/RoommateBoardListGetTest.groovy) UI Validate | 성공 1·오류 0 | [로그](RoommateBoardListGetTest.log), [판정](additional-checks.json) |
| [인증 검색](../../../script/roommate/RoommateBoardListKeywordGetTest.groovy) UI Validate | 성공 1·오류 0 | [로그](RoommateBoardListKeywordGetTest.log), [요약](summary.json) |
| 인증 검색 Agent, 테스트 481 | FINISHED, 성공 1·오류 0, CSV 누락 0 | [테스트](agent-test.json), [개별 요청 집계](agent-request-samples/request-summary.json) |
| Controller 등록본 | 원본과 리소스 내용/hash 일치, 등록 revision 309~311 | [반영 기록](summary.json), [확인 hash](verified-resources.json) |

Page→Slice의 `totalElements` 제거가 원래의 강제 검증을 깨뜨렸다. 현재 기본 모드는 이 필드를 읽지 않는다. `responseValidator`에 Page 검증기를 명시하면 Slice는 `CONTRACT_MISMATCH: contract_mismatch/PAGE_TOTAL_ELEMENTS_REQUIRED (HTTP 200)`로 실패한다. 이 기대 실패는 오프라인 회귀로 확인했으며 업무 계약 변경에 따라 검증기만 갱신하면 된다. HTTP 200 안의 업무 오류도 기본 모드에서는 HTTP 성공으로 집계되므로 결과를 업무 정합성 통과로 해석하지 않는다.

준비 도구는 Validate API에서 Totals가 없으면 고유 표시가 일치하는 프로세스 로그만 사용한다. 둘 다 확인하지 못하면 `RESULT_COLLECTION_FAILED`와 null 건수를 기록해 API 실패와 구별한다. 이번 실제 실행은 API 출력에 Totals가 있었으며, 대체 로그 수집은 성공/미일치/읽기 실패 회귀로 확인했다.

현재 로컬 H2 회원 30명과 Controller/Agent 5개에 토큰을 갱신했다. 만료는 `2026-10-14T02:16:09+09:00`다. JWT·서명 키는 이 기록에 포함하지 않았다. 이 검증은 변경된 두 스크립트 경로의 단건 실행이며 전체 부하 성능 재측정 결과가 아니다. 과거 전체 시험과 `013608` 실패 기록은 그대로 보존했다.

수동 실행은 [UI 안내](../../../docs/ngrinder-ui-testing.md)를 따른다. 현재 Controller에는 반영을 마쳤으므로 Script 화면을 새로고침하고 최신 등록본으로 Validate한다. DB/컨테이너 재생성 또는 토큰 만료 후 아래를 실행한다.

```powershell
python -B C:/dev/workspace/prography/APM/performance-test/tools/prepare-ngrinder-ui.py --backend-project C:/dev/workspace/KnockIn/back/11th-1team-BE
```
