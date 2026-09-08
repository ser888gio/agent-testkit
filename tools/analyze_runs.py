#!/usr/bin/env python3
"""Summarize agentaudit run history from the SQLite store.

Usage:
    python tools/analyze_runs.py [--db PATH] [--org ORG_ID] [--format text|csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path


def load_runs(con: sqlite3.Connection, org_id: str | None) -> list[dict]:
    query = "SELECT id, org_id, agent_id, started_at, finished_at, status, score_json FROM runs"
    params: tuple = ()
    if org_id:
        query += " WHERE org_id = ?"
        params = (org_id,)
    cur = con.execute(query, params)
    rows = []
    for id_, org, agent_id, started_at, finished_at, status, score_json in cur.fetchall():
        score = json.loads(score_json) if score_json else {}
        rows.append(
            {
                "id": id_,
                "org_id": org,
                "agent_id": agent_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "status": status,
                "overall_score": score.get("overall_score"),
                "pass_rate": score.get("pass_rate"),
                "critical_failures": score.get("critical_failures"),
                "flaky": score.get("flaky"),
                "gate_passed": score.get("gate_passed"),
            }
        )
    return rows


def load_test_results(con: sqlite3.Connection, org_id: str | None) -> list[dict]:
    has_origin = "origin" in {row[1] for row in con.execute("PRAGMA table_info(test_results)")}
    origin_col = "origin" if has_origin else "'authored' AS origin"
    query = (
        f"SELECT run_id, org_id, test_id, category, risk, status, latency_ms, {origin_col} "
        "FROM test_results"
    )
    params: tuple = ()
    if org_id:
        query += " WHERE org_id = ?"
        params = (org_id,)
    cur = con.execute(query, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def summarize(runs: list[dict], results: list[dict]) -> dict:
    by_agent = defaultdict(list)
    for r in runs:
        by_agent[r["agent_id"]].append(r)

    agent_summary = {}
    for agent_id, agent_runs in by_agent.items():
        scores = [r["overall_score"] for r in agent_runs if r["overall_score"] is not None]
        agent_summary[agent_id] = {
            "runs": len(agent_runs),
            "avg_score": sum(scores) / len(scores) if scores else None,
            "min_score": min(scores) if scores else None,
            "max_score": max(scores) if scores else None,
            "gate_failures": sum(1 for r in agent_runs if r["gate_passed"] is False),
        }

    by_category = defaultdict(lambda: {"passed": 0, "total": 0, "latencies": []})
    for t in results:
        cat = by_category[t["category"]]
        cat["total"] += 1
        if t["status"] == "passed":
            cat["passed"] += 1
        if t["latency_ms"] is not None:
            cat["latencies"].append(t["latency_ms"])

    category_summary = {}
    for cat, data in by_category.items():
        latencies = data["latencies"]
        category_summary[cat] = {
            "total": data["total"],
            "passed": data["passed"],
            "pass_rate": data["passed"] / data["total"] if data["total"] else None,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else None,
        }

    by_origin = defaultdict(lambda: {"passed": 0, "total": 0})
    for t in results:
        o = by_origin[t["origin"]]
        o["total"] += 1
        if t["status"] == "passed":
            o["passed"] += 1

    origin_summary = {
        origin: {
            "total": data["total"],
            "passed": data["passed"],
            "pass_rate": data["passed"] / data["total"] if data["total"] else None,
        }
        for origin, data in by_origin.items()
    }

    slowest = sorted(
        (t for t in results if t["latency_ms"] is not None),
        key=lambda t: t["latency_ms"],
        reverse=True,
    )[:10]

    failing = [t for t in results if t["status"] not in ("passed", "skipped")]

    return {
        "agent_summary": agent_summary,
        "category_summary": category_summary,
        "origin_summary": origin_summary,
        "slowest_tests": slowest,
        "failing_tests": failing,
    }


def print_text_report(runs: list[dict], results: list[dict], summary: dict) -> None:
    print(f"Runs: {len(runs)}    Test results: {len(results)}\n")

    print("=== By agent ===")
    for agent_id, s in sorted(summary["agent_summary"].items()):
        avg = f"{s['avg_score']:.2f}" if s["avg_score"] is not None else "n/a"
        print(
            f"  {agent_id:<30} runs={s['runs']:<4} avg_score={avg} "
            f"min={s['min_score']} max={s['max_score']} gate_failures={s['gate_failures']}"
        )

    print("\n=== By category ===")
    for cat, s in sorted(summary["category_summary"].items()):
        pr = f"{s['pass_rate']:.0%}" if s["pass_rate"] is not None else "n/a"
        lat = f"{s['avg_latency_ms']:.1f}ms" if s["avg_latency_ms"] is not None else "n/a"
        print(f"  {cat:<25} total={s['total']:<5} pass_rate={pr:<6} avg_latency={lat}")

    print("\n=== By origin (authored/generated/promoted) ===")
    for origin, s in sorted(summary["origin_summary"].items()):
        pr = f"{s['pass_rate']:.0%}" if s["pass_rate"] is not None else "n/a"
        print(f"  {origin:<12} total={s['total']:<5} pass_rate={pr}")

    print("\n=== Slowest tests ===")
    for t in summary["slowest_tests"]:
        print(f"  {t['latency_ms']:.1f}ms  {t['test_id']} ({t['run_id'][:8]})")

    print(f"\n=== Failing/error tests ({len(summary['failing_tests'])}) ===")
    for t in summary["failing_tests"][:20]:
        print(f"  {t['status']:<10} {t['test_id']} ({t['run_id'][:8]})")
    if len(summary["failing_tests"]) > 20:
        print(f"  ... and {len(summary['failing_tests']) - 20} more")


def write_csv_reports(out_dir: Path, runs: list[dict], results: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "runs.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(runs[0].keys()) if runs else [])
        writer.writeheader()
        writer.writerows(runs)

    with open(out_dir / "test_results.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()) if results else [])
        writer.writeheader()
        writer.writerows(results)

    print(f"Wrote {out_dir / 'runs.csv'} and {out_dir / 'test_results.csv'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="database/agentaudit.db", help="Path to agentaudit.db")
    parser.add_argument("--org", default=None, help="Filter to a single org_id")
    parser.add_argument(
        "--format", choices=["text", "csv"], default="text", help="Output format (default: text)"
    )
    parser.add_argument(
        "--out", default="analysis_out", help="Output directory for --format csv"
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"error: no database at {db_path}", file=sys.stderr)
        return 1

    con = sqlite3.connect(str(db_path))
    try:
        runs = load_runs(con, args.org)
        results = load_test_results(con, args.org)
    finally:
        con.close()

    if not runs:
        print("No runs found.")
        return 0

    if args.format == "csv":
        write_csv_reports(Path(args.out), runs, results)
    else:
        summary = summarize(runs, results)
        print_text_report(runs, results, summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
