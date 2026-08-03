from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

import numpy as np

from formal_disk4.mapping_lab import MappingSpace
from formal_disk4.mapping_lab.backend import ObservationBatch
from formal_disk4.mapping_lab.neural import (
    NeuralLearningBackend,
    NeuralStageModel,
    NeuralTrainingDataset,
)


ROOT = Path(__file__).resolve().parents[1]
CASE_ID = "wheel-6-half-turn-fertile-abc"


class MappingLabNeuralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.space = MappingSpace(ROOT, CASE_ID)

    def test_pairwise_features_have_fixed_size_and_encode_the_mapping(self) -> None:
        first = self.space.sample(random.Random(1))
        second = self.space.sample(random.Random(2))
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        first_features = self.space.mapping_feature_vector(first.masks)
        second_features = self.space.mapping_feature_vector(second.masks)
        self.assertEqual(len(first_features), self.space.mapping_feature_dimension)
        self.assertEqual(len(second_features), self.space.mapping_feature_dimension)
        self.assertNotEqual(first_features, second_features)

    def test_dataset_starts_empty_and_keeps_a_bounded_stage_stratified_signal(self) -> None:
        dataset = NeuralTrainingDataset.empty(3)
        candidate_ids = tuple(f"candidate-{index}" for index in range(100))
        features = np.arange(300, dtype=np.float32).reshape(100, 3)
        stages = np.asarray([3] * 50 + [4] * 50, dtype=np.int16)
        dataset.add(
            candidate_ids,
            features,
            stages,
            max_examples_per_stage=20,
        )
        self.assertLessEqual(dataset.training_size + dataset.validation_size, 40)
        self.assertEqual(set(dataset.stage_histogram), {3, 4})
        self.assertGreater(dataset.training_size, 0)
        self.assertGreater(dataset.validation_size, 0)

    def test_neural_head_learns_a_nonlinear_filter_signal_and_round_trips(self) -> None:
        rng = np.random.default_rng(123)
        features = rng.normal(size=(600, 4)).astype(np.float32)
        positive = features[:, 0] * features[:, 1] > 0
        stages = np.where(positive, 4, 3).astype(np.int16)
        dataset = NeuralTrainingDataset(
            train_features=features[:500],
            train_stages=stages[:500],
            validation_features=features[500:],
            validation_stages=stages[500:],
            stage_histogram={
                3: int(np.count_nonzero(~positive)),
                4: int(np.count_nonzero(positive)),
            },
        )
        model = NeuralStageModel(
            4,
            (4,),
            (24, 12),
            seed=9,
            learning_rate=0.003,
            l2=1e-5,
        )
        metrics = model.train(dataset, steps=250, batch_size=96, seed=10)
        self.assertGreater(metrics["transitions"]["4"]["auc"], 0.85)
        before = model.predict_probabilities(features[500:510])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.npz"
            model.save(path)
            restored = NeuralStageModel.load(path)
            after = restored.predict_probabilities(features[500:510])
            dataset_path = Path(directory) / "dataset.npz"
            dataset.save(dataset_path)
            restored_dataset = NeuralTrainingDataset.load(dataset_path)
        np.testing.assert_allclose(before, after, atol=1e-7)
        np.testing.assert_array_equal(
            dataset.validation_stages, restored_dataset.validation_stages
        )

    def test_backend_cold_starts_observes_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            backend, summary = NeuralLearningBackend.load_or_create(
                output,
                input_dimension=4,
                transition_stages=(4,),
                config={
                    "hidden_layers": [12, 6],
                    "steps_per_generation": 2,
                    "batch_size": 16,
                    "max_examples_per_stage": 100,
                },
                seed=3,
                feature_builder=lambda masks: masks,
            )
            self.assertEqual(summary["retained"], 0)
            features = np.asarray(
                [[0.0, 0.0, 0.0, 0.0], [1.0, 1.0, 1.0, 1.0]],
                dtype=np.float32,
            )
            backend.observe(
                ObservationBatch(
                    candidate_ids=("cold-a", "cold-b"),
                    features=features,
                    terminal_stages=np.asarray([3, 4], dtype=np.int16),
                ),
                generation=0,
            )
            restored, restored_summary = NeuralLearningBackend.load_or_create(
                output,
                input_dimension=4,
                transition_stages=(4,),
                config={
                    "hidden_layers": [12, 6],
                    "steps_per_generation": 2,
                    "batch_size": 16,
                    "max_examples_per_stage": 100,
                },
                seed=3,
                feature_builder=lambda masks: masks,
            )
            self.assertEqual(restored_summary["retained"], 2)
            np.testing.assert_allclose(backend.score(features), restored.score(features))


if __name__ == "__main__":
    unittest.main()
