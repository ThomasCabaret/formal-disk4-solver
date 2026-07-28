from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Mapping


@dataclass
class RunStats:
    started_at: float = field(default_factory=time.perf_counter)
    elapsed_before_seconds: float = 0.0
    counters: Dict[str, int] = field(default_factory=dict)
    timings: Dict[str, float] = field(default_factory=dict)
    stop_reason: str = "completed"

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + int(amount)

    def add_time(self, name: str, seconds: float) -> None:
        self.timings[name] = self.timings.get(name, 0.0) + max(0.0, float(seconds))

    def get(self, name: str) -> int:
        return self.counters.get(name, 0)

    @property
    def session_elapsed_seconds(self) -> float:
        return max(0.0, time.perf_counter() - self.started_at)

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, self.elapsed_before_seconds + self.session_elapsed_seconds)

    def restore(
        self,
        counters: Mapping[str, int],
        timings: Mapping[str, float],
        elapsed_seconds: float,
    ) -> None:
        self.counters = {str(key): int(value) for key, value in counters.items()}
        self.timings = {str(key): float(value) for key, value in timings.items()}
        self.elapsed_before_seconds = max(0.0, float(elapsed_seconds))
        self.started_at = time.perf_counter()
        self.stop_reason = "completed"

    def checkpoint_payload(self) -> Dict[str, object]:
        return {
            "elapsed_seconds": self.elapsed_seconds,
            "counters": dict(self.counters),
            "timings": dict(self.timings),
        }

    def to_dict(self) -> Dict[str, object]:
        elapsed = self.elapsed_seconds
        nodes = self.get("placement_nodes")
        placements = self.get("surviving_placements")
        graph_nodes = self.get("residual_graph_nodes")
        systems = self.get("solver_cases")
        sorted_timings = dict(sorted(self.timings.items()))
        return {
            "elapsed_seconds": elapsed,
            "session_elapsed_seconds": self.session_elapsed_seconds,
            "stop_reason": self.stop_reason,
            "counters": dict(sorted(self.counters.items())),
            "timings_seconds": sorted_timings,
            "timing_share_of_elapsed_percent": {
                name: (100.0 * seconds / elapsed if elapsed else 0.0)
                for name, seconds in sorted_timings.items()
            },
            "rates": {
                "placement_nodes_per_second": nodes / elapsed if elapsed else 0.0,
                "surviving_placements_per_second": placements / elapsed if elapsed else 0.0,
                "word_systems_per_second": systems / elapsed if elapsed else 0.0,
                "residual_graph_nodes_per_second": graph_nodes / elapsed if elapsed else 0.0,
                "profiles_per_second": self.get("profiles_emitted") / elapsed if elapsed else 0.0,
            },
        }
