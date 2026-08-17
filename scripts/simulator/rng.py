"""Deterministic per-machine RNG substreams (docs/simulator-spec.md section 3).

One ``random.Random`` instance per simulated machine, seeded from a single
master seed via ``machine_seed``. This derivation must not change silently
once adopted: doing so would silently change every previously generated
dataset's values for the same ``(seed, machine_id)`` pair.
"""

from __future__ import annotations

import hashlib
import random

__all__ = ["machine_rng", "machine_seed"]


def machine_seed(master_seed: int, machine_id: int) -> int:
    digest = hashlib.sha256(f"{master_seed}:{machine_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def machine_rng(master_seed: int, machine_id: int) -> random.Random:
    return random.Random(machine_seed(master_seed, machine_id))
