from __future__ import annotations

import unittest

from formal_disk4.graph_lab.rollout_audit import build_audit_report


def _row(
    generation: int,
    *,
    graph_ids: dict[str, int],
    mapping_ids: dict[str, int],
    trajectory_ids: dict[str, int],
) -> dict[str, object]:
    def level(ids: dict[str, int], revisits: int) -> dict[str, object]:
        return {
            "proposals": {
                "count": 6,
                "unique": 6,
                "bins": {"symmetric": 4, "asymmetric": 2},
            },
            "rollouts": {
                "count": sum(ids.values()),
                "unique": len(ids),
                "id_counts": ids,
                "bins": {"symmetric": sum(ids.values())},
                "new_unique_ids": len(ids) - revisits,
                "historical_revisit_visits": revisits,
                "within_generation_repeat_visits": 0,
                "selection_modes": {"learned": 1, "exploration": 1},
            },
            "locally_not_selected": 4,
            "permanently_closed": 0,
        }

    return {
        "generation": generation,
        "levels": {
            "graph": level(graph_ids, generation),
            "mapping": level(mapping_ids, generation),
            "weak_order": {
                "rollouts": {
                    "count": sum(trajectory_ids.values()),
                    "unique": len(trajectory_ids),
                    "id_counts": trajectory_ids,
                    "new_unique_ids": len(trajectory_ids) - generation,
                    "historical_revisit_visits": generation,
                    "within_generation_repeat_visits": 0,
                    "without_policy_decision": 0,
                },
                "decision_funnel": {
                    "decisions": 2,
                    "legal_masks": 20,
                    "pooled_masks": 12,
                    "viable_actions": 6,
                    "selected_actions": 2,
                    "omitted_by_bounded_random_pool": 8,
                    "rejected_by_existing_prefix_filters": 6,
                    "locally_not_selected_by_policy": 4,
                    "pool_limit_hit_decisions": 1,
                    "progress_bins": {"q1": 1, "q2": 1},
                    "selected_block_size_bins": {"1": 2},
                    "viable_action_count_bins": {"2-8": 2},
                    "selection_modes": {"learned": 1, "exploration": 1},
                },
                "permanently_closed": 0,
            },
        },
    }


class RolloutAuditTest(unittest.TestCase):
    def test_report_separates_historical_and_recent_concentration(self) -> None:
        rows = [
            _row(
                0,
                graph_ids={"g0": 1, "g1": 1},
                mapping_ids={"m0": 1, "m1": 1},
                trajectory_ids={"w0": 1, "w1": 1},
            ),
            _row(
                1,
                graph_ids={"g0": 2},
                mapping_ids={"m0": 2},
                trajectory_ids={"w0": 2},
            ),
        ]

        report = build_audit_report(rows, window_generations=1)
        all_graph = report["all"]["levels"]["graph"]  # type: ignore[index]
        recent_graph = report["recent"]["levels"]["graph"]  # type: ignore[index]
        weak = report["all"]["levels"]["weak_order"]  # type: ignore[index]

        self.assertEqual(all_graph["total"], 4)
        self.assertEqual(all_graph["unique"], 2)
        self.assertEqual(recent_graph["unique"], 1)
        self.assertEqual(recent_graph["top_share"], 1.0)
        self.assertEqual(weak["legal_masks"], 40)
        self.assertEqual(weak["selected_actions"], 4)
        self.assertEqual(weak["permanently_closed"], 0)


if __name__ == "__main__":
    unittest.main()
