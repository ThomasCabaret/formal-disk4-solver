from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from formal_disk4.config import load_geometry_config, load_visualization_config
from formal_disk4.geometry.model import parse_formal_geometry_problem
from formal_disk4.geometry.status import GeometryCandidateStatus, SOLUTION_FOUND
from formal_disk4.graph_lab.app import build_parser as build_lab_app_parser
from formal_disk4.graph_lab.evaluator import GraphEvaluation
from formal_disk4.graph_lab.feedback import LearningFeedback, balanced_binary_weights
from formal_disk4.graph_lab.curriculum import build_curriculum, curriculum_utility
from formal_disk4.graph_lab.mapping import MappingProposal
from formal_disk4.graph_lab.specialization_model import (
    SpecializationDecisionObservation,
    SpecializationLearningModel,
    SpecializationPoolObservation,
    SpecializationPrediction,
    SpecializationRankedPolicy,
)
from formal_disk4.graph_lab.runner import DiversityArchive, GraphLabRunner
from formal_disk4.graph_lab.space import DualGraphCandidate
from formal_disk4.graph_lab.weak_model import (
    WeakOrderDecisionObservation,
    WeakOrderLearningModel,
    WeakOrderPrediction,
    WeakOrderRankedPolicy,
    WeakOrderRolloutObservation,
)
from formal_disk4.pipeline.filter_report import FilterReport, LEARNING_FILTER_IDS
from formal_disk4.enumeration.weak_policy import (
    WeakOrderActionView,
    WeakOrderStateView,
)
from formal_disk4.words.specialization_policy import (
    SpecializationActionView,
    SpecializationOutcomeView,
    SpecializationPoolStateView,
)


ROOT = Path(__file__).resolve().parents[1]


class GraphLabTests(unittest.TestCase):
    @staticmethod
    def _ring_candidate() -> DualGraphCandidate:
        return DualGraphCandidate(
            tile_count=3,
            edges=((-1, 0), (-1, 1), (-1, 2), (0, 1), (0, 2), (1, 2)),
            imposed_permutation=(1, 2, 0),
            origin="test",
            mutation="test",
        )

    def test_sparse_learning_targets_receive_bounded_balancing(self) -> None:
        weights = balanced_binary_weights(
            ((1.0,),) + ((0.0,),) * 999,
            1,
            maximum=50.0,
        )
        self.assertEqual(weights[0][0], 50.0)
        self.assertAlmostEqual(weights[0][1], 1000 / 1998)

    def test_mutation_parent_sampling_uses_the_same_size_growth_prior(self) -> None:
        def observation(tile_count: int) -> SimpleNamespace:
            return SimpleNamespace(
                candidate=SimpleNamespace(tile_count=tile_count),
                stage_index=1,
                profiles=(),
                elapsed_seconds=0.0,
                tainted=False,
            )

        archive = DiversityArchive(())
        archive.cells["small"] = [observation(4)]
        archive.cells["large"] = [observation(13)]
        rng = random.Random(20260815)
        selected = [
            archive.choose_parent(
                rng,
                size_weight=lambda size: 1.4 ** (size - 4),
            ).candidate.tile_count
            for _ in range(2000)
        ]

        self.assertGreater(selected.count(13), 1850)
        self.assertGreater(selected.count(4), 0)

    def test_curriculum_uses_direct_reach_without_cross_filter_products(self) -> None:
        rates = [0.95, 0.40] + [0.0] * 24
        supports = [100] * 26
        active = [True, True] + [False] * 24
        state = build_curriculum(
            empirical_reach_rates=rates,
            reach_supports=supports,
            active_reach_heads=active,
            active_pass_heads=active,
            config={"curriculum_mastery_rate": 0.85},
        )
        self.assertEqual(state.frontier_index, 1)
        score = curriculum_utility(
            state,
            (0.1, 0.8) + (0.0,) * 24,
            (0.5,) * 26,
        )
        self.assertGreater(score, 0.8)
        self.assertIn("never multiplied", state.to_dict()["probability_semantics"])

    def test_geometry_feedback_is_joined_only_at_the_right_scope(self) -> None:
        ring = self._ring_candidate()
        nonring = DualGraphCandidate(
            tile_count=4,
            edges=(
                (-1, 0), (-1, 1), (-1, 2), (-1, 3),
                (0, 1), (1, 2), (2, 3), (0, 3), (0, 2),
            ),
            imposed_permutation=None,
            origin="test",
            mutation="test",
        )
        status = GeometryCandidateStatus(
            "fp-test", SOLUTION_FOUND, "test", 1, 0.0, "now"
        )
        feedback = LearningFeedback(
            {"fp-test": status},
            {ring.graph_id: (("fp-test", True),)},
        )

        self.assertEqual(
            feedback.targets(
                candidate=ring, profile_count=1, profile_ids=("fp-test",)
            ),
            (1.0, 1.0, 0.0),
        )
        self.assertEqual(
            feedback.targets(
                candidate=nonring, profile_count=1, profile_ids=("fp-test",)
            ),
            (1.0, 1.0, 1.0),
        )
        # A graph-level catalog hit must not label every mapping of that graph
        # as a geometric success. Only the graph ranker may use this fallback.
        self.assertEqual(
            feedback.targets(candidate=ring, profile_count=1),
            (1.0, None, 0.0),
        )
        self.assertEqual(
            feedback.targets(
                candidate=ring,
                profile_count=1,
                allow_graph_fallback=True,
            ),
            (1.0, 1.0, 0.0),
        )

    def test_resume_keeps_profile_labels_and_reconstructs_weak_state_path(self) -> None:
        candidate = self._ring_candidate()
        evaluation = GraphEvaluation(
            candidate=candidate,
            stage_index=5,
            elapsed_seconds=0.1,
            stop_reason="test",
            counters={},
            profiles=({"formal_profile_id": "fp-test"},),
            tainted=False,
        )
        restored_evaluation = GraphEvaluation.from_dict(evaluation.to_dict())
        self.assertTrue(restored_evaluation.geometry_ready)
        self.assertEqual(
            restored_evaluation.profiles[0]["formal_profile_id"], "fp-test"
        )

        proposal = MappingProposal(
            candidate=candidate,
            raw_assignment_id=0,
            orientation_signs=(1, 1, 1),
            cyclic_offsets=(0, 0, 0),
            contour_lengths=(3, 3, 3),
            edge_ports=tuple((0.0,) * 8 for _edge in candidate.edges),
        )
        decisions = []
        path: tuple[int, ...] = ()
        for index, mask in enumerate((1, 2)):
            state = WeakOrderStateView(
                assignment_id=0,
                path=path,
                counters=(index, 0, 0),
                targets=(3, 3, 3),
                block_count=index,
                resolved_length_equations=0,
                resolved_angle_equations=0,
                available_mask=7,
                reference_index=0,
            )
            action = WeakOrderActionView(mask, (index + 1, 0, 0), 1, 0, 0)
            decisions.append(
                WeakOrderDecisionObservation(
                    state=state,
                    action=action,
                    candidate_count=2,
                    selection_mode="exploration",
                    selection_probability=0.5,
                    policy_entropy=0.5,
                    predicted_conditional_probabilities=(),
                    predicted_reach_probabilities=(),
                    selection_score=0.0,
                )
            )
            path += (mask,)
        rollout = WeakOrderRolloutObservation(
            proposal=proposal,
            decisions=tuple(decisions),
            filters=FilterReport.from_counters({}),
            elapsed_seconds=0.1,
            profile_count=1,
            profile_ids=("fp-test",),
            selection_mode="exploration",
            random_seed=1,
            tainted=False,
        )
        restored_rollout = WeakOrderRolloutObservation.from_dict(rollout.to_dict())
        self.assertEqual(restored_rollout.decisions[0].state.path, ())
        self.assertEqual(restored_rollout.decisions[1].state.path, (1,))
        self.assertEqual(restored_rollout.profile_ids, ("fp-test",))

    def test_weak_ranker_can_distinguish_different_partial_block_states(self) -> None:
        candidate = self._ring_candidate()
        proposal = MappingProposal(
            candidate=candidate,
            raw_assignment_id=0,
            orientation_signs=(1, -1, 1),
            cyclic_offsets=(0, 1, 2),
            contour_lengths=(3, 3, 3),
            edge_ports=tuple((0.0,) * 8 for _edge in candidate.edges),
        )
        common = {
            "assignment_id": 0,
            "counters": (1, 1, 1),
            "targets": (3, 3, 3),
            "block_count": 2,
            "resolved_length_equations": 0,
            "resolved_angle_equations": 0,
            "available_mask": 7,
            "reference_index": 0,
        }
        left = WeakOrderStateView(path=(1, 6), **common)
        right = WeakOrderStateView(path=(2, 5), **common)
        action = WeakOrderActionView(1, (2, 1, 1), 1, 0, 0)
        model = WeakOrderLearningModel(
            {"hidden_size": 8, "message_layers": 1, "torch_threads": 1}
        )
        model.active_value_heads[:] = True

        left_prediction = model.predict_many(proposal, left, (action,))[0]
        right_prediction = model.predict_many(proposal, right, (action,))[0]

        self.assertNotEqual(
            left_prediction.value_probabilities,
            right_prediction.value_probabilities,
        )

    def test_specialization_ranker_sees_symbolic_family_and_weak_placement(self) -> None:
        candidate = self._ring_candidate()
        proposal = MappingProposal(
            candidate=candidate,
            raw_assignment_id=0,
            orientation_signs=(1, 1, 1),
            cyclic_offsets=(0, 0, 0),
            contour_lengths=(3, 3, 3),
            edge_ports=tuple((0.0,) * 8 for _edge in candidate.edges),
        )
        common_state = {
            "assignment_id": 0,
            "placement_id": 0,
            "placement_block_count": 2,
            "solver_variable_count": 3,
            "equation_count": 2,
            "interface_count": 3,
            "outer_arc_count": 3,
            "contour_literal_count": 3,
            "family_count": 2,
            "candidate_count": 2,
        }
        left_state = SpecializationPoolStateView(
            placement_blocks=((0, 1), (2,)), **common_state
        )
        right_state = SpecializationPoolStateView(
            placement_blocks=((0,), (1, 2)), **common_state
        )
        common_action = {
            "index": 0,
            "family_id": 0,
            "family_kind": "finite",
            "residual_graph_nodes": 3,
            "family_power_depth": 0,
            "family_trace_length": 2,
            "exponent_variable_count": 0,
            "exponent_sum": 0,
            "exponent_minimum": 0,
            "exponent_maximum": 0,
            "environment_variable_count": 2,
            "total_word_literals": 4,
            "maximum_word_literals": 2,
            "distinct_word_count": 2,
            "distinct_literal_variable_count": 2,
            "inverse_literal_count": 1,
            "empty_word_count": 0,
        }
        direct = SpecializationActionView(
            environment_words=((1, 2), (-1, 2)), **common_action
        )
        crossed = SpecializationActionView(
            environment_words=((1, -2), (2, 1)), **common_action
        )
        model = SpecializationLearningModel(
            {"hidden_size": 8, "message_layers": 1, "torch_threads": 1}
        )

        symbolic = model.predict_many(proposal, left_state, (direct, crossed))
        placement = (
            model.predict(proposal, left_state, direct),
            model.predict(proposal, right_state, direct),
        )

        self.assertNotEqual(symbolic[0], symbolic[1])
        self.assertNotEqual(placement[0], placement[1])

        observation = SpecializationPoolObservation(
            proposal=proposal,
            state=left_state,
            decisions=(
                SpecializationDecisionObservation(
                    action=direct,
                    outcome=SpecializationOutcomeView(
                        True, True, False, "emitted", None, 0.01, "fp-test"
                    ),
                    selection_mode="exploration",
                    selection_probability=0.5,
                    policy_entropy=0.5,
                    predicted_valid_probability=0.5,
                    predicted_emission_probability=0.5,
                    selection_score=0.5,
                ),
            ),
            pool_sequence=0,
            random_seed=1,
        )
        compact = observation.to_dict(include_proposal=False)
        restored = SpecializationPoolObservation.from_dict(
            compact, proposal=proposal
        )
        self.assertNotIn("proposal", compact)
        self.assertEqual(restored.pool_id, observation.pool_id)
        self.assertEqual(restored.decisions[0].action.environment_words, direct.environment_words)

    def test_specialization_policy_changes_order_but_never_closes_candidate(self) -> None:
        class FakeModel:
            has_policy_signal = True

            @staticmethod
            def predict_many(_proposal, _state, actions):
                return tuple(
                    SpecializationPrediction(
                        0.99 if action.index == 9 else 0.01,
                        0.5,
                    )
                    for action in actions
                )

        state = SpecializationPoolStateView(
            0, 0, 1, 1, 1, 1, 1, 1, 10, 10, ((0,),)
        )
        actions = tuple(
            SpecializationActionView(
                index,
                index,
                "finite",
                1,
                0,
                0,
                0,
                0,
                0,
                0,
                1,
                1,
                1,
                1,
                1,
                0,
                0,
                ((1,),),
            )
            for index in range(10)
        )
        preferred_first = 0
        visited = set()
        for seed in range(100):
            policy = SpecializationRankedPolicy(
                object(),
                FakeModel(),
                {
                    "exploration_fraction": 0.25,
                    "temperature": 0.05,
                    "epsilon": 0.0,
                    "visits_per_pool": 4,
                },
                random_seed=seed,
            )
            order = tuple(policy.select_specializations(state, actions))
            self.assertEqual(len(order), 4)
            self.assertEqual(len(set(order)), 4)
            self.assertTrue(set(order) <= set(range(10)))
            visited.update(order)
            preferred_first += order[0] == 9

        self.assertGreater(preferred_first, 50)
        self.assertEqual(visited, set(range(10)))

    def test_unified_lab_entry_point_defaults_to_dashboard_and_geometry(self) -> None:
        arguments = build_lab_app_parser().parse_args([])
        self.assertFalse(arguments.no_dashboard)
        self.assertFalse(arguments.no_geometry)
        self.assertEqual(arguments.port, 8766)
        self.assertEqual(arguments.geometry_config, "config/graph_lab/geometry.json")
        self.assertFalse(arguments.exclude_rings)
        self.assertTrue(
            build_lab_app_parser().parse_args(["--exclude-rings"]).exclude_rings
        )

    def test_ring_exclusion_filters_the_generator_before_graph_ranking(self) -> None:
        output_root = ROOT / "output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as raw_output:
            runner = GraphLabRunner(
                ROOT,
                {
                    "output": {"directory": raw_output},
                    "space": {
                        "maximum_tiles": 4,
                        "exclude_rings": True,
                        "symmetric_prior_fraction": 1.0,
                        "imposed_symmetry_bias": 1.0,
                    },
                    "sampling": {"mutation_fraction": 0.0},
                    "learning": {
                        "hidden_size": 8,
                        "message_layers": 1,
                        "torch_threads": 1,
                    },
                    "evaluation": {
                        "base_search_config": "config/cycle_campaign/search.json"
                    },
                },
            )
            pool = runner._candidate_pool(
                random.Random(20260812), DiversityArchive(()), 1
            )

        self.assertTrue(runner.exclude_rings)
        self.assertEqual(len(pool), 1)
        self.assertFalse(pool[0].is_simple_ring)
        with self.assertRaisesRegex(ValueError, "reached the graph ranker"):
            runner._select(
                (self._ring_candidate(),),
                SimpleNamespace(),
                DiversityArchive(()),
                random.Random(1),
                1,
            )

    def test_ring_exclusion_is_checkpoint_compatible_in_both_directions(self) -> None:
        output_root = ROOT / "output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as raw_output:
            base_config = {
                "output": {"directory": raw_output},
                "space": {"maximum_tiles": 4},
                "sampling": {},
                "learning": {
                    "hidden_size": 8,
                    "message_layers": 1,
                    "torch_threads": 1,
                },
                "evaluation": {
                    "base_search_config": "config/cycle_campaign/search.json"
                },
            }
            with_rings = GraphLabRunner(ROOT, base_config)
            no_ring_config = json.loads(json.dumps(base_config))
            no_ring_config["space"]["exclude_rings"] = True
            without_rings = GraphLabRunner(ROOT, no_ring_config)
            state_path = Path(raw_output) / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": "graph-lab-state-v1",
                        "fingerprint": with_rings.fingerprint,
                        "next_generation": 624,
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual(with_rings.fingerprint, without_rings.fingerprint)
            self.assertEqual(without_rings._state_generation(), 624)
            self.assertEqual(with_rings._state_generation(), 624)

    def test_mapping_comparison_excludes_exploration_only_parents(self) -> None:
        def record(
            graph_id: str, mode: str, *, passed: bool
        ) -> tuple[object, dict[str, object]]:
            observation = SimpleNamespace(
                filter_id=LEARNING_FILTER_IDS[0],
                decided=1,
                passed=1 if passed else 0,
            )
            evaluation = SimpleNamespace(
                proposal=SimpleNamespace(
                    candidate=SimpleNamespace(graph_id=graph_id)
                ),
                filters=SimpleNamespace(observations=(observation,)),
                profiles=({"profile": True},) if passed else (),
                reach_vector=(1.0,),
            )
            return evaluation, {
                "selection_mode": mode,
                "predicted_conditional_probabilities": [0.5],
                "predicted_reach_probabilities": [0.5],
            }

        runner = object.__new__(GraphLabRunner)
        metrics = runner._mapping_generation_metrics(
            4,
            (
                record("easy-singleton", "exploration", passed=True),
                record("paired", "exploration", passed=False),
                record("paired", "learned", passed=True),
            ),
            {},
        )
        self.assertEqual(metrics["selection_modes"]["exploration"]["count"], 2)
        comparable = metrics["comparable_selection_modes"]
        self.assertEqual(comparable["exploration"]["count"], 1)
        self.assertEqual(comparable["learned"]["count"], 1)
        self.assertEqual(metrics["comparison"]["comparable_parent_count"], 1)
        self.assertEqual(metrics["comparison"]["excluded_parent_count"], 1)

    def test_weak_order_action_pool_is_uniform_without_mandatory_shapes(self) -> None:
        class PoolOnlyModel:
            active_heads = np.zeros(26, dtype=bool)

            @staticmethod
            def prepare_mapping(_proposal):
                return None

        state = WeakOrderStateView(
            assignment_id=0,
            path=(),
            counters=(0,) * 13,
            targets=(2,) * 13,
            block_count=0,
            resolved_length_equations=0,
            resolved_angle_equations=0,
            available_mask=(1 << 13) - 1,
            reference_index=0,
        )
        masks = tuple(range(1, 1 << 13))
        policy = WeakOrderRankedPolicy(
            object(),
            PoolOnlyModel(),
            {"action_pool_size": 64},
            random_seed=123,
            selection_mode="exploration",
        )

        self.assertEqual(
            tuple(policy.propose_masks(state, masks)),
            tuple(random.Random(123).sample(masks, 64)),
        )

    def test_graph_candidates_can_be_revisited_for_new_descendant_rollouts(self) -> None:
        output_root = ROOT / "output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as raw_output:
            runner = GraphLabRunner(
                ROOT,
                {
                    "output": {"directory": raw_output},
                    "space": {
                        "maximum_tiles": 3,
                        "symmetric_prior_fraction": 1.0,
                        "imposed_symmetry_bias": 0.0,
                    },
                    "sampling": {"mutation_fraction": 0.0},
                    "learning": {
                        "hidden_size": 8,
                        "message_layers": 1,
                        "torch_threads": 1,
                    },
                    "evaluation": {
                        "base_search_config": "config/cycle_campaign/search.json"
                    },
                },
            )
            first = runner._candidate_pool(
                random.Random(1), DiversityArchive(()), 1
            )[0]
            second = runner._candidate_pool(
                random.Random(2), DiversityArchive(()), 1
            )[0]

        self.assertEqual(first.graph_id, second.graph_id)

    def test_weak_order_ranker_changes_the_stochastic_action_distribution(self) -> None:
        class FakeModel:
            active_heads = np.asarray([True] + [False] * 25)
            active_value_heads = np.asarray([True, False, False])
            has_policy_signal = True

            @staticmethod
            def prepare_mapping(_proposal):
                return None

            @staticmethod
            def predict_many(
                _proposal, _state, actions, *, prepared_mapping=None
            ):
                self.assertIsNone(prepared_mapping)
                probabilities = (0.05, 0.95)
                return tuple(
                    WeakOrderPrediction(
                        conditional_probabilities=(probabilities[index],)
                        + (0.5,) * 25,
                        reach_probabilities=(probabilities[index],)
                        + (0.5,) * 25,
                        value_probabilities=(probabilities[index], 0.5, 0.5),
                        auxiliary_progress=0.5,
                        expected_seconds=0.0,
                    )
                    for index, _action in enumerate(actions)
                )

            @staticmethod
            def policy_score(prediction):
                return prediction.reach_probabilities[0]

        state = WeakOrderStateView(
            assignment_id=0,
            path=(),
            counters=(0, 0),
            targets=(2, 2),
            block_count=0,
            resolved_length_equations=0,
            resolved_angle_equations=0,
            available_mask=3,
            reference_index=0,
        )
        actions = (
            WeakOrderActionView(1, (1, 0), 1, 0, 0),
            WeakOrderActionView(3, (1, 1), 2, 0, 0),
        )
        policy = WeakOrderRankedPolicy(
            object(),  # FakeModel does not inspect the mapping proposal.
            FakeModel(),
            {
                "epsilon": 0.0,
                "temperature": 0.1,
                "deeper_utility_weight": 0.0,
                "cost_weight": 0.0,
            },
            random_seed=4,
            selection_mode="learned",
        )

        self.assertEqual(policy.select_actions(state, actions), (3,))
        self.assertEqual(policy.decisions[0].selection_mode, "learned")
        self.assertGreater(policy.decisions[0].selection_probability, 0.99)

    def test_mapping_learning_generation_persists_microfilter_observations(self) -> None:
        output_root = ROOT / "output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as raw_output:
            runner = GraphLabRunner(
                ROOT,
                {
                    "output": {"directory": raw_output},
                    "space": {
                        "maximum_tiles": 3,
                        "symmetric_prior_fraction": 0.0,
                        "imposed_symmetry_bias": 0.0,
                    },
                    "sampling": {
                        "seed": 9,
                        "generations": 1,
                        "batch_size": 1,
                        "pool_multiplier": 1,
                    },
                    "learning": {
                        "hidden_size": 8,
                        "message_layers": 1,
                        "steps_per_generation": 1,
                        "batch_size": 1,
                        "torch_threads": 1,
                    },
                    "mapping_sampling": {
                        "enabled": True,
                        "mappings_per_graph": 1,
                        "pool_multiplier": 2,
                        "exploration_fraction": 0.5,
                        "rollouts_per_mapping": 1,
                    },
                    "mapping_learning": {
                        "hidden_size": 8,
                        "message_layers": 1,
                        "steps_per_generation": 1,
                        "batch_size": 1,
                        "torch_threads": 1,
                    },
                    "weak_order_sampling": {
                        "enabled": True,
                        "rollouts_per_mapping": 2,
                        "exploration_fraction": 0.5,
                        "action_pool_size": 8,
                    },
                    "weak_order_learning": {
                        "hidden_size": 8,
                        "message_layers": 1,
                        "steps_per_generation": 1,
                        "batch_size": 1,
                        "metric_decisions": 8,
                        "torch_threads": 1,
                    },
                    "evaluation": {
                        "base_search_config": "config/cycle_campaign/search.json",
                        "mapping_search_overrides": {
                            "limits": {
                                "max_nodes": 200,
                                "max_placements": 2,
                                "max_profiles": 1,
                                "time_limit_seconds": 3,
                                "stop_on_first_profile": True,
                            }
                        },
                    },
                },
            )
            result = runner.run(restart=True)
            output = Path(raw_output)
            mapping_record = json.loads(
                (output / "mapping_observations.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            self.assertFalse(mapping_record.get("error"), mapping_record)
            mapping_metrics = json.loads(
                (output / "mapping_training_metrics.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            weak_records = [
                json.loads(line)
                for line in (output / "weak_order_rollouts.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            weak_metrics = json.loads(
                (output / "weak_order_training_metrics.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            coverage = json.loads(
                (output / "rollout_coverage_metrics.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
        self.assertEqual(result.observations, 1)
        self.assertEqual(len(mapping_record["target_vector"]), 26)
        self.assertEqual(len(mapping_record["reach_vector"]), 26)
        self.assertEqual(mapping_record["rollout_count"], 2)
        self.assertEqual(mapping_metrics["model"]["examples"], 1)
        self.assertEqual(mapping_metrics["selection_modes"]["exploration"]["count"], 1)
        self.assertEqual(len(weak_records), 2)
        self.assertTrue(
            all(len(record["target_vector"]) == 26 for record in weak_records)
        )
        self.assertTrue(
            all(len(record["reach_vector"]) == 26 for record in weak_records)
        )
        self.assertEqual(weak_metrics["model"]["rollouts"], 2)
        self.assertEqual(
            sum(
                mode["count"]
                for mode in weak_metrics["selection_modes"].values()
            ),
            2,
        )
        self.assertTrue(coverage["semantics"]["graph_revisits_enabled"])
        self.assertTrue(coverage["semantics"]["mapping_revisits_enabled"])
        self.assertTrue(coverage["semantics"]["weak_order_revisits_enabled"])
        self.assertEqual(coverage["levels"]["graph"]["permanently_closed"], 0)
        self.assertEqual(coverage["levels"]["mapping"]["permanently_closed"], 0)
        self.assertEqual(
            coverage["levels"]["weak_order"]["permanently_closed"], 0
        )
        self.assertEqual(coverage["levels"]["mapping"]["proposals"]["count"], 2)
        self.assertEqual(coverage["levels"]["mapping"]["rollouts"]["count"], 1)

    def test_dedicated_geometry_and_visualizer_configs_load(self) -> None:
        geometry = load_geometry_config(ROOT / "config/graph_lab/geometry.json")
        visualization = load_visualization_config(
            ROOT / "config/graph_lab/visualizer.json"
        )
        self.assertIn("graph_lab", geometry["input"]["candidates_file"])
        self.assertIn("graph_lab", visualization["input"]["solutions_file"])

    def test_training_output_budget_stops_cleanly(self) -> None:
        output_root = ROOT / "output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as raw_output:
            runner = GraphLabRunner(
                ROOT,
                {
                    "output": {
                        "directory": raw_output,
                        "max_training_megabytes": 0.000001,
                    },
                    "space": {
                        "maximum_tiles": 13,
                    },
                    "sampling": {"generations": 1, "batch_size": 1},
                    "learning": {
                        "hidden_size": 8,
                        "message_layers": 1,
                        "torch_threads": 1,
                    },
                    "evaluation": {
                        "base_search_config": "config/cycle_campaign/search.json"
                    },
                },
            )
            result = runner.run(restart=True)
        self.assertEqual(result.stop_reason, "max_training_output_bytes")
        self.assertEqual(result.observations, 0)

    def test_one_generation_persists_a_prior_geometry_candidate(self) -> None:
        output_root = ROOT / "output"
        output_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output_root) as raw_output:
            config = {
                "output": {"directory": raw_output},
                "space": {
                    "maximum_tiles": 3,
                    "symmetric_prior_fraction": 1.0,
                },
                "sampling": {
                    "seed": 7,
                    "generations": 1,
                    "batch_size": 1,
                    "pool_multiplier": 1,
                },
                "learning": {
                    "seed": 7,
                    "hidden_size": 16,
                    "message_layers": 1,
                    "steps_per_generation": 1,
                    "batch_size": 1,
                    "torch_threads": 1,
                },
                "evaluation": {
                    "base_search_config": "config/cycle_campaign/search.json",
                    "search_overrides": {
                        "limits": {
                            "max_assignments": 1,
                            "max_nodes": 5000,
                            "max_placements": 10,
                            "max_profiles": 1,
                            "time_limit_seconds": 10,
                            "stop_on_first_profile": True,
                        },
                        "solver": {
                            "max_seconds_per_word_case": 2,
                            "max_graph_nodes_per_placement": 5000,
                        },
                    },
                },
            }
            runner = GraphLabRunner(ROOT, config)
            result = runner.run(restart=True)
            output = Path(raw_output)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            generation_metrics = json.loads(
                (output / "training_metrics.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            candidate_path = output / "geometry_candidates.jsonl"
            candidates = candidate_path.read_text(encoding="utf-8")
            first_candidate = json.loads(candidates.splitlines()[0])
            geometry_problem = parse_formal_geometry_problem(
                first_candidate,
                source_path=candidate_path,
                source_line=1,
            )
        self.assertEqual(result.observations, 1)
        self.assertEqual(result.geometry_ready_graphs, 1)
        self.assertEqual(result.stop_reason, "completed")
        self.assertEqual(len(report["geometry_ready"]), 1)
        self.assertEqual(report["tile_count_prior"], {"3": 1.0})
        self.assertEqual(generation_metrics["generation"], 0)
        self.assertEqual(
            sum(
                item["count"]
                for item in generation_metrics["selection_modes"].values()
            ),
            1,
        )
        self.assertIn('"graph_lab"', candidates)
        self.assertTrue(geometry_problem.segments)


if __name__ == "__main__":
    unittest.main()
