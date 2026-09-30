"""Summarize nGrinder repeat results and Prometheus/Agent resource samples.

Run after all tests finish. Uses only Python's standard library.
"""

import csv
import json
import math
import statistics
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PROMETHEUS = "http://localhost:9090/api/v1/query_range"
METRICS = {
    "processCpu": "process_cpu_usage",
    "systemCpu": "system_cpu_usage",
    "heapBytes": 'sum(jvm_memory_used_bytes{area="heap"})',
    "hikariActive": "hikaricp_connections_active",
    "hikariPending": "hikaricp_connections_pending",
    "boardRps": 'sum(rate(http_server_requests_seconds_count{uri="/roommate/boards"}[30s]))',
    "boardServerMeanSeconds": 'sum(rate(http_server_requests_seconds_sum{uri="/roommate/boards"}[30s])) / sum(rate(http_server_requests_seconds_count{uri="/roommate/boards"}[30s]))',
}


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    lower, upper = math.floor(index), math.ceil(index)
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def prom_samples(query, start, end):
    params = urllib.parse.urlencode({
        "query": query, "start": math.floor(start), "end": math.ceil(end), "step": "5s"
    })
    with urllib.request.urlopen(f"{PROMETHEUS}?{params}", timeout=30) as response:
        payload = json.load(response)
    if payload["status"] != "success":
        raise RuntimeError(payload)
    values = []
    for series in payload["data"]["result"]:
        for stamp, raw in series["values"]:
            value = float(raw)
            if math.isfinite(value):
                values.append([stamp, value])
    return values


def agent_samples():
    path = ROOT / "agent-stats.psv"
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as source:
        for row in csv.DictReader(source, delimiter="|"):
            try:
                stamp = datetime.fromisoformat(row["utc"]).timestamp()
                cpu = float(row["cpu"].rstrip("%"))
                used, unit = row["memory"].split(" / ")[0][:-3], row["memory"].split(" / ")[0][-3:]
                memory_mib = float(used) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}.get(unit, float("nan"))
                rows.append({"stamp": stamp, "container": row["container"], "cpuPct": cpu, "memoryMiB": memory_mib})
            except (ValueError, TypeError, KeyError):
                continue
    return rows


def main():
    agents = agent_samples()
    agent_map = json.loads((ROOT / "agent-container-map.json").read_text(encoding="utf-8"))
    results = []
    raw_metrics = {}
    for path in sorted(ROOT.glob("**/test-*.json")):
        test = json.loads(path.read_text(encoding="utf-8"))
        if not test.get("finishTime"):
            continue
        test_id = test["id"]
        start, end = test["startTime"] / 1000, test["finishTime"] / 1000
        csv_path = path.with_name(f"intervals-{test_id}.csv")
        intervals = []
        if csv_path.exists():
            with csv_path.open(encoding="utf-8-sig", newline="") as source:
                intervals = list(csv.DictReader(source))
        interval_means = [float(row["Mean_Test_Time_(ms)"]) for row in intervals if int(row["Tests"]) > 0]
        metrics = {name: prom_samples(query, start, end) for name, query in METRICS.items()}
        raw_metrics[str(test_id)] = metrics
        report_path = path.with_name(f"basic-report-{test_id}.json")
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        agent_id = (report.get("logs") or [""])[0].split("--")[0]
        agent_container = agent_map.get(agent_id)
        stage_agents = [row for row in agents if start <= row["stamp"] <= end and row["container"] == agent_container]
        summary = {
            "testId": test_id,
            "round": path.parent.name,
            "vusers": test["threads"] * test["processes"] * test["agentCount"],
            "startUtc": datetime.fromtimestamp(start, timezone.utc).isoformat(),
            "durationSeconds": round(end - start, 1),
            "status": test["status"]["name"],
            "successes": test["tests"],
            "errors": test["errors"],
            "errorPercent": round(100 * test["errors"] / max(1, test["tests"] + test["errors"]), 2),
            "meanMs": test["meanTestTime"],
            "tps": test["tps"],
            "intervalMeanP50Ms": round(percentile(interval_means, .5), 1) if interval_means else None,
            "intervalMeanP95Ms": round(percentile(interval_means, .95), 1) if interval_means else None,
            "intervalMeanMaxMs": round(max(interval_means), 1) if interval_means else None,
            "agentContainer": agent_container,
            "agentSamples": len(stage_agents),
            "agentMaxCpuPct": round(max((r["cpuPct"] for r in stage_agents), default=float("nan")), 2),
            "agentMaxMemoryMiB": round(max((r["memoryMiB"] for r in stage_agents), default=float("nan")), 1),
        }
        for name, samples in metrics.items():
            values = [item[1] for item in samples]
            summary[f"{name}Mean"] = round(statistics.mean(values), 4) if values else None
            summary[f"{name}Max"] = round(max(values), 4) if values else None
            summary[f"{name}Samples"] = len(values)
        results.append(summary)
    (ROOT / "analysis.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (ROOT / "prometheus-samples.json").write_text(json.dumps(raw_metrics), encoding="utf-8")
    if results:
        with (ROOT / "analysis.csv").open("w", newline="", encoding="utf-8") as dest:
            writer = csv.DictWriter(dest, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
    print(f"Analyzed {len(results)} tests")


if __name__ == "__main__":
    main()
