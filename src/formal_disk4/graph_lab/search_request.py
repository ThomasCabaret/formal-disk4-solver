from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Mapping, Sequence

from .space import parse_symmetry_order_spec, parse_tile_count_spec


class RegionMode(str, Enum):
    """Which connected part of a proposed structure is solved."""

    FULL = "full"
    OUTER_CROWN = "outer_crown"
    CROWN_REGION = "crown_region"


class OuterBoundaryMode(str, Enum):
    DISK = "disk"
    FREE = "free"


class PrototypeSymmetryMode(str, Enum):
    NONE = "none"
    STRUCTURAL = "structural"


class ArrangementStrategy(str, Enum):
    ENUMERATE = "enumerate"
    JOINT_BACKTRACKING = "joint_backtracking"


class PolicyMode(str, Enum):
    PRIOR = "prior"
    LEARNED = "learned"


def _positive_count_domain(
    value: str | Sequence[int] | None,
) -> tuple[int, ...] | None:
    if value is None:
        return None
    counts: set[int] = set()
    if isinstance(value, str):
        for raw_token in value.split(","):
            token = raw_token.strip()
            if not token:
                raise ValueError("Crown-region domain contains an empty item")
            if "-" not in token:
                counts.add(int(token))
                continue
            parts = token.split("-")
            if len(parts) != 2:
                raise ValueError(f"Invalid crown-region range {token!r}")
            first, last = (int(part.strip()) for part in parts)
            if first > last:
                raise ValueError(f"Descending crown-region range {token!r}")
            counts.update(range(first, last + 1))
    else:
        counts.update(int(item) for item in value)
    if not counts or min(counts) < 1:
        raise ValueError("Crown-region tile counts must be positive")
    return tuple(sorted(counts))


@dataclass(frozen=True)
class SearchDomain:
    tile_counts: tuple[int, ...] | None = None
    symmetry_orders: tuple[int, ...] | None = None
    exclude_rings: bool = False


@dataclass(frozen=True)
class StructuralConstraints:
    stein_symmetric: bool = False
    allow_imposed_symmetry: bool = True


@dataclass(frozen=True)
class RegionSelection:
    mode: RegionMode = RegionMode.FULL
    tile_counts: tuple[int, ...] | None = None


@dataclass(frozen=True)
class BoundaryConditions:
    outer: OuterBoundaryMode = OuterBoundaryMode.DISK


@dataclass(frozen=True)
class PrototypeConstraints:
    symmetry: PrototypeSymmetryMode = PrototypeSymmetryMode.NONE


@dataclass(frozen=True)
class GraphLabSearchRequest:
    """Stable, strategy-neutral description of a Graph Lab search.

    This contract deliberately separates the mathematical domain from the
    algorithm used to traverse it.  A future graph-, mapping-, or weak-order
    backtracker can therefore replace an enumerator without changing callers.
    """

    domain: SearchDomain = SearchDomain()
    structure: StructuralConstraints = StructuralConstraints()
    region: RegionSelection = RegionSelection()
    boundary: BoundaryConditions = BoundaryConditions()
    prototype: PrototypeConstraints = PrototypeConstraints()
    arrangement: ArrangementStrategy = ArrangementStrategy.ENUMERATE
    policy: PolicyMode = PolicyMode.PRIOR

    def __post_init__(self) -> None:
        if self.structure.stein_symmetric and not self.structure.allow_imposed_symmetry:
            raise ValueError("stein_symmetric requires an imposed symmetry")
        if self.domain.symmetry_orders and not self.structure.stein_symmetric:
            raise ValueError("symmetry_orders requires stein_symmetric mode")
        if self.region.mode is not RegionMode.FULL and not self.structure.stein_symmetric:
            raise ValueError("Crown-region searches require stein_symmetric mode")
        if self.region.mode is RegionMode.CROWN_REGION and not self.region.tile_counts:
            raise ValueError("crown_region requires at least one region tile count")
        if self.region.mode is not RegionMode.CROWN_REGION and self.region.tile_counts:
            raise ValueError("Region tile counts are valid only for crown_region")
        if (
            self.region.mode is not RegionMode.FULL
            and self.boundary.outer is OuterBoundaryMode.FREE
        ):
            raise ValueError("Crown regions and a free complete outer boundary are exclusive")
        if (
            self.prototype.symmetry is not PrototypeSymmetryMode.NONE
            and self.region.mode is RegionMode.FULL
        ):
            raise ValueError("Prototype symmetry is currently defined for crown regions")

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "GraphLabSearchRequest":
        space = dict(config.get("space", {}))
        evaluation = dict(config.get("evaluation", {}))
        policy = dict(config.get("policy", {}))

        tile_counts_value = space.get("tile_counts")
        symmetry_orders_value = space.get("symmetry_orders")
        partial_counts = _positive_count_domain(
            evaluation.get("partial_crown_tile_counts")  # type: ignore[arg-type]
        )
        outer_crown = bool(evaluation.get("outer_crown_only", False) or partial_counts)
        region_mode = (
            RegionMode.CROWN_REGION
            if partial_counts
            else RegionMode.OUTER_CROWN
            if outer_crown
            else RegionMode.FULL
        )
        default_prototype = "structural" if outer_crown else "none"
        arrangement_config = dict(evaluation.get("joint_arrangement_search", {}))

        return cls(
            domain=SearchDomain(
                tile_counts=(
                    parse_tile_count_spec(tile_counts_value)  # type: ignore[arg-type]
                    if tile_counts_value is not None
                    else None
                ),
                symmetry_orders=(
                    parse_symmetry_order_spec(symmetry_orders_value)  # type: ignore[arg-type]
                    if symmetry_orders_value is not None
                    else None
                ),
                exclude_rings=bool(space.get("exclude_rings", False)),
            ),
            structure=StructuralConstraints(
                stein_symmetric=bool(space.get("stein_symmetric", False)),
                allow_imposed_symmetry=(
                    float(space.get("imposed_symmetry_bias", 0.75)) > 0.0
                ),
            ),
            region=RegionSelection(mode=region_mode, tile_counts=partial_counts),
            boundary=BoundaryConditions(
                outer=(
                    OuterBoundaryMode.FREE
                    if bool(evaluation.get("free_outer_boundary", False))
                    else OuterBoundaryMode.DISK
                )
            ),
            prototype=PrototypeConstraints(
                symmetry=PrototypeSymmetryMode(
                    str(evaluation.get("prototype_symmetry_mode", default_prototype))
                )
            ),
            arrangement=(
                ArrangementStrategy.JOINT_BACKTRACKING
                if bool(arrangement_config.get("enabled", False))
                else ArrangementStrategy.ENUMERATE
            ),
            policy=PolicyMode(str(policy.get("mode", PolicyMode.PRIOR.value))),
        )

    def with_overrides(
        self,
        *,
        exclude_rings: bool | None = None,
        tile_counts: str | Sequence[int] | None = None,
        stein_symmetric: bool | None = None,
        allow_imposed_symmetry: bool | None = None,
        symmetry_orders: str | Sequence[int] | None = None,
        outer_crown_only: bool | None = None,
        free_outer_boundary: bool | None = None,
        partial_crown_tile_counts: str | Sequence[int] | None = None,
        prototype_symmetry_mode: str | None = None,
        joint_arrangement_search: bool | None = None,
        policy_mode: str | None = None,
    ) -> "GraphLabSearchRequest":
        domain = self.domain
        structure = self.structure
        region = self.region
        boundary = self.boundary
        prototype = self.prototype
        arrangement = self.arrangement
        policy = self.policy

        if exclude_rings is not None:
            domain = replace(domain, exclude_rings=bool(exclude_rings))
        if tile_counts is not None:
            domain = replace(domain, tile_counts=parse_tile_count_spec(tile_counts))
        if stein_symmetric is not None:
            structure = replace(structure, stein_symmetric=bool(stein_symmetric))
        if allow_imposed_symmetry is not None:
            structure = replace(
                structure, allow_imposed_symmetry=bool(allow_imposed_symmetry)
            )
        if symmetry_orders is not None:
            domain = replace(
                domain, symmetry_orders=parse_symmetry_order_spec(symmetry_orders)
            )
        if outer_crown_only is not None:
            region = RegionSelection(
                mode=(RegionMode.OUTER_CROWN if outer_crown_only else RegionMode.FULL)
            )
            if (
                outer_crown_only
                and prototype_symmetry_mode is None
                and self.region.mode is RegionMode.FULL
            ):
                prototype = PrototypeConstraints(
                    symmetry=PrototypeSymmetryMode.STRUCTURAL
                )
            elif not outer_crown_only and prototype_symmetry_mode is None:
                prototype = PrototypeConstraints(
                    symmetry=PrototypeSymmetryMode.NONE
                )
        if partial_crown_tile_counts is not None:
            region = RegionSelection(
                mode=RegionMode.CROWN_REGION,
                tile_counts=_positive_count_domain(partial_crown_tile_counts),
            )
            if (
                prototype_symmetry_mode is None
                and self.region.mode is RegionMode.FULL
            ):
                prototype = PrototypeConstraints(
                    symmetry=PrototypeSymmetryMode.STRUCTURAL
                )
        if free_outer_boundary is not None:
            boundary = BoundaryConditions(
                outer=(
                    OuterBoundaryMode.FREE
                    if free_outer_boundary
                    else OuterBoundaryMode.DISK
                )
            )
        if prototype_symmetry_mode is not None:
            prototype = PrototypeConstraints(
                symmetry=PrototypeSymmetryMode(prototype_symmetry_mode)
            )
        if joint_arrangement_search is not None:
            arrangement = (
                ArrangementStrategy.JOINT_BACKTRACKING
                if joint_arrangement_search
                else ArrangementStrategy.ENUMERATE
            )
        if policy_mode is not None:
            policy = PolicyMode(policy_mode)

        return replace(
            self,
            domain=domain,
            structure=structure,
            region=region,
            boundary=boundary,
            prototype=prototype,
            arrangement=arrangement,
            policy=policy,
        )

    def apply_to_config(self, config: Mapping[str, object]) -> dict[str, Any]:
        result = deepcopy(dict(config))
        space = dict(result.get("space", {}))
        if self.domain.tile_counts is not None:
            space["tile_counts"] = list(self.domain.tile_counts)
        space["exclude_rings"] = self.domain.exclude_rings
        space["stein_symmetric"] = self.structure.stein_symmetric
        if not self.structure.allow_imposed_symmetry:
            space["imposed_symmetry_bias"] = 0.0
        if self.domain.symmetry_orders is None:
            space.pop("symmetry_orders", None)
        else:
            space["symmetry_orders"] = list(self.domain.symmetry_orders)
        result["space"] = space

        evaluation = dict(result.get("evaluation", {}))
        evaluation["outer_crown_only"] = self.region.mode is not RegionMode.FULL
        if self.region.mode is RegionMode.CROWN_REGION:
            evaluation["partial_crown_tile_counts"] = list(
                self.region.tile_counts or ()
            )
        else:
            evaluation.pop("partial_crown_tile_counts", None)
        evaluation["free_outer_boundary"] = (
            self.boundary.outer is OuterBoundaryMode.FREE
        )
        evaluation["prototype_symmetry_mode"] = self.prototype.symmetry.value
        arrangement = dict(evaluation.get("joint_arrangement_search", {}))
        arrangement["enabled"] = (
            self.arrangement is ArrangementStrategy.JOINT_BACKTRACKING
        )
        evaluation["joint_arrangement_search"] = arrangement
        result["evaluation"] = evaluation

        policy = dict(result.get("policy", {}))
        policy["mode"] = self.policy.value
        result["policy"] = policy
        return result
