"""Summarize individual request samples, never percentiles of interval averages."""
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else None


def summarize(directory, expected_requests, expected_workers):
    rows = []
    seen = set()
    files = sorted(directory.rglob("a*-p*-t*.csv"))
    if not files:
        raise ValueError("No worker sample CSVs found")
    workers = set()
    for file in files:
        with file.open(encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                key = tuple(row[name] for name in ("runId", "agent", "process", "thread", "iteration"))
                if key in seen:
                    raise ValueError("Duplicate worker iteration (possibly copied twice)")
                seen.add(key)
                workers.add(key[1:4])
                elapsed = float(row["elapsedMs"])
                if not math.isfinite(elapsed) or elapsed < 0 or row["success"] not in ("true", "false"):
                    raise ValueError("Invalid sample")
                row["elapsedMs"] = elapsed
                row["startedAtEpochMs"] = int(row["startedAtEpochMs"])
                rows.append(row)
    if not rows:
        raise ValueError("No completed request samples")
    identity = {(row["runId"], row["profile"]) for row in rows}
    if len(identity) != 1:
        raise ValueError("Do not combine different runs/profiles")
    manifests = []
    for file in sorted(directory.rglob("a*-p*-manifest.json")):
        manifests.append(json.loads(file.read_text(encoding="utf-8")))
    if not manifests:
        raise ValueError("Collect worker manifests along with CSVs")
    run_id, profile = identity.pop()
    configs = {(item["configSha256"], item["baseUrl"], item["connectTimeoutMs"], item["socketTimeoutMs"])
               for item in manifests}
    if len(configs) != 1 or any(item["runId"] != run_id or item["profileId"] != profile for item in manifests):
        raise ValueError("Worker configuration differs")
    manifest_workers = {(str(item["agent"]), str(item["process"])) for item in manifests}
    if not {(worker[0], worker[1]) for worker in workers}.issubset(manifest_workers):
        raise ValueError("Missing process manifest")
    successful = [row["elapsedMs"] for row in rows if row["success"] == "true"]
    failed = [row for row in rows if row["success"] == "false"]
    span_ms = max(row["startedAtEpochMs"] + row["elapsedMs"] for row in rows) - min(row["startedAtEpochMs"] for row in rows)
    complete = len(rows) == expected_requests and len(workers) == expected_workers and len(files) == expected_workers
    for worker in workers:
        iterations = sorted(int(row["iteration"]) for row in rows
                            if tuple(row[name] for name in ("agent", "process", "thread")) == worker)
        complete = complete and iterations == list(range(len(iterations)))
    if expected_requests % expected_workers == 0:
        counts = Counter(tuple(row[name] for name in ("agent", "process", "thread")) for row in rows)
        complete = complete and all(count == expected_requests // expected_workers for count in counts.values())
    result = {
        "runId": run_id, "profile": profile, "configSha256": manifests[0]["configSha256"],
        "sampleComplete": complete, "expectedRequests": expected_requests, "requests": len(rows),
        "expectedWorkers": expected_workers, "workers": len(workers),
        "successes": len(successful), "errors": len(failed), "errorRatePercent": 100 * len(failed) / len(rows),
        "failures": dict(Counter(row["failure"] for row in failed)),
        "transportFailureRoots": dict(Counter(row.get("failureRoot") for row in failed if row["httpStatus"] == "0" and row.get("failureRoot"))),
        "transportFailuresWithoutRoot": sum(row["httpStatus"] == "0" and not row.get("failureRoot") for row in failed),
        "successMeanMs": sum(successful) / len(successful) if successful else None,
        "successP50Ms": percentile(successful, .50), "successP95Ms": percentile(successful, .95),
        "successP99Ms": percentile(successful, .99),
        "observedAllP95Ms": percentile([row["elapsedMs"] for row in rows], .95),
        "sampleSpanSeconds": span_ms / 1000,
        "sampleSuccessRps": len(successful) * 1000 / span_ms if span_ms else None,
        "inputs": dict(Counter(row["inputIndex"] for row in rows)),
        "notes": ["Nearest-rank quantiles of individual GET durations; response validation and CSV I/O excluded.",
                  "Timeout durations are censored observations, not completed server response times.",
                  "RPS uses the sample time span; compare separately with Controller TPS. Synchronize Agent clocks.",
                  "Incomplete or error-containing runs do not establish safe capacity; inspect Controller status/logs."]
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Collected CSV and manifest folder for ONE test/runId")
    parser.add_argument("--expected-requests", type=int, required=True, help="VUsers * iterations per VUser")
    parser.add_argument("--expected-workers", type=int, required=True, help="Total VUsers")
    args = parser.parse_args()
    if args.expected_requests <= 0 or args.expected_workers <= 0:
        parser.error("Expected counts must be positive")
    try:
        result = summarize(args.directory, args.expected_requests, args.expected_workers)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    output = args.directory / "request-summary.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["sampleComplete"] and result["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
