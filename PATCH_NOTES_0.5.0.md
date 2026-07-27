# Patch 0.5.0 - Mapping-driven assembly visualizer

This patch adds the first rendering layer. It consumes geometric single-piece solutions and reconstructs all congruent copies solely from the formal contact mappings. It does not optimize or search for copy placements.

## Assembly reconstruction

- The map supplies the piece names and reference piece.
- Every contact mapping supplies oriented pairs of terminal contour segments and the direct/reflected relative parity.
- Starting from the identity transform on the reference piece, the assembler propagates Euclidean isometries through the internal-contact graph.
- A direct mapping produces a determinant `+1` relative transform; a reflected mapping produces determinant `-1`.
- Mapping curves are sampled only to validate the derived isometry. The isometry itself is obtained deterministically from an oriented interface chord and the required parity.
- All map cycles are checked after propagation. A solution is rejected by the visualizer if mapped interfaces do not coincide within the configured tolerance.

For the canonical `k3-pizza` solution, the two non-reference copies are rotations by approximately `-2*pi/3` and `+2*pi/3`. The maximum sampled contact residual is about `4.3e-16`.

## Interactive desktop viewer

The Tk viewer provides:

- a medium-gray background;
- one solid, contrasting fill color per piece;
- no contour strokes and no vertex markers;
- one dynamically generated checkbox per piece;
- Previous/Next buttons;
- left/right arrow navigation and Home/End shortcuts;
- stable framing when pieces are hidden;
- lazy JSONL access and a small assembly cache, so all geometric records are not fully loaded into memory.

The piece count is read from the map. The same code handles three-piece and four-piece records.

## New commands

```bat
run_pizza3_visualizer.bat
run_pizza3_pipeline.bat --restart
```

The complete pipeline script executes formal search, single-piece geometry, then opens the assembly viewer. Without `--restart`, the first two stages resume their checkpoints.

A non-GUI mapping check is also available:

```bat
.venv\Scripts\python.exe -m formal_disk4 visualize --config config\pizza3_visualizer.json --validate-only
```

## New files

- `config/pizza3_visualizer.json`
- `run_pizza3_visualizer.bat`
- `run_pizza3_pipeline.bat`
- `scripts/run_visualizer.ps1`
- `scripts/run_pizza3_pipeline.ps1`
- `src/formal_disk4/visualization/assembly.py`
- `src/formal_disk4/visualization/viewer.py`
- `src/formal_disk4/visualization/runner.py`
- `src/formal_disk4/visualization/validate.py`
- `tests/test_visualization.py`

## Validation

The complete suite contains 35 passing tests. New tests cover mapping-only pizza reconstruction, reflected relative isometries, random-access JSONL loading and headless assembly validation.
