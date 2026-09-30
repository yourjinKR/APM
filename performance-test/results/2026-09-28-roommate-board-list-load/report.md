# RoommateBoardListGetTest 단계별 부하 탐색 및 범용 Bash 실행기 검증

- 실행일: 2026-09-28 (Asia/Seoul)
- 대상: 실행 중인 로컬 백엔드, H2 시드 `seed.load-test.records-per-entity=1000`; 게시글 목록의 `totalElements=1002`
- 스크립트: nGrinder `RoommateBoardListGetTest.groovy`, 리비전 34
- 설정: 1 Agent·1 process, VUser 수만큼 thread, 스레드당 100회 요청, ramp-up 없음, sampling interval 2초
- **Connection reset on each test run: 해제** (`connectionReset=false`를 각 테스트 생성 후 REST API에서 재확인)
- 실행 방식: 단계별 순차 실행. 1→5→10→20 VUser 후, 실패 구간을 좁히려고 15 VUser 추가 실행

## 단계별 탐색 결과

이 표는 먼저 수행한 100회/VUser 탐색 시험의 결과다. 당시 사용한 전용 PowerShell 실행기는 [범용 Bash 실행기](../../tools/run-ngrinder-load-stages.sh)로 교체했다. 새 실행기의 동작 검증 결과는 아래에 별도로 기록했다.

| VUser | nGrinder ID | 테스트 이름 | 성공 | 오류 | 평균 응답시간 | TPS | 상태 |
|---:|---:|---|---:|---:|---:|---:|---|
| 1 | 250 | `local-H2-seed1000-RoommateBoardList-VUser1-20260928-195943` | 100 | 0 | 496.30 ms | 1.99 | FINISHED |
| 5 | 251 | `local-H2-seed1000-RoommateBoardList-VUser5-20260928-200139` | 500 | 0 | 1207.14 ms | 4.18 | FINISHED |
| 10 | 252 | `local-H2-seed1000-RoommateBoardList-VUser10-20260928-200402` | 1000 | 0 | 2479.62 ms | 4.04 | FINISHED |
| 15 | 254 | `local-H2-seed1000-RoommateBoardList-VUser15-20260928-201330` | 1396 | 104 | 3524.58 ms | 3.83 | FINISHED, 오류 포함 |
| 20 | 253 | `local-H2-seed1000-RoommateBoardList-VUser20-20260928-200834` | 172 | 178 | 4623.63 ms | 1.93 | STOP_BY_ERROR |

각 단계의 REST API 응답에서 VUser 수와 `connectionReset=false`를 확인했다. 원본: [1 VUser](./VUser1-250.json), [5 VUser](./VUser5-251.json), [10 VUser](./VUser10-252.json), [15 VUser](./VUser15-254.json), [20 VUser](./VUser20-253.json), [전체 CSV](./summary.csv).

## 범용 Bash 실행기 검증

[run-ngrinder-load-stages.sh](../../tools/run-ngrinder-load-stages.sh)는 nGrinder에 등록된 Groovy 스크립트를 `--script`로 여러 개 받고, `--vus`에 지정한 VUser 단계를 **스크립트별로 순차 실행**한다. 환경 라벨, Agent·process 수, 스레드당 실행 횟수, 대상 호스트, health URL, 대기 시간과 결과 디렉토리를 인자로 받는다. 비밀번호는 `NGRINDER_PASSWORD` 환경 변수에서만 읽고 결과 파일에는 넣지 않는다. 시작 전 스크립트 등록 상태와 백엔드 health를 확인하고, 테스트 생성 후 VUser 수와 `connectionReset=false`를 REST API로 검증한다. 완료 결과·실행 조건·집계 CSV를 저장하며, 오류가 발생하면 해당 시점에서 중단한다. 다른 스크립트로 계속할 때는 `--continue-next-script`를 지정한다.

Git Bash 5.2에서 실제 Controller와 백엔드를 대상으로 `RoommateBoardListGetTest.groovy`와 `CalendarCategoryGetTest.groovy`를 각각 1·2 VUser, 스레드당 5회 요청으로 실행했다. 네 테스트 모두 오류 0건으로 완료됐고, nGrinder 시작·종료 시각을 대조했을 때 겹침이 없었다. 네 테스트 모두 `connectionReset=false`와 테스트 이름의 환경·VUser 표기를 확인했다.

| 스크립트 | VUser | nGrinder ID | 성공/오류 | 상태 |
|---|---:|---:|---:|---|
| RoommateBoardListGetTest | 1 | 255 | 5/0 | FINISHED |
| RoommateBoardListGetTest | 2 | 256 | 10/0 | FINISHED |
| CalendarCategoryGetTest | 1 | 257 | 5/0 | FINISHED |
| CalendarCategoryGetTest | 2 | 258 | 10/0 | FINISHED |

검증 원본: [실행 조건](./bash-validation/manifest.json), [집계 CSV](./bash-validation/summary.csv), [테스트 255](./bash-validation/test-255.json), [256](./bash-validation/test-256.json), [257](./bash-validation/test-257.json), [258](./bash-validation/test-258.json). 이 짧은 검증의 지연·TPS는 위의 100회/VUser 탐색 결과와 비교하지 않는다. 네이티브 Linux 환경은 이번에 사용 가능하지 않아 Bash 동작은 Git Bash에서 확인했다.

다음 API를 실행할 때는 데이터 시드와 서버 실행 조건을 먼저 확인한 뒤 예를 들어 다음처럼 실행한다.

```bash
export NGRINDER_USERNAME=admin
export NGRINDER_PASSWORD='<controller password>'
bash performance-test/tools/run-ngrinder-load-stages.sh \
  --script RoommateBoardListGetTest.groovy \
  --script CalendarCategoryGetTest.groovy \
  --vus 1,5,10 --environment local-H2-seed1000 --iterations 100
```

`--environment`는 테스트 이름과 기록에 쓰는 라벨이다. Bash 실행기는 백엔드를 재기동하거나 시드 크기를 변경하지 않는다. 기본 결과 위치는 `performance-test/results/YYYY-MM-DD-ngrinder-load/run-TIMESTAMP/`이다.

## 관찰과 한계

- 5→10 VUser에서 TPS는 4.18→4.04로 늘지 않았고, 평균 응답시간은 1.21→2.48초로 증가했다.
- 15 VUser에서는 `FINISHED` 상태라도 104건의 오류가 있었다. 20 VUser는 오류가 많아 nGrinder가 조기 중단했다. 두 테스트의 에이전트 로그에서 `java.net.SocketTimeoutException: 5000 MILLISECONDS`가 반복됐다. HTTP 5xx나 연결 거절은 확인한 로그에서 나타나지 않았다.
- 측정 종료 후 Controller 실행 중 테스트는 0개, 백엔드 health는 `UP`, 게시글 수는 1002건이었다.
- 각 VUser 단계를 한 번씩 실행한 탐색 결과다. 이 데이터만으로 안전 동시 사용자 한계나 운영 처리 용량을 확정할 수 없다. 5초 클라이언트 타임아웃에 걸린 원인도 서버 CPU·GC·DB·에이전트 자원 지표 없이 특정할 수 없다. 이 평균값은 p95/p99가 아니다.

다음 측정에서는 5~15 VUser 구간을 같은 조건으로 반복하고, 서버 및 nGrinder Agent 자원 지표와 응답시간 분포를 함께 수집한다. PostgreSQL 환경의 용량은 별도로 측정한다.
