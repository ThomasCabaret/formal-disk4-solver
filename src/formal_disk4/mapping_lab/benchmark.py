from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from formal_disk4.maps.base import PlanarMap

from .neural import NeuralStageModel, NeuralTrainingDataset


BENCHMARK_VERSION = "mapping-lab-positive-control-v1"
STAGE_NAMES = (
    "enumerated_placement",
    "preword_pass",
    "word_family",
    "formal_profile",
)
TRANSITION_STAGES = (1, 2, 3)


@dataclass(frozen=True)
class PlacementDataset:
    """Exact labels recovered from the production solver's audit streams."""

    candidate_ids: tuple[str, ...]
    assignment_ids: np.ndarray
    features: np.ndarray
    stages: np.ndarray
    feature_names: tuple[str, ...]

    @property
    def size(self) -> int:
        return int(len(self.stages))

    @property
    def input_dimension(self) -> int:
        return int(self.features.shape[1])

    def stage_histogram(self) -> dict[str, int]:
        return {
            STAGE_NAMES[index]: int(np.count_nonzero(self.stages == index))
            for index in range(len(STAGE_NAMES))
        }

    def passage_summary(self) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for target in TRANSITION_STAGES:
            eligible = self.stages >= target - 1
            passed = self.stages >= target
            denominator = int(np.count_nonzero(eligible))
            numerator = int(np.count_nonzero(eligible & passed))
            result.append(
                {
                    "from": STAGE_NAMES[target - 1],
                    "to": STAGE_NAMES[target],
                    "eligible": denominator,
                    "passed": numerator,
                    "conditional_rate": (
                        numerator / denominator if denominator else None
                    ),
                }
            )
        return result

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as stream:
            np.savez_compressed(
                stream,
                schema_version=np.asarray(BENCHMARK_VERSION),
                candidate_ids=np.asarray(self.candidate_ids),
                assignment_ids=self.assignment_ids,
                features=self.features,
                stages=self.stages,
                feature_names=np.asarray(self.feature_names),
            )
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path) -> "PlacementDataset":
        with np.load(path, allow_pickle=False) as payload:
            version = str(payload["schema_version"].item())
            if version != BENCHMARK_VERSION:
                raise ValueError(f"Unsupported positive-control dataset {version!r}")
            return cls(
                candidate_ids=tuple(str(value) for value in payload["candidate_ids"]),
                assignment_ids=payload["assignment_ids"].astype(np.int32),
                features=payload["features"].astype(np.float32),
                stages=payload["stages"].astype(np.int16),
                feature_names=tuple(str(value) for value in payload["feature_names"]),
            )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON at {path}:{line_number}") from error
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object at {path}:{line_number}")
            records.append(value)
    return records


def _placement_key(record: Mapping[str, Any]) -> tuple[int, int]:
    if "assignment_id" in record and "placement_id" in record:
        return int(record["assignment_id"]), int(record["placement_id"])
    assignment = record["assignment"]
    placement = record["placement"]
    return int(assignment["assignment_id"]), int(placement["placement_id"])


def _feature_names(planar_map: PlanarMap) -> tuple[str, ...]:
    names = [f"position:{item.name}" for item in planar_map.occurrences()]
    for piece in planar_map.pieces:
        names.extend(
            (
                f"orientation:{piece.name}",
                f"offset_sin:{piece.name}",
                f"offset_cos:{piece.name}",
            )
        )
    names.extend(("block_count", "length_margin", "angle_margin"))
    return tuple(names)


def placement_feature_vector(
    planar_map: PlanarMap, record: Mapping[str, Any]
) -> np.ndarray:
    """Features available after a weak order has passed length and angle LPs."""

    assignment = record["assignment"]
    placement = record["placement"]
    blocks = placement["blocks"]
    occurrence_names = tuple(item.name for item in planar_map.occurrences())
    positions: dict[str, int] = {}
    for block_index, block in enumerate(blocks):
        for occurrence in block:
            name = str(occurrence)
            if name in positions:
                raise ValueError(f"Occurrence {name!r} appears in multiple blocks")
            positions[name] = block_index
    missing = set(occurrence_names) - positions.keys()
    extra = positions.keys() - set(occurrence_names)
    if missing or extra:
        raise ValueError(
            f"Placement occurrence mismatch: missing={sorted(missing)}, extra={sorted(extra)}"
        )
    block_count = len(blocks)
    denominator = max(1, block_count - 1)
    features = [
        2.0 * positions[name] / denominator - 1.0 for name in occurrence_names
    ]
    orientation_signs = dict(assignment["orientation_signs"])
    cyclic_offsets = dict(assignment["cyclic_offsets"])
    for piece in planar_map.pieces:
        features.append(float(orientation_signs[piece.name]))
        period = len(piece.contour_vertices)
        angle = 2.0 * math.pi * int(cyclic_offsets[piece.name]) / period
        features.extend((math.sin(angle), math.cos(angle)))
    features.extend(
        (
            block_count / max(1, len(occurrence_names)),
            float(placement.get("length_margin", 0.0)),
            float(placement.get("angle_margin", 0.0)),
        )
    )
    return np.asarray(features, dtype=np.float32)


def load_exact_placement_dataset(
    planar_map: PlanarMap, collection_directory: Path
) -> tuple[PlacementDataset, dict[str, object]]:
    """Join exact placement, pre-word/word, and survivor audit streams."""

    placement_path = collection_directory / "placements.jsonl"
    audit_path = collection_directory / "word_case_audit.jsonl"
    candidate_path = collection_directory / "candidates.jsonl"
    for path in (placement_path, audit_path, candidate_path):
        if not path.exists():
            raise FileNotFoundError(
                f"Required positive-control trace is missing: {path}"
            )

    audits: dict[tuple[int, int], dict[str, Any]] = {}
    for record in _read_jsonl(audit_path):
        audits[_placement_key(record)] = record
    profile_keys = {
        _placement_key(record) for record in _read_jsonl(candidate_path)
    }

    placements: dict[tuple[int, int], dict[str, Any]] = {}
    duplicate_placements = 0
    for record in _read_jsonl(placement_path):
        key = _placement_key(record)
        if key in placements:
            duplicate_placements += 1
        placements[key] = record
    orphan_audits = sorted(set(audits) - set(placements))
    orphan_profiles = sorted(profile_keys - set(placements))
    if orphan_audits or orphan_profiles:
        raise ValueError(
            "Audit streams contain unknown placements: "
            f"audits={orphan_audits[:5]}, profiles={orphan_profiles[:5]}"
        )

    ids: list[str] = []
    assignments: list[int] = []
    feature_rows: list[np.ndarray] = []
    stages: list[int] = []
    for key, record in sorted(placements.items()):
        assignment_id, placement_id = key
        stage = 0
        audit = audits.get(key)
        if audit is not None:
            stage = 1
            if int(audit.get("family_count", 0)) > 0:
                stage = 2
        if key in profile_keys:
            stage = 3
        ids.append(f"{planar_map.name}:a{assignment_id}:p{placement_id}")
        assignments.append(assignment_id)
        feature_rows.append(placement_feature_vector(planar_map, record))
        stages.append(stage)

    names = _feature_names(planar_map)
    features = (
        np.stack(feature_rows).astype(np.float32, copy=False)
        if feature_rows
        else np.empty((0, len(names)), dtype=np.float32)
    )
    dataset = PlacementDataset(
        candidate_ids=tuple(ids),
        assignment_ids=np.asarray(assignments, dtype=np.int32),
        features=features,
        stages=np.asarray(stages, dtype=np.int16),
        feature_names=names,
    )
    return dataset, {
        "placements": dataset.size,
        "word_case_audits": len(audits),
        "profile_placements": len(profile_keys),
        "duplicate_placement_records_removed": duplicate_placements,
        "stage_histogram": dataset.stage_histogram(),
        "passage_rates": dataset.passage_summary(),
    }


def _split_dataset(
    dataset: PlacementDataset, validation_assignments: Sequence[int]
) -> tuple[np.ndarray, np.ndarray]:
    validation_ids = {int(value) for value in validation_assignments}
    if validation_ids:
        validation = np.asarray(
            [int(value) in validation_ids for value in dataset.assignment_ids],
            dtype=bool,
        )
    else:
        validation = np.zeros(dataset.size, dtype=bool)
    if not np.any(validation) or np.all(validation):
        # A deliberately truncated smoke collection may not yet contain the
        # configured held-out assignments. Fall back to a stable row split for
        # diagnostics; the full control still uses assignment-level holdout.
        validation = np.asarray(
            [
                hashlib.sha256(value.encode("utf-8")).digest()[0] < 51
                for value in dataset.candidate_ids
            ],
            dtype=bool,
        )
    if dataset.size >= 2 and (not np.any(validation) or np.all(validation)):
        validation[:] = False
        validation[-1] = True
    training = ~validation
    if not np.any(training) or not np.any(validation):
        raise ValueError("The positive-control split needs nonempty train and validation sets")
    return training, validation


def _neural_dataset(
    dataset: PlacementDataset,
    training_indexes: np.ndarray,
    validation_indexes: np.ndarray,
) -> NeuralTrainingDataset:
    all_stages = dataset.stages[np.concatenate((training_indexes, validation_indexes))]
    return NeuralTrainingDataset(
        train_features=dataset.features[training_indexes],
        train_stages=dataset.stages[training_indexes],
        validation_features=dataset.features[validation_indexes],
        validation_stages=dataset.stages[validation_indexes],
        stage_histogram={
            int(stage): int(np.count_nonzero(all_stages == stage))
            for stage in np.unique(all_stages)
        },
    )


def _new_model(
    input_dimension: int, config: Mapping[str, Any], *, seed: int
) -> NeuralStageModel:
    return NeuralStageModel(
        input_dimension,
        TRANSITION_STAGES,
        tuple(int(value) for value in config.get("hidden_layers", (128, 64))),
        seed=seed,
        learning_rate=float(config.get("learning_rate", 0.001)),
        l2=float(config.get("l2", 1e-5)),
    )


def _auc(targets: np.ndarray, scores: np.ndarray) -> float | None:
    targets = np.asarray(targets, dtype=bool)
    return NeuralStageModel._auc(targets, np.asarray(scores, dtype=np.float64))


def _ranking_metrics(
    model: NeuralStageModel,
    features: np.ndarray,
    stages: np.ndarray,
    fractions: Sequence[float],
) -> dict[str, object]:
    probabilities = model.predict_probabilities(features)
    cumulative = np.cumprod(probabilities, axis=1)
    result: dict[str, object] = {}
    for head, target in enumerate(TRANSITION_STAGES):
        labels = stages >= target
        scores = cumulative[:, head]
        positives = int(np.count_nonzero(labels))
        base_rate = positives / len(labels) if len(labels) else None
        top: dict[str, object] = {}
        order = np.argsort(-scores, kind="mergesort")
        for raw_fraction in fractions:
            fraction = float(raw_fraction)
            count = max(1, min(len(labels), int(math.ceil(fraction * len(labels)))))
            selected_positives = int(np.count_nonzero(labels[order[:count]]))
            rate = selected_positives / count
            top[f"{fraction:.3g}"] = {
                "count": count,
                "positives": selected_positives,
                "rate": rate,
                "uplift_vs_base": (
                    rate / base_rate if base_rate not in (None, 0.0) else None
                ),
                "recall": selected_positives / positives if positives else None,
            }
        result[STAGE_NAMES[target]] = {
            "positives": positives,
            "examples": int(len(labels)),
            "base_rate": base_rate,
            "auc": _auc(labels, scores),
            "top_fractions": top,
        }
    return result


def _discovery_counts(stages: np.ndarray) -> dict[str, int]:
    return {
        STAGE_NAMES[target]: int(np.count_nonzero(stages >= target))
        for target in TRANSITION_STAGES
    }


def _unit_spaced_area(values: np.ndarray) -> float:
    if len(values) <= 1:
        return 0.0
    return float(np.sum((values[:-1] + values[1:]) * 0.5))


def _select_by_model(
    model: NeuralStageModel,
    features: np.ndarray,
    remaining: np.ndarray,
    count: int,
    exploration_fraction: float,
    rng: np.random.Generator,
) -> np.ndarray:
    if len(remaining) <= count:
        return remaining
    active = np.flatnonzero(model.active_heads)
    if not len(active):
        return rng.choice(remaining, size=count, replace=False)
    deepest = int(active[-1])
    probabilities = model.predict_probabilities(features[remaining])
    scores = np.prod(probabilities[:, : deepest + 1], axis=1)
    explore_count = min(count, max(1, int(round(count * exploration_fraction))))
    exploit_count = count - explore_count
    ranked = remaining[np.argsort(-scores, kind="mergesort")]
    exploit = ranked[:exploit_count]
    exploration_pool = ranked[exploit_count:]
    explore = rng.choice(exploration_pool, size=explore_count, replace=False)
    return np.concatenate((exploit, explore))


def _replay_once(
    dataset: PlacementDataset,
    training_indexes: np.ndarray,
    validation_indexes: np.ndarray,
    backend_config: Mapping[str, Any],
    replay_config: Mapping[str, Any],
    *,
    seed: int,
) -> dict[str, object]:
    rng = np.random.default_rng(seed)
    order = rng.permutation(training_indexes)
    warmup = min(len(order), max(1, int(replay_config.get("warmup", 128))))
    shared = order[:warmup]
    learned_observed = list(int(value) for value in shared)
    uniform_observed = list(int(value) for value in shared)
    learned_remaining = np.asarray(order[warmup:], dtype=np.int64)
    uniform_remaining = learned_remaining.copy()
    rng.shuffle(uniform_remaining)
    batch_size = max(1, int(replay_config.get("batch_size", 32)))
    rounds = max(0, int(replay_config.get("rounds", 32)))
    initial_steps = max(0, int(replay_config.get("initial_training_steps", 200)))
    steps_per_round = max(0, int(replay_config.get("steps_per_round", 8)))
    exploration = min(1.0, max(0.0, float(replay_config.get("exploration_fraction", 0.15))))
    model = _new_model(dataset.input_dimension, backend_config, seed=seed)

    def train(steps: int, round_index: int) -> None:
        observed = np.asarray(learned_observed, dtype=np.int64)
        neural = _neural_dataset(dataset, observed, validation_indexes)
        model.train(
            neural,
            steps=steps,
            batch_size=int(backend_config.get("batch_size", 256)),
            seed=seed + round_index * 104729,
        )

    train(initial_steps, 0)
    curve: list[dict[str, object]] = []

    def snapshot(round_index: int) -> None:
        curve.append(
            {
                "round": round_index,
                "budget": len(learned_observed),
                "learned": _discovery_counts(
                    dataset.stages[np.asarray(learned_observed, dtype=np.int64)]
                ),
                "uniform": _discovery_counts(
                    dataset.stages[np.asarray(uniform_observed, dtype=np.int64)]
                ),
                "active_heads": [
                    STAGE_NAMES[TRANSITION_STAGES[index]]
                    for index in np.flatnonzero(model.active_heads)
                ],
            }
        )

    snapshot(0)
    for round_index in range(1, rounds + 1):
        if not len(learned_remaining):
            break
        count = min(batch_size, len(learned_remaining))
        selected = _select_by_model(
            model,
            dataset.features,
            learned_remaining,
            count,
            exploration,
            rng,
        )
        selected_set = set(int(value) for value in selected)
        learned_observed.extend(int(value) for value in selected)
        learned_remaining = np.asarray(
            [value for value in learned_remaining if int(value) not in selected_set],
            dtype=np.int64,
        )
        uniform_observed.extend(int(value) for value in uniform_remaining[:count])
        uniform_remaining = uniform_remaining[count:]
        train(steps_per_round, round_index)
        snapshot(round_index)

    area: dict[str, object] = {}
    for target in TRANSITION_STAGES:
        name = STAGE_NAMES[target]
        learned_values = np.asarray(
            [int(item["learned"][name]) for item in curve], dtype=np.float64
        )
        uniform_values = np.asarray(
            [int(item["uniform"][name]) for item in curve], dtype=np.float64
        )
        learned_area = _unit_spaced_area(learned_values)
        uniform_area = _unit_spaced_area(uniform_values)
        area[name] = {
            "learned": learned_area,
            "uniform": uniform_area,
            "ratio": learned_area / uniform_area if uniform_area else None,
        }
    return {"seed": seed, "curve": curve, "discovery_area": area}


def _mean_replay(replays: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    summary: dict[str, object] = {}
    for target in TRANSITION_STAGES:
        name = STAGE_NAMES[target]
        ratios = [
            float(item["discovery_area"][name]["ratio"])
            for item in replays
            if item["discovery_area"][name]["ratio"] is not None
        ]
        final_learned = [int(item["curve"][-1]["learned"][name]) for item in replays]
        final_uniform = [int(item["curve"][-1]["uniform"][name]) for item in replays]
        summary[name] = {
            "mean_discovery_area_ratio": float(np.mean(ratios)) if ratios else None,
            "final_learned_mean": float(np.mean(final_learned)),
            "final_uniform_mean": float(np.mean(final_uniform)),
        }
    return summary


def run_learning_benchmark(
    dataset: PlacementDataset,
    config: Mapping[str, Any],
    output_directory: Path,
) -> dict[str, object]:
    if dataset.size == 0:
        raise ValueError("The positive-control dataset is empty")
    split_config = dict(config.get("split", {}))
    training_mask, validation_mask = _split_dataset(
        dataset, tuple(split_config.get("validation_assignments", ()))
    )
    training_indexes = np.flatnonzero(training_mask)
    validation_indexes = np.flatnonzero(validation_mask)
    backend_config = dict(config.get("backend", {}))
    seed = int(backend_config.get("seed", 20260809))
    neural = _neural_dataset(dataset, training_indexes, validation_indexes)
    model = _new_model(dataset.input_dimension, backend_config, seed=seed)
    offline_metrics = model.train(
        neural,
        steps=max(0, int(backend_config.get("offline_steps", 1000))),
        batch_size=max(1, int(backend_config.get("batch_size", 256))),
        seed=seed,
    )
    ranking = _ranking_metrics(
        model,
        dataset.features[validation_indexes],
        dataset.stages[validation_indexes],
        tuple(config.get("ranking_fractions", (0.05, 0.1, 0.25))),
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    model.save(output_directory / "offline_model.npz")

    replay_config = dict(config.get("replay", {}))
    replay_seeds = tuple(int(value) for value in replay_config.get("seeds", (seed,)))
    replays = [
        _replay_once(
            dataset,
            training_indexes,
            validation_indexes,
            backend_config,
            replay_config,
            seed=replay_seed,
        )
        for replay_seed in replay_seeds
    ]
    replay_summary = _mean_replay(replays)

    profile_auc = ranking["formal_profile"]["auc"]
    profile_area = replay_summary["formal_profile"]["mean_discovery_area_ratio"]
    word_auc = ranking["word_family"]["auc"]
    if (
        word_auc is not None
        and word_auc >= 0.70
        and profile_auc is not None
        and profile_auc >= 0.65
        and profile_area is not None
        and profile_area > 1.05
    ):
        verdict = "learning_signal_and_online_enrichment"
    elif word_auc is not None and word_auc >= 0.70:
        verdict = "offline_signal_but_no_proven_online_profile_enrichment"
    else:
        verdict = "positive_control_not_learned"

    return {
        "schema_version": BENCHMARK_VERSION,
        "verdict": verdict,
        "dataset": {
            "examples": dataset.size,
            "feature_dimension": dataset.input_dimension,
            "stage_histogram": dataset.stage_histogram(),
            "passage_rates": dataset.passage_summary(),
            "training_examples": int(len(training_indexes)),
            "validation_examples": int(len(validation_indexes)),
            "training_assignments": sorted(
                set(int(value) for value in dataset.assignment_ids[training_indexes])
            ),
            "validation_assignments": sorted(
                set(int(value) for value in dataset.assignment_ids[validation_indexes])
            ),
        },
        "offline": {
            "conditional_metrics": offline_metrics,
            "unconditional_ranking": ranking,
        },
        "online_replay": {
            "summary": replay_summary,
            "runs": replays,
        },
    }


def write_benchmark_report(output: Path, report: Mapping[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "report.json"
    temporary = json_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(json_path)

    dataset = report["dataset"]
    ranking = report["offline"]["unconditional_ranking"]
    replay = report["online_replay"]["summary"]
    lines = [
        "# Mapping Lab positive control",
        "",
        f"Verdict: **{report['verdict']}**",
        "",
        "This benchmark uses exact labels emitted by the production solver. The validation",
        "set holds out complete contour assignments, and the online replay never sees a",
        "label before selecting that placement.",
        "",
        "## Dataset",
        "",
        f"- Examples: {dataset['examples']}",
        f"- Feature dimension: {dataset['feature_dimension']}",
        f"- Train/validation: {dataset['training_examples']} / {dataset['validation_examples']}",
        f"- Validation assignments: {dataset['validation_assignments']}",
        "",
        "| Exact terminal stage | Count |",
        "|---|---:|",
    ]
    for name, count in dataset["stage_histogram"].items():
        lines.append(f"| {name} | {count} |")
    lines.extend(
        [
            "",
            "## Held-out ranking",
            "",
            "AUC measures ordering quality (0.5 is random, 1.0 is perfect). The uplift",
            "compares the positive rate in the best 10% scored placements with the full",
            "held-out positive rate.",
            "",
            "| Target | AUC | Top-10% uplift |",
            "|---|---:|---:|",
        ]
    )
    for name, values in ranking.items():
        auc = values["auc"]
        top = values["top_fractions"].get("0.1", {})
        uplift = top.get("uplift_vs_base")
        lines.append(
            f"| {name} | {auc if auc is not None else 'n/a'} | "
            f"{uplift if uplift is not None else 'n/a'} |"
        )
    lines.extend(
        [
            "",
            "## Online replay",
            "",
            "The discovery-area ratio compares cumulative discoveries at every common",
            "budget. A value above 1 means the learner finds useful placements earlier",
            "than uniform sampling.",
            "",
            "| Target | Mean discovery-area ratio | Final learned | Final uniform |",
            "|---|---:|---:|---:|",
        ]
    )
    for name, values in replay.items():
        lines.append(
            f"| {name} | {values['mean_discovery_area_ratio']} | "
            f"{values['final_learned_mean']} | {values['final_uniform_mean']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- If held-out AUC is good but online enrichment is not, the representation",
            "  contains signal but the acquisition/training loop needs work.",
            "- If even held-out AUC stays near 0.5, the present features/model do not",
            "  extract the known signal on this positive control.",
            "- Success here validates the lab machinery, not transfer to wheel-6; that",
            "  remains a separate and substantially harder distribution.",
            "",
        ]
    )
    markdown_path = output / "report.md"
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
