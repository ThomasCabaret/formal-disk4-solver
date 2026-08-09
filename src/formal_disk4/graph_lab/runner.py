from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evaluator import GRAPH_STAGES, GraphEvaluation, GraphFormalEvaluator
from .isomorphism import IsomorphismIndex
from .model import GraphLearningModel
from .space import DualGraphCandidate, GraphSpace, graph_feature_payload


RESTART_FILES = (
    "observations.jsonl",
    "training_metrics.jsonl",
    "geometry_candidates.jsonl",
    "geometry_graphs.jsonl",
    "model.pt",
    "state.json",
    "report.json",
    "report.md",
    "effective_config.json",
)


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _append_jsonl(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True) + "\n")
        stream.flush()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
    return records


def _diversity_cell(candidate: DualGraphCandidate, stage: int) -> str:
    maximum_edges = max(1, 3 * (candidate.tile_count + 1) - 6)
    density_bin = min(4, int(5 * candidate.edge_count / maximum_edges))
    symmetry = candidate.symmetry_order
    symmetry_bin = "none" if symmetry <= 1 else ("high" if symmetry >= 4 else "low")
    return f"n{candidate.tile_count}:sym-{symmetry_bin}:density-{density_bin}:stage-{stage}"


class DiversityArchive:
    def __init__(self, observations: Sequence[GraphEvaluation]) -> None:
        self.cells: dict[str, list[GraphEvaluation]] = defaultdict(list)
        for observation in observations:
            self.add(observation)

    @staticmethod
    def reward(observation: GraphEvaluation) -> float:
        return (
            float(observation.stage_index)
            + 4.0 * len(observation.profiles)
            - 0.08 * math.log1p(observation.elapsed_seconds)
            - (1.0 if observation.tainted else 0.0)
        )

    def add(self, observation: GraphEvaluation) -> None:
        cell = _diversity_cell(observation.candidate, observation.stage_index)
        values = self.cells[cell]
        values.append(observation)
        values.sort(key=lambda item: (-self.reward(item), item.candidate.graph_id))
        del values[8:]

    def novelty(self, candidate: DualGraphCandidate) -> float:
        prefix = _diversity_cell(candidate, 0).rsplit(":stage-", 1)[0]
        amount = sum(
            len(values) for cell, values in self.cells.items() if cell.startswith(prefix)
        )
        return 1.0 / math.sqrt(1.0 + amount)

    def choose_parent(self, rng: random.Random) -> GraphEvaluation | None:
        nonempty = [values for values in self.cells.values() if values]
        if not nonempty:
            return None
        if rng.random() < 0.75:
            values = rng.choice(nonempty)
            weights = [max(0.1, self.reward(item) + 1.0) for item in values]
            return rng.choices(values, weights=weights, k=1)[0]
        all_values = [item for values in nonempty for item in values]
        weights = [max(0.1, self.reward(item) + 1.0) for item in all_values]
        return rng.choices(all_values, weights=weights, k=1)[0]


@dataclass(frozen=True)
class GraphLabResult:
    output_directory: Path
    generations_completed: int
    observations: int
    geometry_ready_graphs: int
    stop_reason: str


class GraphLabRunner:
    def __init__(self, root: Path, config: Mapping[str, object]) -> None:
        self.root = root.resolve()
        self.config = dict(config)
        output = Path(str(dict(config["output"])["directory"]))
        self.output = (output if output.is_absolute() else self.root / output).resolve()
        try:
            self.output.relative_to(self.root)
        except ValueError as error:
            raise ValueError("Graph Lab output must stay inside the project") from error
        if self.output == self.root:
            raise ValueError("Graph Lab output cannot be the project root")
        raw_budget = dict(config["output"]).get("max_training_megabytes")
        self.max_training_bytes = (
            max(1, int(float(raw_budget) * 1024 * 1024))
            if raw_budget is not None and float(raw_budget) > 0
            else None
        )
        self.space = GraphSpace.from_config(dict(config.get("space", {})))
        self.sampling = dict(config.get("sampling", {}))
        self.learning = dict(config.get("learning", {}))
        self.evaluator = GraphFormalEvaluator(
            self.root, dict(config.get("evaluation", {}))
        )
        self.fingerprint = hashlib.sha256(
            json.dumps(self.config, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    @classmethod
    def from_file(cls, root: Path, path: Path | str) -> "GraphLabRunner":
        source = Path(path)
        if not source.is_absolute():
            source = root / source
        config = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("Graph Lab config must be a JSON object")
        return cls(root, config)

    def _restart(self) -> None:
        self.output.mkdir(parents=True, exist_ok=True)
        for name in RESTART_FILES:
            path = self.output / name
            if path.exists():
                path.unlink()

    def _load_observations(self) -> list[GraphEvaluation]:
        return [
            GraphEvaluation.from_dict(value)
            for value in _load_jsonl(self.output / "observations.jsonl")
        ]

    def _training_output_bytes(self) -> int:
        if not self.output.exists():
            return 0
        return sum(
            path.stat().st_size
            for path in self.output.iterdir()
            if path.is_file() and not path.name.endswith(".tmp")
        )

    def _output_budget_reached(self) -> bool:
        return (
            self.max_training_bytes is not None
            and self._training_output_bytes() >= self.max_training_bytes
        )

    def _state_generation(self) -> int:
        path = self.output / "state.json"
        if not path.exists():
            return 0
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("fingerprint") != self.fingerprint:
            raise ValueError("Stored Graph Lab state is incompatible; use --restart")
        return int(state.get("next_generation", 0))

    def _candidate_pool(
        self,
        rng: random.Random,
        archive: DiversityArchive,
        seen: IsomorphismIndex,
        target: int,
    ) -> list[DualGraphCandidate]:
        pool: list[DualGraphCandidate] = []
        local = IsomorphismIndex()
        mutation_fraction = min(
            1.0, max(0.0, float(self.sampling.get("mutation_fraction", 0.65)))
        )
        attempts = 0
        while len(pool) < target and attempts < target * 200:
            attempts += 1
            parent = archive.choose_parent(rng) if rng.random() < mutation_fraction else None
            candidate = (
                self.space.mutate(parent.candidate, rng)
                if parent is not None
                else self.space.sample_prior(rng)
            )
            if candidate is None or seen.equivalent(candidate) is not None:
                continue
            if local.add(candidate):
                pool.append(candidate)
        if len(pool) < target:
            raise RuntimeError(
                f"Graph generator produced only {len(pool)} novel candidates for a pool of {target}"
            )
        return pool

    def _select(
        self,
        pool: Sequence[DualGraphCandidate],
        model: GraphLearningModel,
        archive: DiversityArchive,
        rng: random.Random,
        amount: int,
    ) -> list[tuple[DualGraphCandidate, Mapping[str, object]]]:
        exploration = min(
            amount,
            max(1, int(round(amount * float(self.sampling.get("exploration_fraction", 0.25))))),
        )
        scored = []
        for candidate in pool:
            novelty = archive.novelty(candidate)
            score, prediction = model.utility(
                candidate,
                novelty=novelty,
                geometry_weight=float(self.sampling.get("geometry_weight", 8.0)),
                novelty_weight=float(self.sampling.get("novelty_weight", 1.5)),
                cost_weight=float(self.sampling.get("cost_weight", 0.08)),
            )
            scored.append((score, candidate, prediction, novelty))
        scored.sort(key=lambda item: (-item[0], item[1].graph_id))
        exploit = amount - exploration
        # Draw the control uniformly from the complete pool first. Sampling it
        # only from the tail left by the ranker would make the control
        # artificially weak and overstate learned enrichment.
        random_control = rng.sample(scored, exploration) if exploration else []
        control_ids = {item[1].graph_id for item in random_control}
        learned = [
            item for item in scored if item[1].graph_id not in control_ids
        ][:exploit]
        selected = [(item, "learned") for item in learned]
        selected.extend((item, "exploration") for item in random_control)
        return [
            (
                candidate,
                {
                    "selection_mode": selection_mode,
                    "selection_score": score,
                    "novelty": novelty,
                    "predicted_stage": prediction.expected_stage,
                    "predicted_geometry_probability": prediction.geometry_probability,
                    "predicted_transition_probabilities": list(
                        prediction.conditional_probabilities
                    ),
                    "predicted_seconds": prediction.expected_seconds,
                },
            )
            for (score, candidate, prediction, novelty), selection_mode in selected
        ]

    def _generation_metrics(
        self,
        generation: int,
        records: Sequence[tuple[GraphEvaluation, Mapping[str, object]]],
        model_metrics: Mapping[str, object],
    ) -> dict[str, object]:
        """Build tiny per-generation aggregates for the live dashboard."""

        modes: dict[str, dict[str, object]] = {}
        for evaluation, selection in records:
            mode = str(
                selection.get(
                    "selection_mode",
                    "known_control"
                    if selection.get("selection") == "known_control"
                    else "unknown",
                )
            )
            bucket = modes.setdefault(
                mode,
                {
                    "count": 0,
                    "stage_reached_counts": {
                        stage: 0 for stage in GRAPH_STAGES
                    },
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

        return {
            "schema_version": "graph-lab-generation-metrics-v1",
            "generation": generation,
            "evaluated": len(records),
            "geometry_ready": sum(
                evaluation.geometry_ready for evaluation, _selection in records
            ),
            "training_output_bytes": self._training_output_bytes(),
            "max_training_bytes": self.max_training_bytes,
            "selection_modes": modes,
            "model": dict(model_metrics),
        }

    def _save_geometry(
        self, evaluation: GraphEvaluation, generation: int
    ) -> None:
        graph_payload = {
            "schema_version": "graph-lab-geometry-graph-v1",
            "generation": generation,
            "candidate": evaluation.candidate.to_dict(),
            "evaluation": evaluation.to_dict(),
        }
        _append_jsonl(self.output / "geometry_graphs.jsonl", graph_payload)
        for profile in evaluation.profiles:
            enriched = dict(profile)
            enriched["graph_lab"] = {
                "generation": generation,
                "graph_id": evaluation.candidate.graph_id,
                "structural_candidate": evaluation.candidate.to_dict(),
                "formal_evaluation": evaluation.to_dict(),
            }
            _append_jsonl(self.output / "geometry_candidates.jsonl", enriched)

    def _report(
        self,
        observations: Sequence[GraphEvaluation],
        model: GraphLearningModel,
        generation: int,
        *,
        stop_reason: str,
    ) -> dict[str, object]:
        stage_histogram = Counter(item.stage_name for item in observations)
        reached = {
            name: sum(item.stage_index >= index for item in observations)
            for index, name in enumerate(GRAPH_STAGES)
        }
        sizes = Counter(item.candidate.tile_count for item in observations)
        symmetries = Counter(item.candidate.symmetry_order for item in observations)
        origins = Counter(item.candidate.origin for item in observations)
        known = {
            item.candidate.source_map_name: {
                "graph_id": item.candidate.graph_id,
                "stage": item.stage_name,
                "profiles": int(item.counters.get("profiles_emitted", 0)),
                "stop_reason": item.stop_reason,
            }
            for item in observations
            if item.candidate.source_map_name is not None
        }
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
        diversity_archive = DiversityArchive(observations)
        report = {
            "schema_version": "graph-lab-report-v1",
            "generation": generation,
            "stop_reason": stop_reason,
            "observations": len(observations),
            "training_output_bytes": self._training_output_bytes(),
            "max_training_bytes": self.max_training_bytes,
            "stage_histogram": dict(stage_histogram),
            "reached_counts": reached,
            "tile_count_histogram": dict(sorted(sizes.items())),
            "symmetry_order_histogram": dict(sorted(symmetries.items())),
            "origin_histogram": dict(origins),
            "diversity_cells": len(diversity_archive.cells),
            "diversity_cell_sizes": {
                name: len(values)
                for name, values in sorted(diversity_archive.cells.items())
            },
            "known_seed_results": known,
            "geometry_ready": geometry,
            "model": model.metrics(observations),
        }
        _atomic_json(self.output / "report.json", report)
        lines = [
            "# Variable-graph learning report",
            "",
            f"Generation: {generation}",
            f"Stop reason: {stop_reason}",
            f"Evaluated graph structures: {len(observations)}",
            f"Geometry-ready graph structures: {len(geometry)}",
            f"Training output: {self._training_output_bytes() / (1024 * 1024):.2f} MiB",
            (
                f"Training output limit: {self.max_training_bytes / (1024 * 1024):.2f} MiB"
                if self.max_training_bytes is not None
                else "Training output limit: disabled"
            ),
            "",
            "## Pipeline depth",
            "",
            "| Stage reached | Count |",
            "|---|---:|",
        ]
        for name in GRAPH_STAGES:
            lines.append(f"| {name} | {reached[name]} |")
        lines.extend(
            [
                "",
                "## Known controls",
                "",
                "| Map | Deepest stage | Profiles | Stop reason |",
                "|---|---|---:|---|",
            ]
        )
        for name, value in sorted(known.items()):
            lines.append(
                f"| {name} | {value['stage']} | {value['profiles']} | {value['stop_reason']} |"
            )
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
        (self.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return report

    def run(
        self,
        *,
        restart: bool = False,
        generations: int | None = None,
        batch_size: int | None = None,
    ) -> GraphLabResult:
        if restart:
            self._restart()
        self.output.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.output / "effective_config.json", self.config)
        observations = self._load_observations()
        seen = IsomorphismIndex()
        for observation in observations:
            seen.add(observation.candidate)
        archive = DiversityArchive(observations)
        model = GraphLearningModel.load_or_create(
            self.output / "model.pt", self.learning
        )
        if observations and not (self.output / "model.pt").exists():
            model.train(
                observations,
                steps=int(self.learning.get("bootstrap_steps", 100)),
                batch_size=int(self.learning.get("batch_size", 16)),
                generation=-1,
            )

        start = self._state_generation()
        total_generations = max(
            1,
            int(
                generations
                if generations is not None
                else self.sampling.get("generations", 1000)
            ),
        )
        target_batch = max(
            1,
            int(
                batch_size
                if batch_size is not None
                else self.sampling.get("batch_size", 8)
            ),
        )
        pending_known = [
            candidate
            for candidate in self.space.known_seeds
            if seen.equivalent(candidate) is None
        ]
        if self.max_training_bytes is None:
            disk_limit = "off"
        elif self.max_training_bytes >= 1024**3:
            disk_limit = f"{self.max_training_bytes / 1024**3:.2f}GiB"
        else:
            disk_limit = f"{self.max_training_bytes / 1024**2:.0f}MiB"
        print(
            f"graph-lab generations={start}..{total_generations - 1} "
            f"batch={target_batch} known-pending={len(pending_known)} "
            f"tiles<= {self.space.maximum_tiles} "
            f"disk-limit={disk_limit}",
            flush=True,
        )

        last_generation = start - 1
        stop_reason = "completed"
        try:
            for generation in range(start, total_generations):
                if self._output_budget_reached():
                    stop_reason = "max_training_output_bytes"
                    print(
                        "[OUTPUT BUDGET] Graph Lab stopped before evaluating another "
                        f"graph: {self._training_output_bytes() / (1024 * 1024):.2f} "
                        "MiB already stored.",
                        flush=True,
                    )
                    self._report(
                        observations,
                        model,
                        last_generation,
                        stop_reason=stop_reason,
                    )
                    break
                rng = random.Random(
                    int(self.sampling.get("seed", 20260809)) + generation * 1000003
                )
                known_quota = min(
                    len(pending_known),
                    target_batch,
                    max(0, int(self.sampling.get("known_seeds_per_generation", 2))),
                )
                selected: list[tuple[DualGraphCandidate, Mapping[str, object]]] = [
                    (
                        pending_known.pop(0),
                        {
                            "selection": "known_control",
                            "selection_mode": "known_control",
                        },
                    )
                    for _ in range(known_quota)
                ]
                remaining = target_batch - len(selected)
                if remaining:
                    pool = self._candidate_pool(
                        rng,
                        archive,
                        seen,
                        max(
                            remaining,
                            remaining * max(1, int(self.sampling.get("pool_multiplier", 6))),
                        ),
                    )
                    selected.extend(self._select(pool, model, archive, rng, remaining))

                generation_evaluations = []
                generation_records: list[
                    tuple[GraphEvaluation, Mapping[str, object]]
                ] = []
                for candidate, selection in selected:
                    if self._output_budget_reached():
                        stop_reason = "max_training_output_bytes"
                        break
                    if seen.equivalent(candidate) is not None:
                        continue
                    evaluation = self.evaluator.evaluate(candidate)
                    observation = evaluation.to_dict()
                    observation["generation"] = generation
                    observation["selection"] = dict(selection)
                    observation["graph_features"] = graph_feature_payload(candidate)
                    _append_jsonl(self.output / "observations.jsonl", observation)
                    seen.add(candidate)
                    archive.add(evaluation)
                    observations.append(evaluation)
                    generation_evaluations.append(evaluation)
                    generation_records.append((evaluation, selection))
                    if evaluation.geometry_ready:
                        self._save_geometry(evaluation, generation)
                        print(
                            "[GEOMETRY READY] "
                            f"g={generation} graph={candidate.graph_id} "
                            f"tiles={candidate.tile_count} edges={candidate.edge_count} "
                            f"sym={candidate.symmetry_order} profiles={len(evaluation.profiles)} "
                            f"source={candidate.source_map_name or 'generated'}",
                            flush=True,
                        )
                    print(
                        f"g{generation} {candidate.graph_id} "
                        f"n={candidate.tile_count} e={candidate.edge_count} "
                        f"sym={candidate.symmetry_order} stage={evaluation.stage_name} "
                        f"profiles={len(evaluation.profiles)} wall={evaluation.elapsed_seconds:.2f}s "
                        f"origin={candidate.origin}",
                        flush=True,
                    )
                    if evaluation.stop_reason == "keyboard_interrupt":
                        raise KeyboardInterrupt

                metrics = model.train(
                    observations,
                    steps=int(self.learning.get("steps_per_generation", 8)),
                    batch_size=int(self.learning.get("batch_size", 16)),
                    generation=generation,
                )
                model.save(self.output / "model.pt")
                _append_jsonl(
                    self.output / "training_metrics.jsonl",
                    self._generation_metrics(
                        generation, generation_records, metrics
                    ),
                )
                if self._output_budget_reached():
                    stop_reason = "max_training_output_bytes"
                _atomic_json(
                    self.output / "state.json",
                    {
                        "schema_version": "graph-lab-state-v1",
                        "fingerprint": self.fingerprint,
                        "next_generation": generation + 1,
                        "observations": len(observations),
                    },
                )
                report = self._report(
                    observations,
                    model,
                    generation,
                    stop_reason=(
                        stop_reason
                        if stop_reason == "max_training_output_bytes"
                        else (
                            "completed"
                            if generation + 1 >= total_generations
                            else "running"
                        )
                    ),
                )
                last_generation = generation
                print(
                    f"generation {generation} complete: evaluated={len(generation_evaluations)} "
                    f"total={len(observations)} geometry={len(report['geometry_ready'])} "
                    f"model_examples={metrics['examples']}",
                    flush=True,
                )
                if stop_reason == "max_training_output_bytes":
                    print(
                        "[OUTPUT BUDGET] Graph Lab stopped cleanly at "
                        f"{self._training_output_bytes() / (1024 * 1024):.2f} MiB.",
                        flush=True,
                    )
                    break
        except KeyboardInterrupt:
            stop_reason = "keyboard_interrupt"
            print("Graph Lab interrupted; completed observations are already durable.", flush=True)
            model.save(self.output / "model.pt")
            self._report(
                observations,
                model,
                last_generation,
                stop_reason=stop_reason,
            )

        geometry_graphs = sum(item.stage_index >= len(GRAPH_STAGES) - 1 for item in observations)
        return GraphLabResult(
            output_directory=self.output,
            generations_completed=max(0, last_generation + 1),
            observations=len(observations),
            geometry_ready_graphs=geometry_graphs,
            stop_reason=stop_reason,
        )
