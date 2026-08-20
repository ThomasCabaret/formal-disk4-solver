from __future__ import annotations

import argparse
import html
import webbrowser
from pathlib import Path
from typing import Any, Mapping, Sequence

from formal_disk4.config import (
    load_config,
    load_geometry_config,
    load_visualization_config,
)
from formal_disk4.enumeration.assignments import AssignmentEnumerator
from formal_disk4.geometry.runner import GeometryRunner
from formal_disk4.graph_lab.space import (
    DualGraphCandidate,
    DynamicPlanarMap,
    build_dynamic_planar_map,
    validate_dual_graph,
)
from formal_disk4.orchestration.catalog_diagrams import (
    build_catalog_schematic,
    catalog_schematic_svg,
)
from formal_disk4.pipeline.runner import SolverRunner
from formal_disk4.visualization.runner import VisualizationRunner


SIZE = 6
TILE_COUNT = 3 * SIZE
OUTPUT_RELATIVE = Path("output/targeted/three-ring-18-column-next-inner")


def _outer(index: int) -> int:
    return index % SIZE


def _middle(index: int) -> int:
    return SIZE + index % SIZE


def _inner(index: int) -> int:
    return 2 * SIZE + index % SIZE


def tile_label(index: int) -> str:
    if index < SIZE:
        return f"E{index}"
    if index < 2 * SIZE:
        return f"M{index - SIZE}"
    return f"I{index - 2 * SIZE}"


def expected_edges() -> tuple[tuple[int, int], ...]:
    """Return exactly the contacts stated for the targeted 18-tile case."""

    edges: set[tuple[int, int]] = set()
    for index in range(SIZE):
        next_index = index + 1
        for left, right in (
            (-1, _outer(index)),
            (_outer(index), _middle(index)),
            (_middle(index), _inner(index)),
            (_outer(index), _inner(next_index)),
            (_middle(index), _inner(next_index)),
            (_inner(index), _inner(next_index)),
        ):
            edges.add((min(left, right), max(left, right)))
    return tuple(sorted(edges))


def imposed_rotation() -> tuple[int, ...]:
    """Map every E_i, M_i and I_i to the corresponding tile at i + 1."""

    return tuple(
        [_outer(index + 1) for index in range(SIZE)]
        + [_middle(index + 1) for index in range(SIZE)]
        + [_inner(index + 1) for index in range(SIZE)]
    )


def build_target_candidate() -> DualGraphCandidate:
    candidate = DualGraphCandidate(
        tile_count=TILE_COUNT,
        edges=expected_edges(),
        imposed_permutation=imposed_rotation(),
        origin="targeted_test",
        mutation="exact_three_ring_column_next_inner",
    )
    validate_dual_graph(candidate.graph(), maximum_tiles=TILE_COUNT)
    return candidate


def build_target_map() -> DynamicPlanarMap:
    dynamic = build_dynamic_planar_map(build_target_candidate())
    if dynamic.imposed_automorphism is None:
        raise AssertionError("The order-6 index shift was not found as an automorphism")
    if dynamic.imposed_equivariance_mode != "pointwise":
        raise AssertionError(
            "The targeted symmetry must constrain mappings and weak orders pointwise"
        )
    if SIZE not in dynamic.automorphism_orders:
        raise AssertionError("The generated map lost its order-6 rotation")
    return dynamic


def raw_assignment_count(dynamic: DynamicPlanarMap) -> int:
    enumerator = AssignmentEnumerator(
        dynamic.planar_map,
        allow_reflections=True,
        symmetry_mode="incremental",
        required_equivariance=dynamic.imposed_automorphism,
        required_equivariance_on_weak_orders=True,
    )
    return enumerator.raw_assignment_count()


def _root(value: str | Path) -> Path:
    return Path(value).resolve()


def _output(root: Path, value: str | Path | None) -> Path:
    return (Path(value).resolve() if value is not None else root / OUTPUT_RELATIVE)


def _contact_rows() -> str:
    rows = []
    for index in range(SIZE):
        labels = (
            f"E{index}--bord extérieur",
            f"E{index}--M{index}",
            f"M{index}--I{index}",
            f"E{index}--I{(index + 1) % SIZE}",
            f"M{index}--I{(index + 1) % SIZE}",
            f"I{index}--I{(index + 1) % SIZE}",
        )
        rows.append(
            "<tr><th>"
            + str(index)
            + "</th><td>"
            + " &nbsp; · &nbsp; ".join(map(html.escape, labels))
            + "</td></tr>"
        )
    return "".join(rows)


def write_preview(root: Path, output: Path) -> Path:
    dynamic = build_target_map()
    schematic = build_catalog_schematic(dynamic.planar_map)
    svg = catalog_schematic_svg(schematic, width=900, height=720)
    # The dynamic-map adapter deliberately uses neutral T_i names.  Relabel only
    # this presentation; the solver continues to consume the unmodified map.
    for index in reversed(range(TILE_COUNT)):
        svg = svg.replace(f">T{index}<", f">{tile_label(index)}<")
    candidate = build_target_candidate()
    page = f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Cas ciblé à 18 tuiles</title>
<style>
body{{font:15px system-ui,sans-serif;background:#eceff1;color:#202428;margin:0}}
main{{max-width:1160px;margin:24px auto;padding:0 20px}}
.card{{background:white;border:1px solid #c8ced3;border-radius:12px;padding:18px;box-shadow:0 4px 18px #0001}}
h1{{margin:0 0 8px}} .meta{{color:#58636c;margin-bottom:16px}}
svg{{width:100%;height:auto;max-height:760px;background:#f0f1f2;border-radius:8px}}
table{{border-collapse:collapse;width:100%;margin-top:15px}} th,td{{border-top:1px solid #dde2e5;padding:8px;text-align:left}}
code{{background:#eef1f3;padding:2px 5px;border-radius:4px}}
</style></head><body><main><div class="card">
<h1>Cas ciblé : 6 colonnes E/M/I</h1>
<div class="meta">18 tuiles · 36 arêtes duales · rotation imposée i → i+1 d'ordre 6 · id <code>{candidate.graph_id}</code></div>
{svg}
<table><thead><tr><th>i</th><th>Contacts imposés</th></tr></thead><tbody>{_contact_rows()}</tbody></table>
<p>Le dessin est un schéma topologique harmonique : les incidences et les contacts sont exacts, pas les formes ni les aires.</p>
</div></main></body></html>"""
    output.mkdir(parents=True, exist_ok=True)
    path = output / "structure.html"
    path.write_text(page, encoding="utf-8")
    return path


def _search_config(
    root: Path,
    output: Path,
    dynamic: DynamicPlanarMap,
    args: argparse.Namespace,
) -> dict[str, Any]:
    config = load_config(root / "config" / "cycle_campaign" / "search.json")
    config["maps"] = [dynamic.planar_map.name]
    config["output"]["directory"] = str(output)
    config["checkpoint"].update(
        {"enabled": True, "resume": True, "restart": bool(args.restart)}
    )
    config["enumeration"]["cyclic_equivariance"] = {
        "enabled": True,
        "automorphism": dynamic.imposed_automorphism,
        "enforce_weak_orders": True,
    }
    config["enumeration"].setdefault("cyclic_shift_equivariance", {})[
        "enabled"
    ] = False
    if args.max_assignments is not None:
        config["limits"]["max_assignments"] = int(args.max_assignments)
    if args.time_limit_seconds is not None:
        config["limits"]["time_limit_seconds"] = float(args.time_limit_seconds)
    if args.stop_on_first_profile:
        config["limits"]["stop_on_first_profile"] = True
    return config


def run_search(root: Path, output: Path, args: argparse.Namespace) -> Mapping[str, object]:
    dynamic = build_target_map()
    count = raw_assignment_count(dynamic)
    print(
        "[TARGET] exact graph ready: "
        f"id={build_target_candidate().graph_id} tiles={TILE_COUNT} edges=36 "
        f"symmetry=order-{SIZE} raw-assignments={count}",
        flush=True,
    )
    config = _search_config(root, output, dynamic, args)
    return SolverRunner(config, planar_maps=(dynamic.planar_map,)).run()


def _geometry_config(root: Path, output: Path, restart: bool) -> dict[str, Any]:
    config = load_geometry_config(root / "config" / "graph_lab" / "geometry.json")
    config["input"]["candidates_file"] = str(output / "candidates.jsonl")
    config["output"]["directory"] = str(output / "geometry")
    config["checkpoint"].update(
        {"enabled": True, "resume": True, "restart": bool(restart)}
    )
    return config


def _visualization_config(root: Path, output: Path) -> dict[str, Any]:
    config = load_visualization_config(root / "config" / "graph_lab" / "visualizer.json")
    config["input"]["solutions_file"] = str(
        output / "geometry" / "geometric_solutions.jsonl"
    )
    config["viewer"]["title"] = "Cas ciblé à 18 tuiles - solutions géométriques"
    config["viewer"]["empty_message"] = (
        "Aucune solution géométrique n'a encore été trouvée pour le cas ciblé."
    )
    return config


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and solve the exact order-6, 18-tile target graph."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show", help="validate and open the structural drawing")
    _add_common(show)
    show.add_argument("--no-browser", action="store_true")

    search = subparsers.add_parser("search", help="run the production formal solver")
    _add_common(search)
    search.add_argument("--restart", action="store_true")
    search.add_argument("--max-assignments", type=int, default=None)
    search.add_argument("--time-limit-seconds", type=float, default=None)
    search.add_argument("--stop-on-first-profile", action="store_true")

    geometry = subparsers.add_parser(
        "geometry", help="run the production numerical solver on formal survivors"
    )
    _add_common(geometry)
    geometry.add_argument("--restart", action="store_true")

    visualize = subparsers.add_parser(
        "visualize", help="open the production geometric-solution viewer"
    )
    _add_common(visualize)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = _root(args.root)
    output = _output(root, args.output)
    if args.command == "show":
        path = write_preview(root, output)
        dynamic = build_target_map()
        print(f"preview: {path}")
        print(
            f"validated: tiles={TILE_COUNT} edges={len(expected_edges())} "
            f"symmetry=order-{SIZE} raw-assignments={raw_assignment_count(dynamic)}"
        )
        if not args.no_browser:
            webbrowser.open(path.as_uri())
        return 0
    if args.command == "search":
        summary = run_search(root, output, args)
        statistics = dict(summary.get("statistics", {}))
        counters = dict(statistics.get("counters", {}))
        files = dict(summary.get("files", {}))
        print(
            "[TARGET SEARCH COMPLETE] "
            f"stop={statistics.get('stop_reason', 'unknown')} "
            f"elapsed={float(statistics.get('elapsed_seconds', 0.0)):.2f}s "
            f"assignments={int(counters.get('assignments_processed', 0))}/60 "
            f"profiles={int(counters.get('profiles_emitted', 0))} "
            f"candidates={files.get('candidates')} "
            f"checkpoint={files.get('checkpoint')}",
            flush=True,
        )
        return 0
    if args.command == "geometry":
        summary = GeometryRunner(
            _geometry_config(root, output, bool(args.restart))
        ).run()
        state = dict(summary.get("state", {}))
        print(
            "[TARGET GEOMETRY COMPLETE] "
            f"stop={summary.get('stop_reason', 'unknown')} "
            f"seen={int(state.get('candidates_seen', 0))} "
            f"solved={int(state.get('candidates_solved', 0))} "
            f"failed={int(state.get('candidates_failed', 0))} "
            f"solutions={summary.get('solutions_file')}",
            flush=True,
        )
        return 0
    if args.command == "visualize":
        VisualizationRunner(_visualization_config(root, output)).run()
        return 0
    raise AssertionError(f"Unknown command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
