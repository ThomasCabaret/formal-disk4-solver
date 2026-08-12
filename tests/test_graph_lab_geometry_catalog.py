from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from formal_disk4.geometry.status import GeometryCandidateStatus
from formal_disk4.graph_lab.geometry_catalog import GeometryCandidateCatalog


def _candidate(
    profile_id: str,
    *,
    generation: int,
    tiles: int,
    symmetry: int,
    ring: bool,
    mixed_orientation: bool = False,
) -> dict[str, object]:
    if ring:
        edges = [[-1, tile] for tile in range(tiles)] + [
            [tile, (tile + 1) % tiles] for tile in range(tiles)
        ]
    else:
        edges = [[-1, tile] for tile in range(tiles)] + [
            [0, tile] for tile in range(1, tiles)
        ]
    signs = {
        f"T{tile}": (-1 if mixed_orientation and tile % 2 else 1)
        for tile in range(tiles)
    }
    return {
        "formal_profile_id": profile_id,
        "map": {"name": "synthetic"},
        "assignment": {"orientation_signs": signs},
        "graph_lab": {
            "generation": generation,
            "graph_id": f"dg-{profile_id}",
            "structural_candidate": {
                "tile_count": tiles,
                "edges": edges,
                "symmetry_order": symmetry,
            },
        },
    }


class GeometryCandidateCatalogTests(unittest.TestCase):
    def test_incremental_index_deduplicates_and_classifies_cards(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "candidates.jsonl"
            records = (
                _candidate(
                    "fp-pizza", generation=2, tiles=4, symmetry=2, ring=True
                ),
                _candidate(
                    "fp-alert", generation=3, tiles=7, symmetry=1, ring=False
                ),
                _candidate(
                    "fp-pizza", generation=4, tiles=4, symmetry=2, ring=True
                ),
            )
            source.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            catalog = GeometryCandidateCatalog(root / "catalog.sqlite3", source)
            try:
                progress = catalog.ingest(maximum_lines=2)
                self.assertEqual(progress["source_line"], 2)
                progress = catalog.ingest()
                self.assertEqual(progress["unique_candidates"], 2)
                statuses = {
                    "fp-pizza": GeometryCandidateStatus(
                        "fp-pizza",
                        "solution_found",
                        "synthetic",
                        1,
                        0.0,
                        "now",
                    )
                }
                page = catalog.page(
                    page=1,
                    page_size=100,
                    statuses=statuses,
                    processing_profile_id="fp-alert",
                )
                items = {
                    item["formal_profile_id"]: item for item in page["items"]
                }
                self.assertEqual(page["total"], 2)
                self.assertEqual(page["distinct_total"], 2)
                self.assertEqual(page["occurrences_total"], 3)
                self.assertEqual(items["fp-pizza"]["occurrences"], 2)
                self.assertEqual(items["fp-pizza"]["importance"], "pizza")
                self.assertEqual(
                    items["fp-pizza"]["pizza_kind"],
                    "uniform_orientation_ring",
                )
                self.assertEqual(items["fp-pizza"]["status"], "solution_found")
                self.assertEqual(items["fp-alert"]["importance"], "alert")
                self.assertEqual(items["fp-alert"]["status"], "processing")
                pending = catalog.pending(set(statuses), limit=10)
                self.assertEqual(
                    [candidate.formal_profile_id for candidate in pending],
                    ["fp-alert"],
                )
                self.assertIn(b"fp-alert", catalog.read_raw(pending[0]))
            finally:
                catalog.close()

    def test_same_edge_count_does_not_make_a_non_cycle_a_pizza(self) -> None:
        candidate = _candidate(
            "fp-not-ring", generation=0, tiles=5, symmetry=5, ring=False
        )
        # Add one edge to make the misleading count exactly 2N while keeping
        # an internal degree pattern that is not a cycle.
        candidate["graph_lab"]["structural_candidate"]["edges"].append([1, 2])
        metadata = GeometryCandidateCatalog._metadata(candidate)
        self.assertEqual(metadata["is_pizza"], 0)
        self.assertEqual(metadata["pizza_kind"], "non_ring")

    def test_mixed_orientation_ring_is_still_a_conservative_pizza(self) -> None:
        candidate = _candidate(
            "fp-mixed",
            generation=0,
            tiles=6,
            symmetry=3,
            ring=True,
            mixed_orientation=True,
        )
        metadata = GeometryCandidateCatalog._metadata(candidate)
        self.assertEqual(metadata["is_pizza"], 1)
        self.assertEqual(metadata["pizza_kind"], "mixed_orientation_ring")


if __name__ == "__main__":
    unittest.main()
