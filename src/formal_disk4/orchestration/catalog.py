from __future__ import annotations

import itertools
import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


CATALOG_SCHEMA = "formal-disk4-case-family-v1"
SUPPORTED_STAGES = ("search", "geometry", "visualize")


@dataclass(frozen=True)
class CaseDefinition:
    """One concrete map/configuration combination exposed to orchestration."""

    case_id: str
    label: str
    description: str
    map_name: str
    group: str
    config_paths: Mapping[str, Path]
    output_directory: Path
    stage_overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    structurally_impossible: bool = False
    source: Path | None = None

    def config_for(self, stage: str) -> Path:
        try:
            return self.config_paths[stage]
        except KeyError as exc:
            raise ValueError(
                f"Case {self.case_id!r} does not provide a {stage!r} configuration."
            ) from exc

    def overrides_for(self, stage: str) -> dict[str, Any]:
        return deepcopy(dict(self.stage_overrides.get(stage, {})))


@dataclass(frozen=True)
class CaseCatalog:
    root: Path
    cases: tuple[CaseDefinition, ...]

    @classmethod
    def load(cls, root: Path | str) -> "CaseCatalog":
        project_root = Path(root).resolve()
        cases: list[CaseDefinition] = []
        cases.extend(_load_static_cases(project_root))
        cases.extend(_load_family_cases(project_root))
        cases.sort(key=lambda item: (item.group.casefold(), item.label.casefold(), item.case_id))

        by_id: dict[str, CaseDefinition] = {}
        for case in cases:
            if case.case_id in by_id:
                previous = by_id[case.case_id]
                raise ValueError(
                    f"Duplicate case id {case.case_id!r} in {previous.source} and {case.source}."
                )
            by_id[case.case_id] = case
        return cls(project_root, tuple(cases))

    def get(self, case_id: str) -> CaseDefinition:
        for case in self.cases:
            if case.case_id == case_id:
                return case
        raise KeyError(f"Unknown case id: {case_id}")

    def groups(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(case.group for case in self.cases))

    def cases_in_group(self, group: str) -> tuple[CaseDefinition, ...]:
        return tuple(case for case in self.cases if case.group == group)


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return data


def _relative_or_default_output(root: Path, search_config: Path, case_id: str) -> Path:
    try:
        data = _read_json(search_config)
        raw = data.get("output", {}).get("directory")
        if raw:
            path = Path(str(raw))
            if path.is_absolute():
                try:
                    return path.relative_to(root)
                except ValueError:
                    return path
            return path
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return Path("output") / "cases" / case_id


def _load_static_cases(root: Path) -> Iterable[CaseDefinition]:
    case_root = root / "config" / "cases"
    if not case_root.exists():
        return ()
    result: list[CaseDefinition] = []
    for manifest_path in sorted(case_root.glob("*/case.json")):
        data = _read_json(manifest_path)
        if data.get("catalog_enabled", True) is False:
            continue
        case_id = str(data["id"])
        config_names = dict(data.get("configs", {}))
        config_paths: dict[str, Path] = {}
        for stage in SUPPORTED_STAGES:
            manifest_key = "visualizer" if stage == "visualize" else stage
            if manifest_key in config_names:
                config_paths[stage] = manifest_path.parent / str(config_names[manifest_key])
        if "search" not in config_paths:
            continue
        output_directory = _relative_or_default_output(
            root, config_paths["search"], case_id
        )
        result.append(
            CaseDefinition(
                case_id=case_id,
                label=str(data.get("label", case_id)),
                description=str(data.get("description", "")),
                map_name=str(data.get("map", case_id)),
                group=str(data.get("group", "Static cases")),
                config_paths=config_paths,
                output_directory=output_directory,
                tags=tuple(str(value) for value in data.get("tags", ())),
                structurally_impossible=bool(data.get("structurally_impossible", False)),
                source=manifest_path,
            )
        )
    return result


def _load_family_cases(root: Path) -> Iterable[CaseDefinition]:
    family_root = root / "config" / "case_families"
    if not family_root.exists():
        return ()
    result: list[CaseDefinition] = []
    for path in sorted(family_root.glob("*.json")):
        data = _read_json(path)
        if data.get("schema_version") != CATALOG_SCHEMA:
            raise ValueError(
                f"Unsupported case family schema in {path}: {data.get('schema_version')!r}."
            )
        result.extend(_expand_family(root, path, data))
    return result


def _expand_family(
    root: Path, source: Path, data: Mapping[str, Any]
) -> Iterable[CaseDefinition]:
    family_id = str(data["family_id"])
    group = str(data.get("label", family_id))
    base_configs = {
        stage: root / str(value)
        for stage, value in dict(data.get("base_configs", {})).items()
    }
    missing = [stage for stage in SUPPORTED_STAGES if stage not in base_configs]
    if missing:
        raise ValueError(f"Family {family_id!r} is missing configs: {', '.join(missing)}")

    output_template = str(data.get("output_template", "output/cases/{case_id}"))
    common_overrides = dict(data.get("stage_overrides", {}))
    common_tags = tuple(str(value) for value in data.get("tags", ()))
    variants = data.get("variants", ())
    if not isinstance(variants, list):
        raise ValueError(f"Family {family_id!r} variants must be a list.")

    result: list[CaseDefinition] = []
    for variant in variants:
        if not isinstance(variant, dict):
            raise ValueError(f"Family {family_id!r} contains a non-object variant.")
        values_by_name = {
            str(name): tuple(values)
            for name, values in dict(variant.get("parameter_values", {})).items()
        }
        combinations = (
            itertools.product(*values_by_name.values()) if values_by_name else [()]
        )
        for values in combinations:
            context = dict(zip(values_by_name, values))
            context["family_id"] = family_id
            context["variant_id"] = str(variant["id"])
            map_name = str(variant["map_template"]).format(**context)
            context["map"] = map_name
            case_id = str(variant.get("case_id_template", "{map}")).format(**context)
            context["case_id"] = case_id
            label = str(variant.get("label_template", variant.get("label", case_id))).format(
                **context
            )
            description = str(variant.get("description", data.get("description", ""))).format(
                **context
            )
            output_directory = Path(output_template.format(**context))
            overrides = _merge_stage_overrides(
                common_overrides, dict(variant.get("stage_overrides", {}))
            )
            tags = common_tags + tuple(str(value) for value in variant.get("tags", ()))
            result.append(
                CaseDefinition(
                    case_id=case_id,
                    label=label,
                    description=description,
                    map_name=map_name,
                    group=group,
                    config_paths=base_configs,
                    output_directory=output_directory,
                    stage_overrides=overrides,
                    tags=tags,
                    structurally_impossible=bool(
                        variant.get("structurally_impossible", False)
                    ),
                    source=source,
                )
            )
    return result


def _deep_merge(target: dict[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = deepcopy(value)
    return target


def _merge_stage_overrides(
    common: Mapping[str, Any], variant: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    stages = set(common) | set(variant)
    result: dict[str, dict[str, Any]] = {}
    for stage in stages:
        merged: dict[str, Any] = {}
        common_stage = common.get(stage, {})
        variant_stage = variant.get(stage, {})
        if isinstance(common_stage, Mapping):
            _deep_merge(merged, common_stage)
        if isinstance(variant_stage, Mapping):
            _deep_merge(merged, variant_stage)
        result[str(stage)] = merged
    return result
