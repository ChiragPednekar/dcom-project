"""
ui_helpers.py -- presentation-only helpers for the IoTGuard GUI.

Kept apart from the simulation modules so the physics stays free of any
Streamlit or HTML concerns.
"""

from __future__ import annotations

import html
from typing import Dict, Iterable, List, Optional, Sequence

# How many bits to draw before we truncate. Beyond a few hundred the display
# stops being readable anyway and the browser starts to struggle.
MAX_BITS_SHOWN = 512


def render_bits(
    bits: Sequence[int],
    highlight: Optional[Iterable[int]] = None,
    group: int = 8,
    max_shown: int = MAX_BITS_SHOWN,
) -> str:
    """Render a bitstream as HTML, painting ``highlight`` indices red.

    ``group`` inserts a thin gap every N bits so long streams stay countable.
    """
    marked = set(highlight or ())
    shown = list(bits[:max_shown])
    truncated = len(bits) - len(shown)

    parts: List[str] = []
    for i, bit in enumerate(shown):
        cls = "bit flip" if i in marked else "bit"
        sep = " spaced" if group and i and i % group == 0 else ""
        parts.append(f'<span class="{cls}{sep}">{bit}</span>')

    body = "".join(parts)
    if truncated > 0:
        hidden_flips = sum(1 for i in marked if i >= max_shown)
        note = f"+{truncated} more bits"
        if hidden_flips:
            note += f" ({hidden_flips} flipped)"
        body += f'<span class="bit-more">… {note}</span>'
    return f'<div class="bitstream">{body}</div>'


def render_text_bits(text: str) -> str:
    """Show a string as characters sitting above their 8-bit ASCII codes."""
    cells: List[str] = []
    for ch in text[:48]:
        code = format(ord(ch), "08b") if ord(ch) < 256 else "--------"
        label = "␣" if ch == " " else html.escape(ch)
        cells.append(
            f'<div class="charcell"><div class="charglyph">{label}</div>'
            f'<div class="charbits">{code}</div></div>'
        )
    more = ""
    if len(text) > 48:
        more = f'<div class="charcell"><div class="charglyph">…</div>' \
               f'<div class="charbits">+{len(text) - 48}</div></div>'
    return f'<div class="charrow">{"".join(cells)}{more}</div>'


def render_codebook(codes: Dict[str, str], freq: Dict[str, int]) -> str:
    """Huffman codebook as a compact chip grid, most frequent symbol first."""
    order = sorted(codes, key=lambda s: (-freq.get(s, 0), len(codes[s]), s))
    chips = []
    for sym in order:
        label = "␣" if sym == " " else html.escape(sym)
        chips.append(
            f'<span class="codechip"><b>{label}</b>'
            f'<span class="codebits">{codes[sym]}</span>'
            f'<span class="codefreq">×{freq.get(sym, 0)}</span></span>'
        )
    return f'<div class="codegrid">{"".join(chips)}</div>'


def stage_header(number: int, title: str, subtitle: str = "") -> str:
    sub = f'<span class="stage-sub">{html.escape(subtitle)}</span>' if subtitle else ""
    return (
        f'<div class="stage-head"><span class="stage-num">{number}</span>'
        f'<span class="stage-title">{html.escape(title)}</span>{sub}</div>'
    )


def verdict_banner(success: bool, decoded: Optional[str], original: str,
                   detail: str = "") -> str:
    """The green-check / red-cross payoff at the end of the demo."""
    if success:
        icon, cls, headline = "✓", "verdict ok", "MESSAGE RECEIVED INTACT"
        body = f'Decoded output matches the original exactly.'
    else:
        icon, cls, headline = "✕", "verdict bad", "MESSAGE CORRUPTED"
        if decoded is None:
            body = "The bitstream could not be decoded at all — Huffman hit an invalid code."
        else:
            body = "The decoder produced output, but it differs from what was sent."
    extra = f'<div class="verdict-detail">{html.escape(detail)}</div>' if detail else ""
    return (
        f'<div class="{cls}"><div class="verdict-icon">{icon}</div>'
        f'<div class="verdict-text"><div class="verdict-head">{headline}</div>'
        f'<div class="verdict-body">{body}</div>{extra}</div></div>'
    )


def diff_text(original: str, decoded: Optional[str]) -> str:
    """Show the decoded string with differing characters marked."""
    if decoded is None:
        return '<div class="decoded-out none">— nothing decodable —</div>'
    if not decoded:
        return '<div class="decoded-out none">— empty output —</div>'

    out: List[str] = []
    for i, ch in enumerate(decoded[:120]):
        same = i < len(original) and original[i] == ch
        label = "␣" if ch == " " else html.escape(ch)
        out.append(f'<span class="{"dc" if same else "dc bad"}">{label}</span>')
    tail = "…" if len(decoded) > 120 else ""
    return f'<div class="decoded-out">{"".join(out)}{tail}</div>'


CSS = """
<style>
.bitstream {
  font-family: "SF Mono", "Menlo", "Consolas", monospace;
  font-size: 12.5px; line-height: 1.9; letter-spacing: .5px;
  word-break: break-all; padding: 10px 12px;
  background: #12151b; border: 1px solid #232833; border-radius: 8px;
}
.bit { color: #7d8590; }
.bit.spaced { margin-left: 6px; }
.bit.flip {
  color: #fff; background: #e5484d; font-weight: 700;
  border-radius: 3px; padding: 1px 2px; margin: 0 1px;
  box-shadow: 0 0 0 1px #e5484d, 0 0 10px rgba(229,72,77,.55);
}
.bit-more { color: #565d68; font-style: italic; margin-left: 8px; }

.charrow { display: flex; flex-wrap: wrap; gap: 4px; }
.charcell {
  background: #12151b; border: 1px solid #232833; border-radius: 6px;
  padding: 5px 6px; text-align: center; min-width: 34px;
}
.charglyph { font-size: 14px; font-weight: 700; color: #e6e8eb; }
.charbits {
  font-family: "SF Mono", Menlo, monospace; font-size: 8.5px;
  color: #6e7681; letter-spacing: .3px; margin-top: 2px;
}

.codegrid { display: flex; flex-wrap: wrap; gap: 6px; }
.codechip {
  display: inline-flex; align-items: center; gap: 6px;
  background: #12151b; border: 1px solid #232833; border-radius: 999px;
  padding: 3px 10px; font-size: 12px;
}
.codechip b { color: #e6e8eb; }
.codebits { font-family: "SF Mono", Menlo, monospace; color: #30a46c; font-size: 11.5px; }
.codefreq { color: #565d68; font-size: 10.5px; }

.stage-head { display: flex; align-items: center; gap: 10px; margin: 4px 0 8px; }
.stage-num {
  display: inline-flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; border-radius: 50%;
  background: #30a46c; color: #04150c; font-weight: 800; font-size: 13px;
}
.stage-title { font-size: 15px; font-weight: 700; color: #e6e8eb; }
.stage-sub { font-size: 12px; color: #7d8590; }

.verdict {
  display: flex; align-items: center; gap: 16px;
  border-radius: 12px; padding: 18px 20px; margin: 6px 0;
}
.verdict.ok  { background: rgba(48,163,108,.12); border: 1px solid rgba(48,163,108,.45); }
.verdict.bad { background: rgba(229,72,77,.12);  border: 1px solid rgba(229,72,77,.45); }
.verdict-icon { font-size: 34px; line-height: 1; }
.verdict.ok  .verdict-icon { color: #30a46c; }
.verdict.bad .verdict-icon { color: #e5484d; }
.verdict-head { font-size: 15px; font-weight: 800; letter-spacing: .5px; }
.verdict.ok  .verdict-head { color: #30a46c; }
.verdict.bad .verdict-head { color: #e5484d; }
.verdict-body { font-size: 13px; color: #b6bcc4; margin-top: 2px; }
.verdict-detail { font-size: 12px; color: #7d8590; margin-top: 4px; }

.decoded-out {
  font-family: "SF Mono", Menlo, monospace; font-size: 14px;
  background: #12151b; border: 1px solid #232833; border-radius: 8px;
  padding: 12px 14px; word-break: break-all; line-height: 1.8;
}
.decoded-out.none { color: #e5484d; font-style: italic; }
.dc { color: #30a46c; }
.dc.bad { color: #fff; background: #e5484d; border-radius: 3px; padding: 0 2px; }

.attempt-pill {
  display: inline-block; font-size: 11.5px; padding: 2px 9px;
  border-radius: 999px; margin-right: 6px; font-weight: 600;
}
.attempt-pill.ok  { background: rgba(48,163,108,.18); color: #30a46c; }
.attempt-pill.bad { background: rgba(229,72,77,.18);  color: #e5484d; }
</style>
"""
