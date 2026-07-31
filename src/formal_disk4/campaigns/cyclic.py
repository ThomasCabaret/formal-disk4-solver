from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

FAMILY_MAP_PREFIXES = {
    "parallel": "double-cycle",
    "offset": "double-cycle-offset",
    "boundary-points": "inner-cycle-boundary-points",
    "center-points": "outer-cycle-center-points",
}
FAMILY_ALIASES = {
    "dc1": "parallel",
    "dc2": "offset",
    "dc4": "boundary-points",
    "dc5": "center-points",
}
SUPPORTED_MODES = ("search", "geometry", "count", "visualize", "info")


@dataclass(frozen=True)
class CyclicCase:
    family: str
    size: int

    @property
    def case_id(self) -> str:
        return f"{FAMILY_MAP_PREFIXES[self.family]}-{self.size}"

    @property
    def map_name(self) -> str:
        return self.case_id

    def to_dict(self) -> dict[str, object]:
        return {
            "family": self.family,
            "size": self.size,
            "case_id": self.case_id,
            "map": self.map_name,
        }


def normalize_family(value: str) -> str:
    family = FAMILY_ALIASES.get(value.lower(), value.lower())
    if family not in FAMILY_MAP_PREFIXES:
        raise ValueError(
            f"Unknown family {value!r}; choose from {', '.join(FAMILY_MAP_PREFIXES)}"
        )
    return family


def make_case(family: str, size: int) -> CyclicCase:
    normalized = normalize_family(family)
    if size < 3:
        raise ValueError("Cyclic two-ring campaigns require N >= 3")
    return CyclicCase(normalized, size)


def project_root() -> Path:
    root = Path.cwd().resolve()
    if not (root / "config" / "cycle_campaign" / "search.json").exists():
        raise RuntimeError(
            "Run this command from the formal_disk4_solver project root."
        )
    return root


def case_output_directory(root: Path, case: CyclicCase) -> Path:
    return root / "output" / "cases" / case.case_id


def _python_command(root: Path) -> list[str]:
    windows_python = root / ".venv" / "Scripts" / "python.exe"
    if windows_python.exists():
        return [str(windows_python)]
    return [sys.executable]


def _run_command(command: Sequence[str]) -> int:
    print("[COMMAND] " + " ".join(str(part) for part in command), flush=True)
    completed = subprocess.run(list(command), check=False)
    return int(completed.returncode)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _case_command(
    root: Path,
    case: CyclicCase,
    mode: str,
    extra: Sequence[str],
) -> list[str]:
    python = _python_command(root)
    output = case_output_directory(root, case)
    config_root = root / "config" / "cycle_campaign"
    if mode == "search":
        return python + [
            "-m",
            "formal_disk4",
            "run",
            "--config",
            str(config_root / "search.json"),
            "--map",
            case.map_name,
            "--output",
            str(output),
            *extra,
        ]
    if mode == "geometry":
        return python + [
            "-m",
            "formal_disk4",
            "geometry",
            "--config",
            str(config_root / "geometry.json"),
            "--input",
            str(output / "candidates.jsonl"),
            "--output",
            str(output / "geometry"),
            *extra,
        ]
    if mode == "visualize":
        return python + [
            "-m",
            "formal_disk4",
            "visualize",
            "--config",
            str(config_root / "visualizer.json"),
            "--input",
            str(output / "geometry" / "geometric_solutions.jsonl"),
            *extra,
        ]
    if mode == "info":
        if extra:
            raise ValueError("The info mode does not accept extra arguments")
        return python + ["-m", "formal_disk4", "map-info", "--map", case.map_name]
    raise ValueError(f"Unsupported command-building mode: {mode}")


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def count_case(root: Path, case: CyclicCase) -> dict[str, object]:
    output = case_output_directory(root, case)
    formal = _count_jsonl(output / "candidates.jsonl")
    solutions = _count_jsonl(output / "geometry" / "geometric_solutions.jsonl")
    checkpoint_path = output / "geometry" / "geometry_checkpoint.json"
    checkpoint: dict[str, Any] = {}
    if checkpoint_path.exists():
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            checkpoint = {}
    return {
        "family": case.family,
        "size": case.size,
        "case_id": case.case_id,
        "formal_candidates": formal,
        "geometry_seen": int(checkpoint.get("candidates_seen", 0)),
        "geometry_solved": solutions,
        "geometry_failed": int(checkpoint.get("candidates_failed", 0)),
        "geometry_completed": bool(checkpoint.get("completed", False)),
    }


def print_count_table(rows: Sequence[dict[str, object]]) -> None:
    print()
    print(f"{'CASE':38} {'FORMAL':>8} {'TESTED':>8} {'SOLVED':>8} {'FAILED':>8}")
    print("-" * 76)
    for row in rows:
        print(
            f"{str(row['case_id']):38} "
            f"{int(row['formal_candidates']):8d} "
            f"{int(row['geometry_seen']):8d} "
            f"{int(row['geometry_solved']):8d} "
            f"{int(row['geometry_failed']):8d}"
        )
    print("-" * 76)
    print(
        f"{'TOTAL':38} "
        f"{sum(int(row['formal_candidates']) for row in rows):8d} "
        f"{sum(int(row['geometry_seen']) for row in rows):8d} "
        f"{sum(int(row['geometry_solved']) for row in rows):8d} "
        f"{sum(int(row['geometry_failed']) for row in rows):8d}"
    )


def write_count_reports(root: Path, suite_id: str, rows: Sequence[dict[str, object]]) -> None:
    output = root / "output" / "suites" / suite_id
    output.mkdir(parents=True, exist_ok=True)
    totals = {
        "formal_candidates": sum(int(row["formal_candidates"]) for row in rows),
        "geometry_seen": sum(int(row["geometry_seen"]) for row in rows),
        "geometry_solved": sum(int(row["geometry_solved"]) for row in rows),
        "geometry_failed": sum(int(row["geometry_failed"]) for row in rows),
    }
    _write_json(
        output / "counts.json",
        {"suite_id": suite_id, "cases": list(rows), "totals": totals},
    )
    with (output / "counts.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)


def load_suite(root: Path, suite_name: str) -> tuple[str, tuple[CyclicCase, ...]]:
    supplied = Path(suite_name)
    if supplied.suffix.lower() == ".json" or supplied.parent != Path("."):
        path = supplied if supplied.is_absolute() else root / supplied
    else:
        path = root / "config" / "suites" / f"{suite_name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Suite file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    suite_id = str(data.get("suite_id") or path.stem)
    cases = tuple(
        make_case(str(entry["family"]), int(entry["size"]))
        for entry in data.get("cases", [])
    )
    if not cases:
        raise ValueError(f"Suite {suite_id!r} contains no cases")
    return suite_id, cases


def combine_solution_files(root: Path, suite_id: str, cases: Iterable[CyclicCase]) -> Path:
    target = root / "output" / "suites" / suite_id / "geometric_solutions.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as writer:
        for case in cases:
            source = (
                case_output_directory(root, case)
                / "geometry"
                / "geometric_solutions.jsonl"
            )
            if not source.exists():
                continue
            with source.open("r", encoding="utf-8") as reader:
                for line in reader:
                    if line.strip():
                        writer.write(line.rstrip("\n") + "\n")
    return target


def run_single_case(case: CyclicCase, mode: str, extra: Sequence[str]) -> int:
    root = project_root()
    print("=" * 72)
    print(f"Cyclic two-ring case: {case.case_id}")
    print(f"Family: {case.family}  N: {case.size}  Mode: {mode}")
    print("=" * 72)
    if mode == "count":
        rows = [count_case(root, case)]
        print_count_table(rows)
        return 0
    return _run_command(_case_command(root, case, mode, extra))




def suite_forwarded_arguments(mode: str, extra: Sequence[str]) -> tuple[list[str], bool]:
    forwarded = list(extra)
    restart_all = "--restart-all" in forwarded
    forwarded = [argument for argument in forwarded if argument != "--restart-all"]
    if "--restart" in forwarded:
        raise ValueError(
            "Use --restart-all for a fresh suite. Omit it entirely to resume each "
            "case from its own checkpoint."
        )
    if restart_all and mode in {"search", "geometry"}:
        forwarded.append("--restart")
    return forwarded, restart_all


def run_suite(suite_name: str, mode: str, extra: Sequence[str]) -> int:
    root = project_root()
    suite_id, cases = load_suite(root, suite_name)
    forwarded, restart_all = suite_forwarded_arguments(mode, extra)
    print("=" * 72)
    print(f"Cyclic two-ring suite: {suite_id}")
    print(f"Mode: {mode}  Cases: {len(cases)}  Restart all: {restart_all}")
    print("=" * 72)

    if mode == "count":
        rows = [count_case(root, case) for case in cases]
        print_count_table(rows)
        write_count_reports(root, suite_id, rows)
        print(f"[REPORT] {root / 'output' / 'suites' / suite_id / 'counts.csv'}")
        return 0

    if mode == "visualize":
        combined = combine_solution_files(root, suite_id, cases)
        if _count_jsonl(combined) == 0:
            print("[VIEWER] No geometric solutions are available in this suite.")
            return 0
        command = _python_command(root) + [
            "-m",
            "formal_disk4",
            "visualize",
            "--config",
            str(root / "config" / "cycle_campaign" / "visualizer.json"),
            "--input",
            str(combined),
            *forwarded,
        ]
        return _run_command(command)

    for index, case in enumerate(cases, 1):
        print()
        print(f"[SUITE {index}/{len(cases)}] {case.case_id}")
        result = run_single_case(case, mode, forwarded)
        if result != 0:
            print(f"[SUITE STOPPED] {case.case_id} returned exit code {result}.")
            return result
    print()
    print(f"[SUITE COMPLETE] {suite_id} mode={mode}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="External campaign runner for cyclic two-ring map families."
    )
    subparsers = parser.add_subparsers(dest="scope", required=True)

    case_parser = subparsers.add_parser("case", help="Run one family and one N")
    case_parser.add_argument("family")
    case_parser.add_argument("size", type=int)
    case_parser.add_argument("mode", choices=SUPPORTED_MODES)
    case_parser.add_argument("extra", nargs=argparse.REMAINDER)

    suite_parser = subparsers.add_parser("suite", help="Run a JSON suite")
    suite_parser.add_argument("suite")
    suite_parser.add_argument("mode", choices=SUPPORTED_MODES)
    suite_parser.add_argument("extra", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.scope == "case":
            return run_single_case(make_case(args.family, args.size), args.mode, args.extra)
        return run_suite(args.suite, args.mode, args.extra)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Current case checkpoint was left in place.")
        return 130
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 8


if __name__ == "__main__":
    raise SystemExit(main())
