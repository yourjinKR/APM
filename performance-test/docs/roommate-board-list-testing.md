# 게시물 목록 성능 개선을 위한 측정 스크립트

작성일: 2026-09-30. 이번 작업은 조건별 측정 스크립트와 기록 절차를 준비한 것이다. 백엔드 최적화나 새 부하 측정 결과를 의미하지 않는다.

## 기존 결과의 충분성

[단계별 탐색](../results/2026-09-28-roommate-board-list-load/report.md), [반복 측정](../results/2026-09-28-roommate-board-list-repeats/report.md), [시드 선정](../results/2026-09-28-read-seed-selection/report.md), [연결 오류 조사](../results/2026-09-21-terms-investigation/report.md)를 검토했다. **기본 조회의 탐색 자료는 있지만, 필터·검색까지 포함한 성능 개선의 기준선은 아직 부족하다.**

| 확인한 사실 | 추가 측정에 반영할 사항 |
|---|---|
| 같은 H2 1,000건에서 최초 1 VU 평균 496ms, 이후 반복 1.33~1.75초 | 커밋·JAR·JVM·SQL 로그·호스트 점유·DB snapshot을 고정하고 반복한다. 두 결과를 하나의 기준선으로 합치지 않는다. |
| 반복 시험의 5 VU에서 오류가 세 번 재현 | 1→3→5 VU부터 다시 확인하고 오류 단계에서 상위 부하로 올라가지 않는다. |
| 기존 p95는 2초 구간 평균의 p95 | 이번 개별 요청 CSV로 p95/p99를 구한다. 기존 p95와 직접 비교하지 않는다. |
| 로컬 H2 중심 결과 | H2는 재현용으로 유지하고 PostgreSQL 시험은 환경별 별도 표로 기록한다. |
| 필터·검색 조건별 결과가 없음 | 단일 필터, 복합 필터, 선택도, 페이지, 인증 여부를 분리한다. |
| 과거 연결 재설정 시험에서 TCP 오류 관찰 | connectionReset=false를 유지하고, 타임아웃·연결 거절·HTTP 오류·검증 실패를 분리한다. |

현재 서비스는 인증 + 공백 아닌 keyword 요청마다 `search`에 INSERT한다. 같은 키워드도 매 요청 새 행이 생기며 0건 검색에도 저장된다. 익명 검색은 저장하지 않는다. 인증 여부에 따라 회원 조회·차단 제외·관심 상태 조회도 달라지므로 **익명/인증 검색의 지연 차이 전체를 INSERT 비용이라고 단정하지 않는다.** SQL/APM의 검색 저장 구간과 함께 판단한다.

## 스크립트 구성

- [RoommateBoardListGetTest.groovy](../script/roommate/RoommateBoardListGetTest.groovy): 키워드 없는 기본·필터·정렬·페이지 조회, GTest 4101.
- [RoommateBoardListKeywordGetTest.groovy](../script/roommate/RoommateBoardListKeywordGetTest.groovy): 키워드 필수. 익명 검색 대조군과 검색 기록 저장을 포함한 인증 검색, GTest 4104. 기존 상세 조회의 4102와 구분한다.
- [roommate-board-list.json](../script/roommate/resources/roommate-board-list.json): 실행 환경과 17개 프로필. 기본값은 측정 결과가 아닌 입력 예시다.
- [RoommateBoardListSupport.txt](../script/roommate/resources/RoommateBoardListSupport.txt): 공통 Groovy 코드. 두 스크립트가 로드한다. nGrinder 일반 Groovy의 배포 가능한 resource 확장자에 맞춰 `.txt`로 보관한다. [공식 resource 안내](https://github.com/naver/ngrinder/wiki/How-to-use-resources)
- [summarize-roommate-board-samples.py](../tools/summarize-roommate-board-samples.py): 개별 GET 지연, 성공·실패, p50/p95/p99, 표본 누락 집계.

관리 기준은 APM 저장소의 `performance-test/script/roommate/`다. 2026-09-30 통합 시 기존 목록 스크립트를 이 버전으로 갱신했고, 이전 파일은 `results/2026-09-30-artifact-consolidation/`에 기록용 txt로 보존했다. 이 디렉터리의 두 스크립트와 resources를 nGrinder에 등록한다. 기존 keyword 스크립트의 `ROOMMATE_BOARD_SEARCH_KEYWORD`는 이번 JSON의 `inputs[].keyword`로 대체했다.

## 조건별 프로필

한 실행은 하나의 프로필만 사용한다. 조건별 수치를 혼합하지 않는다. 여러 키워드를 순환할 때는 같은 선택도의 검증된 입력들만 해당 프로필의 `inputs`에 추가한다. `inputIndex`별 요청 건수도 집계된다.

| 축 | 프로필 | 준비·비교 조건 |
|---|---|---|
| 기본 | `list-anonymous`, `list-authenticated` | 첫 페이지·size 20·최신순. 인증 조회 자체의 차이를 확인 |
| 단일 필터 | `filter-region`, `filter-room-type`, `filter-budget`, `filter-gender` | 한 축씩 변경. 배열은 반복 query parameter로 전달 |
| 복합 필터 | `filter-combined` | 지역+방 유형+성별+예산. 실제 결과가 존재하는 fixture 필요 |
| 관심 | `liked-authenticated` | VU별 회원마다 관심 게시물 fixture 필요 |
| 페이지 | `page-1`, `page-deep` | 깊은 페이지 예시는 page 40, size 20. 실제 노출 게시물이 801건 이상이어야 함 |
| 응답량·정렬 | `size-100`, `sort-hits` | size만 또는 sort만 변경. hits 비교 중 상세 GET을 섞지 않음 |
| 많은 결과 검색 | `search-frequent-anonymous`, `search-frequent-authenticated` | 같은 keyword/query를 사용한 대조군 |
| 희소 검색 | `search-rare-authenticated` | 예시 제목 999. 해당 snapshot에서 정확히 1건인지 사전 확인 |
| 0건 검색 | `search-zero-authenticated` | totalElements=0을 명시. 검색 기록 INSERT는 계속 발생 |
| 검색+필터 | `search-combined-authenticated` | 검색과 복합 조건을 함께 적용 |

제목 외에 지역·방 유형 검색도 수행하려면 검증된 지역명/방 유형명을 keyword로 넣은 **별도 프로필**을 복사해서 추가한다. 희소·0건 검색의 익명 대조군도 동일 입력을 복사하고 `auth`만 `anonymous`로 바꿔 만들 수 있다. 운영 로그가 없으므로 임의의 혼합 비율은 고정하지 않았다.

## 등록과 설정

1. nGrinder 일반 Groovy 스크립트 디렉터리에 두 `.groovy`를 등록한다. 같은 위치의 `resources/`에 공통 `.txt`와 JSON을 등록한다. `performance-test/tools/tests`와 Python 집계기는 Agent 배포 대상이 아니다.
2. JSON의 `baseUrl`을 **Agent에서 접근 가능한 주소**로 설정한다. Bash 실행기의 `--target-host`는 nGrinder 대상 호스트 설정이며 JSON의 실제 GET URL을 바꾸지 않는다. 둘을 함께 맞춘다.
3. `runId`의 `CHANGE-ME`를 `before-H2-seed1000-r1`처럼 바꾼다. Controller의 `grinder.test.id`가 자동으로 붙으므로 여러 VU 단계가 서로 덮어쓰지 않는다. before/after·반복 회차는 각각 다른 prefix를 사용한다.
4. `activeReadProfile`/`activeKeywordProfile`을 선택한다. 두 스크립트가 각각 해당 값을 읽는다. 환경 변수 `ROOMMATE_BOARD_PROFILE`이 있으면 두 설정보다 우선하므로 종류가 다른 스크립트를 연속 실행할 때는 이 변수를 해제한다.
5. 지역/방 유형의 `[null]`을 실제 ID로, `regionFragments`/`roomTypeNames`를 실제 이름으로 채운다. 미완성 fixture는 요청 전에 실패한다. 예산 단위는 API와 DB의 단위로 확인한다.
6. 측정 전 1 VU·1~3회로 count·필터·회원별 결과를 확인한다. `expect.totalElements`, `requiredIds`, `excludedIds`를 추가하면 고정 snapshot의 count·노출/제외까지 확인할 수 있다. `minTotalElements`만으로 필터 적용의 완전한 정합성을 증명할 수는 없다.

인증 토큰은 **Agent 프로세스 환경**의 `ROOMMATE_BOARD_TOKENS`(쉼표 구분) 또는 `ROOMMATE_BOARD_TOKEN_FILE`(Agent 로컬 절대 경로, 한 줄 한 토큰)로 제공한다. Agent 환경 변수를 변경하기 어려우면 배포할 JSON의 `tokenFile`에 Agent 로컬 절대 경로를 지정할 수 있다. 환경 변수 경로가 우선한다. Controller 호스트의 shell 변수만 설정해도 Agent에 자동 전달되는 것은 아니다. 파일/환경 변경은 worker가 실제로 읽는지 확인한다. 토큰·서명 키를 저장소나 결과 파일에 넣지 않는다.

모든 Agent에 동일한 전체 토큰 목록과 같은 정렬을 제공한다. slot은 `(agentNumber × processes + processSlot) × threads + threadNumber`이며 `processSlot=processNumber-firstProcessNumber`다. modulo 재사용 없이 slot마다 다른 토큰을 배정한다. 토큰 수가 부족하면 실패한다. Agent 번호가 불연속이면 최대 slot까지 준비한다. **토큰 문자열이 서로 달라도 같은 회원일 수 있으므로 사전 발급 단계에서 member ID 중복을 확인한다.** [Grinder ScriptContext](https://grinder.sourceforge.net/g3/script-javadoc/net/grinder/script/Grinder.ScriptContext.html)

선택 환경 변수는 `ROOMMATE_BOARD_CONFIG`(Agent 설정 경로), `ROOMMATE_BOARD_RUN_ID`(prefix), `ROOMMATE_BOARD_RESULTS_DIR`(Agent 출력 경로)다. CSV에는 토큰·응답 본문·예외 메시지를 남기지 않는다.

클라이언트 timeout 예시는 connect/socket 각각 5초다. 기존 원본 파일에는 socket 15초가 있지만 과거 로그에는 5초 타임아웃이 있었다. 이전 리비전과 실효 설정 차이를 확인하고, 전후 비교에서는 같은 timeout을 고정한다. timeout 증가 결과를 성능 개선으로 제시하지 않는다.

## 실행 순서

1. 환경별로 snapshot·커밋/JAR·JVM·SQL 로그·풀·Agent 자원 및 선택 프로필을 기록한다. H2 500건 smoke → 1,000건 기준 → 1,250건 증가 비교, PostgreSQL 고정 snapshot은 별도로 수행한다.
2. 1 VU smoke 통과 후 별도 테스트로 워밍업한다. 워밍업 결과와 검색 이력 증가량은 본 측정에서 제외하고, 본 측정 직전에 DB 시작 상태를 기록한다.
3. 우선 1→3→5 VU, 동일 조건 3회 이상 반복한다. 오류 발생 시 상위 단계는 중단한다. 처음부터 모든 환경×조건의 최대 부하를 실행하지 않는다.
4. 기준선이 안정된 조건에서 요청 수/시간을 늘린다. 조건당 최소 1,000건의 성공 표본과 수 분 이상의 정상 구간을 초기 목표로 삼되 p99의 안정성은 반복 편차로 확인한다. 100회/VU 예시는 탐색이며 p99 검증에 충분하다는 뜻이 아니다.
5. DB 쿼리/count·보조 배치 조회·검색 INSERT·CPU/GC·Hikari/DB 대기·Agent 자원을 대조해 병목 가설을 세운다. 실행계획과 SQL 측정은 별도 진단 구간에 수집한다.
6. 병목 근거에 따라 개선하고 같은 snapshot과 조건으로 재측정한다. 검색 시험은 이력을 누적시키므로 각 반복/전후 시험의 초기 이력 수와 분포도 맞춘다. 개선하지 않은 경로의 회귀도 확인한다.

```bash
# JSON: activeReadProfile=list-anonymous,
#       activeKeywordProfile=search-frequent-authenticated,
#       runId=before-H2-seed1000-r1
# 인증 토큰은 이미 Agent에 준비되어 있어야 한다.
export NGRINDER_PASSWORD='<controller password>'
bash performance-test/tools/run-ngrinder-load-stages.sh \
  --script RoommateBoardListGetTest.groovy \
  --script RoommateBoardListKeywordGetTest.groovy \
  --vus 1,3,5 --iterations 100 --cooldown-sec 30 --timeout-sec 1800 \
  --environment before-H2-seed1000-r1
```

실행기는 첫 실패에서 중단한다. 다른 독립 시나리오를 계속 조사할 때만 `--continue-next-script`를 사용한다. 정상 설정은 1 Agent·1 process, ramp-up 없음, connectionReset=false. 새로운 스크립트 등록 후 Controller smoke에서 resource 배포와 HTTP 요청 계측까지 확인한다.

## 표본 수집과 검색 저장 검증

Agent의 `outputDir/<runId>-test_<ID>/` 아래에 worker별 CSV와 process별 manifest를 만든다. 기본 출력 위치는 Linux Agent의 `/tmp/knockin-roommate-board-results`이며 Controller 보고서에 자동 첨부되지 않는다. Windows Agent에서는 절대 경로로 변경한다. 다음 테스트의 resource 배포로 지워지지 않도록 worker의 스크립트 배포 디렉터리 밖에 저장한다. Agent 재시작/정리 전에 수집하고 지속 측정에는 별도 영속 출력 경로를 권장한다. 여러 Agent 파일은 같은 test ID의 한 폴더로 합친다. 파일명에 Agent/process/thread가 있어 충돌하지 않는다.

```bash
python performance-test/tools/summarize-roommate-board-samples.py \
  performance-test/results/<실행폴더>/request-samples \
  --expected-requests 500 --expected-workers 5
```

`expected-requests=VU×회수`, `expected-workers=VU`다. 집계기는 `request-summary.json`을 생성하며 오류·표본 누락 시 exit 1을 반환한다. 강제 종료 시 버퍼의 마지막 최대 99개 표본이 유실될 수 있으므로 **Controller의 성공+오류와 CSV 건수도 대조**한다. 개별 GET 종료까지 `nanoTime`으로 측정하며 검증/CSV 기록 시간은 지연에서 제외된다. 검증/파일 I/O는 다음 요청 발생 속도에는 영향을 주므로 Agent 자원과 Controller TPS를 함께 기록한다.

측정 외 DB 연결로 시험 전후 아래 값을 기록한다. `member_id IN (...)`에는 해당 시험 회원만 넣는다. 다른 트래픽과 분리하고 worker 종료 후 진행 중 요청이 완료된 것을 확인한다.

```sql
SELECT member_id, keyword, COUNT(*) AS history_count
FROM search
WHERE member_id IN (/* 시험 회원 ID */)
GROUP BY member_id, keyword;
```

오류·타임아웃·검증 실패 없는 인증 검색은 정규화된 keyword별 검색 기록 증가량이 해당 입력 요청 수와 같아야 한다. 익명 검색/키워드 없는 조회는 시험 회원의 증가량이 0이어야 한다. timeout 응답을 받지 못해도 서버 commit은 끝났을 수 있다. 오류가 있으면 성공 건수만으로 저장 증가량을 단정하지 않고 서버 로그/DB로 확인한다. 재시도는 하지 않는다. smoke·워밍업 요청의 증가분은 별도로 구분한다.

## 최종 개선 지표 기록 양식

| 환경·snapshot | 프로필 | VU·회수·반복 | 성공/오류율 | 성공 평균/p95/p99 | Controller TPS | 서버 CPU·GC·DB 대기 | 검색 이력 Δ | 판정 |
|---|---|---|---|---|---|---|---|---|
| before / 기입 | 기입 | 기입 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 |
| after / 동일 snapshot | 동일 프로필 | 동일 조건 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 | 미측정 |

- 지연 감소율: `(before-after)/before×100%`. 성공 평균/p95/p99를 각각 계산한다.
- 처리량 증가율: `(after-before)/before×100%`. 동일 부하와 판정 조건에서 비교한다.
- 오류율 차이는 %p로 기록한다. 실패 증가로 성공 요청이 줄어든 실행의 지연 감소를 개선으로 판정하지 않는다.
- 반복별 원본과 중앙값·범위를 함께 제시한다. 타임아웃은 완료 응답 지연이 아닌 검열 표본이다.
- SLO와 허용 오류율을 먼저 정한 뒤, 그 기준을 반복해서 만족하는 최대 시험 부하만 표시한다. 시험하지 않은 상위 부하나 운영 사용자 수로 외삽하지 않는다.

## 이번 검증 범위

기존 `ngrinder/agent:3.5.9-p1` 컨테이너의 Java 11·실제 Groovy/nGrinder/HTTP 라이브러리에서 두 스크립트와 공통 코드를 컴파일하고 오프라인 smoke를 통과했다. 필터/한글 keyword 전달, 응답 검증, Agent/process별 토큰 slot, timeout 실패 표시, CSV 및 토큰 비노출을 확인했다. Python 집계기 테스트 4개(개별 p95/p99, 누락, 중복, 오류 분리)도 통과했다. 이후 현재 소스의 H2 seed1000 서버로 실제 Controller 테스트 289~292를 수행했다. 기본 조회/빈번 검색 × 익명/인증 네 조건에서 각각 1 VU·3회 요청이 성공했고 CSV 누락/오류 0건, 인증 검색 이력 증가 3건을 확인했다. [실제 smoke 결과](../results/2026-09-30-roommate-board-list-smoke/report.md). 다른 snapshot/토큰 및 나머지 프로필은 실행 전 1 VU 검증을 수행한다. 이 smoke 단계에서는 기준선 부하 시험과 백엔드 최적화를 수행하지 않았다. 이후 기준선 실행과 장시간 대조 측정은 아래 기록에서 확인한다.


## 2026-09-30 탐색 기준선 실행기

전용 로컬 H2 seed1000 서버에서는 APM의 `tools/run-roommate-board-baseline.py`를 사용한다. 백엔드는 `test` 프로필, 시드 1,000, SQL 로그 비활성화 상태로 별도 기동하고 같은 JAR 경로를 지정한다. 실행기는 Controller/백엔드 주소를 로컬 주소로 고정한다. DB에서 필터 fixture와 기대 count를 확인하고 관심 관계 한 건을 준비한다. 검색 이력은 시험 회원의 신규 행만 정리하며 시드 행을 유지한다. 초기 identity sequence를 되돌리지는 않는다. Controller 설정은 종료 시 APM 템플릿으로 복원하고 임시 토큰 파일을 제거한다. 백엔드는 실행기를 호출한 측에서 종료한다.

```powershell
python -B performance-test/tools/run-roommate-board-baseline.py --output-directory performance-test/results/<측정일-주제>/<새-runId> --jar C:/dev/workspace/KnockIn/back/11th-1team-BE/build/libs/KnockIn-0.0.1-SNAPSHOT.jar
python -B performance-test/tools/summarize-roommate-board-baseline.py performance-test/results/<측정일-주제>/<runId>
```

기본 계획은 17개 프로필의 1 VU·3회 계약 검증, 기본 익명 목록/인증 빈번 검색의 별도 워밍업, 1→3→5 VU·각 100회·3반복이다. 선택 조건과 부하를 폭넓게 탐색하기 위한 실행이며 짧은 구간의 안정된 p99·SLO·운영 처리량을 보증하지 않는다. [실제 결과와 한계](../results/2026-09-30-roommate-board-baseline/report.md)를 확인한다.

최초 3 VU에서 발견한 공통 helper의 폴더 생성 경쟁 조건을 `Files.createDirectories`로 수정했다. HTTP 오류 0건이어도 worker 누락과 `STOP_BY_ERROR`는 실패로 처리한다. 수정 후 두 경로의 3 worker·9요청 검증을 통과했다. 나머지 프로필 계약 검증은 H2 fixture snapshot에 한정된다. 다른 DB/snapshot에서는 다시 기대 count·회원·관심/차단 관계를 준비해야 한다.


## 2026-09-30~10-01 네 경로 장시간 대조와 SQL 진단

`run-roommate-board-baseline.py --mode controls`는 익명/인증 × 검색어 유무 네 경로를 1 VU·3회씩 실행한다. 각 경로100건 워밍업 후 요청 속도로 회수를 보정하고 실제 GET 구간이 최소180초가 되도록 완료 요청 방식으로 실행한다. 실행 순서를 회전하고15초 휴식한다. 집계기는 처음30초를 제외한 `[+30초,+170초]`의 동일140초 구간에서 시작·완료한 요청만 비교한다. 이 구간의 성공 지연과 성공 처리량에 오류 건수/오류율을 함께 기록한다.

Controller 반복 상한10000회는 긴 익명 측정을 제한한다. 이 모드에서는 Controller가 idle인 것을 확인한 뒤 로컬 관리자 API로 상한만 일시1000000회로 높이고 종료 시 원래 설정과 실효 상한을 복원한다. Controller 재시작은 하지 않는다. 시간 종료나 한 반복에 여러 GET을 묶는 우회는 종료 시 통계/CSV 불일치를 일으켜 사용하지 않는다. `controller-limit.json`과 `cleanup.json`에서 복원을 확인한다. 강제 프로세스 종료 시에는 로컬 Controller 시스템 설정의 `controller.max_run_count`를 이전 값으로 복원하고 실효값을 확인해야 한다.

`passed=true`는 오류0·응답 계약·전체 집계·DB 증분·길이 검증을 모두 통과했다는 뜻이다. `measurementComplete=true`는 끝난 요청의 CSV/Controller/DB 집계와 구간 길이가 맞아 비교 가능한 측정이란 뜻이며 오류가 남아 있을 수 있다. 오류 있는 반복을 숨기지 않는다. 첫 장시간 시험의 통신 실패는 별도 관측 증거를 남긴 후 같은1VU 독립 조건만 계속 수집했다. 종료 상태 이상·표본/Controller 불일치·검색 이력 증분 불일치 시 남은 측정은 중단한다. 이 모드에서는 VU를 올리지 않는다.

```powershell
python -B performance-test/tools/run-roommate-board-baseline.py --mode controls --output-directory performance-test/results/<측정일-주제>/<새-runId> --jar C:/dev/workspace/KnockIn/back/11th-1team-BE/build/libs/KnockIn-0.0.1-SNAPSHOT.jar
python -B performance-test/tools/summarize-roommate-board-controls.py performance-test/results/<측정일-주제>/<runId>
python -B performance-test/tools/diagnose-roommate-board-sql.py performance-test/results/<측정일-주제>/<runId> --jar C:/dev/workspace/KnockIn/back/11th-1team-BE/build/libs/KnockIn-0.0.1-SNAPSHOT.jar
```

중단 후 동일 시험 DB를 유지한 경우에만 `--resume-controls`로 같은 output-directory를 이어간다. 성공/오류가 있는 완료 실행과 보정·종료 불일치 원본을 보존한다. 서버를 재기동했다면 새로운 runId를 사용한다. 백엔드의 `loggers` Actuator endpoint는 SQL 진단에서만 필요하다. 진단 실행기는12회 집계 검증과 Controller idle/H2를 확인한 뒤 H2 query statistics를 켜고 경로별10요청의 SQL 횟수·시간 증분을 수집한다. 그 다음 SQL/bind logger로 경로별1요청을 수집하고 실제 바인딩 값을 넣은 SELECT에만 `EXPLAIN ANALYZE`를 실행한다. 진단이 끝나면 통계와 logger를 원래 상태로 복원한다.

H2 SQL 통계의 실행 시간 단위는 ms다. `EXPLAIN ANALYZE`는 실제 쿼리를 실행하므로 본 측정과 분리한다. SQL 시간은 HTTP 전체·commit·네트워크 시간이 아니며 H2 결과를 PostgreSQL 운영 실행계획으로 외삽하지 않는다. [H2 System Tables](https://h2database.com/html/systemtables.html), [H2 Commands](https://h2database.com/html/commands.html).

[장시간 대조 측정과 진단 기록](../results/2026-09-30-roommate-board-controls/report.md).


최신 CSV schema2는 `failure`에 wrapper 예외 클래스를, `failureRoot`에 최대8단계까지 확인한 뿌리 예외 클래스만 남긴다. 예외 메시지·JWT는 남기지 않는다. 집계기는 schema1도 읽고 뿌리 예외가 없는 전송 오류 수를 구분한다. 이번 장시간 측정은 schema1이고 보강은 측정 종료 후 오프라인 검증·Controller 반영했다.

이번 결과와 엄격한 API 전후 비교를 할 때 `--script-directory performance-test/results/2026-09-30-roommate-board-controls/run-20260930-233949/measurement-source`로 같은 스크립트·리소스를 선택한다. 현재 도구의 기본은 APM 최신 소스다. 측정 당시 실행기와 소스 SHA256도 결과 폴더에 보존했다.

SQL 수집 후에는 다음 두 도구로 보고서와 읽기 전용 차단 SQL 후보를 확인할 수 있다. 후보 수치는 API 개선률과 분리한다.

```powershell
python -B performance-test/tools/summarize-roommate-board-sql.py performance-test/results/<측정일-주제>/<runId>/sql-diagnostics
python -B performance-test/tools/probe-roommate-board-block-sql.py performance-test/results/<측정일-주제>/<runId>
```
