from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .deep_support import DEEP_STAGES, WORD_SOLVER_DEPTH


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def _window(points: object) -> dict[str, Any]:
    records = (
        [item for item in points if isinstance(item, Mapping)]
        if isinstance(points, Sequence) and not isinstance(points, (str, bytes))
        else []
    )
    evaluations = sum(int(item.get("evaluations", 0)) for item in records)
    depth_sum = sum(float(item.get("depth_sum", 0.0)) for item in records)
    reached_word = sum(int(item.get("reached_word_solver", 0)) for item in records)
    reached_metric = sum(int(item.get("reached_first_metric_step", 0)) for item in records)
    return {
        "generations": len(records),
        "evaluations": evaluations,
        "mean_depth": depth_sum / evaluations if evaluations else None,
        "first_metric_rate": reached_metric / evaluations if evaluations else None,
        "word_solver_count": reached_word,
    }


def _bootstrap_summary(output: Path) -> dict[str, Any]:
    path = output / "bootstrap.jsonl"
    records: list[dict[str, Any]] = []
    if path.exists():
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    records.append(payload)
    failures: dict[str, int] = {}
    statuses: dict[str, int] = {}
    reached = {name: 0 for name in DEEP_STAGES}
    diagnostic_errors = 0
    max_depth = 0
    for item in records:
        status = str(item.get("status", "unknown"))
        statuses[status] = statuses.get(status, 0) + 1
        failure = str(item.get("deep_failure", "unknown"))
        failures[failure] = failures.get(failure, 0) + 1
        diagnostics = item.get("diagnostics", {})
        if isinstance(diagnostics, Mapping) and "diagnostic_error" in diagnostics:
            diagnostic_errors += 1
        depth = max(0, min(len(DEEP_STAGES) - 1, int(item.get("deep_depth", 0))))
        max_depth = max(max_depth, depth)
        for index, name in enumerate(DEEP_STAGES):
            if depth >= index:
                reached[name] += 1
    return {
        "records": len(records),
        "diagnostic_errors": diagnostic_errors,
        "max_depth": max_depth,
        "max_stage": DEEP_STAGES[max_depth],
        "status_histogram": dict(sorted(statuses.items())),
        "failure_histogram": dict(
            sorted(failures.items(), key=lambda pair: (-pair[1], pair[0]))
        ),
        "depth_reached_counts": reached,
    }


def _conditional_rates(reached: Mapping[str, int], evaluations: int) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    previous = evaluations
    for name in DEEP_STAGES:
        count = int(reached.get(name, 0))
        result[name] = count / previous if previous else None
        previous = count
    return result


def build_deep_report(output: Path, arms: Sequence[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for arm in arms:
        directory = output / "arms" / arm
        stats = _load(directory / "stats.json")
        metrics = _load(directory / "metrics.json")
        evaluations = int(stats.get("evaluations", 0))
        reached = {
            str(key): int(value)
            for key, value in dict(stats.get("depth_reached_counts", {})).items()
        }
        timing = dict(stats.get("timing_seconds", {}))
        total_seconds = float(timing.get("total", 0.0))
        raw_trend = stats.get("trend", {})
        trend = dict(raw_trend) if isinstance(raw_trend, Mapping) else {}
        initial = _window(trend.get("initial", []))
        recent = _window(trend.get("recent", []))
        raw_repair = stats.get("repair", {})
        repair = dict(raw_repair) if isinstance(raw_repair, Mapping) else {}
        repair_attempted = int(repair.get("attempted", 0))
        score_compared = int(repair.get("score_compared", 0))
        result[arm] = {
            "evaluations": evaluations,
            "timeouts": int(stats.get("timeouts", 0)),
            "errors": int(stats.get("errors", 0)),
            "mean_depth": (
                float(stats.get("depth_sum", 0.0)) / evaluations
                if evaluations
                else 0.0
            ),
            "max_depth": int(stats.get("max_depth", 0)),
            "max_stage": DEEP_STAGES[int(stats.get("max_depth", 0))],
            "depth_reached_counts": reached,
            "depth_reached_rates": {
                name: count / evaluations if evaluations else None
                for name, count in reached.items()
            },
            "depth_conditional_rates": _conditional_rates(reached, evaluations),
            "curriculum_failure_histogram": stats.get(
                "curriculum_failure_histogram", {}
            ),
            "strategy_histogram": stats.get("strategy_histogram", {}),
            "sampling": stats.get("sampling", {}),
            "repair": {
                **repair,
                "topology_retention_rate": (
                    int(repair.get("probe_topology_retained", 0))
                    / repair_attempted
                    if repair_attempted
                    else None
                ),
                "depth_nonregression_rate": (
                    (
                        int(repair.get("improved", 0))
                        + int(repair.get("same", 0))
                    )
                    / repair_attempted
                    if repair_attempted
                    else None
                ),
                "score_improvement_rate": (
                    int(repair.get("score_improved", 0)) / score_compared
                    if score_compared
                    else None
                ),
                "mean_score_delta": (
                    float(repair.get("score_delta_sum", 0.0)) / score_compared
                    if score_compared
                    else None
                ),
            },
            "timing_seconds": timing,
            "deep_candidates_per_total_hour": (
                3600.0 * reached.get("preword_positive_lengths", 0) / total_seconds
                if total_seconds > 0
                else None
            ),
            "word_candidates_per_total_hour": (
                3600.0 * reached.get("word_solver", 0) / total_seconds
                if total_seconds > 0
                else None
            ),
            "trend": {
                "initial": initial,
                "recent": recent,
                "mean_depth_delta": (
                    recent["mean_depth"] - initial["mean_depth"]
                    if recent["mean_depth"] is not None
                    and initial["mean_depth"] is not None
                    else None
                ),
            },
            "model": metrics,
        }

    baseline = result.get("uniform")
    comparisons: dict[str, dict[str, Any]] = {}
    for arm, item in result.items():
        if arm == "uniform" or baseline is None:
            continue
        word_count = int(item["depth_reached_counts"].get("word_solver", 0))
        baseline_word = int(
            baseline["depth_reached_counts"].get("word_solver", 0)
        )
        metric_count = int(
            item["depth_reached_counts"].get("preword_positive_lengths", 0)
        )
        baseline_metric = int(
            baseline["depth_reached_counts"].get("preword_positive_lengths", 0)
        )
        repair = item["repair"]
        repair_attempts = int(repair.get("attempted", 0))
        repair_improved = int(repair.get("improved", 0))
        if word_count > 0:
            verdict = "breakthrough_word_solver_reached"
        elif metric_count > baseline_metric:
            verdict = "breakthrough_positive_lengths_reached"
        elif repair_attempts >= 100 and repair_improved == 0:
            verdict = "repair_neighborhood_not_improving"
        elif item["max_depth"] > baseline["max_depth"]:
            verdict = "promising_deeper_curriculum"
        elif (
            metric_count > baseline_metric
            and item["trend"]["mean_depth_delta"] is not None
            and item["trend"]["mean_depth_delta"] >= 0
        ):
            verdict = "promising_stable_enrichment"
        else:
            verdict = "no_deep_advantage_yet"
        comparisons[arm] = {
            "mean_depth_uplift_vs_uniform": (
                item["mean_depth"] - baseline["mean_depth"]
            ),
            "first_metric_count_uplift_vs_uniform": metric_count - baseline_metric,
            "word_solver_count_uplift_vs_uniform": word_count - baseline_word,
            "verdict": verdict,
        }
    return {
        "schema_version": "mapping-lab-deep-report-v2",
        "stage_names": list(DEEP_STAGES),
        "word_solver_depth": WORD_SOLVER_DEPTH,
        "bootstrap": _bootstrap_summary(output),
        "arms": result,
        "comparisons": comparisons,
        "decision_rule": (
            "A repair method wins by producing formally evaluated positive-length survivors, "
            "then later curriculum or word candidates. Topology retention and "
            "graded LP-score improvement diagnose the generator; AUC and mean "
            "depth alone are not success criteria."
        ),
    }


def write_deep_report(output: Path, arms: Sequence[str]) -> dict[str, Any]:
    report = build_deep_report(output, arms)
    json_path = output / "report.json"
    temporary = json_path.with_name(f"{json_path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(json_path)

    lines = [
        "# Deep Mapping Lab report",
        "",
        "## Recovered prior deep candidates",
        "",
        f"Recovered records: {report['bootstrap']['records']}; "
        f"diagnostic errors: {report['bootstrap']['diagnostic_errors']}; "
        f"deepest exact stage: `{report['bootstrap']['max_stage']}`.",
        "",
        "| first failed stage | candidates |",
        "|---|---:|",
    ]
    for name, count in report["bootstrap"]["failure_histogram"].items():
        lines.append(f"| {name} | {count} |")
    lines.extend([
        "",
        "## Method comparison",
        "",
        "| arm | evaluations | mean depth | max stage | positive length | topology retained | score improved | word solver | verdict |",
        "|---|---:|---:|---|---:|---:|---:|---:|---|",
    ])
    for arm, item in report["arms"].items():
        comparison = report["comparisons"].get(arm, {})
        reached = item["depth_reached_counts"]
        repair = item["repair"]
        topology_rate = repair.get("topology_retention_rate")
        score_rate = repair.get("score_improvement_rate")
        lines.append(
            f"| {arm} | {item['evaluations']} | {item['mean_depth']:.4f} | "
            f"{item['max_stage']} | {reached.get('preword_positive_lengths', 0)} | "
            f"{f'{topology_rate:.3%}' if topology_rate is not None else 'n/a'} | "
            f"{f'{score_rate:.3%}' if score_rate is not None else 'n/a'} | "
            f"{reached.get('word_solver', 0)} | "
            f"{comparison.get('verdict', 'baseline')} |"
        )
    lines.extend(["", "## Exact curriculum", ""])
    lines.append(
        "| stage reached | "
        + " | ".join(f"{arm}: count (P(pass | previous))" for arm in report["arms"])
        + " |"
    )
    lines.append("|---|" + "---:|" * len(report["arms"]))
    for stage in DEEP_STAGES[8:]:
        values = []
        for arm in report["arms"]:
            count = report["arms"][arm]["depth_reached_counts"].get(stage, 0)
            rate = report["arms"][arm]["depth_conditional_rates"].get(stage)
            values.append(
                f"{count} ({rate:.3%})" if rate is not None else f"{count} (n/a)"
            )
        lines.append(f"| {stage} | " + " | ".join(values) + " |")
    lines.extend(["", "## First curriculum failures", ""])
    for arm, item in report["arms"].items():
        lines.append(f"### {arm}")
        lines.append("")
        failures = sorted(
            item["curriculum_failure_histogram"].items(),
            key=lambda pair: -int(pair[1]),
        )
        for name, count in failures[:12]:
            lines.append(f"- `{name}`: {count}")
        lines.append("")
    lines.extend(["## Repair operators", ""])
    for arm, item in report["arms"].items():
        repair = item["repair"]
        lines.append(f"### {arm}")
        lines.append("")
        lines.append(
            f"Attempts: {int(repair.get('attempted', 0))}; "
            f"depth improvements: {int(repair.get('improved', 0))}; "
            f"proposal-only positive-length LP witnesses: "
            f"{int(repair.get('probe_positive_lengths', 0))}."
        )
        attempts = dict(repair.get("operator_attempts", {}))
        nonregressions = dict(repair.get("operator_nonregressions", {}))
        score_compared = dict(repair.get("operator_score_compared", {}))
        score_improvements = dict(
            repair.get("operator_score_improvements", {})
        )
        positive_lengths = dict(
            repair.get("operator_positive_lengths", {})
        )
        for operator, count in sorted(attempts.items()):
            compared = int(score_compared.get(operator, 0))
            improved = int(score_improvements.get(operator, 0))
            lines.append(
                f"- `{operator}`: {int(count)} attempts, "
                f"{int(nonregressions.get(operator, 0))} depth non-regressions, "
                f"{improved}/{compared} LP-score improvements, "
                f"{int(positive_lengths.get(operator, 0))} LP witnesses"
            )
        lines.append("")
    markdown = output / "report.md"
    temporary = markdown.with_name(f"{markdown.name}.{os.getpid()}.tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(markdown)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate the deep experiment report")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument(
        "--arms",
        default="uniform,local_topology,length_repair",
    )
    args = parser.parse_args(argv)
    arms = tuple(value.strip() for value in args.arms.split(",") if value.strip())
    report = write_deep_report(args.input.resolve(), arms)
    print(json.dumps(report["comparisons"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
