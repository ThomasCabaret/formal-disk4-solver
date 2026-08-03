from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from .backend import ObservationBatch


MODEL_VERSION = "mapping-lab-neural-v2"


@dataclass
class NeuralTrainingDataset:
    train_features: np.ndarray
    train_stages: np.ndarray
    validation_features: np.ndarray
    validation_stages: np.ndarray
    stage_histogram: dict[int, int]

    @classmethod
    def empty(cls, input_dimension: int) -> "NeuralTrainingDataset":
        empty_features = np.empty((0, int(input_dimension)), dtype=np.float32)
        empty_stages = np.empty(0, dtype=np.int16)
        return cls(
            train_features=empty_features.copy(),
            train_stages=empty_stages.copy(),
            validation_features=empty_features.copy(),
            validation_stages=empty_stages.copy(),
            stage_histogram={},
        )

    @property
    def input_dimension(self) -> int:
        source = (
            self.train_features
            if len(self.train_features)
            else self.validation_features
        )
        return int(source.shape[1])

    @property
    def training_size(self) -> int:
        return int(len(self.train_stages))

    @property
    def validation_size(self) -> int:
        return int(len(self.validation_stages))

    def sample_indices(
        self, rng: np.random.Generator, batch_size: int
    ) -> np.ndarray:
        size = self.training_size
        if size == 0:
            return np.empty(0, dtype=np.int64)
        count = max(1, int(batch_size))
        random_count = count // 2
        random_part = rng.integers(0, size, size=random_count, dtype=np.int64)
        buckets = {
            stage: np.flatnonzero(self.train_stages == stage)
            for stage in np.unique(self.train_stages)
        }
        nonempty = tuple(bucket for bucket in buckets.values() if len(bucket))
        stratified: list[int] = []
        for _ in range(count - random_count):
            bucket = nonempty[int(rng.integers(0, len(nonempty)))]
            stratified.append(int(bucket[int(rng.integers(0, len(bucket)))]))
        return np.concatenate(
            (random_part, np.asarray(stratified, dtype=np.int64))
        )

    @staticmethod
    def _trim_partition(
        features: np.ndarray,
        stages: np.ndarray,
        *,
        capacity_per_stage: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        retained: list[np.ndarray] = []
        for stage in np.unique(stages):
            indexes = np.flatnonzero(stages == stage)
            retained.append(indexes[-capacity_per_stage:])
        if not retained:
            return features[:0], stages[:0]
        indexes = np.sort(np.concatenate(retained))
        return features[indexes], stages[indexes]

    def add(
        self,
        candidate_ids: Sequence[str],
        features: np.ndarray,
        stages: np.ndarray,
        *,
        max_examples_per_stage: int,
    ) -> None:
        array = np.asarray(features, dtype=np.float32)
        terminal = np.asarray(stages, dtype=np.int16)
        if len(candidate_ids) != len(array) or len(array) != len(terminal):
            raise ValueError("candidate ids, features and stages must have equal lengths")
        if not len(terminal):
            return
        if array.ndim != 2 or array.shape[1] != self.input_dimension:
            raise ValueError("observation feature dimension does not match the dataset")
        validation = np.asarray(
            [_validation_partition(candidate_id) for candidate_id in candidate_ids],
            dtype=bool,
        )
        train_capacity = max(1, int(round(max_examples_per_stage * 0.8)))
        validation_capacity = max(1, int(max_examples_per_stage) - train_capacity)
        self.train_features = np.concatenate(
            (self.train_features, array[~validation]), axis=0
        )
        self.train_stages = np.concatenate(
            (self.train_stages, terminal[~validation]), axis=0
        )
        self.validation_features = np.concatenate(
            (self.validation_features, array[validation]), axis=0
        )
        self.validation_stages = np.concatenate(
            (self.validation_stages, terminal[validation]), axis=0
        )
        self.train_features, self.train_stages = self._trim_partition(
            self.train_features,
            self.train_stages,
            capacity_per_stage=train_capacity,
        )
        self.validation_features, self.validation_stages = self._trim_partition(
            self.validation_features,
            self.validation_stages,
            capacity_per_stage=validation_capacity,
        )
        all_stages = np.concatenate((self.train_stages, self.validation_stages))
        self.stage_histogram = {
            int(stage): int(np.count_nonzero(all_stages == stage))
            for stage in np.unique(all_stages)
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        histogram_stages = np.asarray(sorted(self.stage_histogram), dtype=np.int16)
        histogram_counts = np.asarray(
            [self.stage_histogram[int(stage)] for stage in histogram_stages],
            dtype=np.int64,
        )
        with temporary.open("wb") as stream:
            np.savez_compressed(
                stream,
                model_version=np.asarray(MODEL_VERSION),
                train_features=self.train_features,
                train_stages=self.train_stages,
                validation_features=self.validation_features,
                validation_stages=self.validation_stages,
                histogram_stages=histogram_stages,
                histogram_counts=histogram_counts,
            )
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path) -> "NeuralTrainingDataset":
        with np.load(path, allow_pickle=False) as payload:
            version = str(payload["model_version"].item())
            if version != MODEL_VERSION:
                raise ValueError(f"unsupported neural dataset version {version!r}")
            histogram = {
                int(stage): int(count)
                for stage, count in zip(
                    payload["histogram_stages"], payload["histogram_counts"]
                )
            }
            return cls(
                train_features=payload["train_features"].astype(np.float32),
                train_stages=payload["train_stages"].astype(np.int16),
                validation_features=payload["validation_features"].astype(
                    np.float32
                ),
                validation_stages=payload["validation_stages"].astype(np.int16),
                stage_histogram=histogram,
            )


def _validation_partition(candidate_id: str) -> bool:
    digest = hashlib.sha256(candidate_id.encode("utf-8")).digest()
    return digest[0] < 51  # stable approximately 20 percent split


def load_training_dataset(
    paths: Sequence[Path],
    *,
    feature_builder: Any,
    max_examples_per_stage: int,
    seed: int,
    input_dimension: int,
) -> tuple[NeuralTrainingDataset, dict[str, int]]:
    """Stream and stratify large JSONL histories without retaining all records."""
    capacity = max(1, int(max_examples_per_stage))
    rng = random.Random(int(seed))
    reservoirs: dict[int, list[tuple[str, tuple[int, ...]]]] = {}
    stage_seen: dict[int, int] = {}
    candidate_ids: set[str] = set()
    scanned = 0
    invalid = 0
    duplicates = 0
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                    candidate_id = str(payload["candidate_id"])
                    stage = int(payload["stage_index"])
                    masks = tuple(int(value) for value in payload["masks"])
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    invalid += 1
                    continue
                scanned += 1
                if candidate_id in candidate_ids:
                    duplicates += 1
                    continue
                candidate_ids.add(candidate_id)
                seen = stage_seen.get(stage, 0) + 1
                stage_seen[stage] = seen
                bucket = reservoirs.setdefault(stage, [])
                item = (candidate_id, masks)
                if len(bucket) < capacity:
                    bucket.append(item)
                else:
                    replacement = rng.randrange(seen)
                    if replacement < capacity:
                        bucket[replacement] = item

    train_features: list[np.ndarray] = []
    train_stages: list[int] = []
    validation_features: list[np.ndarray] = []
    validation_stages: list[int] = []
    retained_histogram: dict[int, int] = {}
    for stage, bucket in sorted(reservoirs.items()):
        retained_histogram[stage] = len(bucket)
        for candidate_id, masks in bucket:
            try:
                features = np.asarray(feature_builder(masks), dtype=np.float32)
            except (TypeError, ValueError):
                invalid += 1
                continue
            if _validation_partition(candidate_id):
                validation_features.append(features)
                validation_stages.append(stage)
            else:
                train_features.append(features)
                train_stages.append(stage)

    feature_dimension = (
        len((train_features or validation_features)[0])
        if train_features or validation_features
        else int(input_dimension)
    )

    def feature_array(values: list[np.ndarray]) -> np.ndarray:
        if not values:
            return np.empty((0, feature_dimension), dtype=np.float32)
        return np.stack(values).astype(np.float32, copy=False)

    dataset = NeuralTrainingDataset(
        train_features=feature_array(train_features),
        train_stages=np.asarray(train_stages, dtype=np.int16),
        validation_features=feature_array(validation_features),
        validation_stages=np.asarray(validation_stages, dtype=np.int16),
        stage_histogram=retained_histogram,
    )
    return dataset, {
        "scanned": scanned,
        "duplicates": duplicates,
        "invalid": invalid,
        "retained": dataset.training_size + dataset.validation_size,
        "training": dataset.training_size,
        "validation": dataset.validation_size,
    }


class NeuralStageModel:
    """Small shared MLP with one conditional binary head per filter transition."""

    def __init__(
        self,
        input_dimension: int,
        transition_stages: Sequence[int],
        hidden_layers: Sequence[int],
        *,
        seed: int,
        learning_rate: float,
        l2: float,
    ) -> None:
        hidden = tuple(int(value) for value in hidden_layers)
        if len(hidden) != 2 or any(value <= 0 for value in hidden):
            raise ValueError("neural hidden_layers must contain two positive sizes")
        self.input_dimension = int(input_dimension)
        self.transition_stages = tuple(int(value) for value in transition_stages)
        self.hidden_layers = hidden
        self.learning_rate = float(learning_rate)
        self.l2 = max(0.0, float(l2))
        rng = np.random.default_rng(int(seed))
        h1, h2 = hidden
        output = len(self.transition_stages)
        self.parameters = {
            "w1": rng.normal(
                0.0, math.sqrt(2.0 / self.input_dimension),
                (self.input_dimension, h1),
            ).astype(np.float32),
            "b1": np.zeros(h1, dtype=np.float32),
            "w2": rng.normal(0.0, math.sqrt(2.0 / h1), (h1, h2)).astype(
                np.float32
            ),
            "b2": np.zeros(h2, dtype=np.float32),
            "wo": rng.normal(0.0, math.sqrt(1.0 / h2), (h2, output)).astype(
                np.float32
            ),
            "bo": np.zeros(output, dtype=np.float32),
        }
        self.first_moment = {
            name: np.zeros_like(value) for name, value in self.parameters.items()
        }
        self.second_moment = {
            name: np.zeros_like(value) for name, value in self.parameters.items()
        }
        self.optimizer_step = 0
        self.active_heads = np.zeros(output, dtype=bool)
        self.empirical_rates = np.full(output, 0.5, dtype=np.float32)

    @staticmethod
    def _sigmoid(values: np.ndarray) -> np.ndarray:
        clipped = np.clip(values, -30.0, 30.0)
        return 1.0 / (1.0 + np.exp(-clipped))

    def _forward(
        self, features: np.ndarray
    ) -> tuple[np.ndarray, tuple[np.ndarray, np.ndarray]]:
        hidden1 = np.maximum(
            0.0, features @ self.parameters["w1"] + self.parameters["b1"]
        )
        hidden2 = np.maximum(
            0.0, hidden1 @ self.parameters["w2"] + self.parameters["b2"]
        )
        logits = hidden2 @ self.parameters["wo"] + self.parameters["bo"]
        return logits, (hidden1, hidden2)

    def predict_probabilities(self, features: np.ndarray) -> np.ndarray:
        array = np.asarray(features, dtype=np.float32)
        if array.ndim == 1:
            array = array.reshape(1, -1)
        logits, _ = self._forward(array)
        probabilities = self._sigmoid(logits)
        for index, active in enumerate(self.active_heads):
            if not active:
                probabilities[:, index] = self.empirical_rates[index]
        return probabilities

    def utilities(self, features: np.ndarray) -> np.ndarray:
        """Expected filter depth from conditional pass probabilities."""
        probabilities = self.predict_probabilities(features)
        reach = np.ones(len(probabilities), dtype=np.float32)
        utility = np.full(len(probabilities), 3.0, dtype=np.float32)
        for index in range(len(self.transition_stages)):
            reach *= probabilities[:, index]
            utility += reach
        return utility

    def _head_statistics(
        self, stages: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        positives = []
        negatives = []
        eligible_counts = []
        for target in self.transition_stages:
            eligible = stages >= target - 1
            positive = stages >= target
            positives.append(int(np.count_nonzero(eligible & positive)))
            negatives.append(int(np.count_nonzero(eligible & ~positive)))
            eligible_counts.append(int(np.count_nonzero(eligible)))
        return (
            np.asarray(positives, dtype=np.int64),
            np.asarray(negatives, dtype=np.int64),
            np.asarray(eligible_counts, dtype=np.int64),
        )

    def refresh_head_statistics(self, stages: np.ndarray) -> None:
        positives, negatives, eligible = self._head_statistics(stages)
        self.active_heads = (positives > 0) & (negatives > 0)
        self.empirical_rates = np.divide(
            positives + 0.5,
            eligible + 1.0,
            out=np.full(len(eligible), 0.5, dtype=np.float64),
            where=eligible >= 0,
        ).astype(np.float32)

    def train(
        self,
        dataset: NeuralTrainingDataset,
        *,
        steps: int,
        batch_size: int,
        seed: int,
    ) -> dict[str, Any]:
        if dataset.training_size == 0 or steps <= 0:
            self.refresh_head_statistics(dataset.train_stages)
            return self.metrics(dataset)
        statistic_stages = dataset.train_stages
        self.refresh_head_statistics(statistic_stages)
        positives, negatives, _ = self._head_statistics(statistic_stages)
        rng = np.random.default_rng(int(seed))
        losses: list[float] = []
        for _ in range(int(steps)):
            indexes = dataset.sample_indices(rng, batch_size)
            features = dataset.train_features[indexes]
            stages = dataset.train_stages[indexes]
            logits, (hidden1, hidden2) = self._forward(features)
            probabilities = self._sigmoid(logits)
            gradient_logits = np.zeros_like(probabilities)
            loss = 0.0
            active_count = max(1, int(np.count_nonzero(self.active_heads)))
            for head, target in enumerate(self.transition_stages):
                if not self.active_heads[head]:
                    continue
                eligible = stages >= target - 1
                if not np.any(eligible):
                    continue
                targets = (stages[eligible] >= target).astype(np.float32)
                positive_weight = (positives[head] + negatives[head]) / (
                    2.0 * positives[head]
                )
                negative_weight = (positives[head] + negatives[head]) / (
                    2.0 * negatives[head]
                )
                weights = np.where(
                    targets > 0.5, positive_weight, negative_weight
                ).astype(np.float32)
                predicted = probabilities[eligible, head]
                loss -= float(
                    np.mean(
                        weights
                        * (
                            targets * np.log(np.maximum(predicted, 1e-7))
                            + (1.0 - targets)
                            * np.log(np.maximum(1.0 - predicted, 1e-7))
                        )
                    )
                ) / active_count
                gradient_logits[eligible, head] = (
                    (predicted - targets)
                    * weights
                    / max(1, int(np.count_nonzero(eligible)))
                    / active_count
                )
            gradients: dict[str, np.ndarray] = {}
            gradients["wo"] = hidden2.T @ gradient_logits + self.l2 * self.parameters["wo"]
            gradients["bo"] = gradient_logits.sum(axis=0)
            gradient_hidden2 = gradient_logits @ self.parameters["wo"].T
            gradient_hidden2[hidden2 <= 0] = 0
            gradients["w2"] = hidden1.T @ gradient_hidden2 + self.l2 * self.parameters["w2"]
            gradients["b2"] = gradient_hidden2.sum(axis=0)
            gradient_hidden1 = gradient_hidden2 @ self.parameters["w2"].T
            gradient_hidden1[hidden1 <= 0] = 0
            gradients["w1"] = features.T @ gradient_hidden1 + self.l2 * self.parameters["w1"]
            gradients["b1"] = gradient_hidden1.sum(axis=0)
            self._adam_update(gradients)
            losses.append(loss)
        result = self.metrics(dataset)
        result["training_loss"] = sum(losses) / len(losses) if losses else None
        result["optimizer_steps"] = self.optimizer_step
        return result

    def _adam_update(self, gradients: Mapping[str, np.ndarray]) -> None:
        self.optimizer_step += 1
        beta1 = 0.9
        beta2 = 0.999
        epsilon = 1e-8
        for name, gradient in gradients.items():
            first = self.first_moment[name]
            second = self.second_moment[name]
            first *= beta1
            first += (1.0 - beta1) * gradient
            second *= beta2
            second += (1.0 - beta2) * gradient * gradient
            corrected_first = first / (1.0 - beta1**self.optimizer_step)
            corrected_second = second / (1.0 - beta2**self.optimizer_step)
            self.parameters[name] -= self.learning_rate * corrected_first / (
                np.sqrt(corrected_second) + epsilon
            )

    @staticmethod
    def _auc(targets: np.ndarray, scores: np.ndarray) -> float | None:
        positive_count = int(np.count_nonzero(targets))
        negative_count = len(targets) - positive_count
        if positive_count == 0 or negative_count == 0:
            return None
        order = np.argsort(scores, kind="mergesort")
        ranks = np.empty(len(scores), dtype=np.float64)
        start = 0
        while start < len(order):
            end = start + 1
            while end < len(order) and scores[order[end]] == scores[order[start]]:
                end += 1
            ranks[order[start:end]] = 0.5 * (start + 1 + end)
            start = end
        rank_sum = float(ranks[targets].sum())
        return (
            rank_sum - positive_count * (positive_count + 1) / 2.0
        ) / (positive_count * negative_count)

    def metrics(self, dataset: NeuralTrainingDataset) -> dict[str, Any]:
        features = dataset.validation_features
        stages = dataset.validation_stages
        if not len(stages):
            features = dataset.train_features
            stages = dataset.train_stages
        probabilities = self.predict_probabilities(features)
        transitions: dict[str, dict[str, Any]] = {}
        for head, target in enumerate(self.transition_stages):
            eligible = stages >= target - 1
            targets = stages[eligible] >= target
            scores = probabilities[eligible, head]
            positives = int(np.count_nonzero(targets))
            negatives = int(len(targets) - positives)
            if len(targets):
                clipped = np.clip(scores, 1e-7, 1.0 - 1e-7)
                log_loss = float(
                    -np.mean(
                        targets * np.log(clipped)
                        + (~targets) * np.log(1.0 - clipped)
                    )
                )
            else:
                log_loss = None
            transitions[str(target)] = {
                "eligible": int(len(targets)),
                "positives": positives,
                "negatives": negatives,
                "positive_rate": positives / len(targets) if len(targets) else None,
                "auc": self._auc(targets, scores) if len(targets) else None,
                "log_loss": log_loss,
                "active": bool(self.active_heads[head]),
            }
        return {
            "schema_version": "mapping-lab-neural-metrics-v1",
            "training_examples": dataset.training_size,
            "validation_examples": dataset.validation_size,
            "transitions": transitions,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        payload: dict[str, Any] = {
            "model_version": np.asarray(MODEL_VERSION),
            "input_dimension": np.asarray(self.input_dimension),
            "transition_stages": np.asarray(self.transition_stages, dtype=np.int16),
            "hidden_layers": np.asarray(self.hidden_layers, dtype=np.int32),
            "learning_rate": np.asarray(self.learning_rate),
            "l2": np.asarray(self.l2),
            "optimizer_step": np.asarray(self.optimizer_step),
            "active_heads": self.active_heads,
            "empirical_rates": self.empirical_rates,
        }
        payload.update(self.parameters)
        payload.update({f"m_{name}": value for name, value in self.first_moment.items()})
        payload.update({f"v_{name}": value for name, value in self.second_moment.items()})
        with temporary.open("wb") as stream:
            np.savez_compressed(stream, **payload)
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path) -> "NeuralStageModel":
        with np.load(path, allow_pickle=False) as payload:
            version = str(payload["model_version"].item())
            if version != MODEL_VERSION:
                raise ValueError(f"unsupported neural model version {version!r}")
            result = cls(
                int(payload["input_dimension"].item()),
                tuple(int(value) for value in payload["transition_stages"]),
                tuple(int(value) for value in payload["hidden_layers"]),
                seed=0,
                learning_rate=float(payload["learning_rate"].item()),
                l2=float(payload["l2"].item()),
            )
            result.optimizer_step = int(payload["optimizer_step"].item())
            result.active_heads = payload["active_heads"].astype(bool)
            result.empirical_rates = payload["empirical_rates"].astype(np.float32)
            for name in result.parameters:
                result.parameters[name] = payload[name].astype(np.float32)
                result.first_moment[name] = payload[f"m_{name}"].astype(np.float32)
                result.second_moment[name] = payload[f"v_{name}"].astype(np.float32)
        return result


class NeuralLearningBackend:
    """Persisted neural implementation of the generic learning contract."""

    name = "neural_stage_curriculum"

    def __init__(
        self,
        model: NeuralStageModel,
        dataset: NeuralTrainingDataset,
        *,
        model_path: Path,
        dataset_path: Path,
        steps_per_generation: int,
        batch_size: int,
        max_examples_per_stage: int,
        seed: int,
    ) -> None:
        self.model = model
        self.dataset = dataset
        self.model_path = model_path
        self.dataset_path = dataset_path
        self.steps_per_generation = max(0, int(steps_per_generation))
        self.batch_size = max(1, int(batch_size))
        self.max_examples_per_stage = max(1, int(max_examples_per_stage))
        self.seed = int(seed)

    @classmethod
    def load_or_create(
        cls,
        output: Path,
        *,
        input_dimension: int,
        transition_stages: Sequence[int],
        config: Mapping[str, Any],
        seed: int,
        feature_builder: Any,
        bootstrap_paths: Sequence[Path] = (),
    ) -> tuple["NeuralLearningBackend", dict[str, int]]:
        model_path = output / "model.npz"
        dataset_path = output / "dataset.npz"
        if dataset_path.exists():
            dataset = NeuralTrainingDataset.load(dataset_path)
            dataset_summary = {
                "scanned": 0,
                "duplicates": 0,
                "invalid": 0,
                "retained": dataset.training_size + dataset.validation_size,
                "training": dataset.training_size,
                "validation": dataset.validation_size,
                "cached": 1,
            }
        else:
            dataset, dataset_summary = load_training_dataset(
                bootstrap_paths,
                feature_builder=feature_builder,
                max_examples_per_stage=int(config.get("max_examples_per_stage", 20000)),
                seed=seed,
                input_dimension=input_dimension,
            )
        if dataset.input_dimension != int(input_dimension):
            raise ValueError("stored learning dataset has an incompatible feature dimension")
        if model_path.exists():
            model = NeuralStageModel.load(model_path)
            if model.input_dimension != int(input_dimension):
                raise ValueError("stored neural model has an incompatible feature dimension")
        else:
            model = NeuralStageModel(
                input_dimension,
                transition_stages,
                tuple(int(value) for value in config.get("hidden_layers", [96, 48])),
                seed=seed,
                learning_rate=float(config.get("learning_rate", 0.001)),
                l2=float(config.get("l2", 1e-5)),
            )
            model.train(
                dataset,
                steps=max(0, int(config.get("bootstrap_steps", 0))),
                batch_size=max(1, int(config.get("batch_size", 256))),
                seed=seed + 17,
            )
        backend = cls(
            model,
            dataset,
            model_path=model_path,
            dataset_path=dataset_path,
            steps_per_generation=int(config.get("steps_per_generation", 4)),
            batch_size=int(config.get("batch_size", 256)),
            max_examples_per_stage=int(config.get("max_examples_per_stage", 20000)),
            seed=seed,
        )
        backend.save()
        return backend, dataset_summary

    def score(self, features: np.ndarray) -> np.ndarray:
        return self.model.utilities(features)

    def observe(
        self, batch: ObservationBatch, *, generation: int
    ) -> dict[str, Any]:
        self.dataset.add(
            batch.candidate_ids,
            batch.features,
            batch.terminal_stages,
            max_examples_per_stage=self.max_examples_per_stage,
        )
        metrics = self.model.train(
            self.dataset,
            steps=self.steps_per_generation,
            batch_size=self.batch_size,
            seed=self.seed + int(generation) * 97_409,
        )
        self.save()
        return metrics

    def metrics(self) -> dict[str, Any]:
        return self.model.metrics(self.dataset)

    def save(self) -> None:
        self.dataset.save(self.dataset_path)
        self.model.save(self.model_path)
