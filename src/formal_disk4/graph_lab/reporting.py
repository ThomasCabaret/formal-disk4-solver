from __future__ import annotations

from collections import Counter
from typing import Mapping, Sequence

from .evaluator import GRAPH_STAGES, GraphEvaluation
from .feedback import read_learning_feedback
from .policy import GraphSelectionPolicy
from .proposals import DiversityArchive
from .run_store import GraphLabRunStore
from .search_request import GraphLabSearchRequest, OuterBoundaryMode, RegionMode
from .space import GraphSpace


class GraphLabReporter:
    """Project completed evaluations into durable reports and geometry queues."""

    def __init__(
        self,
        store: GraphLabRunStore,
        space: GraphSpace,
        request: GraphLabSearchRequest,
        *,
        maximum_bytes: int | None,
    ) -> None:
        self.store = store
        self.space = space
        self.request = request
        self.maximum_bytes = maximum_bytes

    def generation_metrics(
        self,
        generation: int,
        records: Sequence[tuple[GraphEvaluation, Mapping[str, object]]],
        model_metrics: Mapping[str, object],
    ) -> dict[str, object]:
        modes: dict[str, dict[str, object]] = {}
        for evaluation, selection in records:
            mode = str(selection.get("selection_mode", "unknown"))
            bucket = modes.setdefault(
                mode,
                {
                    "count": 0,
                    "stage_reached_counts": {stage: 0 for stage in GRAPH_STAGES},
                    "transitions": {
                        stage: {
                            "eligible": 0,
                            "passed": 0,
                            "prediction_sum": 0.0,
                            "prediction_count": 0,
                        }
                        for stage in GRAPH_STAGES[1:]
                    },
                },
            )
            bucket["count"] = int(bucket["count"]) + 1
            reached = bucket["stage_reached_counts"]
            assert isinstance(reached, dict)
            for stage_index, stage in enumerate(GRAPH_STAGES):
                if evaluation.stage_index >= stage_index:
                    reached[stage] = int(reached[stage]) + 1

            raw_predictions = selection.get(
                "predicted_transition_probabilities", ()
            )
            predictions = (
                raw_predictions
                if isinstance(raw_predictions, Sequence)
                and not isinstance(raw_predictions, (str, bytes))
                else ()
            )
            transitions = bucket["transitions"]
            assert isinstance(transitions, dict)
            for head, stage in enumerate(GRAPH_STAGES[1:]):
                target = head + 1
                if evaluation.stage_index < target - 1:
                    continue
                transition = transitions[stage]
                assert isinstance(transition, dict)
                transition["eligible"] = int(transition["eligible"]) + 1
                if evaluation.stage_index >= target:
                    transition["passed"] = int(transition["passed"]) + 1
                if head < len(predictions):
                    transition["prediction_sum"] = float(
                        transition["prediction_sum"]
                    ) + float(predictions[head])
                    transition["prediction_count"] = int(
                        transition["prediction_count"]
                    ) + 1

        comparable = modes if {"exploration", "learned"}.issubset(modes) else {}
        return {
            "schema_version": "graph-lab-generation-metrics-v1",
            "generation": generation,
            "evaluated": len(records),
            "geometry_ready": sum(
                evaluation.geometry_ready for evaluation, _selection in records
            ),
            "training_output_bytes": self.store.total_bytes(),
            "max_training_bytes": self.maximum_bytes,
            "selection_modes": modes,
            "comparable_selection_modes": comparable,
            "comparison": {
                "scope": "same_generation_proposal_pool",
                "comparable_parent_count": 1 if comparable else 0,
                "excluded_parent_count": 0 if comparable else 1,
            },
            "model": dict(model_metrics),
        }

    def save_geometry(self, evaluation: GraphEvaluation, generation: int) -> None:
        graph_payload = {
            "schema_version": "graph-lab-geometry-graph-v1",
            "generation": generation,
            "candidate": evaluation.candidate.to_dict(),
            "evaluation": evaluation.to_dict(),
        }
        self.store.append_jsonl("geometry_graphs.jsonl", graph_payload)
        for profile in evaluation.profiles:
            enriched = dict(profile)
            enriched["graph_lab"] = {
                "generation": generation,
                "graph_id": evaluation.candidate.graph_id,
                "structural_candidate": evaluation.candidate.to_dict(),
                "formal_evaluation": evaluation.to_dict(),
            }
            self.store.append_jsonl("geometry_candidates.jsonl", enriched)

    def report(
        self,
        observations: Sequence[GraphEvaluation],
        policy: GraphSelectionPolicy,
        generation: int,
        *,
        stop_reason: str,
        model_metrics: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        stage_histogram = Counter(item.stage_name for item in observations)
        reached = {
            name: sum(item.stage_index >= index for item in observations)
            for index, name in enumerate(GRAPH_STAGES)
        }
        sizes = Counter(item.candidate.tile_count for item in observations)
        symmetries = Counter(item.candidate.symmetry_order for item in observations)
        origins = Counter(item.candidate.origin for item in observations)
        geometry = [
            {
                "graph_id": item.candidate.graph_id,
                "tiles": item.candidate.tile_count,
                "edges": item.candidate.edge_count,
                "symmetry_order": item.candidate.symmetry_order,
                "profiles": len(item.profiles)
                or int(item.counters.get("profiles_emitted", 0)),
                "source_map": item.candidate.source_map_name,
            }
            for item in observations
            if item.stage_index >= len(GRAPH_STAGES) - 1
        ]
        unique_graph_count = len(
            {item.candidate.graph_id for item in observations}
        )
        unique_geometry_count = len({item["graph_id"] for item in geometry})
        diversity_archive = DiversityArchive(observations)
        partial_counts = self.request.region.tile_counts
        report = {
            "schema_version": "graph-lab-report-v1",
            "generation": generation,
            "stop_reason": stop_reason,
            "observations": len(observations),
            "unique_graphs_evaluated": unique_graph_count,
            "training_output_bytes": self.store.total_bytes(),
            "max_training_bytes": self.maximum_bytes,
            "stage_histogram": dict(stage_histogram),
            "reached_counts": reached,
            "tile_count_prior": {
                str(size): probability
                for size, probability in self.space.size_sampling_distribution()
            },
            "tile_count_domain": list(self.space.tile_counts),
            "requested_tile_count_domain": list(self.space.requested_tile_counts),
            "stein_symmetric": self.request.structure.stein_symmetric,
            "policy_mode": self.request.policy.value,
            "outer_crown_only": self.request.region.mode is not RegionMode.FULL,
            "free_outer_boundary": (
                self.request.boundary.outer is OuterBoundaryMode.FREE
            ),
            "partial_crown_tile_counts": (
                list(partial_counts) if partial_counts is not None else None
            ),
            "prototype_symmetry_mode": self.request.prototype.symmetry.value,
            "symmetry_order_domain": (
                list(self.space.symmetry_orders)
                if self.space.symmetry_orders is not None
                else None
            ),
            "tile_count_histogram": dict(sorted(sizes.items())),
            "symmetry_order_histogram": dict(sorted(symmetries.items())),
            "origin_histogram": dict(origins),
            "diversity_cells": len(diversity_archive.cells),
            "diversity_cell_sizes": {
                name: len(values)
                for name, values in sorted(diversity_archive.cells.items())
            },
            "geometry_ready": geometry,
            "geometry_ready_evaluations": len(geometry),
            "geometry_ready_unique_graphs": unique_geometry_count,
            "model": (
                dict(model_metrics)
                if model_metrics is not None
                else policy.metrics(
                    observations,
                    feedback=read_learning_feedback(self.store.output),
                )
            ),
        }
        self.store.write_json("report.json", report)
        lines = [
            "# Variable-graph search report",
            "",
            f"Generation: {generation}",
            f"Stop reason: {stop_reason}",
            f"Graph policy: {self.request.policy.value}",
            f"Evaluated graph structures: {len(observations)}",
            f"Distinct evaluated graph structures: {unique_graph_count}",
            f"Geometry-ready evaluations: {len(geometry)}",
            f"Distinct geometry-ready graph structures: {unique_geometry_count}",
            f"Training output: {self.store.total_bytes() / (1024 * 1024):.2f} MiB",
            (
                f"Training output limit: {self.maximum_bytes / (1024 * 1024):.2f} MiB"
                if self.maximum_bytes is not None
                else "Training output limit: disabled"
            ),
            "",
            "## Tile-count sampling",
            "",
            "| Tiles | Configured prior probability | Evaluated |",
            "|---:|---:|---:|",
        ]
        for size, probability in self.space.size_sampling_distribution():
            lines.append(
                f"| {size} | {100.0 * probability:.3f}% | {sizes.get(size, 0)} |"
            )
        lines.extend(
            [
                "",
                "## Pipeline depth",
                "",
                "| Stage reached | Count |",
                "|---|---:|",
            ]
        )
        for name in GRAPH_STAGES:
            lines.append(f"| {name} | {reached[name]} |")
        lines.extend(
            [
                "",
                "## Geometry-ready structures",
                "",
                "Every formal candidate is preserved in `geometry_candidates.jsonl`.",
                "The corresponding graph and imposed symmetry are preserved in",
                "`geometry_graphs.jsonl`.",
                "",
                "| Graph | Tiles | Edges | Symmetry order | Profiles | Source |",
                "|---|---:|---:|---:|---:|---|",
            ]
        )
        for value in geometry:
            lines.append(
                f"| {value['graph_id']} | {value['tiles']} | {value['edges']} | "
                f"{value['symmetry_order']} | {value['profiles']} | "
                f"{value['source_map'] or 'generated'} |"
            )
        self.store.path("report.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        return report
