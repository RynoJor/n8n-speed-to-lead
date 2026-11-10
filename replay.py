"""Replay the synthetic sample leads through the n8n speed-to-lead webhook.

Posts each lead in sample-leads.json to the workflow, one at a time, and writes:

* output/replay-log.csv: one row per lead, with the route and the ms per stage
* output/replay-summary.json: the headline numbers (also printed)

Two timings are recorded for each lead:

* workflow_ms: measured inside n8n, from the Settings node to the end of the alert stage
* http_ms: measured here, from sending the POST to reading the full response (end to end)

Standard library only. Usage:

    python replay.py                       # resets the demo state first, then replays
    python replay.py --no-reset            # keep the leads table from earlier runs
    python replay.py --base-url http://localhost:5678
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGES = ("validate", "dedupe", "enrich", "score", "assign", "alert")


def post(url: str, payload: dict) -> tuple[int, dict, float]:
    """POST JSON, return (http status, parsed body, round-trip ms)."""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:  # 422 for a rejected lead is expected
        status, raw = e.code, e.read()
    ms = (time.perf_counter() - t) * 1000
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        body = {"raw": raw.decode(errors="replace")}
    return status, body, ms


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://localhost:5678")
    ap.add_argument("--leads", default=str(HERE / "sample-leads.json"))
    ap.add_argument("--out-dir", default=str(HERE / "output"))
    ap.add_argument("--no-reset", action="store_true", help="don't reset the demo state first")
    args = ap.parse_args(argv)

    leads = json.loads(Path(args.leads).read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.no_reset:
        status, body, _ = post(f"{args.base_url}/webhook/speed-to-lead-reset", {})
        if status != 200:
            raise SystemExit(f"reset failed: HTTP {status} {body}")

    rows = []
    for lead in leads:
        status, res, http_ms = post(f"{args.base_url}/webhook/speed-to-lead", lead)
        stage_ms = res.get("stage_ms", {})
        rows.append({
            "lead_id": lead.get("lead_id", ""),
            "http_status": status,
            "status": res.get("status", "error"),
            "assigned_rep": res.get("assigned_rep", ""),
            "rep_name": res.get("rep_name", ""),
            "assign_reason": res.get("assign_reason", ""),
            "score": res.get("score", ""),
            "dedupe_hit": res.get("dedupe_hit", False),
            "dedupe_match": res.get("dedupe_match", ""),
            "flags": ";".join(res.get("flags", [])),
            **{f"{s}_ms": stage_ms.get(s, "") for s in STAGES},
            "workflow_ms": res.get("total_ms", ""),
            "http_ms": round(http_ms, 2),
        })
        r = rows[-1]
        print(f"{r['lead_id']}: {r['status']:<8} {r['assigned_rep'] or '-':<4} "
              f"{r['assign_reason'] or r['flags']:<38} workflow {r['workflow_ms']} ms, "
              f"http {r['http_ms']} ms")

    with open(out_dir / "replay-log.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    routed = [r for r in rows if r["status"] == "routed"]
    http = [r["http_ms"] for r in rows]
    wf = [r["workflow_ms"] for r in routed]
    summary = {
        "leads": len(rows),
        "routed": len(routed),
        "rejected": sum(r["status"] == "rejected" for r in rows),
        "errors": sum(r["status"] not in ("routed", "rejected") for r in rows),
        "dedupe_hits": sum(bool(r["dedupe_hit"]) for r in routed),
        "end_to_end_ms_median": round(statistics.median(http), 1),
        "end_to_end_ms_max": round(max(http), 1),
        "routed_workflow_ms_median": round(statistics.median(wf), 1) if wf else None,
        "routed_workflow_ms_max": round(max(wf), 1) if wf else None,
        "stage_ms_median": {
            s: round(statistics.median(float(r[f"{s}_ms"]) for r in routed), 2) for s in STAGES
        } if routed else {},
    }
    (out_dir / "replay-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"\n{summary['leads']} leads: {summary['routed']} routed, {summary['rejected']} rejected, "
          f"{summary['dedupe_hits']} dedupe hits, {summary['errors']} errors")
    print(f"End to end (HTTP POST to response): median {summary['end_to_end_ms_median']} ms, "
          f"max {summary['end_to_end_ms_max']} ms")
    print(f"Inside n8n, routed leads: median {summary['routed_workflow_ms_median']} ms")
    print(f"Median ms per stage: {summary['stage_ms_median']}")
    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
