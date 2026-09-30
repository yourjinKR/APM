# 2026-09-21 `/terms` 반복 부하 시험 오류 조사

조사일: 2026-09-21. 본문의 시각은 **KST(UTC+9)**다. nGrinder 원본 로그·CSV는 UTC다. 기존 결과를 읽어 조사했으며 부하 재실행이나 설정 변경은 하지 않았다.

## 1. 결론

**19:33 실행(#36)의 직접적인 실패는 HTTP 응답 오류가 아니라 TCP 연결 거절이다. Windows의 임시 TCP 포트 소진·재사용 제한이 가장 유력한 원인이다.** 오류 시작 직전에 Windows `Tcpip` 이벤트 **4227**이 기록되었다. 두 Agent에서 거의 동시에 `java.net.ConnectException: Connection refused`가 시작됐고, 오류가 지속되자 nGrinder가 시험을 자동 중단했다.

Windows 이벤트와 연결 거절의 시간 일치는 강한 근거다. 다만 당시 소켓별 PID·패킷 기록은 없으므로 **어느 프로세스가 포트를 점유했는지, Docker의 어느 전달 단계에서 실패했는지까지 확정하지는 못했다.** 백엔드 재시작, DB 연결 풀 고갈, HTTP 500 폭증을 뒷받침하는 지표는 관측되지 않았다.

## 2. 6개 실행 비교

Controller 로그의 설정은 모두 `2 agents × 5 processes × 10 threads = 100 VU`, `duration=60000`, `connectionReset=true`, `processIncrement=0`, `ignoreSampleCount=0`이다. 즉 프로세스 ramp-up과 초기 표본 제외가 없다. 실행 당시 선택된 Agent는 `62dbb23e4b8e`, `f41822f38b39`다. 조사 시점에 켜진 Agent 컨테이너 수와 실제 시험에 투입된 Agent 수는 구별한다.

| 화면 시작 시각 / ID | CSV 첫–마지막 표본 | 성공 | 실패 | 실패율 | TPS | 성공 평균(ms) | 연결 수립 평균(ms) |
|---|---|---:|---:|---:|---:|---:|---:|
| 19:24 / #34 | 19:24:32–19:25:20 | 15,805 | 561 | 3.43% | 311.2 | 310.4 | 285.3 |
| 19:32 / #35 | 19:32:28–19:33:15 | 12,609 | 0 | 0% | 257.9 | 383.6 | 356.7 |
| **19:33 / #36** | **19:33:58–19:34:27** | **3,159** | **7,375** | **70.01%** | **103.3** | **316.5** | **286.0** |
| 19:35 / #37 | 19:35:25–19:36:12 | 9,745 | 0 | 0% | 197.6 | 495.9 | 465.2 |
| 19:36 / #38 | 19:37:01–19:37:50 | 7,301 | 0 | 0% | 142.3 | 675.9 | 641.2 |
| 19:38 / #39 | 19:38:36–19:39:23 | 9,946 | 0 | 0% | 202.1 | 492.6 | 445.7 |

성공·실패 합계는 CSV와 `.data` 파일 및 Controller 최종 통계가 일치한다. 시간 평균은 `Σ(구간 성공수 × 구간 평균시간) / Σ성공수`다. 실패 요청은 성공 평균에 포함되지 않는다. TPS는 Controller 최종 통계다. 전체 실행 시간, Controller 수집 시간, CSV 첫–마지막 표본 구간은 서로 다른 값이다.

**정상 실행까지 연결 수립이 성공 평균 시간의 90.38–94.86%를 차지한다.** 이 결과를 그대로 백엔드 비즈니스 로직 처리 시간이나 운영 처리량으로 해석하기 어렵다.

## 3. #36의 실제 장애 순서

| 시각(KST) | 증거 |
|---|---|
| 19:33:46.259 | Controller가 표본 수집 시작 |
| 19:33:55.723 / 56.358 | 확인 가능한 두 Agent의 worker 0 실행 시작 |
| **19:34:06.070** | **Windows System 로그: `Tcpip` 이벤트 4227. 최근 같은 원격 끝점에 사용한 로컬 끝점을 재사용할 수 없어 나가는 TCP 연결 설정 실패** |
| **19:34:06.266 / 06.333** | **두 Agent worker 0에서 `Connection refused` 최초 발생** |
| 19:34:09–25 | CSV 성공 TPS가 0–3.5로 급락. 약 2초 표본마다 실패 595–1,032건 |
| 19:34:27.366 | `TooManyErrorCheckPlugin`이 최근 10초의 과도한 오류를 감지해 시험 중단 결정 |
| 19:34:28.316 | Controller 표본 수집 종료 |
| 19:34:29.367 | `Abnormal test is terminated` 기록 |

화면의 `00:01:00`은 설정된 시간이다. #36은 **Controller 수집 약 42초, 확인 가능한 worker 실행 약 32초** 후 조기 종료했다. 연결 오류가 먼저 발생했고 약 21초 뒤 자동 중단되었으므로, 시험 종료 때문에 최초 오류가 발생한 순서는 아니다.

확인한 두 worker 0 로그는 각각 오류 747건이며 모두 `Connection refused`다. 원본 ZIP에는 각 Agent의 worker 0 로그만 있어 10개 worker의 모든 예외를 직접 검사한 것은 아니다. **7,375건은 전체 집계 실패 수**이고, 1,494건의 보존된 예외가 같은 연결 거절 증상을 보인다. 전체 CSV의 `Response_errors`는 0이다.

## 4. Windows 포트와 반복 실행 조건

조사 시점의 `netsh int ipv4/ipv6 show dynamicport tcp`는 모두 **49152–65535, 16,384개**를 반환했다. `TcpTimedWaitDelay`와 `MaxUserPort`의 명시적 레지스트리 재정의는 조회되지 않았다.

현재 스크립트 `BoTermsTypeList.groovy`는 이름과 달리 `http://host.docker.internal:8080/terms`를 GET하고 200을 검증한다. 요청 사이 대기 코드는 없다. Controller의 `grinder.connectionReset=true` 및 worker JVM의 `-Dngrinder.connection.reset.on.each.test.run=true`도 확인했다. 이 설정은 반복 실행 사이 연결을 초기화하므로 짧은 요청을 반복할 때 신규 연결 생성량이 커진다.

사용 중인 3.5.9-p1의 `HTTPPluginThreadState.beginRun()`은 해당 JVM property가 비어 있지 않으면 이전 연결을 닫고 `HTTPRequester.reset()`을 호출한다. 이 스크립트는 run당 GET이 하나라 매 요청 신규 연결에 해당한다. **JVM 인자에 직접 `false`라는 문자열을 넣어도 초기화가 활성화되는 구현**이므로, 설정을 해제할 때는 worker 명령행에서 해당 property가 없어졌거나 빈 값인지 확인해야 한다. [nGrinder 3.5.9-p1 공식 소스](https://github.com/naver/ngrinder/blob/ngrinder-3.5.9-p1-20240613/ngrinder-runtime/src/main/java/net/grinder/plugin/http/HTTPPluginThreadState.java#L110)

UI에서 체크를 해제하는 정상 경로는 이 함정에 해당하지 않는다. Controller는 `grinder.connectionReset`을 boolean으로 저장하고, Agent의 `PropertyBuilder`는 값이 true일 때만 위 JVM 인자를 추가한다. 따라서 별도의 사용자 JVM 인자가 없다면 **UI 체크 해제로 연결 초기화를 끌 수 있다.** [Controller 매핑](https://github.com/naver/ngrinder/blob/ngrinder-3.5.9-p1-20240613/ngrinder-controller/src/main/java/org/ngrinder/perftest/service/PerfTestService.java), [Agent JVM 인자 생성](https://github.com/naver/ngrinder/blob/ngrinder-3.5.9-p1-20240613/ngrinder-core/src/main/java/net/grinder/engine/agent/PropertyBuilder.java)

따라서 다음 경로가 가장 유력하다.

1. 짧은 GET을 대기 없이 반복하고 매 반복 연결을 초기화한다.
2. Docker Agent에서 Windows 호스트로 향하는 경로에 연결 생성·종료가 누적된다.
3. 임시 포트를 재사용하지 못하는 시점에 Windows 4227과 Agent 연결 거절이 함께 발생한다.
4. 다음 실행은 이전 연결의 잔존 상태와 회복 상태에 영향을 받는다.

**VU·기간·스크립트 설정이 같아도 시작 시점의 포트 상태는 같지 않다.** #35의 종료 후 #36의 실제 부하 시작까지는 약 40초다. 이 차이가 일부 실행에서만 실패하는 현상을 설명할 수 있다. 단, 성공 요청 수를 곧바로 Windows 점유 포트 수로 환산하거나 TIME_WAIT 개수를 역산할 수는 없다.

Windows 4227은 Microsoft가 포트 소진 조사 지표로 안내하는 이벤트다. 정확한 점유 프로세스는 장애 당시 소켓/PID 또는 네트워크 추적으로 좁혀야 한다. [Microsoft: TCP/IP 포트 소진 문제 해결](https://learn.microsoft.com/en-us/troubleshoot/windows-client/networking/tcp-ip-port-exhaustion-troubleshooting)

## 5. 백엔드·DB 지표 대조

Prometheus `job="KnockIn"`, `instance="host.docker.internal:8080"`의 19:23–19:40 기록을 5초 간격으로 조회했다.

| 지표 | 관측 결과 | 해석 |
|---|---|---|
| `up` | 전체 조회 표본 1 | 5초 단위 수집은 계속 성공. 모든 순간의 접속 성공까지 보장하지는 않음 |
| `process_start_time_seconds` | 전체 구간 일정 | 관측 구간 내 백엔드 프로세스 재시작 근거 없음 |
| `/terms` HTTP 지표 | 조회된 상태 시계열은 200만 존재 | 애플리케이션이 처리한 요청에서 4xx/5xx 폭증 근거 없음 |
| Hikari pending / timeout | 19:33:45–19:34:35 pending 0, timeout 증가 0 | 해당 구간 DB 풀 대기·획득 timeout 근거 없음 |
| GC pause 합계 | 같은 구간 약 20ms 증가 | 22초 연결 실패를 설명할 장시간 GC 정지 근거 없음 |
| 백엔드 `process_cpu_usage` | 같은 구간 최대 약 20.5% | 백엔드 프로세스 CPU만으로 설명하기 어려움 |
| 백엔드가 보고한 `system_cpu_usage` | 19:34:00 평가 표본에서 100% | 공유 호스트 자원 경쟁도 존재. 포트 소진의 단독 원인으로 확정하지 않음 |

19:33:45–19:34:35의 `/terms` 서버 계측 누적 차이는 3,502건 / 14.8309초, **완료 요청 평균 약 4.24ms**다. nGrinder의 성공 평균 316.5ms와 큰 차이가 있다. 다만 수집 경계와 요청 집계 범위가 달라 두 평균을 정확히 빼서 네트워크 지연을 산출해서는 안 된다. 서버 처리 전 연결 실패는 HTTP 서버 지표에 잡히지 않는다.

추가 환경 변수로, worker JVM 옵션은 각각 `-Xms1024m -Xmx1024m`이다. 2 Agent × 5 process이면 worker 10개, 설정된 초기/최대 heap 합계가 각각 10GiB다. 이는 실제 메모리 사용량이나 OOM 증거는 아니지만, 같은 호스트에서 측정할 때 프로세스 수를 줄여 비교할 이유가 된다.

## 6. 19:24 실행(#34)의 3.4% 오류

실패 561건은 **마지막 CSV 표본(19:25:20)에만 집중**됐다. 보존된 worker 로그의 오류 구간은 19:25:19.005–21.394이며, 역시 두 Agent에서 `Connection refused`다. 직전부터 연결 수립 지연도 상승했다.

증상은 #36과 같지만 조회한 Windows System 로그에는 이 시각의 4227/4231이 없었다. 따라서 **#34까지 포트 소진으로 확정하지 않는다.** 마지막 약 2초의 일시적 연결 거절이며, 시험 전체에 3.4% 오류가 고르게 분포한 것은 아니다.

## 7. 다음 검증 순서

다음 항목은 아직 실행하지 않았다. 한 번에 한 조건만 바꾸고 시험 시작 전 포트 상태를 기록한다.

1. **연결 재사용 A/B**: 현재 2 Agent × 5 process × 10 thread 및 대상·기간을 유지하고 `Connection reset on each test run`만 해제한 실행과 비교한다. 성공/오류/TPS뿐 아니라 연결 수립 시간, Windows 4227/4231, 소켓 상태를 함께 비교한다. 포트 사용량이 기준선으로 회복된 뒤 반복하여 이전 실행의 잔존 영향을 통제한다.
2. **포트 점유 근거 수집**: 다음 재현 때 호스트의 `Get-NetTCPConnection` 또는 `netstat -anoq`를 일정 간격으로 저장한다. 원격 주소·포트, 상태, PID별 집계를 남긴다. TIME_WAIT/BOUND의 많은 개수만으로 원인을 확정하지 말고 오류 시각·4227과 함께 대조한다. 추적 자료가 필요하면 Microsoft 문서의 네트워크 추적 절차를 적용한다.
3. **부하 생성기 자원 분리**: 연결 재사용을 고정한 상태에서 `2 Agent × 1 process × 50 thread = 100 VU`를 비교한다. JVM 수 감소 효과와 연결 설정 효과를 섞지 않는다. 부하 생성기의 CPU·GC·실제 메모리 사용량도 기록한다.
4. **백엔드 용량 측정 경로 정리**: 가능하면 별도 호스트/VM의 Agent에서 백엔드에 접근하여 공유 CPU 및 Docker→Windows 전달 경로의 영향을 줄인다. 현재 구성은 기능·계측 검증에 사용하고, 환경 한계가 제거된 뒤 장시간 부하와 시나리오별 용량을 판정한다.

재현을 위한 reset-on 시험은 연결 생성 스트레스 시험으로 따로 분류한다. 일반 HTTP 성능 시험에서는 클라이언트의 실제 연결 재사용 특성을 반영한다. 자동 중단을 끄는 것은 연결 실패 원인의 해결이 아니다.

## 8. 보존한 증거와 한계

- [실행별 집계](./run-summary.json): 34–39의 CSV 성공수 가중 평균과 합계.
- [Controller 로그 발췌](./controller-evidence.log): 설정, 총계, 수집 시간, 자동 중단 사유. 수집 시간 발췌는 파일 뒤에 추가되어 있으므로 타임스탬프로 읽는다.
- [Agent 로그 발췌](./agent-evidence.json): 34/36 각 Agent의 worker 0 오류 종류·최초/최종 시각·옵션·통계.
- [Windows TCP/IP 이벤트](./windows-tcpip-events.json): 19:23–19:40 System 로그의 4227/4231 조회 결과.
- [Windows 포트 설정](./windows-port-config.json): 조사 시점의 읽기 전용 조회값.
- [Prometheus 조회 결과](./prometheus-window.json): 19:23–19:40, step 5초. 실제 scrape 시각과 query 평가 시각은 다를 수 있다.

원본 결과 위치: `C:\dev\workspace\prography\APM\ngrinder-controller-data\perftest\0_999\{34..39}`. 현재 스크립트 위치: 같은 Controller 데이터 디렉터리의 `script\admin\BoTermsTypeList.groovy`.

수치 설정이 같다는 것은 Controller 로그로 확인했다. 현재 스크립트와 실행 로그의 `GET /terms`는 확인했지만, 여섯 실행의 과거 스크립트 내용을 해시로 대조한 것은 아니다. 5초 지표로 짧은 순간의 자원 고갈을 완전히 배제할 수 없고, 모든 worker의 예외 로그도 보존돼 있지는 않다. 현재 근거로는 **Windows 포트 재사용 실패 → Agent 연결 거절 → nGrinder 자동 중단**의 설명이 가장 강하다.
