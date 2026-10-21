from __future__ import annotations

"""Lazy direct-contact arrangement search with global metric propagation.

Charts and endpoint comparisons are separate decisions. Every single cut
choice is checked against all physical contact lengths, not only interfaces
whose four endpoints have already been inserted. The downstream adapter still
owns derived word refinements; this first engine makes no finite-closure claim.
"""

from dataclasses import dataclass, replace
from .word_propagation import WordState
from typing import Callable, Iterator

from formal_disk4.maps.base import PlanarMap
from .angles import ContactAngleTheory
from .contact_model import Chart, ContactModel
from .contact_turns import ContactTurnTheory
from .contact_words import ContactWordTheory
from .linear import Form, LinearState, LinearTheory


@dataclass(frozen=True)
class ContactState:
    linear: LinearState
    charts: tuple[Chart | None, ...]
    blocks: tuple[tuple[int, ...], ...]
    coordinates: tuple[Form | None, ...]
    sector: tuple[tuple[Form, bool], ...] = ()
    word_snapshot: WordState | None = None


@dataclass(frozen=True)
class ContactType:
    blocks: tuple[tuple[int, ...], ...]
    charts: tuple[Chart, ...]
    linear: LinearState
    sector: tuple[tuple[Form, bool], ...] = ()


@dataclass(frozen=True)
class SearchStatistics:
    nodes: int
    complete_arrangements: int


class ContactTypeSearch:
    """Fixed-complex V2. A source of complexes is deliberately a separate caller.

    Both parity choices are retained; no physical contact by itself fixes a
    tile's reflection. The reference chart only fixes the global contour gauge.
    The optional validator accepts a partial state and must be consequence-only.
    """

    def __init__(self, planar_map: PlanarMap, *, allow_reflections: bool = True,
                 event_sink: Callable[[str, int], None] | None = None,
                 progress_sink: Callable[[dict], None] | None = None,
                 stop_predicate: Callable[[], bool] | None = None,
                 max_nodes: int | None = None,
                 propagate_turns: bool = True,
                 propagate_words: bool = True,
                 word_refinement_depth: int = 0,
                 word_sectors: bool = False,
                 partial_validator: Callable[[ContactState], bool] | None = None) -> None:
        self.model = ContactModel(planar_map)
        self.theory = LinearTheory(self.model.width)
        self.angles = ContactAngleTheory(planar_map)
        self.turns = ContactTurnTheory(self.model) if propagate_turns else None
        self.words = ContactWordTheory(self.model, self.theory,
                                      refinement_depth=0 if word_sectors else word_refinement_depth) if propagate_words else None
        self.word_sector_depth = word_refinement_depth if word_sectors else 0
        self.word_sector_cases = self.word_sector_rejections = 0
        self.allow_reflections = allow_reflections
        self.event_sink = event_sink or (lambda name, amount=1: None)
        self.progress_sink = progress_sink or (lambda progress: None)
        self.stop_predicate = stop_predicate or (lambda: False)
        self.partial_validator = partial_validator
        self.max_nodes = max_nodes
        self.nodes = self.complete = 0
        self.stopped = False
        self.path: list[dict] = []
        self.completed_branches = 0

    @property
    def statistics(self) -> SearchStatistics:
        return SearchStatistics(self.nodes, self.complete)

    def _event(self, name: str, amount: int = 1) -> None:
        self.event_sink(name, amount)

    def _stop(self) -> bool:
        if self.stop_predicate() or (self.max_nodes is not None and self.nodes >= self.max_nodes):
            self.stopped = True
            return True
        return False

    def _progress(self, state: ContactState) -> None:
        self.progress_sink({
            "engine": "contact_types", "assigned_occurrences": sum(map(len, state.blocks)),
            "total_occurrences": len(self.model.occurrences),
            "active_charts": sum(c is not None for c in state.charts),
            "branch_path": [dict(frame) for frame in self.path],
            "completed_branches": self.completed_branches,
            "linear_calls": self.theory.calls, "linear_rejections": self.theory.rejections,
            "linear_exact_calls": self.theory.oracle.exact_calls,
            "linear_seconds": self.theory.elapsed_seconds,
            "angle_seconds": self.angles.elapsed_seconds,
            "contact_turn_checks": self.turns.calls if self.turns else 0,
            "contact_turn_seconds": self.turns.elapsed_seconds if self.turns else 0,
            "contact_turn_rejections": self.turns.rejections if self.turns else 0,
            "word_propagation_seconds": self.words.elapsed_seconds if self.words else 0,
            "word_propagation_splits": self.words.splits if self.words else 0,
            "word_propagation_unions": self.words.unions if self.words else 0,
            "word_propagation_point_relations": self.words.point_relations if self.words else 0,
            "word_propagation_residuals": self.words.residuals if self.words else 0,
            "word_propagation_limited": self.words.limited if self.words else 0,
            "word_refinement_decisions": self.words.refinement_decisions if self.words else 0,
            "word_refinement_cases": self.words.refinement_cases if self.words else 0,
            "word_refinement_closed": self.words.refinement_closed if self.words else 0,
            "word_refinement_deferred": self.words.refinement_deferred if self.words else 0,
            "word_refinement_length_rejections": self.words.refinement_length_rejections if self.words else 0,
            "word_sector_cases": self.word_sector_cases,
            "word_sector_rejections": self.word_sector_rejections,
            "word_sector_depth": len(state.sector),
        })

    def enumerate(self) -> Iterator[ContactType]:
        m = self.model
        root_chart = m.chart(m.reference_index, 1, 0)
        charts: list[Chart | None] = [None] * len(m.piece_names)
        charts[m.reference_index] = root_chart
        coords: list[Form | None] = [None] * len(m.occurrences)
        for o, q in zip(root_chart.sequence, root_chart.coordinates):
            coords[o] = q
        state = ContactState(m.select_chart(m.root_state, root_chart), tuple(charts),
                             tuple((o,) for o in root_chart.sequence), tuple(coords))
        if not self.theory.check(state.linear):
            self._event("contact_root_length_rejections")
            return
        if not self.angles.check(state.blocks):
            self._event("contact_root_angle_rejections")
            return
        yield from self._search(state)

    def _search(self, state: ContactState) -> Iterator[ContactType]:
        if self._stop():
            return
        self.nodes += 1
        self._event("arrangement_nodes")
        self._event("contact_nodes")
        self._progress(state)
        if self.turns is not None:
            self._event("contact_turn_checks")
            if not self.turns.check(state.blocks, tuple(c.parity if c else 0 for c in state.charts)):
                self._progress(state)
                self._event("contact_turn_rejections")
                self._event(f"contact_depth_{sum(map(len, state.blocks))}_turn_rejections")
                return
        if self.partial_validator is not None and not self.partial_validator(state):
            self._event("contact_custom_rejections")
            return
        if self.words is not None:
            self._event("contact_word_checks")
            if not self.words.check(state):
                self._progress(state)
                self._event("contact_word_rejections")
                self._event(f"contact_depth_{sum(map(len, state.blocks))}_word_rejections")
                self._event("contact_word_rejection_" + self.words.last_reason)
                return
            result = self.words.last_result
            if (result is not None and result.ambiguous is not None and not result.limited
                    and len(state.sector) < self.word_sector_depth):
                diff = result.ambiguous
                for ordinal, (form, strict) in enumerate(((diff, False), (-diff, True), (diff, True)), 1):
                    if self._stop():
                        return
                    self.word_sector_cases += 1
                    linear = state.linear.positive(form) if strict else state.linear.equal(form)
                    if not self.theory.check(linear):
                        self.word_sector_rejections += 1
                        continue
                    self.path.append({"kind": "word-sector", "choice": ordinal, "choices": 3,
                                      "relation": ("equal", "shorter", "longer")[ordinal-1]})
                    yield from self._search(replace(state, linear=linear,
                        sector=state.sector+((form, strict),), word_snapshot=result.state))
                    self.completed_branches += 1
                    self.path.pop()
                return
        placed = {o for block in state.blocks for o in block}
        pending = [o for chart in state.charts if chart is not None
                   for o in chart.sequence if o not in placed]
        if pending:
            # Complete physical junctions first. This changes ordering only;
            # chart monotonicity remains in the linear system whichever corner
            # is selected, including a nonconsecutive one.
            vertex_counts = {}
            for o in placed:
                vertex = self.model.occurrences[o].vertex
                vertex_counts[vertex] = vertex_counts.get(vertex, 0) + 1
            occurrence = max(pending, key=lambda o: (
                vertex_counts.get(self.model.occurrences[o].vertex, 0), -o))
            yield from self._insert(state, occurrence)
            return
        missing = [i for i, chart in enumerate(state.charts) if chart is None]
        if not missing:
            self.complete += 1
            self._event("arrangement_complete")
            self._event("contact_complete")
            yield ContactType(state.blocks, tuple(c for c in state.charts if c is not None),
                              state.linear, state.sector)
            return
        active = {i for i, c in enumerate(state.charts) if c is not None}
        piece = max(missing, key=lambda i: (len(self.model.neighbors[i] & active),
                    len(self.model.neighbors[i]), len(self.model.base_sequences[i]), -i))
        options = [(p, c) for p in ((1, -1) if self.allow_reflections else (1,))
                   for c in range(len(self.model.base_sequences[piece]))]
        for ordinal, (parity, cut) in enumerate(options, 1):
            if self._stop():
                return
            self.path.append({"kind": "chart", "tile": self.model.piece_names[piece],
                              "choice": ordinal, "choices": len(options),
                              "parity": parity, "cut": cut})
            self._progress(state)
            self._event("contact_chart_options")
            chart = self.model.chart(piece, parity, cut)
            linear = self.model.select_chart(state.linear, chart)
            if self.theory.check(linear):
                charts, coords = list(state.charts), list(state.coordinates)
                charts[piece] = chart
                for o, q in zip(chart.sequence, chart.coordinates):
                    coords[o] = q
                yield from self._search(ContactState(linear, tuple(charts), state.blocks, tuple(coords), state.sector))
            else:
                self._event("contact_chart_length_rejections")
            self.completed_branches += 1
            self.path.pop()

    def _insert(self, state: ContactState, occurrence: int) -> Iterator[ContactType]:
        q = state.coordinates[occurrence]
        assert q is not None
        # Prototype zero is fixed by the reference chart. Equalities and every
        # open gap after it cover all [0,1) without omitting weak coincidences.
        # Positive contact lengths already impose each chart's strict order.
        # Restrict to its neighbouring placed corners without an LP call for
        # each impossible crossing. This is a consequence, not a new cutoff.
        chart = next(c for c in state.charts if c is not None and occurrence in c.sequence)
        local = {o: i for i, o in enumerate(chart.sequence)}
        position = local[occurrence]
        lower, upper = -1, len(state.blocks)
        for i, block in enumerate(state.blocks):
            for other in block:
                if other in local:
                    if local[other] < position:
                        lower = max(lower, i)
                    else:
                        upper = min(upper, i)
        options = [(True, i) for i in range(lower + 1, upper)]
        options += [(False, i) for i in range(max(0, lower), upper)]
        self._event("contact_chart_order_excluded_options", 2 * len(state.blocks) - len(options))
        depth = sum(map(len, state.blocks)) + 1
        feasible_options = 0
        for ordinal, (equal, index) in enumerate(options, 1):
            if self._stop():
                return
            self.path.append({"kind": "cut", "occurrence": self.model.occurrences[occurrence].name,
                              "choice": ordinal, "choices": len(options),
                              "relation": "equal" if equal else "inside", "block": index})
            self._progress(state)
            anchor = state.coordinates[state.blocks[index][0]]
            assert anchor is not None
            linear = state.linear.equal(q - anchor) if equal else state.linear.positive(q - anchor)
            if not equal:
                right = (state.coordinates[state.blocks[index + 1][0]]
                         if index + 1 < len(state.blocks) else self.model.one)
                assert right is not None
                linear = linear.positive(right - q)
            self._event("arrangement_candidate_blocks")
            self._event("contact_cut_options")
            self._event(f"contact_depth_{depth}_options")
            if not self.theory.check(linear):
                self._event("contact_cut_length_rejections")
                self._event(f"contact_depth_{depth}_length_rejections")
                self.path.pop()
                continue
            blocks = list(state.blocks)
            if equal:
                blocks[index] = tuple(sorted(blocks[index] + (occurrence,)))
            else:
                blocks.insert(index + 1, (occurrence,))
            if equal and not self.angles.check(tuple(blocks)):
                self._event("contact_cut_angle_rejections")
                self._event(f"contact_depth_{depth}_angle_rejections")
                self.path.pop()
                continue
            feasible_options += 1
            yield from self._search(ContactState(linear, state.charts, tuple(blocks), state.coordinates, state.sector))
            self.completed_branches += 1
            self.path.pop()
        if feasible_options == 1:
            self._event("contact_forced_cut_positions")
