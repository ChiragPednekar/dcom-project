"""
test_iotguard.py -- correctness checks for the IoTGuard simulation core.

Run with:  python test_iotguard.py

These are the properties the demo's conclusions rest on. If any of them fail,
the charts are lying.
"""

from __future__ import annotations

import itertools
import random

import channel
import error_control as ec
import huffman
import pipeline as pl

PASS, FAIL = 0, 0


def check(label: str, condition: bool) -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok    {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label}")


MESSAGES = [
    "temperature: 24.5C humidity: 60%",
    "AAAA BBBB AAAA BBBB",
    "a",
    "ab",
    "node:A7 batt:3.71V rssi:-82dBm",
    "x" * 200,
]


print("\n[1] Huffman source coding")
for m in MESSAGES:
    bits, codes = huffman.encode(m)
    check(f"lossless round-trip: {m[:24]!r}", huffman.decode(bits, codes) == m)
for m in MESSAGES:
    s = huffman.analyze(m)
    # Shannon's source coding theorem, non-strict form: H <= L <= H + 1.
    # The usual strict statement (L < H + 1) assumes a non-degenerate source.
    # A message with a single distinct symbol has H = 0, yet any real code must
    # still emit at least one bit per symbol, giving L = 1 exactly at the bound.
    check(f"entropy bound H <= L <= H+1: {m[:20]!r}",
          s.entropy <= s.avg_code_length + 1e-9 <= s.entropy + 1.0 + 1e-9)

# Pin down that degenerate case explicitly rather than letting it hide.
for degenerate in ("a", "x" * 50):
    s = huffman.analyze(degenerate)
    check(f"single-symbol source: H=0 and L=1 exactly ({degenerate[:6]!r})",
          abs(s.entropy) < 1e-9 and abs(s.avg_code_length - 1.0) < 1e-9)
check("prefix-free codes (no code is a prefix of another)", all(
    not (a != b and a.startswith(b))
    for m in MESSAGES
    for a, b in itertools.permutations(huffman.encode(m)[1].values(), 2)
))
check("empty message handled", huffman.analyze("").compressed_bits == 0)


print("\n[2] CRC-8 error detection")
rng = random.Random(1)
frames = [[rng.randint(0, 1) for _ in range(n)] for n in (8, 32, 137)]
check("clean frames verify", all(ec.crc8_check(ec.crc8_append(f))[0] for f in frames))
check("payload recovered intact", all(
    ec.crc8_check(ec.crc8_append(f))[1] == f for f in frames))
single_ok = True
for f in frames:
    fr = ec.crc8_append(f)
    for i in range(len(fr)):
        bad = fr[:i] + [fr[i] ^ 1] + fr[i + 1:]
        if ec.crc8_check(bad)[0]:
            single_ok = False
check("every single-bit error detected", single_ok)
check("CRC is exactly 8 bits", all(len(ec.crc8(f)) == 8 for f in frames))


print("\n[3] Hamming(7,4) forward error correction")
clean = corrected = syndrome_ok = True
for nib in itertools.product([0, 1], repeat=4):
    n = list(nib)
    cw = ec.hamming74_encode_block(n)
    if ec.hamming74_decode_block(cw) != (n, 0):
        clean = False
    for i in range(7):
        c = cw[:i] + [cw[i] ^ 1] + cw[i + 1:]
        dec, syn = ec.hamming74_decode_block(c)
        if dec != n:
            corrected = False
        if syn != i + 1:
            syndrome_ok = False
check("all 16 codewords decode cleanly", clean)
check("all 16x7 single-bit errors corrected", corrected)
check("syndrome points at the flipped position", syndrome_ok)
check("overhead is exactly 7/4", ec.hamming_overhead_ratio() == 1.75)
stream_ok = True
for L in (1, 3, 4, 5, 7, 8, 137, 200):
    b = [rng.randint(0, 1) for _ in range(L)]
    enc, pad = ec.hamming74_encode(b)
    if ec.hamming74_decode(enc, pad)[0] != b:
        stream_ok = False
check("stream encode/decode with padding", stream_ok)


print("\n[4] Binary symmetric channel")
bits = [0] * 20000
_, flipped = channel.bsc(bits, 0.1, random.Random(7))
rate = len(flipped) / len(bits)
check(f"empirical flip rate {rate:.4f} ~ p=0.1", abs(rate - 0.1) < 0.01)
check("p=0 never flips", channel.bsc([1] * 500, 0.0, random.Random(1))[1] == [])
check("p=1 always flips", len(channel.bsc([1] * 500, 1.0, random.Random(1))[1]) == 500)
check("capacity C(0)=1", abs(channel.channel_capacity(0.0) - 1.0) < 1e-9)
check("capacity C(0.5)=0", abs(channel.channel_capacity(0.5)) < 1e-9)
try:
    channel.bsc([1], 1.5)
    check("rejects p outside [0,1]", False)
except ValueError:
    check("rejects p outside [0,1]", True)


print("\n[5] End-to-end pipeline")
msg = "temperature: 24.5C humidity: 60%"
for s in pl.SCHEMES:
    r = pl.run_scheme(msg, s, 0.0, trials=50, seed=5)
    check(f"{s}: 100% success on a clean channel", r.success_rate == 1.0)
    check(f"{s}: no retransmissions at p=0", r.avg_retransmissions == 0.0)

LIM = 5
rng = random.Random(11)
bounded = bits_ok = giveup_ok = True
for p in (0.0, 0.01, 0.05, 0.2):
    for _ in range(200):
        t = pl.run_trial(msg, "CRC_ARQ", p, rng, max_retransmissions=LIM)
        if not 0 <= t.retransmissions <= LIM or t.retransmissions != len(t.attempts) - 1:
            bounded = False
        if t.bits_transmitted != len(t.encoded_bits) * len(t.attempts):
            bits_ok = False
        if t.gave_up and t.retransmissions != LIM:
            giveup_ok = False
check("ARQ retransmissions bounded by the limit", bounded)
check("bits transmitted == frame size x attempts", bits_ok)
check("give-up only when the budget is exhausted", giveup_ok)

check("RAW never retransmits", all(
    pl.run_trial(msg, "RAW", 0.05, rng).retransmissions == 0 for _ in range(50)))
check("HAMMING never retransmits", all(
    pl.run_trial(msg, "HAMMING", 0.05, rng).retransmissions == 0 for _ in range(50)))
check("HAMMING sends a constant number of bits", len({
    pl.run_trial(msg, "HAMMING", 0.05, rng).bits_transmitted for _ in range(50)}) == 1)

# RAW should track the analytical (1-p)^n curve
stats = huffman.analyze(msg)
for p in (0.002, 0.005):
    emp = pl.run_scheme(msg, "RAW", p, trials=3000, seed=21).success_rate
    theo = channel.expected_block_success(stats.compressed_bits, p)
    # RAW can still "succeed" if corrupted bits happen to decode back to the
    # same text, so empirical sits at or slightly above theory.
    check(f"RAW at p={p} tracks (1-p)^n  (emp {emp:.3f} vs theory {theo:.3f})",
          emp >= theo - 0.05)

# The headline claim of the whole project.
p_mid = 0.02
res = {s: pl.run_scheme(msg, s, p_mid, trials=800, seed=31) for s in pl.SCHEMES}
check("Hamming beats CRC+ARQ on success rate at p=0.02",
      res["HAMMING"].success_rate > res["CRC_ARQ"].success_rate)
check("Hamming beats RAW on success rate at p=0.02",
      res["HAMMING"].success_rate > res["RAW"].success_rate)
check("Hamming sends far fewer bits than CRC+ARQ at p=0.02",
      res["HAMMING"].avg_bits < res["CRC_ARQ"].avg_bits)

print(f"\n{'=' * 52}")
print(f"  {PASS} passed, {FAIL} failed")
print(f"{'=' * 52}\n")
raise SystemExit(1 if FAIL else 0)
