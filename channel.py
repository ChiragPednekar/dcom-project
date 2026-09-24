"""
channel.py -- Binary Symmetric Channel (BSC) model.

The BSC is the standard first-order model of a noisy radio link: every bit
independently flips with probability ``p``, regardless of whether it was a 0
or a 1 (hence "symmetric"). For a low-power IoT node, larger ``p`` stands in
for longer range, more interference, or a weaker transmit power budget.
"""

from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

Bits = List[int]


def bsc(bits: Bits, p: float, rng: Optional[random.Random] = None) -> Tuple[Bits, List[int]]:
    """Push ``bits`` through a BSC with crossover probability ``p``.

    Returns ``(received_bits, flipped_indices)``. The index list is what the
    live-demo view uses to paint the damaged bits red.
    """
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"bit-error probability must be in [0, 1], got {p}")

    r = rng or random
    out: Bits = []
    flipped: List[int] = []
    for i, bit in enumerate(bits):
        if r.random() < p:
            out.append(bit ^ 1)
            flipped.append(i)
        else:
            out.append(bit)
    return out, flipped


def channel_capacity(p: float) -> float:
    """Shannon capacity of the BSC in bits/channel-use: C = 1 - H(p).

    Useful context for the report: no coding scheme can beat this rate, so it
    marks the ceiling every curve in the comparison is pushing against.
    """
    if p <= 0.0 or p >= 1.0:
        return 1.0 if p in (0.0, 1.0) else 0.0
    h = -p * math.log2(p) - (1 - p) * math.log2(1 - p)
    return 1.0 - h


def expected_block_success(n_bits: int, p: float) -> float:
    """P(no bit in an n-bit block is flipped) = (1-p)^n.

    This is the analytical curve the RAW scheme should track, and it is what
    makes the "unprotected transmission collapses fast" point concrete.
    """
    return (1.0 - p) ** n_bits
