from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .evaluator import GraphEvaluation
from .mapping import MappingEvaluation, MappingProposal
from .space import DualGraphCandidate
from .weak_model import WeakOrderRolloutObservation


def weak_trajectory_id(rollout: WeakOrderRolloutObservation) -> str:
    """Identify one exact mapping + weak-order decision path."""

    masks = ",".join(str(decision.action.mask) for decision in rollout.decisions)
    payload = f"{rollout.proposal.mapping_id}|{masks}".encode("ascii")
    return "wr-" + hashlib.sha256(payload).hexdigest()[:24]


def _graph_bin(candidate: DualGraphCandidate) -> str:
    return (
        f"tiles={candidate.tile_count}|edges={candidate.edge_count}|"
        f"sym={candidate.symmetry_order}"
    )


def _mapping_bin(proposal: MappingProposal) -> str:
    reflected = sum(value < 0 for value in proposal.orientation_signs)
    shifted = sum(value != 0 for value in proposal.cyclic_offsets)
    return (
        f"tiles={proposal.candidate.tile_count}|reflected={reflected}|"
        f"shifted={shifted}"
    )


def _selection_level(
    proposed: Sequence[object],
    selected: Sequence[object],
    *,
    proposed_id,
    selected_id,
    proposed_bin,
    selected_bin,
    seen_ids: set[str],
    modes: Iterable[str],
) -> dict[str, object]:
    proposed_ids = [str(proposed_id(item)) for item in proposed]
    selected_ids = [str(selected_id(item)) for item in selected]
    proposed_id_set = set(proposed_ids)
    selected_counts = Counter(selected_ids)
    selected_from_pool = sum(value in proposed_id_set for value in selected_ids)
    return {
        "proposals": {
            "count": len(proposed_ids),
            "unique": len(proposed_id_set),
            "bins": dict(Counter(str(proposed_bin(item)) for item in proposed)),
        },
        "rollouts": {
            "count": len(selected_ids),
            "unique": len(selected_counts),
            # Selected identifiers are deliberately compact enough to retain.
            # They let the offline audit measure concentration and revisits
            # without retaining every rejected proposal.
            "id_counts": dict(selected_counts),
            "bins": dict(Counter(str(selected_bin(item)) for item in selected)),
            "new_unique_ids": sum(value not in seen_ids for value in selected_counts),
            "historical_revisit_visits": sum(
                count for value, count in selected_counts.items() if value in seen_ids
            ),
            "within_generation_repeat_visits": sum(
                max(0, count - 1) for count in selected_counts.values()
            ),
            "selection_modes": dict(Counter(str(mode) for mode in modes)),
        },
        "selected_from_current_pool": selected_from_pool,
        "locally_not_selected": max(0, len(proposed_ids) - selected_from_pool),
        "permanently_closed": 0,
    }


def build_generation_coverage(
    generation: int,
    *,
    graph_pool: Sequence[DualGraphCandidate],
    graph_records: Sequence[tuple[GraphEvaluation, Mapping[str, object]]],
    mapping_pool: Sequence[MappingProposal],
    mapping_records: Sequence[tuple[MappingEvaluation, Mapping[str, object]]],
    weak_rollouts: Sequence[WeakOrderRolloutObservation],
    seen_graph_ids: set[str],
    seen_mapping_ids: set[str],
    seen_trajectory_ids: set[str],
) -> dict[str, object]:
    graph_evaluations = [record[0] for record in graph_records]
    mapping_evaluations = [record[0] for record in mapping_records]
    graph = _selection_level(
        graph_pool,
        graph_evaluations,
        proposed_id=lambda item: item.graph_id,
        selected_id=lambda item: item.candidate.graph_id,
        proposed_bin=_graph_bin,
        selected_bin=lambda item: _graph_bin(item.candidate),
        seen_ids=seen_graph_ids,
        modes=(
            str(
                selection.get(
                    "selection_mode",
                    "known_control"
                    if selection.get("selection") == "known_control"
                    else "unknown",
                )
            )
            for _evaluation, selection in graph_records
        ),
    )
    mapping = _selection_level(
        mapping_pool,
        mapping_evaluations,
        proposed_id=lambda item: item.mapping_id,
        selected_id=lambda item: item.proposal.mapping_id,
        proposed_bin=_mapping_bin,
        selected_bin=lambda item: _mapping_bin(item.proposal),
        seen_ids=seen_mapping_ids,
        modes=(
            str(selection.get("selection_mode", "unknown"))
            for _evaluation, selection in mapping_records
        ),
    )

    trajectory_ids = [weak_trajectory_id(item) for item in weak_rollouts]
    trajectory_counts = Counter(trajectory_ids)
    decisions = [
        decision for rollout in weak_rollouts for decision in rollout.decisions
    ]
    legal_masks = sum(
        max(decision.candidate_count, decision.legal_mask_count)
        for decision in decisions
    )
    pooled_masks = sum(
        max(decision.candidate_count, decision.pooled_mask_count)
        for decision in decisions
    )
    viable_actions = sum(decision.candidate_count for decision in decisions)

    progress_bins: Counter[str] = Counter()
    action_size_bins: Counter[str] = Counter()
    candidate_count_bins: Counter[str] = Counter()
    for decision in decisions:
        total = max(1, decision.state.total_occurrences)
        progress = min(3, 4 * decision.state.placed_occurrences // total)
        progress_bins[f"q{progress + 1}"] += 1
        action_size_bins[str(decision.action.selected_count)] += 1
        count = decision.candidate_count
        candidate_count_bins[
            "1" if count == 1 else "2-8" if count <= 8 else "9-32" if count <= 32 else "33+"
        ] += 1

    weak = {
        "rollouts": {
            "count": len(weak_rollouts),
            "unique": len(trajectory_counts),
            "id_counts": dict(trajectory_counts),
            "new_unique_ids": sum(
                value not in seen_trajectory_ids for value in trajectory_counts
            ),
            "historical_revisit_visits": sum(
                count
                for value, count in trajectory_counts.items()
                if value in seen_trajectory_ids
            ),
            "within_generation_repeat_visits": sum(
                max(0, count - 1) for count in trajectory_counts.values()
            ),
            "without_policy_decision": sum(
                not rollout.decisions for rollout in weak_rollouts
            ),
            "selection_modes": dict(
                Counter(rollout.selection_mode for rollout in weak_rollouts)
            ),
        },
        "decision_funnel": {
            "decisions": len(decisions),
            "legal_masks": legal_masks,
            "pooled_masks": pooled_masks,
            "viable_actions": viable_actions,
            "selected_actions": len(decisions),
            "omitted_by_bounded_random_pool": max(0, legal_masks - pooled_masks),
            "rejected_by_existing_prefix_filters": max(
                0, pooled_masks - viable_actions
            ),
            "locally_not_selected_by_policy": max(
                0, viable_actions - len(decisions)
            ),
            "pool_limit_hit_decisions": sum(
                decision.legal_mask_count > decision.pooled_mask_count
                for decision in decisions
            ),
            "mean_selected_probability": (
                sum(decision.selection_probability for decision in decisions)
                / len(decisions)
                if decisions
                else None
            ),
            "mean_uniform_probability": (
                sum(1.0 / max(1, decision.candidate_count) for decision in decisions)
                / len(decisions)
                if decisions
                else None
            ),
            "progress_bins": dict(progress_bins),
            "selected_block_size_bins": dict(action_size_bins),
            "viable_action_count_bins": dict(candidate_count_bins),
            "selection_modes": dict(
                Counter(decision.selection_mode for decision in decisions)
            ),
        },
        "permanently_closed": 0,
    }

    return {
        "schema_version": "graph-lab-rollout-coverage-v1",
        "generation": generation,
        "semantics": {
            "graph_revisits_enabled": True,
            "mapping_revisits_enabled": True,
            "weak_order_revisits_enabled": True,
            "exact_weak_order_deduplication": False,
            "local_nonselection_is_permanent": False,
        },
        "levels": {"graph": graph, "mapping": mapping, "weak_order": weak},
    }


def _load(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                # A live writer may be between the write and flush of its last
                # line. The next refresh will see the complete generation.
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _merge_counts(rows: Sequence[Mapping[str, Any]], path: Sequence[str]) -> Counter[str]:
    result: Counter[str] = Counter()
    for row in rows:
        value: object = row
        for key in path:
            value = value.get(key, {}) if isinstance(value, Mapping) else {}
        if isinstance(value, Mapping):
            result.update({str(key): int(count) for key, count in value.items()})
    return result


def _sum(rows: Sequence[Mapping[str, Any]], path: Sequence[str]) -> int:
    total = 0
    for row in rows:
        value: object = row
        for key in path:
            value = value.get(key, 0) if isinstance(value, Mapping) else 0
        total += int(value or 0)
    return total


def _distribution_summary(counts: Counter[str]) -> dict[str, object]:
    total = sum(counts.values())
    if not total:
        return {"total": 0, "unique": 0, "top_share": None, "effective_ids": 0.0}
    probabilities = [count / total for count in counts.values()]
    entropy = -sum(value * math.log(value) for value in probabilities)
    return {
        "total": total,
        "unique": len(counts),
        "top_share": max(counts.values()) / total,
        "effective_ids": math.exp(entropy),
    }


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    levels: dict[str, object] = {}
    for level in ("graph", "mapping"):
        ids = _merge_counts(rows, ("levels", level, "rollouts", "id_counts"))
        levels[level] = {
            **_distribution_summary(ids),
            "proposed": _sum(rows, ("levels", level, "proposals", "count")),
            "proposed_unique_per_generation": _sum(
                rows, ("levels", level, "proposals", "unique")
            ),
            "new_unique_ids": _sum(
                rows, ("levels", level, "rollouts", "new_unique_ids")
            ),
            "historical_revisit_visits": _sum(
                rows,
                ("levels", level, "rollouts", "historical_revisit_visits"),
            ),
            "within_generation_repeat_visits": _sum(
                rows,
                ("levels", level, "rollouts", "within_generation_repeat_visits"),
            ),
            "locally_not_selected": _sum(
                rows, ("levels", level, "locally_not_selected")
            ),
            "permanently_closed": _sum(
                rows, ("levels", level, "permanently_closed")
            ),
            "proposal_bins": dict(
                _merge_counts(rows, ("levels", level, "proposals", "bins"))
            ),
            "rollout_bins": dict(
                _merge_counts(rows, ("levels", level, "rollouts", "bins"))
            ),
            "selection_modes": dict(
                _merge_counts(
                    rows, ("levels", level, "rollouts", "selection_modes")
                )
            ),
        }

    ids = _merge_counts(rows, ("levels", "weak_order", "rollouts", "id_counts"))
    weak: dict[str, object] = {
        **_distribution_summary(ids),
        "new_unique_ids": _sum(
            rows, ("levels", "weak_order", "rollouts", "new_unique_ids")
        ),
        "historical_revisit_visits": _sum(
            rows,
            ("levels", "weak_order", "rollouts", "historical_revisit_visits"),
        ),
        "within_generation_repeat_visits": _sum(
            rows,
            ("levels", "weak_order", "rollouts", "within_generation_repeat_visits"),
        ),
        "without_policy_decision": _sum(
            rows, ("levels", "weak_order", "rollouts", "without_policy_decision")
        ),
        "permanently_closed": _sum(
            rows, ("levels", "weak_order", "permanently_closed")
        ),
    }
    for key in (
        "decisions",
        "legal_masks",
        "pooled_masks",
        "viable_actions",
        "selected_actions",
        "omitted_by_bounded_random_pool",
        "rejected_by_existing_prefix_filters",
        "locally_not_selected_by_policy",
        "pool_limit_hit_decisions",
    ):
        weak[key] = _sum(rows, ("levels", "weak_order", "decision_funnel", key))
    for key in (
        "progress_bins",
        "selected_block_size_bins",
        "viable_action_count_bins",
        "selection_modes",
    ):
        weak[key] = dict(
            _merge_counts(rows, ("levels", "weak_order", "decision_funnel", key))
        )
    levels["weak_order"] = weak
    return {"generations": len(rows), "levels": levels}


def build_audit_report(
    rows: Sequence[Mapping[str, Any]], *, window_generations: int
) -> dict[str, object]:
    recent = list(rows[-max(1, window_generations) :])
    return {
        "schema_version": "graph-lab-rollout-audit-v1",
        "generation_first": int(rows[0].get("generation", 0)) if rows else None,
        "generation_last": int(rows[-1].get("generation", 0)) if rows else None,
        "all": summarize(rows),
        "recent": summarize(recent),
        "recent_window_generations": max(1, window_generations),
    }


def _top_bins(values: Mapping[str, object], limit: int = 8) -> str:
    ordered = sorted(values.items(), key=lambda item: (-int(item[1]), item[0]))
    return ", ".join(f"{name}:{count}" for name, count in ordered[:limit]) or "none"


def _print_section(name: str, summary: Mapping[str, Any]) -> None:
    print(f"\n{name} ({summary['generations']} generations)")
    levels = summary["levels"]
    for level in ("graph", "mapping"):
        data = levels[level]
        top = data["top_share"]
        print(
            f"  {level}: rollouts={data['total']} unique={data['unique']} "
            f"new={data['new_unique_ids']} historical-revisits="
            f"{data['historical_revisit_visits']} top-share="
            f"{float(top):.3f} effective-ids={float(data['effective_ids']):.1f}"
            if top is not None
            else f"  {level}: no rollout"
        )
        print(
            f"    proposed={data['proposed']} locally-not-selected="
            f"{data['locally_not_selected']} permanently-closed="
            f"{data['permanently_closed']} modes={_top_bins(data['selection_modes'])}"
        )
        print(f"    proposal-space: {_top_bins(data['proposal_bins'])}")
        print(f"    rollout-space:  {_top_bins(data['rollout_bins'])}")
    data = levels["weak_order"]
    top = data["top_share"]
    print(
        f"  weak_order: rollouts={data['total']} unique-trajectories={data['unique']} "
        f"new={data['new_unique_ids']} historical-revisits="
        f"{data['historical_revisit_visits']} top-share="
        f"{float(top):.3f} effective-trajectories="
        f"{float(data['effective_ids']):.1f}"
        if top is not None
        else "  weak_order: no rollout"
    )
    print(
        "    decision funnel: "
        f"legal={data['legal_masks']} -> random-pool={data['pooled_masks']} "
        f"-> prefix-valid={data['viable_actions']} -> selected={data['selected_actions']}"
    )
    print(
        f"    omitted-by-pool={data['omitted_by_bounded_random_pool']} "
        f"prefix-rejected={data['rejected_by_existing_prefix_filters']} "
        f"locally-not-selected={data['locally_not_selected_by_policy']} "
        f"permanently-closed={data['permanently_closed']}"
    )
    print(f"    progress: {_top_bins(data['progress_bins'])}")
    print(f"    chosen-block-sizes: {_top_bins(data['selected_block_size_bins'])}")
    print(f"    viable-actions/decision: {_top_bins(data['viable_action_count_bins'])}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit historical and recent Graph Lab rollout coverage"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("output/graph_lab/up-to-13/rollout_coverage_metrics.jsonl"),
    )
    parser.add_argument("--window-generations", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = args.input.resolve()
    rows = _load(source)
    if not rows:
        raise SystemExit(f"No rollout coverage metrics found in {source}")
    report = build_audit_report(
        rows, window_generations=max(1, int(args.window_generations))
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"Rollout coverage audit: {source}\n"
            f"generations={report['generation_first']}..{report['generation_last']}\n"
            "Closure invariant: graph=0, mapping=0, weak_order=0. "
            "Pool/ranker nonselection is local and remains resampleable."
        )
        _print_section("ALL", report["all"])  # type: ignore[arg-type]
        _print_section("RECENT", report["recent"])  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
