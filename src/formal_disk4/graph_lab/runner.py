from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evaluator import GRAPH_STAGES, GraphEvaluation, GraphFormalEvaluator
from .feedback import read_learning_feedback
from .hierarchical_policy import HierarchicalPolicyRuntime
from .mapping import MappingEvaluation, MappingProposal
from .mapping_model import MappingLearningModel
from .policy import LearnedGraphPolicy, build_graph_policy
from .proposals import DiversityArchive, StochasticGraphProposalSource
from .replay_store import (
    MAX_MAPPING_REPLAY_IN_MEMORY,
    MAX_SPECIALIZATION_REPLAY_IN_MEMORY,
    MAX_WEAK_ORDER_REPLAY_IN_MEMORY,
    GraphLabReplayStore,
    extend_bounded_replay,
)
from .reporting import GraphLabReporter
from .rollout_audit import build_generation_coverage, weak_trajectory_id
from .run_store import GraphLabRunStore
from .space import (
    DualGraphCandidate,
    GraphSpace,
    format_tile_count_spec,
    graph_feature_payload,
)
from .specialization_model import (
    SpecializationLearningModel,
    SpecializationPoolObservation,
)
from .search_request import GraphLabSearchRequest
from .weak_model import WeakOrderLearningModel, WeakOrderRolloutObservation


def _checkpoint_fingerprint(config: Mapping[str, object]) -> str:
    """Hash only checkpoint-shape/semantics settings.

    Proposal, ordering, and learning policies change traversal rather than the
    stored observation schema.  They are intentionally omitted so a run can
    switch between the prior, learned ranking, enumeration, and joint
    backtracking without discarding already durable evaluations.
    """

    compatible = json.loads(json.dumps(config))
    for key in (
        "policy",
        "sampling",
        "learning",
        "mapping_sampling",
        "mapping_learning",
        "weak_order_sampling",
        "weak_order_learning",
        "specialization_sampling",
        "specialization_learning",
    ):
        compatible.pop(key, None)
    space = compatible.get("space")
    if isinstance(space, dict):
        space.pop("exclude_rings", None)
        space.pop("tile_counts", None)
    evaluation = compatible.get("evaluation")
    if isinstance(evaluation, dict):
        evaluation.pop("joint_arrangement_search", None)
        evaluation.pop("mapping_search_overrides", None)
    return hashlib.sha256(
        json.dumps(compatible, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


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
        self.search_request = GraphLabSearchRequest.from_config(config)
        self.config = self.search_request.apply_to_config(config)
        config = self.config
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
        self.store = GraphLabRunStore(
            self.output, maximum_bytes=self.max_training_bytes
        )
        self.space = GraphSpace.from_config(dict(config.get("space", {})))
        self.exclude_rings = self.space.exclude_rings
        self.stein_symmetric = self.space.stein_symmetric
        self.sampling = dict(config.get("sampling", {}))
        self.proposal_source = StochasticGraphProposalSource(
            self.space,
            mutation_fraction=float(self.sampling.get("mutation_fraction", 0.65)),
            exclude_rings=self.exclude_rings,
        )
        self.reporter = GraphLabReporter(
            self.store,
            self.space,
            self.search_request,
            maximum_bytes=self.max_training_bytes,
        )
        self.learning = dict(config.get("learning", {}))
        self.policy_mode = self.search_request.policy.value
        self.learning_enabled = self.policy_mode == "learned"
        self.mapping_sampling = dict(config.get("mapping_sampling", {}))
        self.mapping_learning = dict(config.get("mapping_learning", {}))
        self.mapping_sampling_enabled = bool(
            self.mapping_sampling.get("enabled", False)
        )
        self.mapping_learning_enabled = bool(
            self.learning_enabled and self.mapping_sampling_enabled
        )
        self.weak_order_sampling = dict(config.get("weak_order_sampling", {}))
        self.weak_order_learning = dict(config.get("weak_order_learning", {}))
        self.weak_order_learning_enabled = bool(
            self.mapping_learning_enabled
            and self.weak_order_sampling.get("enabled", False)
        )
        self.specialization_sampling = dict(
            config.get("specialization_sampling", {})
        )
        self.specialization_learning = dict(
            config.get("specialization_learning", {})
        )
        self.replays = GraphLabReplayStore(
            self.store,
            mapping_learning=self.mapping_learning,
            weak_order_learning=self.weak_order_learning,
            specialization_learning=self.specialization_learning,
        )
        self.specialization_learning_enabled = bool(
            self.weak_order_learning_enabled
            and self.specialization_sampling.get("enabled", False)
        )
        self.evaluator = GraphFormalEvaluator(
            self.root, dict(config.get("evaluation", {}))
        )
        if self.evaluator.joint_arrangement_search_enabled:
            # Joint backtracking replaces the three downstream learned
            # ordering layers; keeping their models active would spend time and
            # memory on decisions that are not consulted by this strategy.
            self.mapping_learning_enabled = False
            self.weak_order_learning_enabled = False
            self.specialization_learning_enabled = False
        self.hierarchical_policy = HierarchicalPolicyRuntime(
            self.evaluator,
            self.store,
            mapping_sampling=self.mapping_sampling,
            weak_order_sampling=self.weak_order_sampling,
            specialization_sampling=self.specialization_sampling,
            mapping_learning_enabled=self.mapping_learning_enabled,
            weak_order_learning_enabled=self.weak_order_learning_enabled,
            specialization_learning_enabled=self.specialization_learning_enabled,
        )
        self.outer_crown_only = self.evaluator.outer_crown_only
        self.free_outer_boundary = self.evaluator.free_outer_boundary
        self.partial_crown_tile_counts = self.evaluator.partial_crown_tile_counts
        self.prototype_symmetry_mode = self.evaluator.prototype_symmetry_mode
        if self.outer_crown_only and not self.stein_symmetric:
            raise ValueError("outer_crown_only requires stein_symmetric mode")
        self.fingerprint = _checkpoint_fingerprint(self.config)

    def _partial_mode_label(self) -> str:
        if self.free_outer_boundary:
            return "complete-map-free-outer-boundary"
        if not self.outer_crown_only:
            return "off"
        if self.partial_crown_tile_counts is None:
            return "outer-crown"
        return "crown-region:" + ",".join(
            str(value) for value in self.partial_crown_tile_counts
        )

    @classmethod
    def from_file(
        cls,
        root: Path,
        path: Path | str,
        *,
        exclude_rings: bool | None = None,
        tile_counts: str | Sequence[int] | None = None,
        stein_symmetric: bool | None = None,
        allow_imposed_symmetry: bool | None = None,
        symmetry_orders: str | Sequence[int] | None = None,
        outer_crown_only: bool | None = None,
        free_outer_boundary: bool | None = None,
        partial_crown_tile_counts: str | Sequence[int] | None = None,
        prototype_symmetry_mode: str | None = None,
        joint_arrangement_search: bool | None = None,
        policy_mode: str | None = None,
        output_directory: Path | str | None = None,
    ) -> "GraphLabRunner":
        source = Path(path)
        if not source.is_absolute():
            source = root / source
        config = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("Graph Lab config must be a JSON object")
        request = GraphLabSearchRequest.from_config(config).with_overrides(
            exclude_rings=exclude_rings,
            tile_counts=tile_counts,
            stein_symmetric=stein_symmetric,
            allow_imposed_symmetry=allow_imposed_symmetry,
            symmetry_orders=symmetry_orders,
            outer_crown_only=outer_crown_only,
            free_outer_boundary=free_outer_boundary,
            partial_crown_tile_counts=partial_crown_tile_counts,
            prototype_symmetry_mode=prototype_symmetry_mode,
            joint_arrangement_search=joint_arrangement_search,
            policy_mode=policy_mode,
        )
        config = request.apply_to_config(config)
        if output_directory is not None:
            output = dict(config.get("output", {}))
            output["directory"] = str(output_directory)
            config["output"] = output
        return cls(root, config)

    def restart_outputs(self) -> None:
        self.store.restart()

    def _load_observations(self) -> list[GraphEvaluation]:
        return [
            GraphEvaluation.from_dict(value)
            for value in self.store.iter_jsonl("observations.jsonl")
        ]

    def _training_output_bytes(self) -> int:
        return self.store.total_bytes()

    def _output_budget_reached(self) -> bool:
        return self.store.budget_reached()

    def _state_generation(self) -> int:
        path = self.output / "state.json"
        if not path.exists():
            return 0
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("fingerprint") != self.fingerprint:
            raise ValueError("Stored Graph Lab state is incompatible; use --restart")
        return int(state.get("next_generation", 0))

    def run(
        self,
        *,
        restart: bool = False,
        generations: int | None = None,
        batch_size: int | None = None,
    ) -> GraphLabResult:
        if restart:
            self.restart_outputs()
        self.output.mkdir(parents=True, exist_ok=True)
        self.store.write_json("effective_config.json", self.config)
        observations = self._load_observations()
        if self.mapping_learning_enabled:
            (
                mapping_observations,
                seen_mapping_ids,
                mapping_observation_count,
            ) = self.replays.load_mappings()
        else:
            mapping_observations, seen_mapping_ids, mapping_observation_count = (
                [],
                set(),
                0,
            )
        if self.weak_order_learning_enabled:
            (
                weak_order_rollouts,
                seen_trajectory_ids,
                weak_order_rollout_count,
            ) = self.replays.load_weak_orders()
        else:
            weak_order_rollouts, seen_trajectory_ids, weak_order_rollout_count = (
                [],
                set(),
                0,
            )
        if self.specialization_learning_enabled:
            (
                specialization_pools,
                specialization_pool_count,
            ) = self.replays.load_specializations()
        else:
            specialization_pools, specialization_pool_count = [], 0
        seen_graph_ids = {
            observation.candidate.graph_id for observation in observations
        }
        archive = DiversityArchive(observations)
        feedback = read_learning_feedback(self.output)
        graph_policy = build_graph_policy(
            self.policy_mode,
            output=self.output,
            learning=self.learning,
            sampling=self.sampling,
        )
        if isinstance(graph_policy, LearnedGraphPolicy):
            graph_policy.bootstrap(observations, feedback=feedback)
        mapping_model = (
            MappingLearningModel.load_or_create(
                self.output / "mapping_model.pt", self.mapping_learning
            )
            if self.mapping_learning_enabled
            else None
        )
        weak_order_model = (
            WeakOrderLearningModel.load_or_create(
                self.output / "weak_order_model.pt", self.weak_order_learning
            )
            if self.weak_order_learning_enabled
            else None
        )
        specialization_model = (
            SpecializationLearningModel.load_or_create(
                self.output / "specialization_model.pt", self.specialization_learning
            )
            if self.specialization_learning_enabled
            else None
        )
        if (
            mapping_model is not None
            and mapping_observations
            and not (self.output / "mapping_model.pt").exists()
        ):
            mapping_model.train(
                mapping_observations,
                steps=int(self.mapping_learning.get("bootstrap_steps", 100)),
                batch_size=int(self.mapping_learning.get("batch_size", 16)),
                generation=-1,
                feedback=feedback,
            )
        if weak_order_model is not None and weak_order_rollouts and not (
            self.output / "weak_order_model.pt"
        ).exists():
            weak_order_model.train(
                weak_order_rollouts,
                steps=int(self.weak_order_learning.get("bootstrap_steps", 100)),
                batch_size=int(self.weak_order_learning.get("batch_size", 16)),
                generation=-1,
                feedback=feedback,
            )
        if specialization_model is not None and specialization_pools and not (
            self.output / "specialization_model.pt"
        ).exists():
            specialization_model.train(
                specialization_pools,
                steps=int(
                    self.specialization_learning.get("bootstrap_steps", 100)
                ),
                batch_size=int(
                    self.specialization_learning.get("batch_size", 16)
                ),
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
        if self.max_training_bytes is None:
            disk_limit = "off"
        elif self.max_training_bytes >= 1024**3:
            disk_limit = f"{self.max_training_bytes / 1024**3:.2f}GiB"
        else:
            disk_limit = f"{self.max_training_bytes / 1024**2:.0f}MiB"
        print(
            f"graph-lab generations={start}..{total_generations - 1} "
            f"batch={target_batch} "
            f"tiles={format_tile_count_spec(self.space.tile_counts)} "
            f"mode={'stein-symmetric' if self.stein_symmetric else 'general'} "
            f"policy={self.policy_mode} "
            f"partial={self._partial_mode_label()} "
            f"prototype-symmetry={self.prototype_symmetry_mode} "
            f"exclude-rings={'on' if self.exclude_rings else 'off'} "
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
                    self.reporter.report(
                        observations,
                        graph_policy,
                        last_generation,
                        stop_reason=stop_reason,
                    )
                    break
                rng = random.Random(
                    int(self.sampling.get("seed", 20260809)) + generation * 1000003
                )
                selected: list[tuple[DualGraphCandidate, Mapping[str, object]]] = []
                generation_graph_pool: list[DualGraphCandidate] = []
                remaining = target_batch
                if remaining:
                    pool = self.proposal_source.pool(
                        rng,
                        archive,
                        max(
                            remaining,
                            remaining * max(1, int(self.sampling.get("pool_multiplier", 6))),
                        ),
                    )
                    generation_graph_pool.extend(pool)
                    selected.extend(
                        graph_policy.select(
                            pool,
                            novelty=archive.novelty,
                            rng=rng,
                            amount=remaining,
                        )
                    )

                generation_evaluations = []
                generation_mapping_records: list[
                    tuple[MappingEvaluation, Mapping[str, object]]
                ] = []
                generation_mapping_pool: list[MappingProposal] = []
                generation_weak_order_records: list[
                    WeakOrderRolloutObservation
                ] = []
                generation_specialization_records: list[
                    SpecializationPoolObservation
                ] = []
                generation_records: list[
                    tuple[GraphEvaluation, Mapping[str, object]]
                ] = []
                for candidate, selection in selected:
                    if self._output_budget_reached():
                        stop_reason = "max_training_output_bytes"
                        break
                    if self.evaluator.joint_arrangement_search_enabled:
                        evaluation = self.evaluator.evaluate_joint_arrangements(
                            candidate
                        )
                        new_mapping_observations = []
                        new_weak_order_records = []
                        new_specialization_records = []
                    elif self.mapping_sampling_enabled:
                        (
                            evaluation,
                            new_mapping_records,
                            new_weak_order_records,
                            new_mapping_pool,
                            new_specialization_records,
                        ) = (
                            self.hierarchical_policy.evaluate(
                                candidate,
                                mapping_model,
                                weak_order_model,
                                specialization_model,
                                rng,
                                generation,
                            )
                        )
                        new_mapping_observations = (
                            [item for item, _metadata in new_mapping_records]
                            if self.mapping_learning_enabled
                            else []
                        )
                        generation_mapping_records.extend(new_mapping_records)
                        generation_mapping_pool.extend(new_mapping_pool)
                        generation_weak_order_records.extend(
                            new_weak_order_records
                        )
                        generation_specialization_records.extend(
                            new_specialization_records
                        )
                    else:
                        evaluation = self.evaluator.evaluate(candidate)
                        new_mapping_observations = []
                        new_weak_order_records = []
                        new_specialization_records = []
                    mapping_observation_count += len(new_mapping_observations)
                    weak_order_rollout_count += len(new_weak_order_records)
                    specialization_pool_count += len(new_specialization_records)
                    extend_bounded_replay(
                        mapping_observations,
                        new_mapping_observations,
                        limit=min(
                            MAX_MAPPING_REPLAY_IN_MEMORY,
                            int(
                                self.mapping_learning.get(
                                    "replay_examples", 50000
                                )
                            ),
                        ),
                    )
                    extend_bounded_replay(
                        weak_order_rollouts,
                        new_weak_order_records,
                        limit=min(
                            MAX_WEAK_ORDER_REPLAY_IN_MEMORY,
                            int(
                                self.weak_order_learning.get(
                                    "replay_rollouts", 50000
                                )
                            ),
                        ),
                    )
                    extend_bounded_replay(
                        specialization_pools,
                        new_specialization_records,
                        limit=min(
                            MAX_SPECIALIZATION_REPLAY_IN_MEMORY,
                            int(
                                self.specialization_learning.get(
                                    "replay_pools", 20000
                                )
                            ),
                        ),
                    )
                    observation = evaluation.to_dict()
                    observation["generation"] = generation
                    observation["selection"] = dict(selection)
                    observation["graph_features"] = graph_feature_payload(candidate)
                    self.store.append_jsonl("observations.jsonl", observation)
                    archive.add(evaluation)
                    observations.append(evaluation)
                    generation_evaluations.append(evaluation)
                    generation_records.append((evaluation, selection))
                    if evaluation.geometry_ready:
                        self.reporter.save_geometry(evaluation, generation)
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

                feedback = read_learning_feedback(self.output)
                metrics = graph_policy.train(
                    observations,
                    generation=generation,
                    feedback=feedback,
                )
                if self.mapping_learning_enabled:
                    assert mapping_model is not None
                    mapping_metrics = mapping_model.train(
                        mapping_observations,
                        steps=int(
                            self.mapping_learning.get("steps_per_generation", 8)
                        ),
                        batch_size=int(self.mapping_learning.get("batch_size", 16)),
                        generation=generation,
                        feedback=feedback,
                    )
                    mapping_model.save(self.output / "mapping_model.pt")
                    self.store.append_jsonl(
                        "mapping_training_metrics.jsonl",
                        self.hierarchical_policy.mapping_generation_metrics(
                            generation,
                            generation_mapping_records,
                            mapping_metrics,
                        ),
                    )
                else:
                    mapping_metrics = {
                        "mode": "disabled",
                        "status": "learning_disabled",
                        "examples": len(mapping_observations),
                        "filters": {},
                        "reach": {},
                        "values": {},
                    }
                if self.weak_order_learning_enabled:
                    assert weak_order_model is not None
                    weak_order_metrics = weak_order_model.train(
                        weak_order_rollouts,
                        steps=int(
                            self.weak_order_learning.get(
                                "steps_per_generation", 8
                            )
                        ),
                        batch_size=int(
                            self.weak_order_learning.get("batch_size", 16)
                        ),
                        generation=generation,
                        feedback=feedback,
                    )
                    weak_order_model.save(
                        self.output / "weak_order_model.pt"
                    )
                    self.store.append_jsonl(
                        "weak_order_training_metrics.jsonl",
                        self.hierarchical_policy.weak_order_generation_metrics(
                            generation,
                            generation_weak_order_records,
                            weak_order_metrics,
                        ),
                    )
                else:
                    weak_order_metrics = {
                        "mode": "disabled",
                        "status": "learning_disabled",
                        "rollouts": len(weak_order_rollouts),
                        "filters": {},
                        "reach": {},
                        "values": {},
                    }
                if self.specialization_learning_enabled:
                    assert specialization_model is not None
                    specialization_metrics = specialization_model.train(
                        specialization_pools,
                        steps=int(
                            self.specialization_learning.get(
                                "steps_per_generation", 8
                            )
                        ),
                        batch_size=int(
                            self.specialization_learning.get("batch_size", 16)
                        ),
                        generation=generation,
                    )
                    specialization_model.save(
                        self.output / "specialization_model.pt"
                    )
                    self.store.append_jsonl(
                        "specialization_training_metrics.jsonl",
                        self.hierarchical_policy.specialization_generation_metrics(
                            generation,
                            generation_specialization_records,
                            specialization_metrics,
                        ),
                    )
                else:
                    specialization_metrics = {
                        "mode": "disabled",
                        "status": "learning_disabled",
                        "pools": len(specialization_pools),
                        "transitions": {},
                        "values": {},
                    }
                self.store.append_jsonl(
                    "training_metrics.jsonl",
                    self.reporter.generation_metrics(
                        generation, generation_records, metrics
                    ),
                )
                coverage = build_generation_coverage(
                    generation,
                    graph_pool=generation_graph_pool,
                    graph_records=generation_records,
                    mapping_pool=generation_mapping_pool,
                    mapping_records=generation_mapping_records,
                    weak_rollouts=generation_weak_order_records,
                    seen_graph_ids=seen_graph_ids,
                    seen_mapping_ids=seen_mapping_ids,
                    seen_trajectory_ids=seen_trajectory_ids,
                )
                self.store.append_jsonl("rollout_coverage_metrics.jsonl", coverage)
                seen_graph_ids.update(
                    evaluation.candidate.graph_id
                    for evaluation, _selection in generation_records
                )
                seen_mapping_ids.update(
                    evaluation.proposal.mapping_id
                    for evaluation, _selection in generation_mapping_records
                )
                seen_trajectory_ids.update(
                    weak_trajectory_id(rollout)
                    for rollout in generation_weak_order_records
                )
                if self._output_budget_reached():
                    stop_reason = "max_training_output_bytes"
                self.store.write_json(
                    "state.json",
                    {
                        "schema_version": "graph-lab-state-v1",
                        "fingerprint": self.fingerprint,
                        "exclude_rings": self.exclude_rings,
                        "tile_counts": list(self.space.tile_counts),
                        "stein_symmetric": self.stein_symmetric,
                        "policy_mode": self.policy_mode,
                        "outer_crown_only": self.outer_crown_only,
                        "free_outer_boundary": self.free_outer_boundary,
                        "partial_crown_tile_counts": (
                            list(self.partial_crown_tile_counts)
                            if self.partial_crown_tile_counts is not None
                            else None
                        ),
                        "prototype_symmetry_mode": self.prototype_symmetry_mode,
                        "symmetry_orders": (
                            list(self.space.symmetry_orders)
                            if self.space.symmetry_orders is not None
                            else None
                        ),
                        "next_generation": generation + 1,
                        "observations": len(observations),
                        "mapping_observations": mapping_observation_count,
                        "weak_order_rollouts": weak_order_rollout_count,
                        "specialization_pools": specialization_pool_count,
                    },
                )
                report = self.reporter.report(
                    observations,
                    graph_policy,
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
                    model_metrics=metrics,
                )
                last_generation = generation
                print(
                    f"generation {generation} complete: evaluated={len(generation_evaluations)} "
                    f"total-visits={len(observations)} "
                    f"unique-graphs={report['unique_graphs_evaluated']} "
                    f"geometry-visits={report['geometry_ready_evaluations']} "
                    f"geometry-graphs={report['geometry_ready_unique_graphs']} "
                    f"graph_examples={metrics['examples']} "
                    f"mapping_examples={mapping_metrics['examples']}",
                    f" weak_rollouts={weak_order_metrics.get('rollouts', 0)}",
                    f" specialization_pools={specialization_metrics.get('pools', 0)}",
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
            graph_policy.save()
            if mapping_model is not None:
                mapping_model.save(self.output / "mapping_model.pt")
            if weak_order_model is not None:
                weak_order_model.save(self.output / "weak_order_model.pt")
            if specialization_model is not None:
                specialization_model.save(self.output / "specialization_model.pt")
            self.reporter.report(
                observations,
                graph_policy,
                last_generation,
                stop_reason=stop_reason,
            )

        geometry_graphs = len(
            {
                item.candidate.graph_id
                for item in observations
                if item.stage_index >= len(GRAPH_STAGES) - 1
            }
        )
        return GraphLabResult(
            output_directory=self.output,
            generations_completed=max(0, last_generation + 1),
            observations=len(observations),
            geometry_ready_graphs=geometry_graphs,
            stop_reason=stop_reason,
        )
