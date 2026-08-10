from __future__ import annotations

import argparse
import json
import random
import time
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from formal_disk4.config import load_config
from formal_disk4.maps.registry import build_map
from formal_disk4.orchestration.catalog import CaseCatalog, CaseDefinition

from .isomorphism import IsomorphismIndex
from .space import DualGraphCandidate, GraphSpace, candidate_from_planar_map


@dataclass
class CatalogGraphClass:
    representative: DualGraphCandidate
    case_ids: list[str] = field(default_factory=list)
    map_names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CatalogCoverageDomain:
    classes: tuple[CatalogGraphClass, ...]
    excluded_cases: tuple[Mapping[str, object], ...]
    selectable_case_count: int


def _deep_merge(target: dict[str, Any], source: Mapping[str, object]) -> None:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = deepcopy(value)


def _imposed_symmetry(case: CaseDefinition) -> str | None:
    config = load_config(case.config_for("search"))
    _deep_merge(config, case.overrides_for("search"))
    cyclic = dict(config.get("enumeration", {}).get("cyclic_equivariance", {}))
    if not bool(cyclic.get("enabled", False)):
        return None
    name = cyclic.get("automorphism")
    return str(name) if name else None


def collect_catalog_graph_classes(
    root: Path, *, maximum_tiles: int
) -> CatalogCoverageDomain:
    """Collapse catalog cases into graph + imposed-symmetry isomorphism classes."""

    catalog = CaseCatalog.load(root)
    index = IsomorphismIndex()
    by_representative: dict[str, CatalogGraphClass] = {}
    excluded: list[Mapping[str, object]] = []
    selectable = 0
    for case in catalog.cases:
        if case.structurally_impossible:
            excluded.append(
                {
                    "case_id": case.case_id,
                    "map": case.map_name,
                    "reason": "marked_structurally_impossible",
                }
            )
            continue
        selectable += 1
        try:
            symmetry = _imposed_symmetry(case)
            tile_count = len(build_map(case.map_name).pieces)
            if tile_count > maximum_tiles:
                raise ValueError(
                    f"{tile_count} tiles exceeds the configured maximum "
                    f"of {maximum_tiles}"
                )
            candidate = candidate_from_planar_map(
                case.map_name,
                imposed_automorphism=symmetry,
                origin="catalog_coverage_target",
            )
        except (KeyError, OSError, StopIteration, ValueError) as error:
            excluded.append(
                {
                    "case_id": case.case_id,
                    "map": case.map_name,
                    "reason": f"outside_current_graph_domain: {error}",
                }
            )
            continue

        representative = index.equivalent(candidate)
        if representative is None:
            index.add(candidate)
            representative = candidate
            by_representative[representative.graph_id] = CatalogGraphClass(
                representative=representative
            )
        target = by_representative[representative.graph_id]
        target.case_ids.append(case.case_id)
        if case.map_name not in target.map_names:
            target.map_names.append(case.map_name)

    classes = tuple(
        sorted(
            by_representative.values(),
            key=lambda item: (
                item.representative.tile_count,
                item.representative.symmetry_order,
                item.case_ids[0],
            ),
        )
    )
    return CatalogCoverageDomain(
        classes=classes,
        excluded_cases=tuple(excluded),
        selectable_case_count=selectable,
    )


def measure_prior_coverage(
    space: GraphSpace,
    domain: CatalogCoverageDomain,
    *,
    samples: int,
    seed: int,
    report_every: int = 10_000,
) -> dict[str, object]:
    """Measure catalog rediscovery using only ``GraphSpace.sample_prior``."""

    target_index = IsomorphismIndex()
    class_by_id = {}
    for target in domain.classes:
        target_index.add(target.representative)
        class_by_id[target.representative.graph_id] = target

    rng = random.Random(seed)
    hits: dict[str, int] = {}
    tile_histogram: Counter[int] = Counter()
    symmetry_histogram: Counter[int] = Counter()
    started = time.perf_counter()
    drawn = 0
    for sample_index in range(1, max(0, int(samples)) + 1):
        candidate = space.sample_prior(rng)
        drawn = sample_index
        tile_histogram[candidate.tile_count] += 1
        symmetry_histogram[candidate.symmetry_order] += 1
        representative = target_index.equivalent(candidate)
        if representative is not None and representative.graph_id not in hits:
            hits[representative.graph_id] = sample_index
            target = class_by_id[representative.graph_id]
            print(
                "[CATALOG HIT] "
                f"sample={sample_index} classes={len(hits)}/{len(domain.classes)} "
                f"cases={','.join(target.case_ids)}",
                flush=True,
            )
        if len(hits) == len(domain.classes):
            break
        if report_every > 0 and sample_index % report_every == 0:
            print(
                f"prior-coverage samples={sample_index} "
                f"classes={len(hits)}/{len(domain.classes)}",
                flush=True,
            )

    elapsed = time.perf_counter() - started
    class_records = []
    missed = []
    for target in domain.classes:
        graph_id = target.representative.graph_id
        record = {
            "graph_id": graph_id,
            "tile_count": target.representative.tile_count,
            "symmetry_order": target.representative.symmetry_order,
            "case_ids": target.case_ids,
            "map_names": target.map_names,
            "first_sample": hits.get(graph_id),
        }
        class_records.append(record)
        if graph_id not in hits:
            missed.append(record)
    return {
        "schema_version": "graph-lab-prior-coverage-v1",
        "samples_requested": int(samples),
        "samples_drawn": drawn,
        "seed": int(seed),
        "elapsed_seconds": elapsed,
        "samples_per_second": drawn / elapsed if elapsed > 0 else None,
        "selectable_catalog_cases": domain.selectable_case_count,
        "representable_catalog_cases": sum(
            len(target.case_ids) for target in domain.classes
        ),
        "representable_graph_symmetry_classes": len(domain.classes),
        "classes_hit": len(hits),
        "complete": len(hits) == len(domain.classes),
        "classes": class_records,
        "missed_classes": missed,
        "excluded_cases": list(domain.excluded_cases),
        "sampled_tile_count_histogram": dict(sorted(tile_histogram.items())),
        "sampled_symmetry_order_histogram": dict(
            sorted(symmetry_histogram.items())
        ),
    }


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="formal-disk4-graph-coverage",
        description=(
            "Measure how quickly the unlearned Graph Lab prior rediscovers "
            "representable catalog graph/symmetry classes."
        ),
    )
    parser.add_argument("--root", default=".")
    parser.add_argument("--config", default="config/graph_lab/up-to-13.json")
    parser.add_argument("--samples", type=int, default=1_000_000)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--report-every", type=int, default=10_000)
    parser.add_argument(
        "--output", default="output/graph_lab/prior-coverage.json"
    )
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="return a failing exit status when a representable class is missed",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path
    config = json.loads(config_path.read_text(encoding="utf-8"))
    space_config = dict(config.get("space", {}))
    # This measures the complete unlearned prior, including its stochastic
    # neighbourhood bias around known structural templates. It still performs
    # no direct known-control injection and uses no learned/archive proposal.
    space = GraphSpace.from_config(space_config)
    domain = collect_catalog_graph_classes(
        root, maximum_tiles=space.maximum_tiles
    )
    seed = int(
        args.seed
        if args.seed is not None
        else dict(config.get("sampling", {})).get("seed", 20260809)
    )
    report = measure_prior_coverage(
        space,
        domain,
        samples=max(0, int(args.samples)),
        seed=seed,
        report_every=max(0, int(args.report_every)),
    )
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    _atomic_json(output, report)
    print(
        "prior-coverage complete: "
        f"classes={report['classes_hit']}/"
        f"{report['representable_graph_symmetry_classes']} "
        f"samples={report['samples_drawn']} "
        f"rate={float(report['samples_per_second'] or 0.0):.1f}/s "
        f"excluded-cases={len(report['excluded_cases'])} "
        f"report={output}",
        flush=True,
    )
    return 1 if args.require_complete and not bool(report["complete"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
