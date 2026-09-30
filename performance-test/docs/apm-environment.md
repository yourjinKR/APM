# 기존 APM Compose 환경 적용

- 확인일: 2026-09-21
- APM 저장소: `C:/dev/workspace/prography/APM`, 커밋 `38e336da726235c9818723106b65f569716ce44b`
- 백엔드 계측 확인: `98130f0b530949b53c67d19907e78d9ea74fe35d`
- 범위: Compose·Prometheus 설정·README와 백엔드 코드의 정적 확인. 실행 중인 컨테이너, Grafana 저장 상태, 실제 scrape 결과는 이번에 확인하지 않았다.
- 연결 문서: [전체 계획](./plan.md), [S00~S13 상세 시나리오](./scenarios.md)

## 1. 전략 변경의 핵심

14개 업무 시나리오와 정합성 검증은 유지한다. **기존 관측 환경의 수집 검증 → 로컬 비교 → 부하 발생기를 분리한 용량 시험** 순서로 실행 전략을 구체화한다. nGrinder는 부하와 사용자 관점의 결과, Prometheus/Grafana는 서버 자원과 병목 근거를 담당한다.

| 확인한 구성 | 전략에 미치는 영향 |
|---|---|
| Prometheus `prom/prometheus`, Grafana `grafana/grafana` | 재설치하지 않고 재사용. 태그가 없어 반복 시험 전 실제 버전·digest를 고정할 필요가 있음 |
| Controller/Agent 모두 `3.5.9-p1` | 버전 후보 선정 단계는 생략하고 실제 JVM·스크립트 호환 smoke 수행 |
| `ngrinder-agent` 서비스 1개, 고정 `container_name` | 기존 계획의 Agent 2/4개 시험은 현재 구성으로 바로 실행할 수 없음 |
| Prometheus job `KnockIn`, 5초 주기, `/actuator/prometheus`, `host.docker.internal:8080` | 현재 대상은 Docker 호스트의 로컬 8080 앱. 다른 서버로 바꾸면 scrape target과 nGrinder BASE_URL을 각각 갱신 |
| 백엔드 Actuator/Prometheus 의존성·endpoint 노출·application 태그 있음 | 기본 지표 구현보다 `up`, 실제 metric 이름/label 확인이 먼저 |
| Prometheus/Grafana의 명시적 데이터 volume·provisioning 선언 없음 | 재생성 후 결과·대시보드 보존을 보장하도록 영속화와 설정 버전 관리 필요 |
| Controller만 `./ngrinder-controller-data` bind mount | 기존 스크립트/설정을 보존하며 migration. 과거 샘플을 현재 API와 대조해야 함 |
| scrape job은 백엔드 1개뿐 | Agent/컨테이너/호스트/PostgreSQL 지표와 nGrinder 결과가 자동 수집된다고 가정하지 않음 |

## 2. 실행 단계를 둘로 구분

### 로컬 비교 시험

현재 Compose와 로컬 백엔드로 D0 계약 검증 및 작은 고정 데이터의 변경 전후 비교를 한다. 1 VU → 10 VU → 20 VU → 자원 여유가 있으면 50 VU 순서로 올린다. 1 Agent 기준 `1×2×5=10`, `1×4×5=20`, `1×5×10=50`을 예시로 사용하며 각 단계의 process ramp를 별도로 기록한다.

Docker Desktop의 CPU/RAM 배정과 컨테이너 실효 자원 제한, 호스트의 다른 작업, 백엔드 프로필·DB를 고정한다. 현재 기본 test가 H2인 점은 그대로이므로 PostgreSQL 성능 검증 시 DB를 명시적으로 바꿔야 한다. 이 단계의 결론은 같은 조건에서의 개선·회귀와 병목 후보다.

### 분산 용량 시험

Agent를 대상 백엔드와 다른 호스트에 배치하고 본 계획의 A=2/4단계를 수행한다. Controller·Grafana·Prometheus도 대상 서버의 CPU/디스크와 경합하지 않는 관측 호스트에 두는 구성을 우선한다. 동일 Docker 호스트에 Agent 컨테이너만 늘리면 네트워크·CPU 용량이 같이 늘어나는 것은 아니다.

`container_name`이 지정된 Compose 서비스는 복제 확장이 제한된다. Agent를 복제하려면 해당 고정 이름을 제거하는 Compose 변경 또는 호스트별 독립 Agent 구성을 준비한다. **설정 파일 수정만으로 서로 다른 물리 호스트에 배치되지는 않는다.** Controller 주소, 테스트 제어 포트, Agent 등록/승인과 각 Agent의 대상 서버 연결을 확인한 뒤 A/P/T를 확정한다. [Docker 서비스 설정](https://docs.docker.com/reference/compose-file/services/)

## 3. 통신 경로와 실행 전 확인

| 경로 | 현재 설정 / 확인할 점 |
|---|---|
| Grafana → Prometheus | 같은 Compose 네트워크의 `http://prometheus:9090`; Grafana 컨테이너의 localhost로 지정하지 않음 |
| Prometheus → 백엔드 | `http://host.docker.internal:8080/actuator/prometheus`; `extra_hosts`는 현재 Prometheus에만 선언됨 |
| Agent → Controller | `ngrinder-controller:80`, 등록 포트 16001 및 테스트 제어 포트 12000~12029 접근 확인 |
| Agent → 백엔드 | Agent 기준으로 도달 가능한 BASE_URL. Docker Desktop에서 host.docker.internal 사용 가능 여부를 확인하고 Linux Agent는 필요 시 별도 host-gateway 매핑 또는 명시적 서버 DNS 사용 |
| 원격 Agent → 백엔드 | host.docker.internal은 그 Agent의 호스트를 가리키므로 원격 대상 서버 주소로 교체 |

Compose 네트워크에서는 서비스 이름을, Docker Desktop에서 호스트 서비스를 연결할 때는 해당 호스트 연결 방식을 사용한다. [Docker Compose 네트워크](https://docs.docker.com/compose/how-tos/networking/), [Docker Desktop 호스트 연결](https://docs.docker.com/desktop/features/networking/networking-how-tos/)

실행 담당자가 아래를 확인하고 결과를 run manifest에 저장한다.

1. `docker compose ps`에서 대상 서비스와 Agent를 확인한다. 컨테이너 Running만으로 Controller 등록·수집 준비가 완료된 것으로 처리하지 않는다.
2. Prometheus target `up{job="KnockIn"}`이 연속 scrape에서 1인지 확인한다. 실제 target 주소·프로필·DB도 확인해 다른 앱을 측정하지 않도록 한다.
3. 1 VU 요청 전후 `http_server_requests_seconds_count`가 증가하는지 확인한다. JVM·Hikari metric과 `application="KnockIn"`, `job`, `instance`, `method`, `uri`, `status` label의 실제 존재를 기록한다.
4. Grafana datasource 연결과 패널을 확인한다. 기존 README의 Dashboard 11378은 출발점이며 현재 metric 이름과 맞지 않는 빈 패널은 수정한다.
5. CPU/heap/Hikari·Agent 자원을 확인한 뒤 부하를 올린다. DB 내부 지표가 없으면 DB 잠금/쿼리가 병목이라고 확정하지 않는다.
6. `runId`, nGrinder test ID, commit/seed, 워밍업·측정·회복의 UTC 시각을 기록하고 Grafana annotation 또는 저장된 시간 범위와 연결한다.

5초 scrape 주기는 첫 시험에서 유지한다. 1분 rate는 추세용, 긴 구간의 histogram은 안정 분포 확인용으로 사용한다. 짧은 spike가 평균화되는 점을 고려해 nGrinder 표본도 함께 보며, 지표 해상도를 높일 때는 수집 자체 비용을 따로 비교한다.

## 4. 지표 역할과 Grafana 패널

| 역할 | 지표 / 측정 주체 |
|---|---|
| 최종 사용자 결과 | nGrinder API별 요청·지연 p95/p99·timeout·업무 assertion, 여정 TPS |
| 서버 HTTP | Prometheus API별 처리 RPS·서버 지연·status 분포; `/actuator` 수집 요청은 제외 |
| JVM·DB 풀 | heap/GC/CPU/thread, Hikari active/max/pending/acquire/timeout; 실제 노출 metric에 맞춰 구성 |
| DB 원인 | PostgreSQL 연결·wait/lock·slow query·실행계획. DB 관측 연결 또는 exporter를 별도로 준비 |
| 부하 발생 한계 | Agent CPU/heap/GC/network·활성 worker; Controller 통계나 별도 호스트 관측 사용 |
| 실시간·비동기 | STOMP 상대 수신, SSE 전달, FCM 대기/완료 등은 추가 계측. HTTP timer가 대신하지 않음 |

현재 APM README의 평균 응답 시간은 p95/p99를 제공하지 않는다. 백엔드 저장소의 기본 설정에서도 HTTP histogram 설정은 확인되지 않았다. 아래는 **시험 프로필에 추가할 후보 설정이며 아직 적용하지 않았다**. 실제 runtime override와 bucket 노출을 확인한 뒤 사용한다.

```properties
management.metrics.distribution.percentiles-histogram.http.server.requests=true
management.metrics.distribution.slo.http.server.requests=100ms,300ms,500ms,1s,2s,5s,10s
```

Spring Boot의 metric 분포 설정과 Micrometer histogram을 사용하면 bucket을 합산해 서버 percentile을 계산할 수 있다. 개별 인스턴스 percentile을 평균하지 않으며, 사용자 지연의 판정 기준은 여전히 nGrinder다. URI에는 경로 템플릿을 사용하고 memberId/boardId/JWT/runId를 HTTP metric label에 추가하지 않는다. [Spring Boot Metrics](https://docs.spring.io/spring-boot/reference/actuator/metrics.html), [Micrometer Histograms](https://docs.micrometer.io/micrometer/reference/concepts/histogram-quantiles.html)

아래 PromQL은 현재 job/application 값에 맞춘 패널 초안이다. 먼저 실제 metric·label·bucket을 확인한다. REST 추세에서 SSE 장기 요청은 제외하고 별도 패널로 다룬다.

```promql
# API별 서버 RPS: 사용자 여정 TPS와 구분
sum by (method, uri) (
  rate(http_server_requests_seconds_count{
    job="KnockIn", application="KnockIn",
    uri!~"/actuator.*", uri!="/alarms/subscribe"
  }[1m])
)

# 서버 응답 p95(ms): classic histogram bucket이 있을 때만 사용
histogram_quantile(0.95,
  sum by (le, method, uri) (
    rate(http_server_requests_seconds_bucket{
      job="KnockIn", application="KnockIn",
      uri!~"/actuator.*", uri!="/alarms/subscribe"
    }[5m])
  )
) * 1000

# 서버 5xx RPS: 전체 실패율은 nGrinder의 timeout/업무 실패까지 함께 판단
sum by (method, uri) (
  rate(http_server_requests_seconds_count{
    job="KnockIn", application="KnockIn", status=~"5..",
    uri!~"/actuator.*", uri!="/alarms/subscribe"
  }[1m])
)
```

p99는 quantile을 0.99로 바꾸되 충분한 표본과 bucket 범위를 확인한다. PromQL은 각 counter에 rate를 적용한 후 bucket을 합산한다. 위 5분 창이 ramp/워밍업을 포함하면 정상 구간 통계로 쓰지 않으며, 최종 보고서는 측정 구간 전체를 별도로 집계한다. 빈 시계열은 0ms·오류 0건이 아니라 미계측/미발생 상태일 수 있다. [Prometheus query functions](https://prometheus.io/docs/prometheus/latest/querying/functions/)

## 5. 관리 위치와 보완 순서

| 관리 위치 | 책임 |
|---|---|
| APM 저장소 | Compose·관측 설정과 성능 테스트 스크립트·설정·도구·계획·시나리오·측정 원본·레포트 전체 |
| 백엔드 저장소 | Actuator·histogram 설정, 필요한 업무 metric, 시험 프로필과 데이터/토큰 준비 코드 |
| `KnockIn/doc/test/perf/README.md` | APM의 `performance-test/README.md`로 연결하는 안내 |

`APM/performance-test/README.md`를 산출물 관리 인덱스로 사용한다. 기존 `ngrinder-performance-testing-*.md`는 초기 스크립트 작성 참고 자료다. 상태 코드만 확인하는 샘플, 고정 ID/공유 계정, 생성 응답의 ID 유무와 후속 ID 연계가 검증되지 않은 코드, 오래된 DTO는 시나리오별 smoke로 정비한다. 중복되는 실행 스크립트를 두 저장소에서 각각 관리하지 않고 APM 쪽 실행본의 commit/hash를 결과에 남긴다. 토큰·개인정보가 포함된 Controller 데이터 디렉터리를 문서 저장소에 복사하지 않는다.

정적 대조에서 확인한 대표 수정 사항은 다음과 같다. 경로는 APM의 `performance-test/` 기준이다.

| 기존 가이드 | 확인한 차이 | 적용할 기준 |
|---|---|---|
| `ngrinder-performance-testing-chat.md` | 생성 body `targetMemberId`, 실시간 `/ws`·`/topic`·`/app`은 현재 계약과 다름 | S04의 `requesteeId`+`chatMessage.contents`, S06의 `/ws-chat`·`/sub`·`/pub` |
| 같은 채팅 가이드 | 200/201/400/403/404/409 모두 성공 허용, 수신 callback의 내용 검증 없음 | 정상과 거절 run 분리, 상대 clientMessageId 수신·DB 저장 검증 |
| `ngrinder-performance-testing-roommate.md` | 게시글 생성 필드와 추천의 page/regionId/roomTypeId query가 현재 DTO와 다름 | S01/S02/S12 DTO, `size/excludeMemberIds/likedOnly` 사용 |
| `ngrinder-performance-testing-roommate_management.md` | 일정의 평면 body와 repeat ID 선택이 현재 중첩 DTO·기본 일정 ID와 다름 | S09의 calendar/repeatInfo 및 일별 응답 ID 연계 |
| HTTP·WebSocket 샘플 공통 | HTTP client/multipart/Jakarta WebSocket imports·provider가 실제 Agent에 있다는 보장 없음 | 현재 이미지에서 생성한 샘플과 호환 라이브러리로 1 VU 컴파일·송수신 검증 |

`@BeforeProcess`, `@BeforeThread`, API별 GTest, timeout 설정의 구조는 재사용할 수 있다. 성공률·TPS를 비교하기 전에 위 계약과 assertion을 바로잡는다.

1. **바로 진행할 준비**: 기존 네 도구와 계측 의존성 재사용, 1 VU 계약 확인, 실제 target/metric/Agent 등록 확인.
2. **정상 부하 전에 보완**: HTTP histogram, 필수 패널, Prometheus/Grafana 영속 데이터 volume, 이미지 고정, 대시보드 JSON/provisioning 버전 관리. 기존 UI 설정을 먼저 내보내 보존한다. [Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
3. **용량 판정 전에 보완**: 별도 호스트 Agent, DB/Agent 관측, PostgreSQL 데이터 규모, STOMP/SSE 수신 계측.

이번 변경은 위 관리 경계를 반영한 계획 문서다. APM Compose·백엔드 설정을 변경하거나 컨테이너를 재시작하지 않았다.
