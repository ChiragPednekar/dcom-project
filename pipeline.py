"""
pipeline.py -- End-to-end IoTGuard simulation.

Runs a sensor message through the full chain

    text -> Huffman -> error-control coding -> BSC -> decode -> verify

for three schemes:

* ``RAW``      -- no protection at all (the baseline that fails fastest)
* ``CRC_ARQ``  -- CRC-8 detection with automatic repeat request
* ``HAMMING``  -- Hamming(7,4) forward error correction

Every run reports the three quantities the comparison hinges on: did the
message arrive intact, how many bits went over the air (energy), and how many
retransmissions were needed (latency + energy).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import huffman
from channel import bsc
from error_control import (
    crc8_append,
    crc8_check,
    hamming74_decode,
    hamming74_encode,
)

Bits = List[int]

SCHEMES = ("RAW", "CRC_ARQ", "HAMMING")

SCHEME_LABELS = {
    "RAW": "RAW (no protection)",
    "CRC_ARQ": "CRC-8 + ARQ",
    "HAMMING": "Hamming(7,4) FEC",
}

DEFAULT_MAX_RETRANSMISSIONS = 5


# --------------------------------------------------------------------------- #
# Result containers
# --------------------------------------------------------------------------- #

@dataclass
class Attempt:
    """One trip across the channel (an ARQ scheme may need several)."""
    index: int
    sent: Bits
    received: Bits
    flipped: List[int]
    accepted: bool


@dataclass
class TrialResult:
    """A single end-to-end run, with enough detail to drive the step-by-step
    demo view."""
    scheme: str
    message: str
    p: float
    success: bool = False
    decoded: Optional[str] = None
    source_bits: Bits = field(default_factory=list)      # after Huffman
    encoded_bits: Bits = field(default_factory=list)     # after channel coding
    received_bits: Bits = field(default_factory=list)    # last received frame
    flipped_indices: List[int] = field(default_factory=list)
    corrected_bits: Bits = field(default_factory=list)   # after FEC repair
    bits_transmitted: int = 0        # total across all attempts
    retransmissions: int = 0
    blocks_corrected: int = 0
    undetected_error: bool = False   # CRC passed but payload was wrong
    gave_up: bool = False            # exhausted the ARQ budget
    attempts: List[Attempt] = field(default_factory=list)
    codes: Dict[str, str] = field(default_factory=dict)


@dataclass
class SchemeResult:
    """Averages over many trials at one value of p."""
    scheme: str
    p: float
    trials: int
    success_rate: float
    avg_bits: float
    avg_retransmissions: float
    undetected_error_rate: float
    give_up_rate: float


# --------------------------------------------------------------------------- #
# Single trial
# --------------------------------------------------------------------------- #

def run_trial(
    message: str,
    scheme: str,
    p: float,
    rng: Optional[random.Random] = None,
    max_retransmissions: int = DEFAULT_MAX_RETRANSMISSIONS,
    source_bits: Optional[Bits] = None,
    codes: Optional[Dict[str, str]] = None,
) -> TrialResult:
    """Run ``message`` through ``scheme`` once at bit-error probability ``p``.

    ``source_bits``/``codes`` may be passed in to reuse a codebook across many
    trials instead of rebuilding the Huffman tree every time.
    """
    if scheme not in SCHEMES:
        raise ValueError(f"unknown scheme {scheme!r}; expected one of {SCHEMES}")

    r = rng or random
    if source_bits is None or codes is None:
        source_bits, codes = huffman.encode(message)

    res = TrialResult(
        scheme=scheme, message=message, p=p,
        source_bits=list(source_bits), codes=dict(codes),
    )

    # ---------------- RAW: send the compressed bits bare ----------------
    if scheme == "RAW":
        res.encoded_bits = list(source_bits)
        received, flipped = bsc(res.encoded_bits, p, r)
        res.received_bits, res.flipped_indices = received, flipped
        res.corrected_bits = list(received)
        res.bits_transmitted = len(res.encoded_bits)
        res.attempts = [Attempt(0, res.encoded_bits, received, flipped, True)]
        res.decoded = huffman.decode(received, codes)

    # ------------- CRC_ARQ: detect, then ask for a resend ---------------
    elif scheme == "CRC_ARQ":
        frame = crc8_append(source_bits)
        res.encoded_bits = frame
        accepted_payload: Optional[Bits] = None

        for attempt in range(max_retransmissions + 1):
            received, flipped = bsc(frame, p, r)
            res.bits_transmitted += len(frame)
            valid, payload = crc8_check(received)
            res.attempts.append(Attempt(attempt, frame, received, flipped, valid))
            res.received_bits, res.flipped_indices = received, flipped
            if valid:
                accepted_payload = payload
                break

        # The first trip across the channel is the original transmission, not a
        # retransmission -- so the count is one less than the number of attempts.
        # Counting inside the loop would over-report by one whenever the budget
        # ran out, since the final failure is never actually re-sent.
        res.retransmissions = len(res.attempts) - 1

        if accepted_payload is None:
            res.gave_up = True          # budget exhausted, message dropped
            res.decoded = None
        else:
            res.corrected_bits = list(accepted_payload)
            res.decoded = huffman.decode(accepted_payload, codes)
            # CRC said "fine" but the payload differs -> undetected error
            if accepted_payload != list(source_bits):
                res.undetected_error = True

    # ------------- HAMMING: fix it at the receiver, no resend -----------
    else:
        encoded, pad = hamming74_encode(source_bits)
        res.encoded_bits = encoded
        received, flipped = bsc(encoded, p, r)
        res.received_bits, res.flipped_indices = received, flipped
        res.bits_transmitted = len(encoded)
        res.attempts = [Attempt(0, encoded, received, flipped, True)]
        repaired, corrected = hamming74_decode(received, pad)
        res.corrected_bits = repaired
        res.blocks_corrected = corrected
        res.decoded = huffman.decode(repaired, codes)

    res.success = res.decoded == message
    return res


# --------------------------------------------------------------------------- #
# Many trials at one p
# --------------------------------------------------------------------------- #

def run_scheme(
    message: str,
    scheme: str,
    p: float,
    trials: int = 200,
    seed: Optional[int] = None,
    max_retransmissions: int = DEFAULT_MAX_RETRANSMISSIONS,
) -> SchemeResult:
    """Average ``trials`` independent runs to get a stable success rate."""
    rng = random.Random(seed)
    source_bits, codes = huffman.encode(message)

    successes = bits = retx = undetected = gave_up = 0
    for _ in range(max(1, trials)):
        t = run_trial(
            message, scheme, p, rng, max_retransmissions,
            source_bits=source_bits, codes=codes,
        )
        successes += t.success
        bits += t.bits_transmitted
        retx += t.retransmissions
        undetected += t.undetected_error
        gave_up += t.gave_up

    n = max(1, trials)
    return SchemeResult(
        scheme=scheme, p=p, trials=n,
        success_rate=successes / n,
        avg_bits=bits / n,
        avg_retransmissions=retx / n,
        undetected_error_rate=undetected / n,
        give_up_rate=gave_up / n,
    )


# --------------------------------------------------------------------------- #
# Sweep across p -- this is what the charts plot
# --------------------------------------------------------------------------- #

def sweep(
    message: str,
    p_values: Sequence[float],
    schemes: Sequence[str] = SCHEMES,
    trials: int = 200,
    seed: Optional[int] = 42,
    max_retransmissions: int = DEFAULT_MAX_RETRANSMISSIONS,
) -> Dict[str, List[SchemeResult]]:
    """Run every scheme across every p. Returns ``{scheme: [SchemeResult, ...]}``."""
    out: Dict[str, List[SchemeResult]] = {}
    for scheme in schemes:
        rows: List[SchemeResult] = []
        for i, p in enumerate(p_values):
            # Vary the seed per point so the points are independent but the
            # whole sweep stays reproducible.
            s = None if seed is None else seed + i * 1000
            rows.append(run_scheme(message, scheme, p, trials, s, max_retransmissions))
        out[scheme] = rows
    return out


def sweep_to_rows(results: Dict[str, List[SchemeResult]]) -> List[Dict[str, float]]:
    """Flatten a sweep into plain dicts -- convenient for DataFrames and CSV."""
    rows: List[Dict[str, float]] = []
    for scheme, series in results.items():
        for r in series:
            rows.append({
                "scheme": scheme,
                "label": SCHEME_LABELS[scheme],
                "p": r.p,
                "success_rate": r.success_rate,
                "avg_bits": r.avg_bits,
                "avg_retransmissions": r.avg_retransmissions,
                "undetected_error_rate": r.undetected_error_rate,
                "give_up_rate": r.give_up_rate,
            })
    return rows
