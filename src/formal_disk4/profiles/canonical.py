from __future__ import annotations

import hashlib
import json
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from formal_disk4.words.algebra import Literal, Word, inverse_word


def _normalized_linear_signature(word: Sequence[Literal]) -> Tuple[Tuple[int, bool], ...]:
    renaming: Dict[str, Tuple[int, bool]] = {}
    next_index = 0
    output = []
    for literal in word:
        if literal.variable not in renaming:
            # Flip the generator if needed so its first occurrence is positive.
            renaming[literal.variable] = (next_index, literal.inverse)
            next_index += 1
        index, generator_flip = renaming[literal.variable]
        output.append((index, literal.inverse ^ generator_flip))
    return tuple(output)


def canonical_contour_signature(word: Word) -> Tuple[Tuple[int, bool], ...]:
    if not word:
        return ()
    candidates = []
    for oriented in (tuple(word), inverse_word(word)):
        for offset in range(len(oriented)):
            rotated = oriented[offset:] + oriented[:offset]
            candidates.append(_normalized_linear_signature(rotated))
    return min(candidates)


def conservative_profile_key(
    map_name: str,
    assignment_key: object,
    blocks: object,
    environment: Mapping[str, Word],
) -> str:
    payload = {
        "map": map_name,
        "assignment": assignment_key,
        "blocks": blocks,
        "environment": {
            variable: [(literal.variable, literal.inverse) for literal in word]
            for variable, word in sorted(environment.items())
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
