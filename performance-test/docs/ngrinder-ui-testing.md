# nGrinder UI에서 조회 스크립트 실행하기

확인일: 2026-10-07. 현재 환경은 Docker의 nGrinder Controller/Agent `3.5.9-p1`, Windows 호스트의 백엔드다. [스크립트 인덱스](../script/README.md)에서 API별 파일과 인증·데이터 조건을 확인한다.

## 현재 로컬 환경의 실행 준비와 갱신

2026-10-05 Controller 등록본을 실행 가능한 입력값으로 준비했다. 인증 검색 JSON에 `tokenFile`을 지정하고, 나머지 15개 등록본의 `TOKEN_POOL`도 같은 파일을 읽도록 바꿨다. 상세 조회 ID·캘린더 날짜는 현재 H2의 테스트 회원 30명에 맞췄다. 소스의 일반 스크립트 템플릿과 과거 측정 보존본은 유지한다. **Script 화면을 새로고침한 뒤 최신 등록본으로 Validate**한다. 기존 성능 테스트를 복제할 때도 최신 스크립트 리비전을 선택한다.

토큰 만료 또는 테스트 DB/컨테이너 재생성 후에는 아래 준비 명령을 다시 실행한다. 대상은 `localhost:8080`의 정상 H2 서버와 기존 `load_test_user_*` 회원이며, 백엔드 재시작·시드 데이터 생성·부하 단계 실행은 하지 않는다. Controller가 성능 테스트를 실행 중이면 준비를 중단한다.

```powershell
python -B C:/dev/workspace/prography/APM/performance-test/tools/prepare-ngrinder-ui.py --backend-project C:/dev/workspace/KnockIn/back/11th-1team-BE
```

기본 동작은 토큰/등록본 입력·공통 리소스 갱신과 인증 검색 Validate 1회다. 토큰 유효기간은 백엔드 기본과 같은 7일이며, 결과 JSON에 정확한 만료 시각을 남긴다. JWT·서명 키는 결과/소스에 저장하지 않고 Controller와 Agent의 `/tmp/knockin-ngrinder-tokens.txt`에만 토큰을 둔다. 전체 단건 검증이 필요하면 `--validate-all`, Agent에서 인증 검색 1회도 확인하려면 `--verify-agent`를 추가한다. 반복 요청으로 인증 검색 이력·게시글 조회수·채팅 읽음 상태가 바뀔 수 있다.

## 기본 부하 판정과 선택 응답 검증 (2026-10-07)

목록·검색의 기본 실행은 **설정한 HTTP 상태와 통신 성공 여부**만 판정한다. 응답 본문을 JSON으로 파싱하지 않으므로 Page→Slice 변경이나 필드 추가·삭제로 부하 실행이 중단되지 않는다. 성공은 HTTP 요청 성공을 뜻하며 업무 결과의 정확성을 보증하지 않는다. 요청 URL·필터·인증 입력은 실제 API 요구사항에 맞춰 준비한다.

`resources/roommate-board-list.json` 최상위 기본값은 다음과 같다.

```json
"expectedStatusCodes": [200],
"responseValidator": null
```

기존 Page의 count·필터·정렬·노출/제외 검증이 필요할 때만 `responseValidator`를 `"resources/RoommateBoardPageContract.txt"`로 설정한다. 선택한 프로필 내부에 같은 키를 두면 최상위 값을 덮어쓴다. 프로필의 `responseValidator: null`은 해당 프로필의 검증을 끈다. HTTP 상태는 최상위/프로필의 `expectedStatusCodes`로 지정하며 누락 시 `[200]`이다. 기본 모드에서는 `inputs[].expect`를 생략할 수 있다. Page 검증을 켠 경우에만 기대 count·지역/방 유형 이름이 필요하다.

Page 검증은 `totalElements`가 있는 응답에만 적용한다. 현재 Slice API에 선택하면 `CONTRACT_MISMATCH`와 `PAGE_TOTAL_ELEMENTS_REQUIRED`가 표시된다. 다른 응답 계약을 확인하려면 별도 txt 리소스에서 `static void validateInput(Map input)`과 `static void validateResponse(def response, Map input)`을 구현하고 경로를 지정한다. 검증기는 원본 응답을 받아 자체 파싱하며 공통 실행기에 응답 필드를 추가하지 않는다.

준비 도구는 저장소의 공통 실행기와 Page 검증 리소스를 Controller에 자동 반영한다. JSON의 실행 프로필·입력·명시적으로 선택한 검증기는 유지한다. 따라서 도구 재실행으로 옵션이 몰래 꺼지지 않는다. Script 화면에서 최신 리비전을 선택한다. 결과 manifest/준비 summary에는 HTTP 상태 조건과 선택 검증기 경로가 기록된다. 본문·JWT는 개별 요청 CSV에 저장하지 않는다.

| 준비 결과/오류 유형 | 의미 |
|---|---|
| `PASS` | Validate 1회 성공·오류 0건을 확인 |
| `SETUP_FAILED` | 컴파일·리소스·설정·토큰 등 초기화 실패 |
| `HTTP_REQUEST_FAILED` | 허용하지 않은 HTTP 상태, 예: 401/500 |
| `TRANSPORT_FAILED` | 연결 실패·타임아웃; 뿌리 예외 클래스 확인 |
| `CONTRACT_MISMATCH` | 선택한 검증기의 계약 불일치; 기본 모드에서는 발생하지 않음 |
| `REQUEST_FAILED` | 기존 스크립트의 실행 오류; 로그에서 원인 확인 |
| `RESULT_COLLECTION_FAILED` | 단건 Totals를 수집하지 못해 실행 결과 미확인; API 실패로 단정하지 않음 |

nGrinder가 Validate API에서 stderr만 반환하면 준비 도구는 해당 실행에 삽입한 고유 표시와 일치하는 Controller 프로세스 로그를 읽는다. 다른 Validate 로그는 사용하지 않는다. 결과 디렉터리의 `.api.log`는 API 출력, `.log`는 판정에 사용한 로그이며 `summary.json`에 출처를 남긴다.

[2026-10-07 변경 검증 기록](../results/2026-10-07-ui-readiness/http-response-decoupling/report.md): 기본 목록·인증 검색 Validate 각 1회와 Agent 인증 검색 1회(테스트 481)가 성공했다.

## 1. Script에서 실행 입력 준비

`http://localhost`의 **Script**에서 실행할 `.groovy`를 선택한다. Controller에 현재 스크립트 17개가 등록되어 있다. 새로 업로드할 때는 `performance-test/script/<도메인>/`의 원본을 사용한다.

| 스크립트 종류 | 실행 전에 확인할 값 |
|---|---|
| 게시글 목록·검색 2개 | 같은 디렉터리의 `resources/RoommateBoardListSupport.txt`, `resources/roommate-board-list.json` 필요 |
| 위 2개의 JSON | `baseUrl`, `runId`, `activeReadProfile`/`activeKeywordProfile`, 선택 프로필의 검색어·필터·허용 HTTP 상태·선택 검증기 |
| 나머지 조회 15개 | `targetHost`, 실제 JWT의 `TOKEN_POOL`, 토큰 사용자가 접근 가능한 ID 풀 |
| 월·일 캘린더 | 데이터가 존재하는 `YEAR`, `MONTH`, `DAY` |

현재 백엔드 주소는 `http://host.docker.internal:8080`이다. Controller/Agent 컨테이너에서 Windows 백엔드에 접근하는 주소이며, 컨테이너 내부의 `localhost:8080`과 다르다.

목록·검색 JSON은 기존 `profiles`를 유지하고 필요한 항목만 편집한다. `runId`는 `ui-20261005-01`처럼 공백 없는 고유한 이름을 사용한다. 기본 목록은 `activeReadProfile: list-anonymous`, 익명 검색은 `activeKeywordProfile: search-frequent-anonymous`로 토큰 없이 확인할 수 있다. 인증 검색을 측정하려면 `search-frequent-authenticated`를 선택하고 다음 단계의 토큰을 준비한다. 두 검색 프로필은 서버 처리와 검색 이력 저장 여부가 다르므로 결과를 구분한다.

2026-10-04 보고서의 `execution/deployed-scripts` 링크는 **측정 당시 보존본**이다. 당시 토큰 파일 `/tmp/knockin-entire-20261004/tokens.txt`는 종료 후 제거했다. 보존본에 있는 임시 경로·회원/데이터 ID를 새 환경에서도 사용할 수 있다고 가정하지 않는다.

## 2. 인증 목록·검색의 토큰 파일 준비

Validate는 **Controller에서**, 실제 성능 테스트는 **Agent에서** 실행된다. 같은 토큰 파일을 양쪽에 준비해야 한다. 유효한 access token을 `Bearer ` 접두사 없이 한 줄에 하나씩 적은 UTF-8 파일을 저장소 밖에 준비한다. 토큰 만료 또는 테스트 DB 재생성 후에는 현재 회원에 맞는 토큰으로 갱신한다.

Windows PowerShell에서 아래를 실행한다. 실제 JWT 내용은 명령에 붙이지 않는다.

```powershell
$ngrinderTokensPath = Read-Host '준비한 토큰 파일의 전체 경로'
docker cp $ngrinderTokensPath ngrinder-controller:/tmp/knockin-ngrinder-tokens.txt
docker ps --filter 'ancestor=ngrinder/agent:3.5.9-p1' --format '{{.Names}}' |
    ForEach-Object { docker cp $ngrinderTokensPath "${_}:/tmp/knockin-ngrinder-tokens.txt" }
```

Script의 `resources/roommate-board-list.json` 최상위에 `"tokenFile": "/tmp/knockin-ngrinder-tokens.txt"`를 추가하고 저장한다. 파일을 복사하는 방식은 컨테이너 재시작이 필요 없다. 컨테이너 재생성 시에는 다시 복사한다. `ROOMMATE_BOARD_TOKENS`/`ROOMMATE_BOARD_TOKEN_FILE` 환경 변수가 설정되어 있으면 JSON보다 우선한다.

1 Agent·1 process·30 threads는 **서로 다른 회원의 토큰 30개**를 같은 순서로 각 Agent에 제공한다. Validate는 첫 토큰을 사용한다. 그 외 스크립트의 `TOKEN_POOL`은 실제 JWT로 바꾸고, 상세·편집·채팅·하우스룰의 ID 풀도 해당 회원과 맞춘다. 기존 15개 스크립트는 토큰을 modulo로 재사용하므로 토큰 수와 사용자 배정 방식을 확인한다.

## 3. Save → Validate

리소스와 스크립트를 저장한 뒤 **Validate**를 누른다. Validate는 초기화뿐 아니라 실제 요청도 실행한다. 인증 검색에는 검색 이력 저장이 발생한다.

2026-10-05 `RoommateBoardListKeywordGetTest.groovy`의 로그에서 `Controller test ID is required for unique sample directories`를 확인했다. 공통 리소스가 성능 테스트 전용 `grinder.test.id`를 Validate에도 요구한 문제였다. `grinder.script.validation=true`일 때만 UUID가 포함된 별도 출력 폴더를 쓰도록 원본과 Controller의 공통 리소스를 수정했다. 실제 성능 테스트의 ID·토큰 배정은 유지한다. Validate의 HTTP/응답 검증 실패도 예외로 표시한다.

수정 후 기본 목록 Validate 2회 연속 통과와 실제 Agent 라이브러리의 오프라인 검증을 확인했다. 이후 인증 검색의 토큰 미설정을 해결하고, 17개 스크립트의 UI Validate를 각각 1회·오류 0건으로 확인했다. 인증 검색의 Agent 1 VU·1회 실행도 통과했다(테스트 449). 이전 검증에서 준비한 토큰의 만료는 `2026-10-12T20:20:02+09:00`다. [검증 기록](../results/2026-10-04-entire-test/execution/ui-readiness-20261005/report.md)을 참조한다.

| 오류 | 확인할 항목 |
|---|---|
| `Controller test ID is required...` | Script의 공통 txt 리소스가 2026-10-05 수정본인지 확인 |
| `Authentication requires...` | Controller와 Agent의 토큰 환경/파일 설정 |
| `FileNotFoundException` | 누락된 resources 또는 실행 컨테이너에 없는 토큰 파일 |
| `Token pool too small...` | Agent/process/thread slot에 필요한 토큰 수 |
| `HTTP 401/403` | 토큰 만료·현재 DB 회원·데이터 접근 권한 |
| `CONTRACT_MISMATCH` / `contract_mismatch` | 선택 검증기의 계약과 현재 응답/fixture 비교; Page 검증에 Slice를 사용했는지 확인 |
| 과거 `response_validation` | 예전 공통 리소스의 응답 검증 오류; 최신 리소스로 갱신 |

## 4. Performance Test → Create Test

실행할 스크립트의 **최신 저장 리비전**을 선택하고 다음 값으로 첫 실행을 만든다. Process/Threads가 자동 계산되면 상세 설정에서 명시한다.

| 항목 | 첫 확인 | 전체 시험과 같은 10 VU / 30 VU 단계 |
|---|---|---|
| Target Host | `host.docker.internal` | 동일 |
| Agent Count | 1 | 1 |
| Processes | 1 | 1 |
| Threads / Vuser per Agent | 1 | 10 / 30 |
| Run Count | 1 | 100 |
| Ramp-up | 비활성화 | 비활성화 |
| Connection Reset | 비활성화 | 비활성화 |

**Save and Start** 후 완료 상태와 성공 요청 수·오류 수를 확인한다. 1 VU 확인을 통과하면 별도 워밍업을 하고 10 VU, 30 VU를 각각 실행한다. Run Count는 thread별 반복 수이므로 1 Agent·1 process에서 각각 1,000건, 3,000건이다. 오류가 있는 단계는 원인을 확인한 뒤 다음 단계로 진행한다. 전체 시험에서는 인증 검색·추천 목록의 30 VU에서 오류를 관찰했다.

Validate 출력 CSV는 Controller, 성능 테스트 출력 CSV는 Agent의 JSON `outputDir` 아래에 저장된다. UI 결과 화면은 기본 집계를 제공하고, 개별 요청 CSV는 자동 첨부하지 않는다. 직접 실행 결과를 비교할 때는 DB seed/데이터, 백엔드 JAR·커밋, 토큰 회원, timeout, 워밍업, VU·반복 수를 함께 기록한다.
