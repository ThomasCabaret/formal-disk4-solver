from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

import numpy as np

from formal_disk4.mapping_lab import CompleteMappingEvaluator, MappingLabRunner, MappingSpace
from formal_disk4.mapping_lab.core import STAGES
from formal_disk4.mapping_lab.core import LengthRepairProbe
from formal_disk4.mapping_lab.deep_support import (
    DeepArchive,
    DeepSampler,
    PersistentSeen,
    recover_deep_candidates,
)
from formal_disk4.mapping_lab.runner import EvaluationWorker
from formal_disk4.mapping_lab.seeds import DeepSeedBuffer, DeepSeedEntry


ROOT = Path(__file__).resolve().parents[1]
CASE_ID = "wheel-6-half-turn-fertile-abc"


class ConstantBackend:
    name = "test"

    def score(self, features: np.ndarray) -> np.ndarray:
        return np.zeros(len(features), dtype=np.float32)


class MappingLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.space = MappingSpace(ROOT, CASE_ID)

    def test_sampler_constructs_complete_symmetric_subdomain_mappings(self) -> None:
        candidate = self.space.sample(random.Random(1234))
        self.assertIsNotNone(candidate)
        assert candidate is not None
        half_size = len(candidate.masks)
        self.assertGreater(half_size, 0)
        self.assertEqual(len(candidate.blocks), 2 * half_size)
        expected_rotated = tuple(
            tuple(
                sorted(self.space.transform.map_occurrence_id(item) for item in block)
            )
            for block in candidate.blocks[:half_size]
        )
        self.assertEqual(candidate.blocks[half_size:], expected_rotated)
        self.assertTrue(self.space.subdomain.allows_leaf(candidate.blocks))

    def test_mapping_features_round_trip_to_the_original_masks(self) -> None:
        candidate = self.space.sample(random.Random(4321))
        self.assertIsNotNone(candidate)
        assert candidate is not None
        features = self.space.mapping_feature_vector(candidate.masks)
        recovered_masks = self.space.mapping_masks_from_feature_vector(features)
        recovered = self.space.candidate_from_masks(recovered_masks)
        self.assertEqual(recovered_masks, candidate.masks)
        self.assertEqual(recovered.candidate_id, candidate.candidate_id)

    def test_production_adapter_returns_a_structured_depth_score(self) -> None:
        candidate = self.space.sample(random.Random(42))
        self.assertIsNotNone(candidate)
        assert candidate is not None
        result = CompleteMappingEvaluator(self.space).evaluate(candidate)
        self.assertIn(result.terminal_stage, STAGES)
        self.assertEqual(result.stage_index, STAGES.index(result.terminal_stage))
        self.assertEqual(result.masks, candidate.masks)
        self.assertGreaterEqual(result.elapsed_seconds, 0.0)

    def test_length_repair_probe_returns_a_graded_finite_score(self) -> None:
        candidate = self.space.sample(random.Random(42))
        self.assertIsNotNone(candidate)
        assert candidate is not None
        probe = CompleteMappingEvaluator(self.space).repair_probe(candidate)
        self.assertEqual(probe.candidate_id, candidate.candidate_id)
        if probe.normalized_length_slack is not None:
            self.assertGreaterEqual(probe.normalized_length_slack, 0.0)

    def test_hard_timeout_restarts_the_evaluation_worker(self) -> None:
        second = self.space.sample(random.Random(7))
        self.assertIsNotNone(second)
        assert second is not None
        with EvaluationWorker(
            ROOT,
            CASE_ID,
            {},
            startup_timeout_seconds=60.0,
        ) as worker:
            # Sound early filters may now reject some candidates in under the
            # minimum 1 ms worker timeout.  Find a descendant that actually
            # exercises the kill/restart path instead of assuming one fixed
            # random mapping is necessarily slow on every machine.
            timed_out = None
            for seed in range(128):
                first = self.space.sample(random.Random(seed))
                assert first is not None
                result = worker.evaluate(first, 0.001)
                if result.status == "timeout":
                    timed_out = result
                    break
            recovered = worker.evaluate(second, 10.0)
        self.assertIsNotNone(timed_out)
        assert timed_out is not None
        self.assertEqual(timed_out.status, "timeout")
        self.assertNotIn(recovered.status, {"timeout", "evaluation_error"})

    def test_sampler_keeps_an_independent_uniform_control(self) -> None:
        runner = MappingLabRunner(
            ROOT,
            {
                "case_id": CASE_ID,
                "output": {"directory": "output/mapping_lab/test-unused"},
                "sampling": {"uniform_fraction": 0.25, "pool_multiplier": 2},
            },
        )
        seeds = DeepSeedBuffer(capacity=8, minimum_stage_index=8)
        candidates = runner.sampler.sample_batch(
            ConstantBackend(),
            random.Random(99),
            20,
            {"learned": set(), "uniform": set()},
            seeds=seeds,
        )
        sources = [candidate.proposal_source for candidate in candidates]
        self.assertEqual(sources.count("uniform"), 5)
        self.assertEqual(sources.count("learned"), 15)
        self.assertEqual(
            sum(
                count
                for key, count in runner.sampler.last_diagnostics.items()
                if key.startswith("accepted.")
            ),
            20,
        )

    def test_seed_buffer_retains_only_the_deepest_mappings(self) -> None:
        seeds = DeepSeedBuffer(capacity=2, minimum_stage_index=6)
        for candidate_id, stage in (("a", 6), ("b", 8), ("c", 7)):
            seeds.add(
                DeepSeedEntry(
                    candidate_id=candidate_id,
                    stage_index=stage,
                    score=float(stage),
                    status="rejected",
                    proposal_source="learned",
                    proposal_strategy="model_random_pool",
                    masks=(1,),
                )
            )
        seeds.finalize()
        self.assertEqual([entry.candidate_id for entry in seeds.entries], ["b", "c"])

    def test_seed_archive_validates_and_loads_mapping_masks(self) -> None:
        candidate = self.space.sample(random.Random(42))
        self.assertIsNotNone(candidate)
        assert candidate is not None
        with tempfile.TemporaryDirectory() as raw_directory:
            path = Path(raw_directory) / "archive.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "case_id": CASE_ID,
                        "candidate_id": candidate.candidate_id,
                        "stage_index": 8,
                        "score": 8.0,
                        "status": "rejected",
                        "masks": list(candidate.masks),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            seeds = DeepSeedBuffer(capacity=8, minimum_stage_index=6)
            summary = seeds.load_archive(path, space=self.space)
        self.assertEqual(summary["retained"], 1)
        self.assertEqual(seeds.entries[0].masks, candidate.masks)

    def test_local_and_broad_seed_mutations_force_a_new_mapping(self) -> None:
        reference = self.space.sample(random.Random(42))
        self.assertIsNotNone(reference)
        assert reference is not None
        for prefix_fraction in (1.0, 0.6):
            mutated = None
            for seed in range(100):
                mutated = self.space.sample(
                    random.Random(seed),
                    reference_masks=reference.masks,
                    mutation_prefix_fraction=prefix_fraction,
                    proposal_source="learned",
                    proposal_strategy="test_mutation",
                )
                if mutated is not None:
                    break
            self.assertIsNotNone(mutated)
            assert mutated is not None
            self.assertNotEqual(mutated.candidate_id, reference.candidate_id)
            self.assertTrue(self.space.subdomain.allows_leaf(mutated.blocks))

    def test_true_local_neighbors_change_only_one_adjacent_boundary(self) -> None:
        reference = self.space.sample(random.Random(42))
        self.assertIsNotNone(reference)
        assert reference is not None
        neighbors = self.space.local_neighbors(
            reference.masks,
            random.Random(7),
            limit=128,
            proposal_source="test_local",
        )
        self.assertTrue(neighbors)

        def is_one_edit(candidate_masks: tuple[int, ...], operator: str) -> bool:
            original = reference.masks
            if operator == "local_merge":
                return any(
                    candidate_masks
                    == (*original[:i], original[i] | original[i + 1], *original[i + 2 :])
                    for i in range(len(original) - 1)
                    if not original[i] & original[i + 1]
                )
            if operator == "local_split":
                return any(
                    candidate_masks[:i] == original[:i]
                    and candidate_masks[i + 2 :] == original[i + 1 :]
                    and candidate_masks[i] & candidate_masks[i + 1] == 0
                    and candidate_masks[i] | candidate_masks[i + 1] == original[i]
                    for i in range(len(original))
                    if len(candidate_masks) == len(original) + 1
                )
            if operator == "local_swap":
                return any(
                    candidate_masks
                    == (*original[:i], original[i + 1], original[i], *original[i + 2 :])
                    for i in range(len(original) - 1)
                )
            if operator in {"local_shift_left", "local_shift_right"}:
                return any(
                    candidate_masks[:i] == original[:i]
                    and candidate_masks[i + 2 :] == original[i + 2 :]
                    and candidate_masks[i] | candidate_masks[i + 1]
                    == original[i] | original[i + 1]
                    and (candidate_masks[i], candidate_masks[i + 1])
                    != (original[i], original[i + 1])
                    for i in range(len(original) - 1)
                )
            return False

        for candidate, operator in neighbors:
            self.assertTrue(self.space.subdomain.allows_leaf(candidate.blocks))
            self.assertTrue(is_one_edit(candidate.masks, operator), operator)

    def test_length_repair_sampler_prefers_a_positive_local_neighbor(self) -> None:
        reference = None
        neighbors = ()
        for seed in range(100):
            candidate = self.space.sample(random.Random(seed))
            if candidate is None:
                continue
            candidate_neighbors = self.space.local_neighbors(
                candidate.masks,
                random.Random(3),
                limit=128,
            )
            if any(operator == "local_merge" for _item, operator in candidate_neighbors):
                reference = candidate
                neighbors = candidate_neighbors
                break
        self.assertIsNotNone(reference)
        assert reference is not None
        merge_ids = {
            candidate.candidate_id
            for candidate, operator in neighbors
            if operator == "local_merge"
        }
        archive = DeepArchive(capacity=16, per_failure=16)
        archive.add(
            {
                "candidate_id": reference.candidate_id,
                "masks": list(reference.masks),
                "stage_index": 8,
                "reason": "seed",
                "diagnostics": {
                    "preword_linear_curriculum": {"passed_steps": 0}
                },
            }
        )

        def fake_probe(candidate):
            positive = candidate.candidate_id in merge_ids
            return LengthRepairProbe(
                candidate.candidate_id,
                True,
                True,
                positive,
                0.1 if positive else None,
                0.0 if positive else 0.5,
                "test",
            )

        with tempfile.TemporaryDirectory() as raw_directory:
            seen = PersistentSeen(Path(raw_directory) / "seen.sqlite3")
            seen.add(reference.candidate_id)
            sampler = DeepSampler(
                self.space,
                "length_repair",
                pool_multiplier=8,
                exploration_fraction=0.0,
                mutation_fraction=1.0,
                max_attempts=20,
                local_neighbors_per_parent=128,
            )
            selected = sampler.sample_batch(
                ConstantBackend(),
                archive,
                random.Random(9),
                1,
                seen,
                repair_probe=fake_probe,
            )
            seen.close()
        self.assertIn(selected[0].candidate.candidate_id, merge_ids)
        self.assertEqual(selected[0].context.parent_id, reference.candidate_id)

    def test_deep_archive_is_accepted_as_a_bootstrap_source(self) -> None:
        reference = self.space.sample(random.Random(42))
        self.assertIsNotNone(reference)
        assert reference is not None
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            (directory / "archive.json").write_text(
                json.dumps(
                    {
                        "capacity": 10,
                        "per_failure": 10,
                        "entries": [
                            {
                                "candidate_id": reference.candidate_id,
                                "masks": list(reference.masks),
                                "depth": 8,
                                "failure": "preword_positive_lengths",
                                "reason": "test",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            recovered = recover_deep_candidates(
                self.space,
                (directory,),
                minimum_stage=8,
            )
        self.assertEqual(
            [candidate.candidate_id for candidate in recovered],
            [reference.candidate_id],
        )

    def test_preferred_mutation_targets_a_requested_fundamental_block(self) -> None:
        reference = self.space.sample(random.Random(42))
        self.assertIsNotNone(reference)
        assert reference is not None
        target = min(2, len(reference.masks) - 1)
        mutated = None
        for seed in range(200):
            mutated = self.space.sample(
                random.Random(seed),
                reference_masks=reference.masks,
                preferred_mutation_indices=(target,),
                proposal_strategy="targeted_test",
            )
            if mutated is not None:
                break
        self.assertIsNotNone(mutated)
        assert mutated is not None
        first_difference = next(
            index
            for index, (left, right) in enumerate(
                zip(reference.masks, mutated.masks)
            )
            if left != right
        )
        self.assertEqual(first_difference, target)

if __name__ == "__main__":
    unittest.main()
