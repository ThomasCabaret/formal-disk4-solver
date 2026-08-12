from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from formal_disk4.graph_lab.dashboard import (
    build_dashboard_data,
    build_unified_dashboard_data,
)
from formal_disk4.graph_lab.geometry_catalog import GeometryCandidateCatalog
from formal_disk4.graph_lab.space import DualGraphCandidate
from formal_disk4.graph_lab.structure_gallery import RecentStructureGallery
from formal_disk4.graph_lab.dashboard_page import UNIFIED_DASHBOARD_HTML


def _mode(eligible: int, passed: int, predicted: float) -> dict[str, object]:
    transitions = {}
    for stage in (
        "assignment",
        "placement",
        "preword_pass",
        "word_family",
        "geometry_ready",
    ):
        transitions[stage] = {
            "eligible": eligible,
            "passed": passed,
            "prediction_sum": predicted * eligible,
            "prediction_count": eligible,
        }
    return {"count": eligible, "transitions": transitions}


class GraphLabDashboardTests(unittest.TestCase):
    def test_recent_structure_gallery_preserves_visits_and_renders_schematic(self) -> None:
        candidate = DualGraphCandidate(
            tile_count=3,
            edges=((-1, 0), (-1, 1), (-1, 2), (0, 1), (0, 2), (1, 2)),
            imposed_permutation=(1, 2, 0),
            origin="test_prior",
            mutation="test",
        )
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "observations.jsonl"
            rows = [
                {
                    "generation": generation,
                    "candidate": candidate.to_dict(),
                    "stage_name": "geometry_ready" if generation == 2 else "placement",
                    "profile_count": generation,
                    "selection": {"selection_mode": "learned"},
                }
                for generation in range(3)
            ]
            source.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            gallery = RecentStructureGallery(source)
            recent = gallery.recent(2)
            rendered = gallery.svg("3")
            with source.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "generation": 3,
                            "candidate": candidate.to_dict(),
                            "stage_name": "assignment",
                            "profile_count": 0,
                            "selection": {"selection_mode": "exploration"},
                        }
                    )
                    + "\n"
                )
            appended = gallery.recent(1)

        self.assertEqual(recent["available"], 3)
        self.assertEqual(
            [item["generation"] for item in recent["items"]], [2, 1]
        )
        self.assertEqual(recent["items"][0]["symmetry_order"], 3)
        self.assertEqual(recent["items"][0]["symmetry_cycles"], "(T0 T1 T2)")
        self.assertIsNotNone(rendered)
        self.assertEqual(rendered.count("<polygon"), 3)
        self.assertEqual(appended["latest_line"], 4)
        self.assertEqual(appended["items"][0]["generation"], 3)
        self.assertIn('data-view="structures"', UNIFIED_DASHBOARD_HTML)

    def test_required_comparison_uses_only_parent_matched_modes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "mapping.jsonl"
            raw_mode = {
                "count": 100,
                "profile_emitting_count": 100,
                "filters": {
                    "assignment.canonical": {
                        "eligible": 100,
                        "passed": 100,
                        "prediction_sum": 50.0,
                        "prediction_count": 100,
                    }
                },
            }
            comparable_random = {
                "count": 10,
                "profile_emitting_count": 2,
                "filters": {
                    "assignment.canonical": {
                        "eligible": 10,
                        "passed": 2,
                        "prediction_sum": 5.0,
                        "prediction_count": 10,
                    }
                },
            }
            comparable_learned = {
                "count": 30,
                "profile_emitting_count": 9,
                "filters": {
                    "assignment.canonical": {
                        "eligible": 30,
                        "passed": 9,
                        "prediction_sum": 15.0,
                        "prediction_count": 30,
                    }
                },
            }
            source.write_text(
                json.dumps(
                    {
                        "generation": 1,
                        "evaluated": 130,
                        "geometry_ready": 11,
                        "filter_order": ["assignment.canonical"],
                        "selection_modes": {
                            "exploration": raw_mode,
                            "learned": comparable_learned,
                        },
                        "comparable_selection_modes": {
                            "exploration": comparable_random,
                            "learned": comparable_learned,
                        },
                        "comparison": {"scope": "same_generation_and_graph"},
                        "model": {"filters": {}},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            data = build_dashboard_data(
                source, window_generations=10, require_comparable=True
            )
        transition = data["transitions"][0]
        self.assertEqual(transition["recent_random"]["rate"], 0.2)
        self.assertEqual(transition["recent_learned"]["rate"], 0.3)
        self.assertEqual(data["recent_outcomes"]["exploration"]["rate"], 0.2)
        self.assertEqual(data["recent_outcomes"]["learned"]["rate"], 0.3)
        self.assertEqual(data["comparison"]["statistics_generations"], 1)

    def test_unified_dashboard_contains_three_levels_and_gallery(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            graph_row = {
                "generation": 0,
                "evaluated": 2,
                "geometry_ready": 1,
                "selection_modes": {
                    "exploration": _mode(1, 1, 0.5),
                    "learned": _mode(1, 1, 0.5),
                },
                "model": {"transitions": {}},
            }
            filter_mode = {
                "count": 1,
                "filters": {
                    "assignment.canonical": {
                        "eligible": 1,
                        "passed": 1,
                        "prediction_sum": 0.5,
                        "prediction_count": 1,
                    }
                },
            }
            filter_row = {
                "generation": 0,
                "evaluated": 2,
                "geometry_ready": 0,
                "filter_order": ["assignment.canonical"],
                "selection_modes": {
                    "exploration": filter_mode,
                    "learned": filter_mode,
                },
                "model": {"filters": {}},
            }
            weak_row = dict(filter_row)
            weak_row["schema_version"] = (
                "graph-lab-weak-order-generation-metrics-v1"
            )
            for name, row in (
                ("training_metrics.jsonl", graph_row),
                ("mapping_training_metrics.jsonl", filter_row),
                ("weak_order_training_metrics.jsonl", weak_row),
            ):
                (output / name).write_text(
                    json.dumps(row) + "\n", encoding="utf-8"
                )
            source = output / "geometry_candidates.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "formal_profile_id": "fp-demo",
                        "map": {"name": "demo"},
                        "graph_lab": {
                            "generation": 0,
                            "graph_id": "dg-demo",
                            "structural_candidate": {
                                "tile_count": 4,
                                "edges": [
                                    [-1, 0], [-1, 1], [-1, 2], [-1, 3],
                                    [0, 1], [1, 2], [2, 3], [3, 0],
                                ],
                                "symmetry_order": 2,
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            geometry = output / "geometry"
            catalog = GeometryCandidateCatalog(
                geometry / "geometry_candidate_catalog.sqlite3", source
            )
            try:
                catalog.ingest()
                data = build_unified_dashboard_data(
                    output, catalog, window_generations=1
                )
            finally:
                catalog.close()

        self.assertEqual([level["kind"] for level in data["levels"]], ["graph", "mapping", "weak_order"])
        self.assertEqual(data["gallery"]["total"], 1)
        self.assertEqual(
            data["gallery"]["items"][0]["importance"], "pizza"
        )
        self.assertEqual(data["gallery"]["occurrences_total"], 1)

    def test_mapping_metrics_use_the_microfilter_order(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "mapping_training_metrics.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "generation": 4,
                        "evaluated": 4,
                        "geometry_ready": 0,
                        "filter_order": ["assignment.canonical", "weak.positive_length"],
                        "selection_modes": {
                            "exploration": {
                                "count": 2,
                                "filters": {
                                    "assignment.canonical": {
                                        "eligible": 2,
                                        "passed": 1,
                                        "prediction_sum": 1.0,
                                        "prediction_count": 2,
                                    },
                                    "weak.positive_length": {
                                        "eligible": 1,
                                        "passed": 1,
                                        "prediction_sum": 0.5,
                                        "prediction_count": 1,
                                    },
                                },
                            },
                            "learned": {
                                "count": 2,
                                "filters": {
                                    "assignment.canonical": {
                                        "eligible": 2,
                                        "passed": 2,
                                        "prediction_sum": 1.5,
                                        "prediction_count": 2,
                                    },
                                    "weak.positive_length": {
                                        "eligible": 2,
                                        "passed": 1,
                                        "prediction_sum": 1.0,
                                        "prediction_count": 2,
                                    },
                                },
                            },
                        },
                        "model": {"filters": {}},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            data = build_dashboard_data(source, window_generations=1)

        self.assertEqual(data["kind"], "mapping")
        self.assertEqual(data["stages"][1:], ["assignment.canonical", "weak.positive_length"])
        self.assertEqual(data["transitions"][0]["recent_learned"]["rate"], 1.0)

    def test_compares_initial_recent_random_and_learned_conditionally(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source = Path(raw) / "training_metrics.jsonl"
            rows = [
                {
                    "generation": 0,
                    "evaluated": 20,
                    "geometry_ready": 1,
                    "training_output_bytes": 100,
                    "max_training_bytes": 1000,
                    "selection_modes": {
                        "exploration": _mode(10, 2, 0.2),
                        "learned": _mode(10, 3, 0.3),
                    },
                    "model": {"training_loss": 1.0, "transitions": {}},
                },
                {
                    "generation": 1,
                    "evaluated": 20,
                    "geometry_ready": 2,
                    "training_output_bytes": 200,
                    "max_training_bytes": 1000,
                    "selection_modes": {
                        "exploration": _mode(10, 4, 0.4),
                        "learned": _mode(10, 9, 0.8),
                    },
                    "model": {
                        "training_loss": 0.5,
                        "transitions": {},
                        "values": {
                            "profile_emitted": {
                                "eligible": 20,
                                "mean_rate": 0.25,
                                "mean_prediction": 0.3,
                                "auc": 0.8,
                                "active": True,
                            }
                        },
                        "pairwise_ranking": {
                            "profile_emitted": {
                                "pairs": 10,
                                "accuracy": 0.7,
                                "scope": "same_tile_count",
                            }
                        },
                    },
                },
            ]
            source.write_text(
                "".join(json.dumps(row) + "\n" for row in rows),
                encoding="utf-8",
            )
            data = build_dashboard_data(source, window_generations=1)

        first = data["transitions"][0]
        self.assertAlmostEqual(first["baseline"]["rate"], 0.2)
        self.assertAlmostEqual(first["recent_random"]["rate"], 0.4)
        self.assertAlmostEqual(first["recent_learned"]["rate"], 0.9)
        self.assertAlmostEqual(first["learned_vs_random_pp"], 50.0)
        self.assertEqual(data["summary"]["evaluated"], 40)
        self.assertEqual(data["summary"]["geometry_ready"], 3)
        self.assertEqual(data["objectives"][0]["eligible"], 20)
        self.assertEqual(data["objectives"][0]["auc"], 0.8)
        self.assertEqual(data["objectives"][0]["pair_accuracy"], 0.7)


if __name__ == "__main__":
    unittest.main()
