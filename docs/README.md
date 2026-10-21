# Documentation

Start with the [research charter](research/README.md),
[operating method](research/METHODOLOGY.md),
[live agenda](research/AGENDA.md),
[research backbone](research/BACKBONE.md),
[mathematical-results registry](research/MATHEMATICAL_RESULTS.md), and
[approach inventory](research/STATE.md), updated 2026-10-21. They define the
current objective, dependency map and evidence standard. Technical notes below
describe existing components; historical roadmaps are not automatically the
next research plan.

`docs/` is the single documentation source tree for the project.

- Markdown and text files document the maintained architecture, APIs, output
  schemas, experiments, and mathematical notes.
- Editable LaTeX sources remain beside the argument they document.
- `docs/legacy/` contains historical experiment notes. They are references,
  not maintained runtime contracts.
- Existing committed PDFs are dated or reviewed snapshots. New local builds
  should be written to `output/docs/`, which is ignored by Git.

## Build LaTeX documents

From PowerShell at the repository root:

```powershell
.\scripts\build-docs.ps1
```

To build selected sources:

```powershell
.\scripts\build-docs.ps1 -Sources docs\joint_solver_filter_flowchart.tex,docs\filter_pipeline_roadmap.tex
```

The script uses `latexmk` when available and falls back to two `pdflatex`
passes. It never writes generated auxiliary files into `docs/`.

