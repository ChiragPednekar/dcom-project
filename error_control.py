"""
error_control.py -- Channel coding for IoTGuard.

Two strategies, representing the two classical answers to "the channel is
noisy, now what?":

* **CRC-8 + ARQ** (detection + retransmission). Cheap to add, but every
  detected error costs a full retransmission -- bandwidth and battery.
* **Hamming(7,4)** (forward error correction). Pays a fixed 75% overhead up
  front, but repairs any single-bit error per block with no round trip.
"""

from __future__ import annotations

from typing import List, Tuple

Bits = List[int]

# CRC-8-ATM / ITU-T I.432.1: x^8 + x^2 + x + 1
CRC8_POLY = 0x07
CRC8_WIDTH = 8

# Hamming(7,4) constants
HAMMING_DATA_BITS = 4
HAMMING_BLOCK_BITS = 7


# --------------------------------------------------------------------------- #
# CRC-8 -- error DETECTION
# --------------------------------------------------------------------------- #

def crc8(bits: Bits) -> Bits:
    """Compute the 8-bit CRC remainder of ``bits`` (MSB-first, init 0x00)."""
    reg = 0
    for bit in bits:
        msb = (reg >> (CRC8_WIDTH - 1)) & 1
        reg = ((reg << 1) & 0xFF)
        if msb ^ (bit & 1):
            reg ^= CRC8_POLY
    return [(reg >> i) & 1 for i in range(CRC8_WIDTH - 1, -1, -1)]


def crc8_append(bits: Bits) -> Bits:
    """Frame = payload followed by its 8 CRC bits."""
    return list(bits) + crc8(bits)


def crc8_check(frame: Bits) -> Tuple[bool, Bits]:
    """Split a received frame and verify it.

    Returns ``(is_valid, payload)``. Note that CRC-8 is not perfect: with
    enough bit flips a corrupted frame can still satisfy the check. Those
    *undetected* errors are the interesting failure mode of ARQ and the
    pipeline counts them separately.
    """
    if len(frame) < CRC8_WIDTH:
        return False, []
    payload, received = frame[:-CRC8_WIDTH], frame[-CRC8_WIDTH:]
    return crc8(payload) == received, payload


# --------------------------------------------------------------------------- #
# Hamming(7,4) -- forward error CORRECTION
# --------------------------------------------------------------------------- #
# Block layout (1-indexed positions): p1 p2 d1 p3 d2 d3 d4
#   p1 covers positions 1,3,5,7
#   p2 covers positions 2,3,6,7
#   p3 covers positions 4,5,6,7

def hamming74_encode_block(nibble: Bits) -> Bits:
    """4 data bits -> 7-bit codeword."""
    d1, d2, d3, d4 = nibble
    p1 = d1 ^ d2 ^ d4
    p2 = d1 ^ d3 ^ d4
    p3 = d2 ^ d3 ^ d4
    return [p1, p2, d1, p3, d2, d3, d4]


def hamming74_decode_block(block: Bits) -> Tuple[Bits, int]:
    """7-bit codeword -> ``(4 data bits, error_position)``.

    ``error_position`` is the 1-indexed bit the syndrome points at, or 0 if the
    block arrived clean. A single flipped bit is corrected here. Two flipped
    bits produce a non-zero syndrome pointing at the *wrong* bit, so the
    "correction" makes it worse -- that is the documented limit of a distance-3
    code and it is why the success curve still bends down at high noise.
    """
    b = list(block)
    s1 = b[0] ^ b[2] ^ b[4] ^ b[6]  # positions 1,3,5,7
    s2 = b[1] ^ b[2] ^ b[5] ^ b[6]  # positions 2,3,6,7
    s3 = b[3] ^ b[4] ^ b[5] ^ b[6]  # positions 4,5,6,7
    syndrome = s1 + (s2 << 1) + (s3 << 2)

    if syndrome:
        idx = syndrome - 1
        if 0 <= idx < HAMMING_BLOCK_BITS:
            b[idx] ^= 1
    return [b[2], b[4], b[5], b[6]], syndrome


def hamming74_encode(bits: Bits) -> Tuple[Bits, int]:
    """Encode a whole stream. Zero-pads up to a multiple of 4.

    Returns ``(encoded_bits, pad_length)``; keep ``pad_length`` so the decoder
    can drop the padding again.
    """
    data = list(bits)
    pad = (-len(data)) % HAMMING_DATA_BITS
    data.extend([0] * pad)

    out: Bits = []
    for i in range(0, len(data), HAMMING_DATA_BITS):
        out.extend(hamming74_encode_block(data[i : i + HAMMING_DATA_BITS]))
    return out, pad


def hamming74_decode(bits: Bits, pad: int = 0) -> Tuple[Bits, int]:
    """Decode a whole stream, correcting one bit per 7-bit block.

    Returns ``(data_bits, blocks_corrected)``.
    """
    out: Bits = []
    corrected = 0
    for i in range(0, len(bits) - (len(bits) % HAMMING_BLOCK_BITS), HAMMING_BLOCK_BITS):
        nibble, syndrome = hamming74_decode_block(bits[i : i + HAMMING_BLOCK_BITS])
        out.extend(nibble)
        if syndrome:
            corrected += 1
    if pad:
        out = out[: len(out) - pad]
    return out, corrected


def hamming_overhead_ratio() -> float:
    """7/4 = 1.75 -- every 4 payload bits cost 7 on the air."""
    return HAMMING_BLOCK_BITS / HAMMING_DATA_BITS
