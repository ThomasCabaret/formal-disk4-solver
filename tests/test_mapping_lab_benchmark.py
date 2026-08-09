from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from formal_disk4.mapping_lab.benchmark import (
    PlacementDataset,
    load_exact_placement_dataset,
    run_learning_benchmark,
)
from formal_disk4.mapping_lab.positive_control import (
    build_collection_config,
    load_positive_control_config,
)
from formal_disk4.maps.registry import build_map


class MappingLabBenchmarkTests(unittest.TestCase):
    def test_positive_control_uses_the_catalog_case_and_isolated_audits(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = load_positive_control_config(
            root,
            "config/mapping_lab/double-cycle-offset-6-positive-control.json",
        )
        search, collection = build_collection_config(
            root, config, restart=True, max_placements=17
        )
        self.assertEqual(search["maps"], ["double-cycle-offset-6"])
        self.assertEqual(search["limits"]["max_placements"], 17)
        self.assertTrue(search["output"]["write_placements"])
        self.assertTrue(search["output"]["write_word_cases"])
        self.assertEqual(collection.name, "collection")

    def test_exact_streams_produce_nested_stage_labels(self) -> None:
        planar_map = build_map("double-cycle-offset-6")
        occurrence_names = [item.name for item in planar_map.occurrences()]
        pieces = [piece.name for piece in planar_map.pieces]

        def placement_record(placement_id: int) -> dict[str, object]:
            blocks = [
                occurrence_names[offset::4]
                for offset in range(4)
                if occurrence_names[offset::4]
            ]
            return {
                "map": planar_map.name,
                "assignment": {
                    "assignment_id": 0,
                    "orientation_signs": {piece: 1 for piece in pieces},
                    "cyclic_offsets": {piece: 0 for piece in pieces},
                },
                "placement": {
                    "assignment_id": 0,
                    "placement_id": placement_id,
                    "blocks": blocks,
                    "length_margin": 0.1,
                    "angle_margin": 0.2,
                },
            }

        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            placements = [placement_record(index) for index in range(4)]
            (directory / "placements.jsonl").write_text(
                "".join(json.dumps(value) + "\n" for value in placements),
                encoding="utf-8",
            )
            audits = [
                {"assignment_id": 0, "placement_id": 1, "family_count": 0},
                {"assignment_id": 0, "placement_id": 2, "family_count": 2},
                {"assignment_id": 0, "placement_id": 3, "family_count": 1},
            ]
            (directory / "word_case_audit.jsonl").write_text(
                "".join(json.dumps(value) + "\n" for value in audits),
                encoding="utf-8",
            )
            (directory / "candidates.jsonl").write_text(
                json.dumps(
                    {
                        "assignment": {"assignment_id": 0},
                        "placement": {"placement_id": 3},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            dataset, summary = load_exact_placement_dataset(planar_map, directory)

        self.assertEqual(dataset.stages.tolist(), [0, 1, 2, 3])
        self.assertEqual(dataset.features.shape, (4, len(dataset.feature_names)))
        self.assertEqual(summary["profile_placements"], 1)

    def test_synthetic_positive_control_writes_stable_metrics(self) -> None:
        rng = np.random.default_rng(123)
        features = rng.normal(size=(240, 6)).astype(np.float32)
        signal = features[:, 0] + 0.5 * features[:, 1]
        stages = np.zeros(240, dtype=np.int16)
        stages[signal > -0.5] = 1
        stages[signal > 0.2] = 2
        stages[signal > 0.9] = 3
        dataset = PlacementDataset(
            candidate_ids=tuple(f"item-{index}" for index in range(240)),
            assignment_ids=np.asarray([index % 10 for index in range(240)]),
            features=features,
            stages=stages,
            feature_names=tuple(f"x{index}" for index in range(6)),
        )
        config = {
            "split": {"validation_assignments": [2, 7]},
            "backend": {
                "seed": 123,
                "hidden_layers": [24, 12],
                "learning_rate": 0.003,
                "l2": 0.0,
                "offline_steps": 150,
                "batch_size": 64,
            },
            "ranking_fractions": [0.1],
            "replay": {
                "seeds": [123],
                "warmup": 48,
                "batch_size": 24,
                "rounds": 4,
                "exploration_fraction": 0.15,
                "initial_training_steps": 50,
                "steps_per_round": 4,
            },
        }
        with tempfile.TemporaryDirectory() as raw_directory:
            report = run_learning_benchmark(dataset, config, Path(raw_directory))
        self.assertEqual(report["schema_version"], "mapping-lab-positive-control-v1")
        self.assertGreater(
            report["offline"]["unconditional_ranking"]["word_family"]["auc"],
            0.75,
        )


if __name__ == "__main__":
    unittest.main()
