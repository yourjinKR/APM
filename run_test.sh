#!/usr/bin/env bash

set -euo pipefail

NGRINDER_BASE_URL="http://localhost"
NGRINDER_AUTH="admin:admin"

usage() {
    cat <<'EOF'
사용법:
  ./run_test.sh <TEST_ID> [반복횟수] [실행간격초]

예시:
  ./run_test.sh 97
  ./run_test.sh 97 5
  ./run_test.sh 97 5 120
EOF
}

require_positive_integer() {
    local name="$1"
    local value="$2"

    if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
        echo "$name 값은 1 이상의 정수여야 합니다: $value" >&2
        exit 1
    fi
}

require_non_negative_integer() {
    local name="$1"
    local value="$2"

    if [[ ! "$value" =~ ^[0-9]+$ ]]; then
        echo "$name 값은 0 이상의 정수여야 합니다: $value" >&2
        exit 1
    fi
}

if [[ $# -lt 1 || $# -gt 3 ]]; then
    usage
    exit 1
fi

TEST_ID="$1"
MAX_LOOP="${2:-1}"
INTERVAL_SECONDS="${3:-120}"

require_positive_integer "Test ID" "$TEST_ID"
require_positive_integer "반복 횟수" "$MAX_LOOP"
require_non_negative_integer "실행 간격" "$INTERVAL_SECONDS"

response_file="$(mktemp)"
trap 'rm -f "$response_file"' EXIT

running_test_count() {
    local http_code
    local count

    : > "$response_file"
    if ! http_code="$(curl --silent --show-error \
        --output "$response_file" \
        --write-out '%{http_code}' \
        --user "$NGRINDER_AUTH" \
        "${NGRINDER_BASE_URL}/perftest/api/status")"; then
        echo "nGrinder 실행 상태 조회에 실패했습니다." >&2
        cat "$response_file" >&2
        exit 1
    fi

    if [[ ! "$http_code" =~ ^2[0-9][0-9]$ ]]; then
        echo "nGrinder 실행 상태 조회 실패: HTTP ${http_code}" >&2
        cat "$response_file" >&2
        exit 1
    fi

    count="$(grep -oE '"runningTestsCount"[[:space:]]*:[[:space:]]*[0-9]+' "$response_file" \
        | grep -oE '[0-9]+' \
        | head -n 1 \
        || true)"

    if [[ -z "$count" ]]; then
        echo "nGrinder 실행 상태 응답을 해석하지 못했습니다." >&2
        cat "$response_file" >&2
        exit 1
    fi

    printf '%s' "$count"
}

wait_until_controller_idle() {
    local count

    while true; do
        count="$(running_test_count)"
        if [[ "$count" == "0" ]]; then
            return
        fi

        echo "[$(date +'%Y-%m-%d %H:%M:%S')] 실행 중인 테스트 ${count}개가 끝나기를 기다립니다..."
        sleep 5
    done
}

echo "================================================="
echo " nGrinder 반복 실행"
echo " - Test ID     : ${TEST_ID}"
echo " - 반복 횟수   : ${MAX_LOOP}회"
echo " - 실행 간격   : ${INTERVAL_SECONDS}초"
echo "================================================="

for ((i=1; i<=MAX_LOOP; i++)); do
    wait_until_controller_idle
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ${i}/${MAX_LOOP} 실행 요청 중..."

    : > "$response_file"
    if ! http_code="$(curl --silent --show-error \
        --output "$response_file" \
        --write-out '%{http_code}' \
        --user "$NGRINDER_AUTH" \
        --header 'Content-Type: application/json' \
        --request POST \
        "${NGRINDER_BASE_URL}/perftest/api/${TEST_ID}/clone_and_start" \
        --data '{}')"; then
        echo "nGrinder 실행 요청에 실패했습니다." >&2
        cat "$response_file" >&2
        exit 1
    fi

    if [[ ! "$http_code" =~ ^2[0-9][0-9]$ ]]; then
        echo "nGrinder 실행 요청 실패: HTTP ${http_code}" >&2
        cat "$response_file" >&2
        exit 1
    fi

    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ${i}/${MAX_LOOP} 실행 요청 완료 (HTTP ${http_code})"

    if [[ $i -lt $MAX_LOOP && $INTERVAL_SECONDS -gt 0 ]]; then
        sleep "$INTERVAL_SECONDS"
    fi
done

echo "================================================="
echo " Test ID ${TEST_ID}의 반복 실행 요청 ${MAX_LOOP}회가 완료되었습니다."
echo " 마지막 테스트의 완료 상태는 nGrinder Controller에서 확인하세요."
echo "================================================="
