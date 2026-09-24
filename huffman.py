"""
huffman.py -- Source coding for IoTGuard.

Huffman compression reduces the number of bits an IoT sensor has to transmit,
which directly saves radio-on time and therefore battery. This module builds a
Huffman codebook from the message itself, encodes/decodes, and reports the
information-theoretic figures of merit (entropy, average code length,
compression ratio).

Bitstreams are represented as ``List[int]`` containing only 0 and 1.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

Bits = List[int]


# --------------------------------------------------------------------------- #
# Bit helpers (shared by the rest of the pipeline)
# --------------------------------------------------------------------------- #

def bits_to_string(bits: Bits) -> str:
    """[1,0,1] -> '101'."""
    return "".join(str(b) for b in bits)


def string_to_bits(s: str) -> Bits:
    """'101' -> [1,0,1]."""
    return [1 if c == "1" else 0 for c in s]


def text_to_bits(text: str) -> Bits:
    """Plain 8-bit-per-character encoding. This is the *uncompressed* baseline
    that Huffman is compared against."""
    out: Bits = []
    for byte in text.encode("utf-8"):
        out.extend((byte >> i) & 1 for i in range(7, -1, -1))
    return out


def bits_to_text(bits: Bits) -> str:
    """Inverse of :func:`text_to_bits`. Returns '' if the stream is unusable."""
    if len(bits) % 8 != 0:
        bits = bits[: len(bits) - (len(bits) % 8)]
    try:
        data = bytes(
            int(bits_to_string(bits[i : i + 8]), 2) for i in range(0, len(bits), 8)
        )
        return data.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


# --------------------------------------------------------------------------- #
# Huffman tree
# --------------------------------------------------------------------------- #

@dataclass
class Node:
    freq: int
    symbol: Optional[str] = None
    left: Optional["Node"] = None
    right: Optional["Node"] = None

    @property
    def is_leaf(self) -> bool:
        return self.left is None and self.right is None


def build_frequency(message: str) -> Dict[str, int]:
    freq: Dict[str, int] = {}
    for ch in message:
        freq[ch] = freq.get(ch, 0) + 1
    return freq


def build_tree(freq: Dict[str, int]) -> Optional[Node]:
    """Standard Huffman construction.

    Ties are broken by a monotonically increasing counter and by sorting the
    symbols first, so the same message always yields the same codebook. That
    determinism matters for a live demo -- the professor should see the same
    codes every run.
    """
    if not freq:
        return None

    counter = 0
    heap: List[Tuple[int, int, Node]] = []
    for symbol in sorted(freq):
        heapq.heappush(heap, (freq[symbol], counter, Node(freq[symbol], symbol)))
        counter += 1

    # Single distinct symbol: wrap it so it still gets a 1-bit code.
    if len(heap) == 1:
        _, _, only = heapq.heappop(heap)
        return Node(only.freq, None, only, None)

    while len(heap) > 1:
        f1, _, n1 = heapq.heappop(heap)
        f2, _, n2 = heapq.heappop(heap)
        heapq.heappush(heap, (f1 + f2, counter, Node(f1 + f2, None, n1, n2)))
        counter += 1

    return heap[0][2]


def build_codes(tree: Optional[Node]) -> Dict[str, str]:
    """Walk the tree, assigning '0' for left and '1' for right."""
    codes: Dict[str, str] = {}
    if tree is None:
        return codes

    def walk(node: Node, prefix: str) -> None:
        if node.is_leaf and node.symbol is not None:
            # A lone symbol would otherwise get the empty code.
            codes[node.symbol] = prefix or "0"
            return
        if node.left is not None:
            walk(node.left, prefix + "0")
        if node.right is not None:
            walk(node.right, prefix + "1")

    walk(tree, "")
    return codes


# --------------------------------------------------------------------------- #
# Encode / decode
# --------------------------------------------------------------------------- #

def encode(message: str) -> Tuple[Bits, Dict[str, str]]:
    """Compress ``message``. Returns the bitstream and the codebook used.

    The codebook is assumed to be shared out-of-band (both sensor and gateway
    know it), which is the usual simplifying assumption for this kind of study.
    """
    freq = build_frequency(message)
    codes = build_codes(build_tree(freq))
    bits: Bits = []
    for ch in message:
        bits.extend(string_to_bits(codes[ch]))
    return bits, codes


def decode(bits: Bits, codes: Dict[str, str]) -> Optional[str]:
    """Decompress. Returns ``None`` if the bitstream is not a valid encoding --
    which is exactly what happens when the channel corrupts an unprotected
    stream, so callers must handle it."""
    if not codes:
        return "" if not bits else None

    lookup = {code: sym for sym, code in codes.items()}
    out: List[str] = []
    buf = ""
    max_len = max(len(c) for c in lookup)

    for b in bits:
        buf += str(b)
        if buf in lookup:
            out.append(lookup[buf])
            buf = ""
        elif len(buf) > max_len:
            return None  # no code can ever match -- stream is garbage

    if buf:
        return None  # trailing bits that decode to nothing
    return "".join(out)


# --------------------------------------------------------------------------- #
# Information-theoretic metrics
# --------------------------------------------------------------------------- #

def entropy(message: str) -> float:
    """Shannon entropy in bits/symbol -- the theoretical floor for any
    lossless code on this source."""
    n = len(message)
    if n == 0:
        return 0.0
    freq = build_frequency(message)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def average_code_length(message: str, codes: Dict[str, str]) -> float:
    """Actual bits/symbol achieved by the Huffman code."""
    n = len(message)
    if n == 0 or not codes:
        return 0.0
    freq = build_frequency(message)
    return sum(freq[s] * len(codes[s]) for s in freq) / n


def compression_ratio(message: str, compressed_bits: int) -> float:
    """original_bits / compressed_bits. >1 means we saved bandwidth."""
    original = len(text_to_bits(message))
    if compressed_bits == 0:
        return 0.0
    return original / compressed_bits


@dataclass
class HuffmanStats:
    message: str
    codes: Dict[str, str] = field(default_factory=dict)
    bits: Bits = field(default_factory=list)
    original_bits: int = 0
    compressed_bits: int = 0
    entropy: float = 0.0
    avg_code_length: float = 0.0
    compression_ratio: float = 0.0
    savings_percent: float = 0.0
    efficiency: float = 0.0  # entropy / avg_code_length


def analyze(message: str) -> HuffmanStats:
    """One call that produces everything the GUI's stats panel needs."""
    bits, codes = encode(message)
    original = len(text_to_bits(message))
    compressed = len(bits)
    h = entropy(message)
    lbar = average_code_length(message, codes)
    return HuffmanStats(
        message=message,
        codes=codes,
        bits=bits,
        original_bits=original,
        compressed_bits=compressed,
        entropy=h,
        avg_code_length=lbar,
        compression_ratio=compression_ratio(message, compressed),
        savings_percent=(100.0 * (original - compressed) / original) if original else 0.0,
        efficiency=(h / lbar) if lbar > 0 else 0.0,
    )
