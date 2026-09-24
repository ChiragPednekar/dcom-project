"""
make_plots.py -- matplotlib comparison plots for IoTGuard.

These are the *export* figures: static, high-resolution, print-ready, and used
for the PDF/PNG report bundle. The on-screen interactive charts in the GUI are
built with Plotly instead -- this module is what you hand to a printer.
"""

from __future__ import annotations

import io
import zipfile
from typing import Dict, List, Optional, Sequence

import matplotlib
matplotlib.use("Agg")  # headless: no display needed
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

from pipeline import SCHEME_LABELS, SchemeResult

# One consistent colour per scheme across every figure.
SCHEME_COLORS = {
    "RAW": "#e5484d",
    "CRC_ARQ": "#f5a623",
    "HAMMING": "#30a46c",
}
SCHEME_MARKERS = {"RAW": "o", "CRC_ARQ": "s", "HAMMING": "^"}

Sweep = Dict[str, List[SchemeResult]]


def _style(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, fontsize=13, fontweight="bold", pad=12)
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.grid(True, alpha=0.25, linestyle="--", linewidth=0.7)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.legend(frameon=False, fontsize=9)


def _line_figure(results: Sweep, attr: str, title: str, ylabel: str,
                 percent: bool = False):
    fig, ax = plt.subplots(figsize=(7.5, 4.5), dpi=150)
    for scheme, series in results.items():
        xs = [r.p for r in series]
        ys = [getattr(r, attr) * (100 if percent else 1) for r in series]
        ax.plot(xs, ys,
                marker=SCHEME_MARKERS.get(scheme, "o"), markersize=5,
                linewidth=2, color=SCHEME_COLORS.get(scheme, "#888"),
                label=SCHEME_LABELS.get(scheme, scheme))
    if percent:
        ax.set_ylim(-3, 103)
    _style(ax, title, "Channel bit-error probability  p", ylabel)
    fig.tight_layout()
    return fig


def success_rate_figure(results: Sweep):
    """The headline chart: how often the message arrives intact."""
    return _line_figure(
        results, "success_rate",
        "Message Success Rate vs Channel Noise",
        "Successful deliveries (%)", percent=True)


def overhead_figure(results: Sweep):
    """Energy proxy: bits actually pushed over the air, retransmissions included."""
    return _line_figure(
        results, "avg_bits",
        "Transmitted Bits vs Channel Noise  (battery cost)",
        "Average bits transmitted per message")


def retransmission_figure(results: Sweep):
    """Only ARQ retransmits; the flat lines make that the point."""
    return _line_figure(
        results, "avg_retransmissions",
        "Retransmissions vs Channel Noise  (latency cost)",
        "Average retransmissions per message")


def all_figures(results: Sweep) -> Dict[str, "plt.Figure"]:
    return {
        "success_rate": success_rate_figure(results),
        "overhead_bits": overhead_figure(results),
        "retransmissions": retransmission_figure(results),
    }


def _summary_figure(message: str, stats, results: Sweep, trials: int):
    """A text cover page so the exported PDF stands alone in the report."""
    fig = plt.figure(figsize=(7.5, 9.5), dpi=150)
    fig.text(0.07, 0.94, "IoTGuard", fontsize=26, fontweight="bold")
    fig.text(0.07, 0.905,
             "Error-Resilient Communication for Low-Power IoT Sensor Networks",
             fontsize=11, color="#555")
    fig.text(0.07, 0.878, "_" * 74, fontsize=10, color="#bbb")

    y = 0.83
    fig.text(0.07, y, "Source message", fontsize=12, fontweight="bold")
    y -= 0.028
    shown = message if len(message) <= 62 else message[:59] + "..."
    fig.text(0.07, y, f'"{shown}"', fontsize=10, family="monospace", color="#333")

    y -= 0.05
    fig.text(0.07, y, "Source coding (Huffman)", fontsize=12, fontweight="bold")
    y -= 0.03
    for label, value in [
        ("Entropy of source", f"{stats.entropy:.4f} bits/symbol"),
        ("Average code length", f"{stats.avg_code_length:.4f} bits/symbol"),
        ("Coding efficiency", f"{stats.efficiency * 100:.2f} %"),
        ("Uncompressed size", f"{stats.original_bits} bits (8 bits/char)"),
        ("Compressed size", f"{stats.compressed_bits} bits"),
        ("Compression ratio", f"{stats.compression_ratio:.3f} : 1"),
        ("Bandwidth saved", f"{stats.savings_percent:.1f} %"),
    ]:
        fig.text(0.09, y, label, fontsize=9.5, color="#555")
        fig.text(0.52, y, value, fontsize=9.5, family="monospace")
        y -= 0.024

    y -= 0.028
    fig.text(0.07, y, f"Channel results  ({trials} trials per point)",
             fontsize=12, fontweight="bold")
    y -= 0.032
    for col, head in zip((0.09, 0.30, 0.46, 0.64, 0.82),
                         ("Scheme", "p", "Success", "Avg bits", "Avg retx")):
        fig.text(col, y, head, fontsize=9, fontweight="bold", color="#333")
    y -= 0.02

    for scheme, series in results.items():
        for r in series:
            if y < 0.06:
                break
            for col, val in zip(
                (0.09, 0.30, 0.46, 0.64, 0.82),
                (SCHEME_LABELS.get(scheme, scheme), f"{r.p:.3f}",
                 f"{r.success_rate * 100:.1f}%", f"{r.avg_bits:.0f}",
                 f"{r.avg_retransmissions:.2f}"),
            ):
                fig.text(col, y, val, fontsize=8.5,
                         family="monospace" if col > 0.2 else "sans-serif",
                         color="#333")
            y -= 0.019
    return fig


def export_pdf(message: str, stats, results: Sweep, trials: int) -> bytes:
    """Full report: cover page with the numbers, then all three charts."""
    figs = [_summary_figure(message, stats, results, trials)]
    figs.extend(all_figures(results).values())
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for fig in figs:
            pdf.savefig(fig)
    for fig in figs:
        plt.close(fig)
    return buf.getvalue()


def export_png_bundle(message: str, stats, results: Sweep, trials: int,
                      csv_text: Optional[str] = None) -> bytes:
    """ZIP of high-resolution PNGs plus the raw results as CSV."""
    figs = all_figures(results)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, fig in figs.items():
            img = io.BytesIO()
            fig.savefig(img, format="png", dpi=200, bbox_inches="tight")
            z.writestr(f"iotguard_{name}.png", img.getvalue())
            plt.close(fig)

        summary = _summary_figure(message, stats, results, trials)
        img = io.BytesIO()
        summary.savefig(img, format="png", dpi=200, bbox_inches="tight")
        z.writestr("iotguard_summary.png", img.getvalue())
        plt.close(summary)

        if csv_text:
            z.writestr("iotguard_results.csv", csv_text)
    return buf.getvalue()
