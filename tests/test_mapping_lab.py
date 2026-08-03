from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

import numpy as np

from formal_disk4.mapping_lab import CompleteMappingEvaluator, MappingLabRunner, MappingSpace
from formal_disk4.mapping_lab.core import STAGES
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

    def test_production_adapter_returns_a_structured_depth_score(self) -> None:
        candidate = self.space.sample(random.Random(42))
        self.assertIsNotNone(candidate)
        assert candidate is not None
        result = CompleteMappingEvaluator(self.space).evaluate(candidate)
        self.assertIn(result.terminal_stage, STAGES)
        self.assertEqual(result.stage_index, STAGES.index(result.terminal_stage))
        self.assertEqual(result.masks, candidate.masks)
        self.assertGreaterEqual(result.elapsed_seconds, 0.0)

    def test_hard_timeout_restarts_the_evaluation_worker(self) -> None:
        first = self.space.sample(random.Random(42))
        second = self.space.sample(random.Random(7))
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        with EvaluationWorker(
            ROOT,
            CASE_ID,
            {},
            startup_timeout_seconds=60.0,
        ) as worker:
            timed_out = worker.evaluate(first, 0.001)
            recovered = worker.evaluate(second, 10.0)
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


if __name__ == "__main__":
    unittest.main()
