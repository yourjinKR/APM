#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run registered nGrinder Groovy scripts sequentially at each requested VUser level.

Requirements: Bash, curl, Python 3, NGRINDER_PASSWORD.

Usage:
  bash run-ngrinder-load-stages.sh \
    --script RoommateBoardListGetTest.groovy \
    [--script AnotherGetTest.groovy ...] \
    --vus 1,5,10,20 --environment local-H2-seed1000 \
    [--iterations 100] [--output-dir PATH]

Options:
  --script NAME                 Add one registered Groovy script; repeat for more.
  --vus CSV                     Total VUsers per stage, in execution order.
  --environment LABEL           Name label, for example local-H2-seed1000.
  --iterations N                Runs per VUser (default: 100).
  --agents N                    Agent count (default: 1).
  --processes N                 Processes per agent (default: 1).
  --target-host HOST            nGrinder target host (default: host.docker.internal).
  --controller-url URL          nGrinder controller (default: http://localhost).
  --health-url URL              Backend readiness URL (default: http://localhost:8080/actuator/health).
  --cooldown-sec N              Pause between completed tests (default: 15).
  --timeout-sec N               Per-test completion timeout (default: 600).
  --output-dir PATH             Result directory (default: ../results/YYYY-MM-DD-ngrinder-load/run-TIMESTAMP).
  --continue-next-script        On a failed stage, skip its higher stages and run the next script.
  --help                        Show this help.

Each test has connectionReset=false and ignoreTooManyError=false. The script
does not start, stop, or reseed the backend. Confirm the dataset before running.
EOF
}

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
is_positive() { [[ "$1" =~ ^[1-9][0-9]*$ ]]; }
is_nonnegative() { [[ "$1" =~ ^[0-9]+$ ]]; }

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
controller_url='http://localhost'
health_url='http://localhost:8080/actuator/health'
target_host='host.docker.internal'
environment=''
vus_csv=''
iterations=100
agents=1
processes=1
cooldown_sec=15
timeout_sec=600
output_dir="$script_dir/../results/$(date +%F)-ngrinder-load/run-$(date +%Y%m%d-%H%M%S)"
failure_policy='stop-suite'
scripts=()

while (($#)); do
  case "$1" in
    --script) (($# >= 2)) || die '--script needs a value'; scripts+=("$2"); shift 2 ;;
    --vus) (($# >= 2)) || die '--vus needs a value'; vus_csv="$2"; shift 2 ;;
    --environment) (($# >= 2)) || die '--environment needs a value'; environment="$2"; shift 2 ;;
    --iterations) (($# >= 2)) || die '--iterations needs a value'; iterations="$2"; shift 2 ;;
    --agents) (($# >= 2)) || die '--agents needs a value'; agents="$2"; shift 2 ;;
    --processes) (($# >= 2)) || die '--processes needs a value'; processes="$2"; shift 2 ;;
    --target-host) (($# >= 2)) || die '--target-host needs a value'; target_host="$2"; shift 2 ;;
    --controller-url) (($# >= 2)) || die '--controller-url needs a value'; controller_url="$2"; shift 2 ;;
    --health-url) (($# >= 2)) || die '--health-url needs a value'; health_url="$2"; shift 2 ;;
    --cooldown-sec) (($# >= 2)) || die '--cooldown-sec needs a value'; cooldown_sec="$2"; shift 2 ;;
    --timeout-sec) (($# >= 2)) || die '--timeout-sec needs a value'; timeout_sec="$2"; shift 2 ;;
    --output-dir) (($# >= 2)) || die '--output-dir needs a value'; output_dir="$2"; shift 2 ;;
    --continue-next-script) failure_policy='continue-next-script'; shift ;;
    --help|-h) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

((${#scripts[@]} > 0)) || die 'Provide at least one --script.'
[[ -n "$vus_csv" ]] || die 'Provide --vus.'
[[ -n "$environment" ]] || die 'Provide --environment.'
[[ -n "${NGRINDER_PASSWORD:-}" ]] || die 'Set NGRINDER_PASSWORD.'
NGRINDER_USERNAME="${NGRINDER_USERNAME:-admin}"
is_positive "$iterations" || die '--iterations must be positive.'
is_positive "$agents" || die '--agents must be positive.'
is_positive "$processes" || die '--processes must be positive.'
is_positive "$timeout_sec" || die '--timeout-sec must be positive.'
is_nonnegative "$cooldown_sec" || die '--cooldown-sec must be nonnegative.'
[[ "$controller_url" =~ ^https?:// ]] || die '--controller-url must be HTTP(S).'
[[ "$health_url" =~ ^https?:// ]] || die '--health-url must be HTTP(S).'
[[ -n "$target_host" ]] || die '--target-host cannot be empty.'

IFS=',' read -r -a vus <<< "$vus_csv"
((${#vus[@]} > 0)) || die '--vus has no values.'
for vu in "${vus[@]}"; do
  is_positive "$vu" || die "Invalid VUser count: $vu"
  ((vu % (agents * processes) == 0)) || die "VUser $vu must be divisible by agents * processes."
done
for script in "${scripts[@]}"; do
  [[ "$script" == *.groovy ]] || die "Expected a .groovy script name: $script"
done

command -v curl >/dev/null || die 'curl is required.'
if command -v python3 >/dev/null; then
  python_bin=python3
elif command -v python >/dev/null; then
  python_bin=python
else
  die 'Python 3 is required.'
fi
"$python_bin" -c 'import sys; sys.exit(0 if sys.version_info.major == 3 else 1)' || die 'Python 3 is required.'

controller_url="${controller_url%/}"
mkdir -p -- "$output_dir"
output_dir="$(cd -- "$output_dir" && pwd)"
probe="$output_dir/.write-check.tmp"
: > "$probe" || die "Cannot write to $output_dir"
rm -f -- "$probe"

api_get() {
  curl --silent --show-error --fail --connect-timeout 5 --max-time 30 \
    --user "$NGRINDER_USERNAME:$NGRINDER_PASSWORD" "$controller_url$1"
}

json_value() {
  "$python_bin" -c '
import json,sys
value=json.load(sys.stdin)
for key in sys.argv[1].split("."):
    value=value.get(key) if isinstance(value,dict) else None
print("" if value is None else str(value).lower() if isinstance(value,bool) else value)
' "$1"
}

check_health() {
  curl --silent --show-error --fail --connect-timeout 5 --max-time 30 "$health_url" >/dev/null \
    || die "Backend health check failed: $health_url"
}

wait_for_idle() {
  local deadline=$((SECONDS + timeout_sec)) status count
  while ((SECONDS < deadline)); do
    status="$(api_get '/perftest/api/status')"
    count="$(printf '%s' "$status" | json_value runningTestsCount)"
    [[ "$count" =~ ^[0-9]+$ ]] || die 'Controller status did not include runningTestsCount.'
    [[ "$count" == 0 ]] && return 0
    sleep 3
  done
  die 'Controller did not become idle.'
}

write_summary() {
  "$python_bin" - "$output_dir" <<'PY'
import csv, glob, json, os, sys
directory = sys.argv[1]
fields = ['testId', 'testName', 'scriptName', 'vusers', 'connectionReset',
          'runCountPerUser', 'status', 'tests', 'errors', 'meanTestTimeMs',
          'tps', 'peakTps', 'runtime', 'scriptRevision']
rows = []
for path in glob.glob(os.path.join(directory, 'test-*.json')):
    with open(path, encoding='utf-8') as source:
        test = json.load(source)
    if not test.get('finishTime'):
        continue
    rows.append({
        'testId': test.get('id'), 'testName': test.get('testName'),
        'scriptName': test.get('scriptName'),
        'vusers': test.get('agentCount', 0) * test.get('processes', 0) * test.get('threads', 0),
        'connectionReset': test.get('connectionReset'),
        'runCountPerUser': test.get('runCount'),
        'status': (test.get('status') or {}).get('name'),
        'tests': test.get('tests'), 'errors': test.get('errors'),
        'meanTestTimeMs': test.get('meanTestTime'), 'tps': test.get('tps'),
        'peakTps': test.get('peakTps'), 'runtime': test.get('runtime'),
        'scriptRevision': test.get('scriptRevision')
    })
rows.sort(key=lambda row: row['testId'])
with open(os.path.join(directory, 'summary.csv'), 'w', newline='', encoding='utf-8') as target:
    writer = csv.DictWriter(target, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
PY
}

active_test_id=''
stop_active_test() {
  if [[ -n "$active_test_id" ]]; then
    curl --silent --show-error --connect-timeout 5 --max-time 15 \
      --user "$NGRINDER_USERNAME:$NGRINDER_PASSWORD" --request PUT \
      "$controller_url/perftest/api/$active_test_id?action=stop" >/dev/null 2>&1 || true
  fi
}
trap stop_active_test EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

check_health
wait_for_idle
registered="$(api_get '/script/api')"
printf '%s' "$registered" | "$python_bin" -c '
import json,sys
available={item.get("fileName") for item in json.load(sys.stdin) if item.get("fileType")=="GROOVY_SCRIPT"}
missing=[name for name in sys.argv[1:] if name not in available]
if missing:
    print("Missing registered scripts: " + ", ".join(missing), file=sys.stderr)
    sys.exit(1)
' "${scripts[@]}" || die 'Script registration check failed.'

"$python_bin" - "$output_dir/manifest.json" "$environment" "$controller_url" \
  "$health_url" "$target_host" "$agents" "$processes" "$iterations" "$vus_csv" \
  "$failure_policy" "${scripts[@]}" <<'PY'
import datetime, json, sys
path, environment, controller, health, target, agents, processes, iterations, vus, policy, *scripts = sys.argv[1:]
manifest = {
    'startedAtUtc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'environment': environment, 'controllerUrl': controller, 'healthUrl': health,
    'targetHost': target, 'agents': int(agents), 'processesPerAgent': int(processes),
    'iterationsPerVUser': int(iterations), 'vusers': [int(item) for item in vus.split(',')],
    'scripts': scripts, 'failurePolicy': policy, 'connectionReset': False,
    'ignoreTooManyError': False, 'rampUp': False
}
with open(path, 'w', encoding='utf-8') as target_file:
    json.dump(manifest, target_file, ensure_ascii=False, indent=2)
PY

suite_failed=0
test_index=0
for script in "${scripts[@]}"; do
  script_label="${script##*/}"
  script_label="${script_label%.groovy}"
  script_label="$(printf '%s' "$script_label" | tr -c 'A-Za-z0-9_-' '_')"
  environment_label="$(printf '%s' "$environment" | tr -c 'A-Za-z0-9_-' '_')"
  for vu in "${vus[@]}"; do
    if ((test_index > 0 && cooldown_sec > 0)); then sleep "$cooldown_sec"; fi
    test_index=$((test_index + 1))
    check_health
    wait_for_idle
    threads=$((vu / agents / processes))
    stamp="$(date +%Y%m%d-%H%M%S)"
    test_name="${environment_label}-${script_label}-VUser${vu}-${stamp}"
    printf 'Starting %s: %s, VUser=%s, %s runs each\n' "$test_name" "$script" "$vu" "$iterations"

    created="$(curl --silent --show-error --fail --connect-timeout 5 --max-time 30 \
      --user "$NGRINDER_USERNAME:$NGRINDER_PASSWORD" \
      --data-urlencode "testName=$test_name" \
      --data-urlencode "description=environment=$environment; script=$script; VUser=$vu; connectionReset=false" \
      --data-urlencode "scriptName=$script" \
      --data-urlencode 'status=READY' \
      --data-urlencode 'threshold=R' \
      --data-urlencode "runCount=$iterations" \
      --data-urlencode "agentCount=$agents" \
      --data-urlencode "processes=$processes" \
      --data-urlencode "threads=$threads" \
      --data-urlencode "vuserPerAgent=$((processes * threads))" \
      --data-urlencode "targetHosts=$target_host" \
      --data-urlencode 'samplingInterval=2' \
      --data-urlencode 'useRampUp=false' \
      --data-urlencode 'connectionReset=false' \
      --data-urlencode 'ignoreTooManyError=false' \
      --data-urlencode 'ignoreSampleCount=0' \
      "$controller_url/perftest/api")" || die "Could not create $test_name"
    active_test_id="$(printf '%s' "$created" | json_value id)"
    [[ "$active_test_id" =~ ^[0-9]+$ ]] || die "Controller did not return a test ID for $test_name"
    printf '%s\n' "$created" > "$output_dir/created-$active_test_id.json"

    deadline=$((SECONDS + timeout_sec))
    config_checked=0
    finished=0
    while ((SECONDS < deadline)); do
      sleep 3
      state="$(api_get "/perftest/api/$active_test_id")"
      printf '%s\n' "$state" > "$output_dir/test-$active_test_id.json"
      if ((config_checked == 0)); then
        printf '%s' "$state" | "$python_bin" -c '
import json,sys
t=json.load(sys.stdin)
name,script,vu,agents,processes,threads,runs=sys.argv[1:]
valid=(t.get("testName")==name and t.get("scriptName")==script
       and t.get("connectionReset") is False and t.get("useRampUp") is False
       and t.get("agentCount")==int(agents) and t.get("processes")==int(processes)
       and t.get("threads")==int(threads) and t.get("vuserPerAgent")==int(processes)*int(threads)
       and int(agents)*int(processes)*int(threads)==int(vu)
       and t.get("runCount")==int(runs))
sys.exit(0 if valid else 1)
' "$test_name" "$script" "$vu" "$agents" "$processes" "$threads" "$iterations" \
          || die "Test $active_test_id has unexpected VUser/connection settings; requesting stop."
        config_checked=1
        printf 'Verified test %s: VUser=%s, connectionReset=false\n' "$active_test_id" "$vu"
      fi
      finish_time="$(printf '%s' "$state" | json_value finishTime)"
      stoppable="$(printf '%s' "$state" | json_value status.stoppable)"
      if [[ -n "$finish_time" && "$stoppable" == false ]]; then finished=1; break; fi
    done
    if ((finished == 0)); then
      write_summary
      die "Test $active_test_id exceeded $timeout_sec seconds; requesting stop."
    fi
    completed_id="$active_test_id"
    active_test_id=''
    basic_report="$(api_get "/perftest/api/$completed_id/basic_report")" \
      && printf '%s\n' "$basic_report" > "$output_dir/basic-report-$completed_id.json" || true
    write_summary
    result_line="$(printf '%s' "$state" | "$python_bin" -c '
import json,sys
t=json.load(sys.stdin)
print("{}\t{}\t{}\t{}\t{}".format(t["status"]["name"],t.get("tests") or 0,t.get("errors") or 0,t.get("meanTestTime") or 0,t.get("tps") or 0))
')"
    IFS=$'\t' read -r result_status successful errors mean_ms tps <<< "$result_line"
    printf 'Finished test %s: status=%s, successful=%s, errors=%s, mean=%s ms, TPS=%s\n' \
      "$completed_id" "$result_status" "$successful" "$errors" "$mean_ms" "$tps"
    if [[ "$result_status" != FINISHED || "$errors" != 0 || "$successful" != "$((vu * iterations))" ]]; then
      suite_failed=1
      if [[ "$failure_policy" == stop-suite ]]; then
        die "Stage $script VUser=$vu failed; subsequent tests were not started."
      fi
      printf 'Skipping higher VUser stages for %s after a failed stage.\n' "$script" >&2
      break
    fi
  done
done

printf 'Results saved to %s\n' "$output_dir"
exit "$suite_failed"
