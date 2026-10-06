# KnockIn 백엔드 nGrinder 부하 테스트 계획

- 작성일: 2026-09-20
- 갱신일: 2026-09-28 — H2 조회 API 시드 선정·단계별 부하 탐색 반영
- 최초 서비스 분석: `back/11th-1team-BE`, 커밋 `cb6073c7d4d4bb636ff35e428447690268b43c3f`; 계측 구성 재확인: `98130f0b530949b53c67d19907e78d9ea74fe35d`
- 상태: **H2 조회 API 탐색 측정 진행 / PostgreSQL 기반 용량 시험 전**
- 상세 설계: [테스트 시나리오](./scenarios.md)
- 기존 환경 적용: [APM Compose 기반 실행·관측 전략](./apm-environment.md)
- 실행 결과 조사: [2026-09-21 `/terms` 반복 시험의 연결 거절·Windows TCP 포트 조사](../results/2026-09-21-terms-investigation/report.md)
- 조회 API 시드 크기 선정: [2026-09-28 1 VUser 순차 실행 결과](../results/2026-09-28-read-seed-selection/report.md) · [검증된 14개 조회 스크립트 실행기](../tools/run-read-sequential.ps1)
- 게시글 목록 동시 부하 탐색: [2026-09-28 RoommateBoardListGetTest 단계별 결과와 범용 실행기 검증](../results/2026-09-28-roommate-board-list-load/report.md) · [Bash 실행 스크립트](../tools/run-ngrinder-load-stages.sh)
- 게시글 목록 필터·검색 측정: [2026-09-30 기존 결과 검토·17개 조건별 프로필·검색 기록 저장 검증·전후 비교 절차](./roommate-board-list-testing.md)

## 1. 목적과 판단 범위

사용자가 탐색 → 상세 확인 → 관심 등록 → 채팅 → 룸메이트 연결·일정 관리로 이동하는 동안, 어느 부하부터 응답 지연·실패·데이터 불일치가 발생하는지 측정한다. 최종 결과는 최대 TPS 하나가 아니라 **데이터 규모와 환경별로 기준을 만족하는 지속 처리량, 동시 사용자 수, 최초 병목, 회복 시간**으로 제시한다.

다음 세 종류의 실험을 구분한다.

1. **실사용 혼합 부하**: 사용자 여정, 생각 시간, 인증과 데이터 분포를 반영한다.
2. **병목 분리 부하**: 추천, 복합 검색, 인기 게시글, 긴 채팅 이력 등 특정 비용을 분리한다.
3. **동시성·장애 실험**: 토글, 중복 방 생성, 요청 수락 경합, 연결 재접속의 최종 상태를 검증한다. 정상 성능 수치와 합산하지 않는다.

실제 사용자 수·접속 로그·운영 SLO·서버 사양은 아직 확인되지 않았다. 아래 VU, 비율, 데이터량, 시간 기준은 **첫 측정을 위한 가설**이며 운영 용량이나 이미 달성한 성능을 뜻하지 않는다. 시험 전 담당자가 값을 확정하고 실행 기록에 남긴다.

## 2. 서비스 분석과 주요 성능 가설

| 영역 | 코드에서 확인한 동작 | 시험에서 확인할 가설 |
|---|---|---|
| 실행 구조 | Java 21, Spring Boot 4.0.5, Spring MVC, JPA/QueryDSL, PostgreSQL | HTTP 처리 스레드와 DB 연결 대기가 처리량 상한을 결정할 수 있다. |
| 인증 | JWT 검증 후 `memberId`로 회원을 DB 조회; Access Token 유효 기간 7일 | 같은 API라도 익명/인증 부하가 다르다. 인증 필터도 측정 경로에 포함한다. |
| 게시물 검색 | 복합 필터·조인·페이지 및 count 쿼리; 로그인 키워드 검색마다 검색 이력 INSERT | 조회 트래픽에도 쓰기·WAL 비용이 발생한다. 깊은 페이지와 낮은 선택도의 검색을 분리한다. |
| 게시물 상세·관심 | 상세 GET은 hits UPDATE; 관심 POST는 토글이며 게시물 행에 비관적 잠금 | 인기 게시물 하나에 요청이 몰리면 읽기처럼 보이는 요청도 경합한다. |
| 추천 목록 | `random()` 정렬, `size+1` 조회, 관련 데이터 batch 조회, Java 적합도 계산 | 후보 수·반환 수·제외 ID 길이 증가에 따른 DB 정렬 및 CPU 비용을 확인한다. |
| 관심 회원 | 기존 관심 행 잠금 후 토글; 최초 INSERT의 경합은 별도 검증 필요 | 같은 회원 쌍의 최초 동시 요청이 중복 행을 만들 수 있는지 확인한다. |
| 채팅 | 현재 생성 API는 `POST /chats`; 상세는 메시지 전체 조회 및 읽음 갱신 | 메시지 누적에 따라 응답 크기·heap·DB 비용이 증가한다. |
| 실시간 | STOMP simple broker, SSE emitter는 애플리케이션 프로세스 메모리에 보관 | 연결 수와 메시지 전달량을 별도로 측정하고, 다중 인스턴스 전달도 검증한다. |
| 알림·파일 | DB 알림 저장, SSE 전송, 비동기 FCM; prod 파일 업로드는 R2/S3 동기 호출 | 외부 지연과 비동기 대기가 HTTP 성공 뒤에 숨을 수 있다. |
| 일정·온보딩 | 반복 일정의 월/일 조회; 프로필·선호 저장 시 관련 테이블 변경 | 데이터 밀도와 갱신 이력이 읽기 성능에 미치는 영향을 확인한다. |

`GET /roommate/matches/score`와 `GET /roommates/me/calendar/{id}`는 현재 빈 DTO를 반환한다. 적합도 계산이나 일정 상세 성능을 대표하는 API로 사용하지 않는다. `/chat-requests`는 deprecated 경로이므로 현재 채팅 생성의 주 부하에서 제외하고 필요할 때 회귀 시험만 진행한다.

프런트의 탐색 화면은 게시글·추천 첫 목록을 함께 요청하며 로그인 사용자는 선호 조회와 알림 조회도 수행한다. 알림은 15초 간격 polling이 있다. 따라서 화면 진입을 목록 GET 한 건으로 축약하지 않는다. 상세한 호출 순서는 S00에 정의한다.

## 3. 시험 환경

### 3.1 구성과 실행 전 확정 항목

```text
nGrinder Controller ── 제어/수집 ── Agent A..N
                                    │ HTTP(S), WebSocket/STOMP, SSE
                                    ▼
                        시험용 진입점/LB → Backend → PostgreSQL
                                            ├→ 격리된 파일 저장소
                                            └→ FCM·메일 등 시험 대역
별도 관측 경로: Agent / JVM / HTTP / DB / 외부 호출 / 전달 결과
```

기존 `C:/dev/workspace/prography/APM`에서 Prometheus·Grafana·nGrinder Controller/Agent를 Compose로 관리한다. 현재 설정은 Agent 1개와 호스트의 8080 백엔드를 대상으로 하므로 **로컬 smoke·변경 전후 비교**에 우선 사용한다. 최대 처리량을 판단하는 본 시험에서는 특히 Agent와 대상 백엔드를 서로 다른 호스트로 분리하고, 관측 도구·DB의 자원 경합도 확인한다. 같은 호스트의 컨테이너 분리만으로 부하 발생 자원이 분리되지는 않는다.

운영과 같은 DB 버전·스키마·인덱스·풀러 유무·네트워크 경로를 기록하되 대상은 복구 가능한 시험 환경으로 정한다. 이 절은 PostgreSQL 기반 본 시험의 준비 기준이다. 현재까지 완료한 H2 조회 API 탐색 결과는 위의 2026-09-28 보고서에 기록했다.

| 항목 | 준비 기준 / 기록할 값 |
|---|---|
| 대상 | `BASE_URL`, 배포 커밋, 인스턴스 수, CPU/RAM, JVM heap/GC 옵션, TLS/LB/프록시 timeout |
| DB | PostgreSQL 버전, CPU/RAM/스토리지, pooler 모드, DB 연결 상한, 실제 인덱스/제약조건, 스냅샷 ID |
| nGrinder | Controller·Agent 동일 버전, JDK, 이미지 digest 또는 배포 파일 checksum, HTTP client 종류 |
| 현재 도구 설정 | Controller `ngrinder/controller:3.5.9-p1`, Agent `ngrinder/agent:3.5.9-p1`. 실제 image digest와 컨테이너 JDK를 확인하며 백엔드 Java 21과 분리한다. |
| 설정 | Hikari/Tomcat/비동기 executor 설정, 로그 레벨, 타임존, 파일 저장 구현, 스케줄러 실행 여부 |
| 테스트 | runId, script hash, seed, 데이터 세트, 계정 shard, A/P/T, 시간표, 목표량, 실제 달성량 |

기존 nGrinder 버전을 우선 재사용한다. [공식 릴리스](https://github.com/naver/ngrinder/releases)의 JDK 기준과 실제 이미지 런타임을 대조하고, Controller·Agent·클라이언트/JAR 조합을 smoke로 검증한 뒤 반복 시험에 고정한다.

### 3.2 현재 설정과 시험 환경의 차이

- 기본 `test`는 H2 메모리 DB, `create-drop`, SQL 출력이 활성화돼 있다. 이 결과를 PostgreSQL 운영 용량으로 해석하지 않는다.
- 저장소의 prod 설정은 Hikari 최대 20, 최소 idle 5, connection timeout 5초이며 SQL DEBUG/bind TRACE와 WebSocket DEBUG가 켜져 있다. 이는 **설정 파일의 값**이며 실제 배포값은 별도 확인한다. 최초 기준 시험에서는 실효 설정을 기록하고, 로그 변경 비교는 별도 실행으로 남긴다.
- STOMP 인증 인터셉터는 현재 native header 전체를 INFO로 기록한다. 시험 전 Authorization 값을 마스킹하고, 메시지당 로그 출력이 만드는 I/O 비용과 적용 로그 설정을 기록한다.
- `perf` 전용 설정은 아직 없다. 구현 시 기본 test/H2 설정을 상속하지 않도록 프로필·DB·DDL을 명시한다. `@Profile("!prod")`의 `SeedDataConfig`와 로컬 파일 업로드가 perf에도 활성화된다는 점을 처리해야 한다. prod를 그대로 실행해 시험 환경을 만드는 방식도 사용하지 않는다.
- R2 성능을 측정하려면 격리 버킷에 연결하는 업로드 구현을 선택한다. 로컬 저장·대역 저장·실제 R2 결과에 각각 다른 라벨을 붙인다.
- 일반 핵심 부하에서는 외부 OAuth 로그인을 반복하지 않는다. FCM 없는 계정은 push가 조기 반환하므로 이 결과를 알림 외부 연동 성능으로 주장하지 않는다. 외부 지연 실험은 실제 경계를 통과하는 대역을 준비한다. 해당 주입 설정은 추가 구현 대상이다.
- 매일 03:00 KST 회원 삭제 스케줄러가 있다. 기본 시험에서는 실행 시간을 피하거나 시험 환경에서 제어하고, 장시간 시험과 겹치면 별도 구간으로 표시한다.

## 4. 인증 및 테스트 데이터

### 4.1 인증·소유권

- 정상 부하는 VU마다 독립 회원과 `Authorization: Bearer <accessToken>`을 사용한다. 토큰은 시험 환경의 발급 로직으로 사전 생성하고 대상 회원 존재·USER 권한·만료 시각을 확인한다. 현재 코드에 일반 refresh API가 있다고 가정하지 않는다.
- JWT·서명 키·접속 비밀값을 문서/스크립트 저장소/로그에 포함하지 않는다. 실행 시 Agent에 제한된 수명으로 주입한다.
- 익명 시나리오는 헤더와 쿠키를 모두 비운다. 계정을 바꿀 때 이전 쿠키를 재사용하지 않는다.
- `agentShard/processSlot/threadSlot`으로 계정과 자원을 겹치지 않게 사전 배정한다. 각 Agent에서 동일 CSV 첫 행을 읽는 방식은 사용하지 않는다. 여러 Agent 간 공유 메모리나 단일 JVM 카운터를 전제로 하지 않는다.
- 채팅·룸메이트 시나리오는 A/B 계정 쌍과 소유 roomId를 배정한다. 동시성 실험에서만 의도적으로 같은 계정·자원을 공유한다.

### 4.2 데이터 규모와 분포

아래는 합성 데이터 제안값이다. FK와 실제 업무 제약을 만족한 전체 스냅샷을 만들고 `ANALYZE` 및 조회 smoke 후 사용한다. 기본 seed 몇 건만으로 성능을 판단하지 않는다.

| 데이터 | D0 계약 smoke | D1 기준 | D2 증가 |
|---|---:|---:|---:|
| 회원 | 100 | 10,000 | 100,000 |
| 게시글 | 200 | 20,000 | 200,000 |
| 관심 관계 합계 | 500 | 100,000 | 1,000,000 |
| 검색 이력 | 1,000 | 100,000 | 1,000,000 |
| 채팅방 | 50 | 5,000 | 50,000 |
| 채팅 메시지 | 1,000 | 500,000 | 5,000,000 |
| 알림 | 1,000 | 100,000 | 1,000,000 |
| 룸메이트 관계 / 일정 | 10 / 100 | 1,000 / 20,000 | 10,000 / 200,000 |

- 검색·추천 후보는 온보딩 완료, 활성/공개, 삭제되지 않은 회원을 충분히 만든다. SEEKER/OFFER 각각 50%, 여러 지역·방 유형·예산·생활패턴·중요 조건을 섞는다. 주 시험에서 대부분의 점수가 null이 되는 불완전 계정을 사용하지 않는다.
- 별도 경계 집합에 비공개·탈퇴·차단(양방향)·생활패턴 없음·선호 없음·삭제/만료 게시글을 둔다. 정상 반환 집합과 제외 집합을 manifest에 저장한다.
- 게시글 입주일은 run 기준일에 상대적으로 생성한다. 기본 노출 유예 7일을 고려해 반복 실행 중 노출 대상이 저절로 사라지지 않게 한다.
- 일반 접근은 넓게 분산한다. 인기 집중 시험은 상위 1% 자원에 50% 접근하는 분포와 단일 자원 100% 접근을 별도로 사용한다. 이는 트래픽 가설이다.
- 메시지는 방당 0/100/1,000/10,000건 cohort로, 알림은 회원당 미읽음 0/20/1,000건으로 나눈다. 평균 데이터량만 맞추지 않는다.
- 한 회원의 활성 채팅방 상한은 현재 5개다. 총 방 수·회원 배치가 이를 어기지 않게 하고, 상한 시험용 4개/5개 cohort를 별도로 만든다.

### 4.3 소모성 데이터와 복원

`accounts`, `pairs`, `boards`, `rooms`, `requests`, `calendar`, `metadata` manifest에 runId와 소유 shard를 기록한다. 생성·수락·취소는 처리한 ID를 재사용하지 않는다. 필요한 쌍 수는 `목표 여정/초 × 측정 초 × 여정당 소비 쌍 수 × 1.2`로 계산하고 워밍업·사전검증 소비량을 추가한다. 예를 들어 새 채팅 2건/초를 30분 측정하면 최소 4,320쌍과 추가 워밍업 물량이 필요하므로 D1 기본 회원 수로 감당 가능한지도 확인한다.

조회 전용 cohort, 토글 cohort, 생성 cohort, 수락 cohort를 분리한다. 토글은 최초 상태와 호출 수를 기록하고, 타임아웃 이후 자동 재시도하지 않는다. 소프트 삭제 행·검색 이력·채팅 이력은 cleanup 호출만으로 원상복구되지 않으므로 실행 사이에는 전용 DB 스냅샷 복원을 우선한다. 파일은 run별 업로드 목록으로 격리 저장소에서 정리한다. 측정 도중 전체 삭제/재시딩을 하지 않는다.

## 5. 부하 모델

### 5.1 실사용 혼합 비율 M1

| VU 집단 | 비율 | 여정 | 반복 간 생각 시간 |
|---|---:|---|---|
| 익명 탐색 | 10% | S01 익명 목록·검색 + S02 익명 추천 | 2~5초 |
| 로그인 탐색 | 40% | S00 진입, S01 목록→상세, S02 추천→상세 | 2~5초, 상세 열람 3~8초 |
| 관심 관리 | 10% | S03 두 종류 관심 등록→관심 목록→해제 | 1~3초 |
| 기존 대화 확인 | 20% | S05 채팅방 목록→선택한 방 이력 | 3~8초 |
| 연결된 룸메이트 | 10% | S08 알림 조회 + S09 월/일 일정 조회 | 3~8초 |
| 프로필 수정 | 5% | S10 기존 프로필·선호 조회→수정→조회 | 5~10초 |
| 메타 조회 | 5% | S11 약관/지역/생활패턴/인기 검색어 | 5~10초 |
| 합계 | 100% | | |

비율은 **VU 배정 비율**이다. 여정마다 요청 수와 시간이 다르므로 HTTP 요청 비율이나 TPS 비율과 같지 않다. 100 VU 이상에서 정확한 비율을 적용하고 소규모 smoke에서는 시나리오별로 실행한다. 고정 seed의 난수로 ID·생각 시간을 분산하고 실제 API별 요청 비율을 함께 보고한다. S00은 화면 진입 시 수행하며 모든 HTTP 요청마다 전체 초기 호출을 반복하지 않는다. 로그인 집단의 알림 polling은 화면 활성 시간에 15초 주기로 반영하고 S08과 중복 계수하지 않는다.

S04 신규 방 생성, S07 룸메이트 수락, S09 일정 쓰기, S12 파일 업로드는 우선 독립 부하로 실행한다. 이후 M1 90% + 선택한 쓰기 여정 10%의 M2로 추가 영향만 비교한다. S06/STOMP와 S08/SSE는 HTTP VU 수와 별개인 연결 수·메시지율을 설정해 M1과 동시 실행한다.

### 5.2 단계와 초기 VU 예시

현재 Compose의 Agent는 1개이므로 아래 A=2/4 설정은 **분산 본 시험을 위한 확장안**이다. 로컬에서는 1 VU 계약 확인 → 10 VU 기준 → 20 VU → 조건 충족 시 50 VU로 비교한다. 동일 호스트에서 VU만 올린 결과를 운영 용량으로 해석하지 않는다. Agent의 고정 `container_name` 해소, 별도 호스트 배치 및 네트워크 준비는 [APM 적용 문서](./apm-environment.md)를 따른다.

`VU = Agent 수(A) × Agent당 process 수(P) × process당 thread 수(T)`로 계획한다. 아래는 출발점이며 Agent 포화 시 thread 수를 무작정 높이지 않고 Agent를 늘린다. nGrinder의 기본 ramp-up은 **process 증가**이므로 실제 증가 VU를 계산한다. [공식 Test Configuration](https://github.com/naver/ngrinder/wiki/Test-Configuration)

| 단계 | A × P × T 예시 | 시간 / 실행 방식 | 판단 목적 |
|---|---|---|---|
| 계약 smoke | 1 × 1 × 1 | 시나리오별 1~3회, 연결은 A/B 1쌍 | 인증·응답·ID 상관관계·정리 확인 |
| 낮은 부하 기준 | 1 × 2 × 5 = 10 | 워밍업 5분 + 측정 10분 | 단일 비용/계측 기준 |
| L1 | 2 × 5 × 5 = 50 | ramp 2분 + 워밍업 5분 + 측정 15분 | 초기 정상 부하 |
| L2 | 2 × 5 × 10 = 100 | ramp 3분 + 워밍업 5분 + 측정 20분 | 기준 후보 |
| L3 | 2 × 4 × 25 = 200 | ramp 3분 + 워밍업 5분 + 측정 20분 | 목표 후보, 병목 확인 |
| stress | 4 × 4 × 25 = 400, 필요 시 4 × 5 × 50 = 1,000 | 직전 단계 통과 후, 각 10분 측정 | 지속 가능 상한과 포화 원인 |
| spike | 정상 수준→3배→정상 | 5분→1분 상승·2분 유지→10분 회복 | 대기열과 회복 |
| soak | 최대 통과 VU의 70~80% | 워밍업 후 최소 2시간 | heap·연결·검색 이력/로그 누적 |

L1~L3는 Agent당 초기 process 1개, 단계마다 process 1개 추가, initial sleep 0으로 설정한다. L1은 30초 간격으로 10→20→30→40→50 VU, L2는 45초 간격으로 20→40→60→80→100 VU, L3는 60초 간격으로 50→100→150→200 VU가 된다. 마지막 process 시작 뒤 워밍업과 측정 시간을 별도로 확보한다. stress도 초기 process 1개에서 60초마다 1개씩 늘려 최종 부하 도달 후 워밍업 5분·측정 10분을 진행한다. Controller에는 ramp·워밍업·측정을 모두 포함하는 전체 실행 시간을 입력하고 실제 process 시작 시각, 초기/추가 process 수, 증가 간격을 manifest에 남긴다.

각 정상 단계는 독립 실행·동일 스냅샷·같은 설정으로 3회 반복한다. 지속 가능 용량은 세 번 모두 기준을 통과한 최대 **측정 구간**으로 정의한다. spike의 하강은 기본 process ramp-up만으로 표현된다고 가정하지 않는다. 사전 검증한 시간 기반 활성 VU gate로 요청 시작을 중단/재개하고, 휴면 thread의 대기는 API 측정에서 제외한다. 단순히 테스트를 종료해 회복 구간으로 간주하지 않는다.

### 5.3 처리량 해석

nGrinder의 일반 thread 반복은 응답을 기다리는 폐쇄형 부하다. `대략적 여정/초 = VU / (여정 응답시간 합 + 생각시간 합)`, `HTTP RPS = 여정/초 × 평균 요청 수`로 예상량을 계산하고 실제량과 비교한다. VU 200을 200 RPS로 해석하지 않는다.

서버가 느려지면 요청 유입도 줄어 지연을 과소평가할 수 있다. 정상 혼합 시험과 별도로 생각 시간 없는 단일 API 용량 시험을 수행한다. 특정 도착률 검증이 필요하면 Agent별 요청 시작률 pacing과 충분한 VU를 사전 검증하고 목표/실제 시작률·지연 시작·미시작 건수를 보고한다. 목표율을 달성하지 못한 실행을 해당 RPS 통과로 처리하지 않는다.

## 6. nGrinder 스크립트 구현 규칙

성능 테스트 산출물은 APM 저장소의 `performance-test/`에서 관리한다. 실행 스크립트와 리소스는 `script/<도메인>/`, 실행·집계·검증 도구는 `tools/`, 계획과 절차는 `docs/`, 측정 원본과 레포트는 `results/`에 둔다. 현재 관리 인덱스는 [performance-test README](../README.md)다.

| 수명주기 / 기능 | 설계 |
|---|---|
| `@BeforeProcess` | 환경·읽기 전용 데이터 파일·GTest 정의 로드. DB seed나 OAuth 대량 로그인 금지 |
| `@BeforeThread` | shard별 계정/역할과 client 세션 배정. 가변 token/header/cookie/ID를 thread 간 공유하지 않음 |
| `@Test` | 하나의 명시적 여정 실행. 앞 응답에서 ID 추출→검증→후속 요청. 실패하면 의존 단계 중단 |
| 종료 | 연결 close, 소모 ID/불확실 요청 목록 기록. 강제 중단에서도 별도 cleanup manifest로 회수 |
| HTTP 계측 | API·경로 종류별 고정 GTest ID 사용. 동적 memberId/boardId를 metric 이름으로 만들지 않음 |
| 검증 | 기본 부하는 기대 HTTP 상태/통신을 확인. JSON·업무 계약은 선택 검증기 또는 별도 기능 검증으로 확인하고 판정 범위를 기록 |
| 시간 | API 시간에 생각 시간·CSV 읽기·seed 시간을 포함하지 않음. 사용자 여정 시간은 별도 지표로 기록 |
| timeout | 초기 일반 HTTP 10초, 업로드 30초 제안. 연결/응답 timeout을 분리 기록하고 실패 표본을 버리지 않음 |
| 재시도 | 측정 중 자동 HTTP 재시도·로그인 redirect 따라가기 비활성. 연결 재접속은 해당 시나리오에서만 수행 |
| 로그 | 정상 응답 전문·JWT 출력 금지. 실패 유형/시나리오/상관 ID와 요약 기록. 로그 I/O가 Agent를 막지 않게 함 |

Groovy 수명주기와 GTest 계측은 [공식 Groovy Script Structure](https://github.com/naver/ngrinder/wiki/Groovy-Script-Structure)를 기준으로 구현한다. API를 계측한 뒤 여정 전체도 같은 GTest 합계에 중복 계측해 HTTP TPS가 부풀지 않도록 한다. 이름은 예를 들어 `S02_MATCH_LIST_AUTH_SIZE20`, `S05_CHAT_HISTORY_1000`처럼 고정한다.

STOMP는 연결·CONNECT 인증·SUBSCRIBE·SEND·MESSAGE 수신까지 구현하는 Java 클라이언트가 필요하고 SSE는 스트림을 계속 읽는 클라이언트가 필요하다. 기본 HTTP GET/SEND 성공을 메시지 전달 성공으로 대체하지 않는다. 호환 JAR를 nGrinder `lib/`에 배포하는 방식은 [공식 라이브러리 가이드](https://github.com/naver/ngrinder/wiki/How-to-use-library)를 따른다. Agent의 실제 Java 버전보다 높은 bytecode로 빌드한 라이브러리를 그대로 넣지 않는다. 수신 callback에서는 표본을 thread 안전 큐에 넣고 worker에서 timeout/누락을 판정해 GTest 결과 또는 별도 histogram에 반영한다.

## 7. 관측과 잠정 통과 기준

### 7.1 수집 계획

2026-09-21 확인한 백엔드에는 Actuator와 `micrometer-registry-prometheus`가 이미 있다. `/actuator/prometheus` 노출, `application=KnockIn` 공통 태그, SecurityConfig의 `/actuator/**` 허용도 설정돼 있다. APM Prometheus는 `job="KnockIn"`, `host.docker.internal:8080`을 5초마다 수집하도록 구성돼 있다. 따라서 기본 계측 신규 구축 대신 **실제 scrape 성공과 지표 존재 검증**부터 시작한다. 설정 존재만으로 현재 정상 수집을 단정하지 않는다.

HTTP histogram bucket, DB/호스트 관측, STOMP·SSE 전달 계측은 별도 확인·보완 항목이다. 서버 RPS·지연·JVM·Hikari는 Prometheus/Grafana, 클라이언트 지연·검증 실패·여정 TPS는 nGrinder로 함께 판단한다. 서버 평균을 클라이언트 p95/p99로 대신하지 않는다. 구체적인 패널·PromQL·실행 전 확인은 [APM 적용 문서](./apm-environment.md)에 정의한다.

| 관측 지점 | 필수 지표 |
|---|---|
| 부하 발생기 | API별 요청/성공/실패 수, RPS, 여정 TPS, 응답 byte, p50/p95/p99, 실제 활성 VU, Agent CPU/heap/GC/network |
| 서버 | CPU, heap/GC pause, HTTP active/queue, 요청 시간·예외, Hikari active/idle/pending/acquire timeout, 비동기 executor active/queue |
| PostgreSQL | CPU/IO, 연결·wait event, slow query, 계획/rows, lock wait/deadlock, WAL/쓰기, `pg_stat_statements`가 준비됐으면 정규화 쿼리별 통계 |
| 실시간 | 연결 성공률/지연, 현재 연결 수, 전송·수신·저장 수, MESSAGE 전달 지연, 누락/중복, reconnect 수, SSE emitter 수 |
| 외부·상태 | R2 처리시간/실패, 대역 지연/실패율, FCM 완료/실패/대기, 토글 중복 행, 방 중복, 요청/룸메이트/일정 정합성 |

nGrinder 평균·최대·TPS만으로 p95/p99를 추정하지 않는다. 선택 버전의 raw 통계가 요청별 시간을 제공하는지 1 VU로 확인한다. 부족하면 Agent에서 고정 metric별 histogram 또는 비동기 표본 파일을 구현해 병합한다. histogram은 동일 경계로 합치고 **Agent별 percentile의 평균을 전체 percentile로 사용하지 않는다**. percentile 수집의 자체 오버헤드도 낮은 부하에서 확인한다.

API 지연은 클라이언트 관측 시간을 기준으로 하고 서버 시간을 보조 지표로 사용한다. 워밍업/ramp/정상/회복의 시작·끝을 같은 시계로 구분한다. timeout 표본과 실패 지연은 별도 포함·보고하며 빠른 실패만으로 성능이 좋아진 것처럼 보이지 않게 한다. metric별 1,000건 미만이면 p99 표본 부족을 명시하고 저빈도 시나리오를 추가 실행한다.

### 7.2 정상 부하의 초기 기준

| 지표 | 잠정 기준 |
|---|---|
| 메타·단순 목록·관심 토글 | p95 ≤ 500ms, p99 ≤ 1,000ms |
| 검색·추천·상세·채팅 이력·일정 조회 | p95 ≤ 1,000ms, p99 ≤ 2,000ms |
| 방 생성·요청 수락·프로필/일정 저장 | p95 ≤ 1,000ms, p99 ≤ 2,000ms |
| 파일 업로드 | 1MiB 단일 파일 p95 ≤ 3초; 큰 파일 cohort는 크기/대역폭별 따로 판단 |
| 정상 요청 실패 | 예상하지 않은 HTTP/업무/검증 실패 합계 < 1%; 미인증/권한 데이터 준비 오류는 0건 |
| 실시간 | send 시작→상대 MESSAGE 수신 p95 ≤ 500ms, p99 ≤ 1초; 정상 구간 전달 누락/중복 0건 |
| 정합성 | 관심 관계·채팅방·수락·일정의 정의된 불변조건 위반 0건 |
| 안정성 | OOM/재시작/deadlock 0건, heap·대기열·연결 수의 지속 상승 없음 |
| 회복 | spike 종료 5분 안에 응답시간·실패율이 직전 정상 기준으로 복귀 |

기준은 모든 중요 API와 데이터 cohort에 각각 적용한다. 소량의 빠른 메타 응답이 느린 추천을 가리는 전체 평균으로 판정하지 않는다. 업무상 예상한 4xx는 S13 전용 결과에만 따로 집계하며 정상 혼합 결과에서 임의로 제외하지 않는다. 부하 규모별로 CPU/DB 여유를 함께 기록하고 기준 변경은 결과를 본 뒤 소급하지 않는다.

**중단 조건**: 정상 부하에서 예상 밖 실패율 5% 이상 1분 지속, p99 10초 이상 2분 지속, DB 연결/잠금 대기 지속 증가, OOM/재시작, 저장소 여유 15% 미만 또는 정합성 위반 발견 시 상승을 중단하고 증거를 보존한다. Agent CPU 80% 이상·네트워크 포화 등이 2분 지속되면 해당 결과를 서버 한계 판정에 쓰지 않고 Agent 용량을 재검증한다. 재개 전 원인·변경·복원 상태를 기록한다.

## 8. 실행 순서와 완료 산출물

1. **기존 APM 확인·환경 고정**: scrape 정상 여부, Agent 등록, Grafana datasource·지표를 확인하고 로컬 비교/분산 본 시험을 선택한다. 위 미확정값, 목표 기준, 제외 API, 외부 대역 범위를 실행 manifest에 확정한다.
2. **준비 구현**: perf 설정, 시딩/복원, JWT 공급, Agent shard, 부족한 metric·histogram, HTTP 스크립트를 준비한다. APM의 기존 가이드 스크립트는 현재 DTO·상관 ID·assertion에 맞춰 검증 후 재사용한다. STOMP/SSE는 1쌍으로 송수신 계약부터 검증한다.
3. **사전 검증**: D0로 S00~S13 계약을 확인한다. 정상 입력 실패·잘못된 응답·stub 호출은 수정하거나 해당 시나리오를 기능 미충족으로 표시한다. 결함을 통과하도록 assertion을 완화하지 않는다.
4. **분리 측정**: D1에서 S01/S02/S03/S05 우선 → S04/S07/S09/S10 쓰기 → S06/S08 연결 → S11/S12 보조 기능 순으로 낮은 부하 기준을 수집한다.
5. **혼합 측정**: M1 L1~L3, 조건 충족 시 stress·M2·spike·soak를 수행한다. D2는 동일 VU/쿼리로 비교 후 증가한다. DB 크기와 VU를 동시에 바꾸는 비교는 피한다.
6. **후검증**: Agent 결과와 DB 저장·최종 상태를 대조한다. 프로토콜 전달 누락, ambiguous timeout, 알림 비동기 backlog를 해소한 뒤 판정한다.
7. **개선 재측정**: 가장 큰 병목 하나를 변경하고 같은 데이터·부하·설정의 변경 전/후 3회를 비교한다.

결과 문서는 `results/<runId>/report.md`에 다음을 남긴다(실행 시 생성).

| 기록 | 내용 |
|---|---|
| 재현 정보 | commit/script hash, 환경, nGrinder/JDK, seed/스냅샷, 시간대, 외부 대역, A/P/T 및 부하 시간표 |
| 결과 표 | scenario/API/cohort별 표본 수, 성공/실패 원인, p50/p95/p99, RPS, 여정 TPS, byte, 기준 통과 여부 |
| 정합성 | 기대/실제 토글 상태·중복 수, 요청/방/메시지/일정 수, 누락·불확실 요청 목록 |
| 병목 근거 | 같은 시간대의 서버/Agent/DB 지표, 느린 쿼리·실행계획, 잠금 대기, GC/외부 지연 |
| 결론 | 최대 지속 가능 부하, 3회 편차, spike 회복, soak 추세, 미검증 영역, 개선 우선순위 |

완료 조건은 계획된 중요 시나리오의 측정·후검증과 재현 가능한 증거가 갖춰지는 것이다. 기능 미구현이나 관측 부재로 실행하지 못한 항목은 성능 통과로 표시하지 않는다.

## 9. 저장소 근거

아래는 분석 기준 파일이다. 스크립트 작성 시 배포 커밋의 DTO·컨트롤러와 다시 대조한다.

- [빌드 및 기존 performance/concurrency 테스트 분리](../../../../KnockIn/back/11th-1team-BE/build.gradle), [기존 관심 등록 락 성능 테스트](../../../../KnockIn/back/11th-1team-BE/src/test/java/org/example/knockin/service/impl/RoommateBoardInterestLockPerformanceTest.java): H2 기반 서비스 직접 호출 관찰 시험으로 HTTP/nGrinder 결과를 대체하지 않는다.
- [보안 정책](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/global/config/SecurityConfig.java), [JWT 발급·회원 조회](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/global/auth/util/TokenProvider.java), [공통 응답](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/global/api/CommonResponse.java).
- [게시물·추천 API](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/board/controller/RoomMateController.java), [게시물 서비스](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/board/service/impl/RoommateBoardServiceImpl.java), [추천 서비스](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/mate/service/impl/RoommateMatchingServiceImpl.java), [점수 계산](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/util/service/impl/JavaRoommateScoreService.java).
- [채팅 API](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/chat/controller/ChatController.java), [채팅 서비스](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/chat/service/impl/ChatServiceImpl.java), [WebSocket 설정](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/global/config/WebSocketConfig.java), [SSE·알림](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/meta/service/impl/AlarmServiceImpl.java).
- [룸메이트·일정 API](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/mate/controller/RoomMatesController.java), [요청 API](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/mate/controller/RoomMateRequestController.java), [프로필 API](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/member/controller/UserController.java), [온보딩 서비스](../../../../KnockIn/back/11th-1team-BE/src/main/java/org/example/knockin/util/service/impl/OnBoardingServiceImpl.java).
