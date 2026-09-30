# nGrinder 테스트 시나리오 상세 설계

[전체 계획·환경·데이터·통과 기준](./plan.md)과 함께 사용한다. 이 문서는 현재 구현에 근거한 스크립트 명세이며 실제 측정 결과는 아니다. P0는 첫 용량 검증에 필수, P1은 후속 업무 흐름·성장 검증, P2는 경계·장애 회귀다.

## 공통 계약과 판정

- REST 정상 응답은 현재 대상 컨트롤러 기준 HTTP 200 및 `{ "status": 200, "data": ..., "error": null }`이다. 생성 API라고 임의로 201을 기대하지 않는다. 오류는 HTTP status와 `error.code`/`codeNo`를 함께 확인한다.
- 익명 접근은 게시글·추천 **목록**과 허용된 메타 조회에 한정한다. 게시글·추천 상세는 SecurityConfig상 인증이 필요하다. 익명 사용자에게 상세 조회 성공을 기대하는 여정을 만들지 않는다.
- 모든 ID는 유효 fixture 또는 직전 응답에서 추출한다. 빈 목록을 성공적인 전체 여정으로 세지 않는다. 0건 검색은 명시된 별도 입력군에서만 정상 결과다.
- `runId + agentShard + processSlot + threadSlot + iteration`으로 고유 값을 만든다. 타임아웃 발생 시 후속 쓰기를 중단하고 결과 불명 목록에 기록한다. 특히 토글·생성·메시지 송신을 자동 재시도하지 않는다.
- 정상 혼합, 인기 집중, 같은 계정 경쟁, 예상 거절은 각각 다른 test/run/metric으로 측정한다.
- 데이터 확인용 GET도 조회수 증가·읽음 처리를 유발할 수 있다. 필요한 사후 DB 읽기는 측정 종료 후 별도 연결에서 수행하며 그 비용을 서비스 RPS에 포함하지 않는다.

## 시나리오 목록

| ID | 우선순위 | 시나리오 | 주요 측정 축 |
|---|---|---|---|
| S00 | P0 | 탐색 화면 진입·알림 polling | 초기 동시 요청, 인증 조회 비용 |
| S01 | P0 | 게시물 목록·검색·상세 | 복합 필터, count, 검색 이력 INSERT, hits 경합 |
| S02 | P0 | 추천 목록·상세·추가 탐색 | random 정렬, 배치 조회, Java 점수 계산 |
| S03 | P0 | 게시물·회원 관심 토글 | 인기 행 잠금, 최초 삽입·최종 상태 |
| S04 | P0 | 직접 채팅방 생성 | 최초 메시지·방·참여자 저장, 중복 생성 |
| S05 | P0 | 채팅 목록·누적 이력 조회 | 전체 메시지 직렬화, 읽음 UPDATE |
| S06 | P0 | STOMP 대화 | 연결 수, 전송률, 상대 수신·저장 |
| S07 | P1 | 룸메이트 요청·수락·거절·취소 | 역할별 상태 전환, 수락 경쟁 |
| S08 | P0 | 알림 REST·SSE | 미읽음 누적, 스트림 수, 전달·재접속 |
| S09 | P1 | 공유 일정·반복 일정 | 반복 계산, 월/일 조회, 수정 범위 |
| S10 | P1 | 신규 온보딩·기존 프로필 수정 | 다중 테이블 변경, 선호·점수 반영 |
| S11 | P1 | 메타·인기 검색어 | 검색 이력 전체 집계의 증가 비용 |
| S12 | P1 | 게시글·채팅 이미지 업로드 | multipart, 메모리, 저장소·네트워크 |
| S13 | P2 | 예상 거절·경계·외부 지연 | 실패 분리, 자원 회수, 회복 |

## S00. 탐색 화면 진입과 주기 조회

**전제**: 익명 집단과 완성 프로필을 가진 로그인 집단. 알림 조회기는 로그인 VU마다 하나만 둔다.

**흐름**

1. 화면 진입 시 `GET /roommate/boards?page=0&size=20&sort=createdAt,DESC`와 `GET /roommate/matches?size=20`을 호출한다.
2. 로그인 VU는 `GET /users/me/preferences/all`, `GET /alarms`를 추가한다.
3. 화면 체류 동안 알림을 15초마다 조회한다. 최초 poll 시각에 jitter를 두고, 이후 주기를 유지한다.
4. 다음 행동은 게시물 탐색(S01) 또는 추천 탐색(S02)으로 연결한다. 한 화면의 시작 비용과 이후 스크롤 비용을 분리한다.

**설계·검증**: 프런트는 활성 탭과 관계없이 두 목록 query를 사용한다. 첫 재현은 요청별로 계측하되 동시 fan-out을 지원하는 client/harness를 사전 검증한다. 동시 요청 구현이 없어서 직렬 호출했다면 그 차이를 결과에 명시한다. callback/보조 thread 통계가 nGrinder worker에 정확히 귀속되는지도 확인한다. 화면 전환 후 cache hit/재요청 여부는 프런트 실제 동작에 맞춰 조정하며 같은 쿼리 구독 개수를 그대로 HTTP 건수로 복제하지 않는다.

**관측**: 화면 진입 전체 시간, API별 지연, 순간 요청량, 인증 관련 DB 조회. 초기 진입과 재방문을 구별한다.

## S01. 게시글 탐색·필터 검색·상세

**전제**: 유효 게시글·작성자·이미지·지역·방 유형을 가진 D1/D2. 로그인 VU는 본인과 다른 작성자의 게시글을 조회한다.

**호출 순서**

1. `GET /roommate/boards?page=0&size=20&sort=createdAt,DESC`에서 `data.content[].id` 추출.
2. 로그인 집단은 반환된 ID로 `GET /roommate/boards/{boardId}`. 익명 집단은 목록까지만 측정.
3. `page=1`, 필요 시 `page=2`로 이동. `data.last`가 참이면 종료.
4. 별도 반복에서 필터 또는 keyword를 적용한다. URI query 값은 URL encode한다.

| 입력 축 | 기준 / 비교 |
|---|---|
| 정렬 | `sort=createdAt,DESC`, `sort=hits,DESC` |
| 필터 | `regionIds`, `roomTypeIds`, `gender`, `minDeposit`, `maxDeposit`, `minMounthRent`, `maxMounthRent` |
| 검색어 | 고빈도 일치 / 희소 일치 / 의도한 0건; 한글 포함. 제목·지역·방 유형 대상 |
| 선택도 | 필터 없음 / 단일 지역 / 지역+방 유형+예산+성별 |
| 페이지 | 0/1/2와 데이터가 충분한 깊은 페이지 50/500 별도; 빈 페이지 반복으로 대체하지 않음 |
| 접근 분포 | 여러 게시글 분산 / 상위 인기 집중 / 단일 게시글 상세 집중 |

월세 query 이름은 현재 `minMounthRent`/`maxMounthRent`다. 이름을 교정해 전송하면 필터가 빠질 수 있으므로 알려진 결과 집합으로 필터 적용을 확인한다. 배열 파라미터는 Controller binding smoke를 통과한 하나의 표현으로 고정한다.

**정확성**: 응답 개수 ≤ size, 요청 필터에 맞는 데이터, 제외 fixture 미노출, 상세 `data.boardId` 일치, 관심 상태 일치. 고정 스냅샷의 목록에서 count·페이지 경계도 확인한다. hits가 변하는 동시 시험은 정렬 중 이동하는 결과를 정적 pagination 불변조건과 섞지 않는다.

**특화 검증**: 로그인 + 공백 아닌 keyword는 매 요청 검색 이력을 저장한다. 익명 검색과 키워드 없는 조회를 별도 metric으로 둔다. 상세는 hits를 갱신하므로 성공 상세 수와 DB hits 증가량을 대조한다. 이 검증에 상세 GET을 추가 호출하지 않는다. 타임아웃이 있어 commit 여부가 불명확하면 서버 로그/DB로 확정할 때까지 정확한 증가량 판정을 보류한다.

**관측**: content/count 쿼리 시간, 검색 이력 INSERT, hits UPDATE 및 row lock 대기, 상세 점수 계산, 응답 byte. 데이터 크기·페이지·집중도를 한 번에 바꾸지 않는다.

## S02. 추천 탐색과 적합도 계산

**전제**: 로그인 주 부하 계정에 생활패턴·선호·중요 조건이 존재하고, 후보에는 공개/활성 SEEKER·OFFER가 충분히 있다. 익명과 생활패턴 없는 계정은 별도 cohort다.

**호출 순서**

1. `GET /roommate/matches?size=20` → `data.content[].memberId` 수집.
2. 로그인 VU는 한 명을 선택해 `GET /roommate/matches/{memberId}`.
3. 반환받은 **전체** memberId를 누적한 `excludeMemberIds`로 추가 목록 요청을 2~3회 수행한다. `last=true` 또는 새 후보가 없으면 종료한다.
4. 새 탐색 세션에서는 제외 목록을 초기화한다. 관심 목록은 `likedOnly=true`로 별도 조회한다.

**입력 변형**: `size=1/20/50`, exclude 개수 0/20/200/1,000, D1/D2를 하나씩 바꾼다. 긴 exclude는 ingress request-line 한도 안에서 정상 부하로 수행하고 한도 초과는 S13으로 분리한다. URI byte 수를 기록한다. 이 API는 `page`·예산·지역 필터를 받는 게시글 검색 API가 아니다.

**정확성**: 응답은 Page가 아닌 Slice다. `content.length ≤ size`, 응답 내 중복 없음, 본인/명시적 제외 ID/차단/비공개/비활성 후보가 목록에 없는지 확인한다. DB random 정렬이므로 동일 순서나 특정 첫 후보를 기대하지 않는다. 익명 또는 요청자 생활패턴 없음은 `score=null`이 정상이고, 계산된 점수는 0~100이다. 대표 프로필 쌍은 별도 정답 fixture로 기대 점수를 확인해 항상 null/0인 저비용 경로만 타지 않게 한다.

추천 상세의 노출 필터는 목록과 완전히 같지 않다. 차단·비활성 후보를 직접 ID로 조회하는 정책은 S13에서 기능 계약부터 확인하고 정상 부하의 성공 데이터로 사용하지 않는다. `GET /roommate/matches/score`는 빈 DTO이므로 사용하지 않는다.

**관측**: 후보 random 정렬, size+1 추출, 관련 데이터 batch 조회와 점수 계산의 CPU/쿼리 수, exclude 길이에 따른 계획 변화. 프런트 매칭 상세의 별도 목록 query가 실제 추가 호출되는 경우 해당 호출도 S00식 진입 비용으로 반영한다.

## S03. 관심 등록·해제와 잠금 경쟁

게시글은 `POST /roommate/boards/{boardId}/likes`, 회원은 `POST /roommate/matches/{memberId}/likes`다. 두 API 모두 **토글**이며 응답 `data.updatedAt`에 최종 interested 값은 없다.

**정상 여정**: 초기 OFF fixture → POST → 해당 `likedOnly=true` 목록에서 포함 확인 → 상세 `interested=true` 확인 → POST → 관심 목록에서 제외 확인. 목록 첫 페이지에 항상 대상이 있다는 전제는 두지 않으며 관심 수가 적은 독립 fixture 또는 페이지 탐색으로 확인한다. 검증 GET은 별도 metric으로 집계한다.

| 실험 | 계정·대상 배치 | 기대 검증 |
|---|---|---|
| C1 분산 | VU별 서로 다른 사용자·게시물/회원 | 일반 토글 비용 |
| C2 인기 게시물 | 여러 사용자 → 같은 게시물 | 게시물 행 잠금으로 인한 대기·처리량 비교 |
| C3 동일 쌍 | 같은 user-target을 N개 동시 요청 | 최초 OFF/ON 각각 최종 parity·중복 행 확인 |
| C4 회원 최초 관계 | 아직 관계 행 없는 같은 회원 쌍 | 최초 INSERT race, 실제 DB unique 제약 및 중복 여부 |
| C5 회원 기존 관계 | 미리 만든 관심 행을 동시 토글 | 기존 행 lock과 C4의 차이 |

동시 요청은 독립 run에서 2/10/50개 묶음으로 같은 예정 시각에 시작한다. Agent 간 시계를 맞추고 실제 도착 분산을 기록한다. 한 JVM barrier가 전체 Agent를 동기화한다고 가정하지 않는다.

**불변조건**: 쌍별 관심 관계가 중복되지 않고, `최종 ON = 초기 ON XOR (DB에 적용된 토글 수 mod 2)`다. 타임아웃이 없고 모든 요청이 성공했을 때만 성공 응답 수를 적용 수로 사용할 수 있다. 타임아웃은 결과 불명으로 분류해 별도 감사한다. 인기 게시글의 hot badge는 실제 정책 임계값 전후도 확인한다. 일반 부하에서 동일 계정을 공유해 토글이 상쇄되도록 만들지 않는다.

## S04. 직접 채팅방 생성

**전제**: 활성·차단 없음·기존 활성 방 없음인 전용 A/B 쌍. 각 회원 활성 방 수 < 5이며, 종료 시 방을 나갈 수 있도록 A/B 모두 활성 룸메이트가 없어야 한다. 일반 탐색 pool과 분리한다.

```json
{
  "requesteeId": 123,
  "chatMessage": { "contents": "perf-<runId>-<pairId>-first" }
}
```

`123`은 fixture B ID로 치환한다. 게시글 진입은 `boardId`도 전달할 수 있으나 현재 서비스는 이를 저장 로직에 사용하지 않으므로 게시글 연결 성공을 assertion으로 삼지 않는다.

**순서**: A `POST /chats` → `data.chatRoomId` 저장 → A/B `GET /chats`에 방이 보이는지 확인 → B `GET /chats/{id}`에서 최초 메시지 확인 → 필요 시 S06 → A/B `POST /chats/{id}/leave` → 연결 종료. 각 요청 시간을 분리한다. cleanup은 최초 생성 성능 metric에서 제외한다.

**검증**: 단일 활성 방, A/B 참여자, 최초 메시지 정확히 한 건. 메시지에 넣은 run 식별자로 시스템 메시지와 구별한다. DB 생성 상태를 API 결과와 대조한다.

**변형**: fresh pair 생성 / 같은 pair 생성 재요청 / 서로 다른 상대와 상한 4→5 / 이미 5개인 회원의 생성 거절. 마지막 셋은 정상 성공 부하와 별도 측정하고 현재 계약을 smoke로 고정한다. 같은 A/B의 동시 최초 생성에서 중복 방이 없는지는 별도 정합성 시험이다. 단순 반복 생성으로 5개 제한에 걸리는 실행을 정상 TPS 결과로 사용하지 않는다.

## S05. 채팅 목록과 읽음 처리

**전제**: 회원당 활성 방 1/3/5개, 방당 메시지 0/100/1,000/10,000개. 이미 읽은 cohort와 다량 미읽음 cohort를 분리한다.

**순서**: `GET /chats`의 `data[].chatRoomId` 중 소유 방 선택 → `GET /chats/{id}` → 다시 목록에서 미읽음 `messageCount`와 마지막 메시지 확인.

**검증**: 상대 프로필·messages·최근 메시지 일치, 소유 방만 조회, 읽기 전후 미읽음 감소. 신규 메시지 생산이 없는 정적 cohort에서는 읽은 뒤 미읽음 0을 기대한다. 메시지가 계속 유입되는 S06 동시 시험에서는 관측 시점별 신규분을 고려한다.

상세 GET은 전체 메시지를 반환하며 읽음을 갱신한다. 같은 방만 반복하면 첫 요청 뒤 쓰기 비용이 사라진다. **미읽음 첫 열람**은 충분한 fresh 방 pool에서 1회씩, **기열람 재조회**는 고정 방에서 측정한다. 임의 page/size를 붙여 실제로 pagination됐다고 가정하지 않는다.

**관측**: 응답 byte, 직렬화·heap/GC, DB 메시지 조회 및 읽음 UPDATE row 수, 잠금 대기. 대용량 방의 표본을 빠른 소형 방과 합쳐 판단하지 않는다.

## S06. STOMP 연결·양방향 메시지

**전제**: S04 또는 seed로 만든 A/B 방, 충분한 토큰 수명, 호환되는 nGrinder Java STOMP client. 1쌍 검증을 통과해야 확장한다.

```text
WS 연결: /ws-chat
STOMP CONNECT native header: Authorization: Bearer <accessToken>
SUBSCRIBE: /sub/chats/{chatRoomId}
SEND: /pub/chats/{chatRoomId}/messages
TEXT body: {"clientMessageId":"<run>-<pair>-<seq>","type":"TEXT","message":"..."}
IMAGE body: {"clientMessageId":"<run>-<pair>-<seq>","type":"IMAGE","imageUrl":"<S12 결과>"}
```

HTTP Upgrade의 인증만으로 CONNECT 인증을 대체하지 않는다. native WS를 기본으로 시작하고, SockJS 사용 시 별도 cohort로 표시한다. 프런트는 heartbeat 입출력 10초를 요청하므로 서버와 실제 협상된 heartbeat를 기록한다.

**순서**

1. A/B 연결 및 CONNECTED 확인 → 양쪽 구독 → 준비 메시지 왕복으로 구독 준비 확인(워밍업 표본).
2. 20/200/500자 TEXT를 제안 비율 50/40/10%로 교대 전송한다. 송신마다 고유 clientMessageId 사용.
3. 반대편 `USER_MESSAGE` 이벤트의 `chatRoomId`, `payload.clientMessageId`, `senderId`, `contents`를 확인한다.
4. 메시지 drain 후 DB/REST의 사용자 메시지 수와 내용 확인 → UNSUBSCRIBE/DISCONNECT/소켓 close.

**부하 축**: 총 연결 20→100→500→1,000개(2개/방), 연결당 송신 0.05/0.2/1건·초를 별개로 변화시킨다. 연결만 유지하는 idle 부하와 메시지 부하를 분리한다. 100연결×0.2건/초라면 송신 20건/초이며 broker fan-out 수신 건수는 별도다. Agent 연결 한계도 먼저 확인한다.

**성공 정의**: SEND 호출 완료가 아니라 **상대방의 대응 이벤트 수신** 및 저장이다. 초기 메시지·시스템 메시지와 시험 TEXT를 분리하고 송신자 echo를 상대 수신으로 중복 계산하지 않는다. `clientMessageId`는 상관 ID이지 서버의 idempotency key가 아니다. 중복 송신이 DB에서 자동 제거된다고 가정하지 않는다. 누락·중복·허용되지 않은 방 수신은 0건이어야 한다.

**시간 측정**: 같은 Agent가 A/B를 담당하면 같은 단조 시계로 전송→수신을 잰다. 서로 다른 Agent면 시계 오차를 기록하거나 왕복 측정으로 보완한다. 시험 종료 후 최대 10초 drain/수신 timeout을 두고 미수신 표본도 실패로 계수한다.

**확장**: 재접속 10% 동시/전체 집중, 토큰 만료, 한쪽 퇴장, 비참여자 구독은 S13으로 분리한다. 다중 백엔드라면 A/B 연결·REST 요청을 같은 인스턴스/서로 다른 인스턴스로 배치해 전달을 비교한다. simple broker만으로 인스턴스 간 전달이 보장된다고 가정하지 않는다.

## S07. 룸메이트 요청과 상태 전환

**전제**: 활성 A/B 채팅방, 현재 PENDING 요청 없음, 수락 집단은 양쪽 모두 활성 룸메이트 없음. accept/reject/cancel에 서로 다른 fixture 쌍을 배정한다.

**순서**

1. A `POST /roommate-requests`, body `{"chatRoomId": <id>}`.
2. `data.roommateMatchingRequiredInfo.requiredId` 저장.
3. B `GET /roommate-requests?page=0&size=20&sort=createdAt,DESC`에서 `data.content[]`의 requiredId·PENDING·A/B·chatRoomId 확인.
4. B `POST /roommate-requests/{requiredId}/accept` 또는 `/reject`; 취소 집단은 A가 `/cancel`.
5. accept는 A/B `GET /roommates/me`에서 같은 `data.id`, `data.chatRoomId` 확인. 관계·점수 생성 및 공개 설정 PRIVATE 전환을 후검증한다.
6. 필요하면 S09로 연결한다. 복원 시 `DELETE /roommates/me/{myRoommateId}` 후 방 나가기. 관계 삭제 시 PUBLIC으로 바뀌므로 탐색 후보 pool에 섞지 않는다.

**불변조건**: 요청은 한 최종 상태, 수락 시 회원당 활성 룸메이트 관계 하나, 중복 관계 없음. 같은 처리 완료 ID를 매 반복 다시 accept하지 않는다. 룸메이트가 있으면 방 나가기가 거절될 수 있으므로 leave만으로 원복하지 않는다.

**경합 시험**: 동일 PENDING에 accept↔reject, accept↔cancel; B가 A/C의 서로 다른 요청을 동시에 수락. 정상 흐름과 분리하며 최종 상태·관계·점수·알림을 DB audit한다. 현재 코드의 조회 후 상태 변경에 대해 동시성 보장을 선제적으로 가정하지 않는다.

**실시간 연계**: STOMP `ROOMMATE_REQUEST`를 수신 검증한다. SSE `ROOM_MATCHING`은 요청 생성 시 B, 수락·거절 시 A가 수신한다. 취소에는 현재 SSE 발송이 없으므로 STOMP 상태 변경만 기대한다. legacy `/chat-requests`의 accept는 상태만 바꾸므로 이 시나리오의 방 생성 단계로 사용하지 않는다.

## S08. 알림 목록·읽음과 SSE

### S08-A REST

`GET /alarms?page=0&size=20`의 `data.alarms[]`에서 소유 알림 ID → `PATCH /alarms/{id}/read` → 목록에서 읽음 확인. 별도 run은 `PATCH /alarms/read-all` 전후 미읽음 수를 비교한다. 응답을 `data.content`로 파싱하지 않는다.

회원당 미읽음 0/20/1,000건을 분리한다. read-all 반복은 처음 한 번 이후 비용이 달라지므로 fresh 회원 pool을 소비한다. 15초 polling은 S00/M1의 VU별 단일 스케줄과 합쳐 중복 생성하지 않는다.

### S08-B SSE

**연결**: `GET /alarms/subscribe`, `Accept: text/event-stream`, Bearer 인증. 정상 부하는 **계정당 하나의 연결**이다. 현재 memberId별 emitter 하나가 저장되며 중복 연결은 최근 emitter로 대체된다.

**순서**: B 스트림 연결 → A가 S07의 룸메이트 요청으로 이벤트 발생 → B `ROOM_MATCHING` 수신 → 이벤트 data의 알림 `id`를 `/alarms` 결과와 연결 → 읽음 검증 → close.

초기 연결 이벤트·heartbeat가 없어 응답 전체 완료 또는 최초 byte를 기다리면 준비 판단이 멈출 수 있다. 준비용 합성 이벤트를 보내 스트림 수신을 확인하고 그 표본과 상태를 본 측정에서 분리한다. 이 준비 요청도 fixture를 소비한다.

**부하 축**: 연결 10/100/500/1,000개, 알림 생성률 1/5/20건·초를 독립 설정한다. 연결 대상과 유발 A/B 쌍을 충분히 공급한다. 정상 해제, 네트워크 강제 해제, 1시간 emitter timeout 이후 재접속, 동시 재접속을 분리한다. soak는 1시간을 넘어 실제 timeout 경계를 포함한다.

**검증**: 안정 연결 구간에서 기대 알림 ID의 전달·저장·수신자 일치 및 누락 없음. SSE transport event ID는 회원/시간 기반이므로 DB 알림 `data.id`도 함께 사용한다. `Last-Event-ID` replay 구현을 전제로 하지 않는다. 단절 구간은 REST 알림 목록으로 복구한 수와 SSE 미수신 수를 각각 보고한다. 같은 회원 두 기기 구독은 S13의 계약 검증이다.

**관측**: 연결 준비시간, 이벤트 지연, emitter 수, socket/thread/heap, disconnect 후 자원 회수. REST 200과 FCM 비동기 전송 완료는 별개다. 다중 인스턴스 SSE 구독과 이벤트 생산이 다른 서버에 배치되는 경우도 검증한다.

## S09. 공유 일정과 오래된 반복 일정

**전제**: 수락 완료 A/B, `GET /roommates/me`에서 얻은 myRoommateId. writer는 A, 담당자 memberIds는 A/B만 사용한다.

**조회**: `GET /roommates/me/calendar?year=<Y>&month=<M>`에는 day를 넣지 않는다. `data.calendarDays[].targetDate/exists`로 날짜를 선택한 뒤 `year`, `month`, `day`를 모두 전달해 `data.calendars[]`를 조회한다. 날짜는 run 기준 월로 생성한다.

**쓰기 여정**

1. A `POST /roommates/me/calendar`로 `calendar:{myRoommateId,title,contents,startDate,endDate}`, `categoryName`, `memberIds:[A,B]` 전송. startDate < endDate, 고유 run title 사용.
2. 생성 응답에는 updatedAt만 있으므로 일 목록에서 고유 title·시간·담당자가 맞는 단 한 건을 찾아 `calendarBasicInfo.calendarId`를 얻는다.
3. B 일 목록에서 확인 → A `PUT /roommates/me/calendar/{calendarId}` → 일 목록으로 변경 확인 → A `DELETE` → 목록 제외 확인.

상세 `GET /roommates/me/calendar/{id}`는 현재 빈 DTO라 검증에 사용하지 않는다. 수정·삭제는 작성자 권한을 사용하며 B도 언제나 수정 가능하다고 가정하지 않는다.

**반복 변형**: `/calendar/repeat` POST에 `repeatInfo:{endDate,repeatType}` 추가. `WEEKLY`, `BI_WEEKLY`, `MONTHLY` 및 시작 시점 1개월/1년/5년 전을 나눠 이번 달을 조회한다. 반복 수 1/20/100개 cohort, 기간 겹침·월 경계·2월·윤년은 정답 달력 fixture와 대조한다. 실제 구현은 시작일부터 반복 계산하므로 오래된 시작일을 시험해야 한다.

반복 수정 PUT `/roommates/me/calendar/repeat/{calendarId}`에는 `modifyType: THIS|THIS_AND_FOLLOWING|ALL`, `originalCalendar:{startDate,endDate}`를 연계한다. ID는 기본 일정 ID이며 반복 테이블 PK가 아니다. THIS는 원 회차 제외+새 회차 하나, 이후 변경은 경계 전/후, ALL은 전체를 일 목록으로 검증한다. 정상 성능 데이터에는 명시 종료일을 둔다. 종료일 null은 조회 조건에 따른 누락 가능성이 있어 먼저 S13 기능 검증 대상으로 둔다.

## S10. 신규 온보딩과 기존 프로필 수정

**신규 집단**: 외부 로그인만 완료한 시험 계정을 충분히 사전 준비한다. 계정당 1회 `POST /users/me/profile/all` → `POST /users/me/preferences/all` → 각각 GET 재조회 → 추천 목록을 수행한다. 같은 계정에 POST를 무한 반복하면 신규 등록 시험이 아니다.

| DTO | 중요한 필드·ID |
|---|---|
| profile/all POST | `name` 10자 이하, 과거 `birth`, `gender`, `email`, 현행 `terms`, `lifestyles`는 LifePatternInformation ID 목록 |
| 방 정보 | `type`은 `OFFER` 또는 `SEEKER`, `region` ID 목록, `roomProfile` 방 유형 ID 목록, `comeEnableAt`, 보증금·월세 값 |
| 월세 JSON | `minMonthlyRent`, `maxMonthlyRent`, `monthlyRent` 사용. 게시글 query/생성 DTO와 혼동 금지 |
| preferences/all POST | `lifestyles:[LifePatternInformation ID]`, `conditions:[LifePattern ID]` |

**기존 집단**: GET `/users/me/profile/all`, `/users/me/preferences/all` → PUT `/users/me/profile/lifestyle` 또는 `/users/me/preferences/all` → GET 재확인. 수정 lifestyles의 항목은 단순 Long 배열이 아니라 `{id: 회원의 기존 관계 행 ID, lifestyleId: 새 값 ID}`다. ID는 GET 결과와 DTO를 대조해 연결하고 다른 회원의 ID를 재사용하지 않는다.

**변형**: 생활패턴 개수, 중요 조건, 여러 지역/방 유형, OFFER↔SEEKER 전환, 같은/다른 값을 반복 수정. 신규 등록과 수정·이력 누적 시험을 따로 보고한다.

**검증**: 기본정보·약관·방 subtype·생활패턴·선호의 변경 반영, 유실/중복 없음, fixture 정답 점수의 변화. PUBLIC/PRIVATE 상태와 목록 노출도 setup에서 확인한다. 이력 증가량 및 장시간 수정 후 조회 지연을 측정한다.

## S11. 메타 조회와 인기 검색어 집계

**대상**: `GET /terms`, `/meta/regions`, `/meta/room-types`, `/meta/lifestyle-patterns`, `/meta/room-add-options`, `/search/popular`.

첫 앱 진입에서 필요한 메타를 읽는 묶음과 개별 endpoint 기준 성능을 구분한다. 반환 ID·필수 데이터·스키마를 검증하며 nGrinder 스크립트가 자체 캐시해 요청을 보내지 않는 구간을 서버 성능으로 세지 않는다.

**인기 검색어 특화**: S01 인증 keyword 검색으로 이력을 증가시킨 뒤 고정 snapshot 10만/100만 건을 비교한다. 현재 구현은 시간 범위 없이 검색 이력 전체를 keyword로 GROUP BY/count한다. 고빈도 몇 단어 중심과 고유 키워드가 많은 집합을 분리한다. 상위 개수는 실행 정책(`popular.count.size`, 기본 10)을 확인하고 동점 순위를 고정 assertion으로 두지 않는다.

## S12. 파일 업로드와 게시글 작성

외부 대역/로컬 저장/R2 시험은 별도 결과다. 성능 기본 파일은 유효 이미지 100KiB/1MiB/5MiB로 준비하고 크기·checksum·MIME을 고정한다. Agent가 매번 파일을 생성하거나 로그에 응답을 모두 쓰지 않게 한다.

### 게시글 multipart

1. A `POST /roommate/boards`: `request` JSON part + 반복 `files` binary part.
2. request는 `title`, `contents`, `deposit`, **`mountlyRent`**, `managementCost`, `roomTypeId`, `regionId`, `comeableDateNegotiable`, `comeableDate`, `images:[{fileIndex,thumbnail}]`, `extraOptionIds`를 DTO에 맞춰 준비한다. 생성 월세 철자가 수정 DTO와 다르다.
3. 응답은 updatedAt뿐이다. `GET /users/me/boards`의 `data.boards`에서 VU별 고유 제목으로 boardId를 찾고 필요하면 페이지를 탐색한다. 생성 cohort의 소유 게시글 수를 제한해 ID 탐색 부하를 통제한다.
4. 상세/편집 form 조회 → A `PUT /roommate/boards/{boardId}` → 필요 시 A `DELETE`로 정리한다.

수정 JSON은 `monthlyRent`, `existingImages:[{boardFileId,thumbnail}]`, `newImages:[{fileIndex,thumbnail}]`, `deleteExtraOptionIds`, `newExtraOptionIds` 등 실제 DTO를 사용한다. fileIndex와 files 순서를 일치시키고, 이미지가 있다면 실제 정책에 맞는 대표 이미지 수(기본 1)를 유지한다. 무이미지/1장/정책 상한 근처(현재 최대 10장)를 분리한다. 생성 DTO의 보증금·월세 상한도 smoke에서 충족한다.

### 채팅 이미지

참여자가 `POST /chats/{chatRoomId}/images`의 `file` part를 업로드 → `data.imageUrl` 저장 → S06에서 IMAGE 전송 → 상대 이벤트 및 DB 파일 연결을 확인한다. upload만 성공하고 SEND하지 않은 경우는 메시지 전송 성공으로 세지 않는다. 업로드 응답 값이 항상 완전한 HTTP URL이라고 가정하지 않는다.

**관측**: 업로드 latency/byte·Agent/서버 bandwidth·heap/GC·파일 byte 배열 할당·R2 지연·고아 파일. 파일 cleanup은 run 업로드 manifest로 수행한다. 단순 게시글 soft delete가 저장소 파일까지 정리한다고 가정하지 않는다.

## S13. 예상 거절·연결 경계·외부 지연

정상 성능 실험과 별도 run에서 낮은 부하부터 수행한다. REST 거절은 **예상 HTTP status + error.code + 상태 변화 없음**, STOMP 거절은 **ERROR 프레임의 JSON status·error 및 메시지 미저장**, SSE는 **연결 종료·재접속·이벤트 전달 상태**로 판정한다. 이미 열린 스트림이나 STOMP 프레임 오류에 새 HTTP 오류 응답을 기대하지 않는다. 배포 커밋의 오류 enum과 smoke 응답으로 계약을 고정한다. 현재 duplicate PENDING 룸메이트 요청은 404, 처리 완료 상태는 409, 잘못된 역할은 403처럼 직관과 다른 계약이 있으므로 모든 실패를 한 4xx 기대값으로 묶지 않는다.

| 케이스 | 검증 목적 |
|---|---|
| 만료/누락 JWT, 익명 상세, 익명 likedOnly | 정상 데이터 실패를 빠른 성능 성공으로 계산하는 오류 방지 |
| 비참여자 채팅 조회·SUBSCRIBE/SEND | 거절과 비인가 메시지 유출 없음 |
| 차단 상대와 채팅, 5개 상한, 퇴장 후 접근 | 정책 거절, 새 방/메시지의 부당 생성 없음 |
| 본인과 직접 채팅방 생성 | 현재 서비스에 명시적 본인 검증이 없어 제품 정책·기능 smoke를 먼저 확인; 특정 거절 코드를 가정하지 않음 |
| S03 동일 토글, S04 중복 생성, S07 수락 경쟁 | 최종 DB 상태, 중복 관계·중복 방·이중 수락 없음 |
| 추천 size 0/51, 과도한 exclude URL | 입력 검증과 gateway 한도, 5xx/자원 고갈 여부 |
| 공개·차단·활성 상태가 목록/상세에서 다른 후보 | 제품 정책 확인과 기능 결함 분리; 정상 API 결과로 강제 허용하지 않음 |
| 반복 일정 무기한 종료, 경계 일자 | 누락/중복 여부를 먼저 확인한 뒤 성능 fixture 채택 |
| SSE 같은 계정 2개 연결 | 최근 연결 전달 정책, 예전 연결 종료·자원 회수 |
| WS/SSE 강제 단절·토큰 만료·재접속 | backoff, 재연결 폭주, 손실/중복, 연결/heap 회수 |
| 다중 백엔드에서 생산자/구독자 분리 | 프로세스 내 broker/emitter의 전달 범위 확인 |
| 저장소/FCM/메일 대역에 100/500/2,000ms 및 1/5% 실패 주입 | 외부 호출 timeout, 비동기 대기·실패, 정상화 후 backlog 해소 |

외부 장애 주입은 해당 대역을 실제 호출하는 경로에서만 의미가 있다. 기본 FCM 토큰 없음 cohort의 조기 반환 경로는 이 실험을 대신하지 않는다. 사용자-facing 성능과 외부 비동기 완료를 각각 보고한다. 메일 인증·OAuth·관리자 BO·탈퇴/정리 배치는 첫 핵심 부하 범위에서 제외하고 사용량이나 운영 요구가 확인되면 별도 계획을 추가한다.

## 구현·검증 시 참고할 파일

- [게시글 목록 DTO](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/board/dto/BoardListDto.java), [추천 목록 DTO](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/util/dto/MatchListDto.java), [게시글 생성 DTO](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/board/dto/BoardDto.java), [게시글 수정 DTO](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/board/dto/BoardModifyDto.java).
- [채팅 생성 DTO](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/chat/dto/ChatRoomCreateDto.java), [STOMP 메시지 DTO](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/chat/dto/ChatMessageDto.java), [STOMP 인증/권한](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/global/config/StompAuthenticationChannelInterceptor.java), [룸메이트 요청 서비스](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/mate/service/impl/RoommateRequestServiceImpl.java), [일정 서비스](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/mate/service/impl/CalendarServiceImpl.java).
- [신규 프로필 DTO](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/member/dto/SaveProfileAllDto.java), [선호 수정 DTO](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/life/dto/ModifyPreferencesAllDto.java).
- 프런트 근거: [탐색 진입](../../../../KnockIn/front/knock-in-rn/components/tabs/explore/use-explore-screen.ts), [목록·추천 pagination](../../../../KnockIn/front/knock-in-rn/lib/api/use-roommate.ts), [게시글에서 채팅 시작](../../../../KnockIn/front/knock-in-rn/components/room/detail-screen/use-room-detail-screen.ts), [STOMP 연결](../../../../KnockIn/front/knock-in-rn/lib/api/use-chat-socket.ts), [알림 polling](../../../../KnockIn/front/knock-in-rn/lib/api/use-notifications.ts), [SSE](../../../../KnockIn/front/knock-in-rn/lib/api/use-alarm-stream.ts).
