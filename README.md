# APM & Load Testing Environment

성능 테스트 스크립트·설정·실행 도구·측정 레포트의 관리 기준은 이 저장소다. [산출물 인덱스](./performance-test/README.md)에서 현재 파일과 실행 절차를 확인한다.

로컬 개발 환경에서 **Prometheus**, **Grafana**, 그리고 **nGrinder**를 활용하여 Application Performance Monitoring(APM) 및 부하 테스트(Load Testing)를 수행할 수 있도록 재구성한 환경입니다.

---

## 🛠️ 기술 스택 및 서비스 구성

| 서비스 | 이미지 / 버전 | 포트 (Host) | 역할 |
|---|---|---|---|
| **Prometheus** | `prom/prometheus` | `9090` | 메트릭 수집 및 저장 (로컬 애플리케이션 메트릭 수집) |
| **Grafana** | `grafana/grafana` | `3000` | 모니터링 시각화 대시보드 (`http://localhost:3000`) |
| **nGrinder Controller** | `ngrinder/controller:3.5.9-p1` | `80`, `16001`, `12000-12029` | 부하 테스트 제어 Web UI (`http://localhost:80`) 및 에이전트 관리 |
| **nGrinder Agent** | `ngrinder/agent:3.5.9-p1` | - | Controller의 명령을 받아 실제 부하를 생성 |

---

## 🎯 모니터링 수집 대상 (Local App)

- **대상 애플리케이션 주소**: `http://host.docker.internal:8080`
- **Metrics Path**: `/actuator/prometheus`
- **설명**: Prometheus 컨테이너가 Docker 호스트의 `8080` 포트에서 실행 중인 로컬 Spring Boot 애플리케이션 메트릭을 수집합니다 (`extra_hosts` 설정 적용).

---

## 🚀 Docker Compose 실행 및 관리 방법

### 1. 전체 컨테이너 실행 (백그라운드)
```bash
docker compose up -d
```
*(또는 `docker-compose up -d`)*

### 2. 컨테이너 상태 확인
```bash
docker compose ps
```

### 3. 실시간 로그 확인
```bash
# 전체 로그 확인
docker compose logs -f

# 특정 서비스 로그 확인 (예: prometheus 또는 ngrinder-controller)
docker compose logs -f prometheus
docker compose logs -f ngrinder-controller
```

### 4. 전체 컨테이너 중지 및 종료
```bash
docker compose down
```

### 5. nGrinder AGENT 설정

아래와 같이 AGENT의 숫자를 설정할 수 있습니다. (default 5)

```bash
docker compose up -d --scale ngrinder-agent=8
```

nGrinder AGENT만 변경시에는 다음 명령어 실행

```bash
docker compose up -d --no-deps --scale ngrinder-agent=5 ngrinder-agent
```

---

## 📊 Grafana 설정 및 대시보드 Import

1. **Grafana 접속**: [http://localhost:3000](http://localhost:3000) (기본 계정: `admin` / `admin`)
2. **Prometheus 데이터 소스(Data Source) 추가**:
   - `Connections` -> `Data sources` -> `Add data source`
   - **Prometheus** 선택
   - **URL**: `http://prometheus:9090` (또는 `http://prometheus-knock-in:9090`)
   - `Save & test` 버튼 클릭하여 연결 정상 여부 확인
3. **대시보드 Import**:
   - `Dashboards` -> `New` -> `Import` 메뉴 이동
   - **Dashboard ID**: `11378` (Spring Boot Statistics 대시보드) 입력 후 `Load` 클릭
   - Data Source로 방금 생성한 Prometheus를 선택하고 `Import` 완료

## 📊 Grafana Monitoring Dashboard Guide

Prometheus 데이터 소스를 활용하여 애플리케이션(KnockIn)의 TPS 및 응답 시간을 모니터링하기 위한 패널 추가 가이드입니다.

### 🛠️ 기본 설정 방법
1. 그라파나 대시보드 진입
2. 우측 상단 **Edit** 클릭
3. **Add visualization** 또는 **Add panel** 선택
4. **Data source**: `Prometheus` 선택

---

### 1. 전체 TPS / RPS
* **설명**: 전체 애플리케이션의 초당 요청 수(TPS)를 모니터링합니다.
* **PromQL**:
  ```promql
  sum(rate(http_server_requests_seconds_count{application="KnockIn"}[1m]))
  ```

---

### 2. API별 TPS
* **설명**: 액츄에이터(`/actuator.*`) 경로를 제외한 각 API 엔드포인트별 TPS를 추적합니다.
* **PromQL**:
  ```promql
  sum by (method, uri) (
    rate(http_server_requests_seconds_count{application="KnockIn", uri!~"/actuator.*"}[1m])
  )
  ```
* **Panel 설정 팁**: 
  * **Legend**: `{{method}} {{uri}}`
  * **Graph style**: Time series

---

### 3. API별 TPS Top 10
* **설명**: 호출량이 가장 많은 상위 10개의 API를 확인합니다.
* **PromQL**:
  ```promql
  topk(10,
    sum by (method, uri) (
      rate(http_server_requests_seconds_count{uri!~"/actuator.*"}[1m])
    )
  )
  ```

---

### 4. API별 평균 응답 시간 (ms)
* **설명**: 각 API별 평균 응답 시간을 밀리초(ms) 단위로 측정합니다. (`sum / count * 1000`)
* **PromQL**:
  ```promql
  (
    sum by (method, uri) (
      rate(http_server_requests_seconds_sum{application="KnockIn", uri!~"/actuator.*"}[1m])
    )
    /
    sum by (method, uri) (
      rate(http_server_requests_seconds_count{application="KnockIn", uri!~"/actuator.*"}[1m])
    )
  ) * 1000
  ```
---

## 🧪 nGrinder 부하 테스트 툴 사용 방법

1. **nGrinder Controller Web UI 접속**: [http://localhost](http://localhost) (또는 `http://localhost:80`)
2. **초기 로그인**:
   - **ID**: `admin`
   - **Password**: `admin`
3. **Agent 연결 확인**:
   - 상단 메뉴에서 `Agent Management` 클릭 후 `ngrinder-agent`가 정상 연동되어 있는지 확인
4. **부하 테스트 스크립트 작성 및 실행**:
   - `Script` 메뉴에서 Groovy 기반 테스트 스크립트 작성 (대상 주소: `http://host.docker.internal:8080` 또는 로컬 IP)
   - `Performance Test` 메뉴에서 테스트 생성 및 VUser 설정 후 부하 테스트 수행
