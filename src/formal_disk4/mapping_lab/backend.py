from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np


@dataclass(frozen=True)
class ObservationBatch:
    """Model-independent learning signal produced by one evaluated batch."""

    candidate_ids: tuple[str, ...]
    features: np.ndarray
    terminal_stages: np.ndarray


class LearningBackend(Protocol):
    """Minimal contract needed by the campaign runner and proposal sampler."""

    @property
    def name(self) -> str: ...

    def score(self, features: np.ndarray) -> np.ndarray: ...

    def observe(
        self, batch: ObservationBatch, *, generation: int
    ) -> dict[str, Any]: ...

    def metrics(self) -> dict[str, Any]: ...

    def save(self) -> None: ...
