#!/usr/bin/env python3
"""Summarize saved, graded model runs without estimating missing metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, stdev


def stats(values: list[float]) -> dict:
    return {
        "count": len(values),
        "mean": mean(values) if values else None,
        "stddev": stdev(values) if len(values) > 1 else None,
    }


def score(expectations: list[dict]) -> dict:
    passed = sum(item["passed"] for item in expectations)
    total = len(expectations)
    return {"passed": passed, "total": total, "pass_rate": passed / total if total else None}


def summarize(workspace: Path) -> dict:
    runs = []
    counts: dict[str, dict[str, int]] = {}
    for run_dir in sorted(workspace.glob("eval-*/*/run-*")):
        config = run_dir.parent.name
        eval_dir = run_dir.parent.parent
        metadata = json.loads((eval_dir / "eval_metadata.json").read_text())
        # Missing output or grading is an incomplete run, not a pass to omit.
        output = (run_dir / "outputs/response.md").read_text()
        grading = json.loads((run_dir / "grading.json").read_text())
        expected = {item["text"]: item["category"] for item in metadata["expectations"]}
        actual = grading["expectations"]
        if len(actual) != len(expected) or {item["text"] for item in actual} != set(expected):
            raise ValueError(f"Incomplete or duplicate grading: {run_dir}")
        for item in actual:
            if not isinstance(item["passed"], bool) or not item.get("evidence"):
                raise ValueError(f"Missing verdict or evidence: {run_dir}")
        timing_file = run_dir / "timing.json"
        timing = json.loads(timing_file.read_text()) if timing_file.exists() else {}
        tokens = timing.get("total_tokens")
        seconds = timing.get("total_duration_seconds")
        if tokens is not None and (type(tokens) is not int or tokens < 0):
            raise ValueError(f"Invalid token count: {run_dir}")
        if seconds is not None and (type(seconds) not in (int, float) or seconds < 0):
            raise ValueError(f"Invalid duration: {run_dir}")
        categories = {
            category: score([item for item in actual if expected[item["text"]] == category])
            for category in sorted(set(expected.values()))
        }
        counts.setdefault(str(metadata["eval_id"]), {}).setdefault(config, 0)
        counts[str(metadata["eval_id"])][config] += 1
        runs.append({
            "eval_id": metadata["eval_id"], "eval_name": metadata["eval_name"],
            "configuration": config, "run_number": int(run_dir.name.removeprefix("run-")),
            "result": {**score(actual), "time_seconds": seconds, "tokens": tokens,
                       "output_chars": len(output), "output_words": len(output.split())},
            "categories": categories, "expectations": actual,
        })
    if not runs:
        raise ValueError("No saved runs found")
    runs.sort(key=lambda run: (run["configuration"] != "with_skill", run["configuration"],
                               run["eval_id"], run["run_number"]))
    summaries = {}
    for config in dict.fromkeys(run["configuration"] for run in runs):
        selected = [run for run in runs if run["configuration"] == config]
        summaries[config] = {
            "runs": len(selected),
            **{metric: stats([run["result"][metric] for run in selected
                              if run["result"][metric] is not None])
               for metric in ("output_chars", "output_words", "tokens", "time_seconds")},
            "categories": {
                category: stats([run["categories"][category]["pass_rate"] for run in selected
                                 if category in run["categories"]])
                for category in sorted({cat for run in selected for cat in run["categories"]})
            },
        }
    return {
        "metadata": {"skill_name": "handoff", "evals_run": sorted(counts),
                     "runs_per_eval_configuration": counts},
        "runs": runs, "run_summary": summaries,
        "notes": ["Behavior and output quality are graded separately by model review.",
                  "Each run answers a combined scenario suite; scenarios are not independent model runs.",
                  "Characters and whitespace-delimited words are measured from response.md, not token estimates.",
                  "Missing token usage is unknown. One run cannot establish variance or reliability."],
    }


def markdown(report: dict) -> str:
    lines = ["# Handoff evaluation", "", "| Configuration | Actual suite runs | Behavior | Output quality | Words (mean) | Characters (mean) | Tokens (mean) | Seconds (mean) |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for config, summary in report["run_summary"].items():
        def metric(name: str) -> str:
            value = summary[name]["mean"]
            return "unknown" if value is None else f"{value:.1f}"

        def category(name: str) -> str:
            value = summary["categories"].get(name, {}).get("mean")
            return "unknown" if value is None else f"{value:.0%}"

        lines.append(f"| {config} | {summary['runs']} | {category('behavior')} | {category('output_quality')} | {metric('output_words')} | {metric('output_chars')} | {metric('tokens')} | {metric('time_seconds')} |")
    lines += ["", *[f"- {note}" for note in report["notes"]], ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    report = summarize(args.workspace)
    (args.workspace / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
    (args.workspace / "benchmark.md").write_text(markdown(report))


if __name__ == "__main__":
    main()
