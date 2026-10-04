"""
IoTGuard -- Error-Resilient Communication for Low-Power IoT Sensor Networks

Streamlit front end over the simulation modules. Run with:

    streamlit run app.py

The algorithms live in huffman.py / error_control.py / channel.py / pipeline.py;
nothing in this file reimplements them.
"""

from __future__ import annotations

import csv
import io
import random
import time

import plotly.graph_objects as go
import streamlit as st

import huffman
# matplotlib is only needed for the PDF/PNG export. In a WebAssembly build
# (stlite/Pyodide) it may be unavailable, so treat it as optional rather than
# letting an import failure take the whole app down.
try:
    import make_plots
    EXPORT_AVAILABLE = True
except Exception:  # pragma: no cover - environment dependent
    make_plots = None
    EXPORT_AVAILABLE = False
import ui_helpers as ui
from pipeline import (
    DEFAULT_MAX_RETRANSMISSIONS,
    SCHEME_LABELS,
    SCHEMES,
    run_scheme,
    run_trial,
    sweep,
    sweep_to_rows,
)

SCHEME_COLORS = {"RAW": "#e5484d", "CRC_ARQ": "#f5a623", "HAMMING": "#30a46c"}
SCHEME_CHOICES = {
    "RAW": "No protection",
    "CRC_ARQ": "CRC-8 + ARQ (detect & resend)",
    "HAMMING": "Hamming(7,4) (detect & fix)",
}
DEFAULT_MESSAGE = "temperature: 24.5C humidity: 60%"

st.set_page_config(
    page_title="IoTGuard — Error-Resilient IoT Communication",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(ui.CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Sidebar: just the two inputs that matter, everything else tucked away
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.markdown("### 📡 IoTGuard")
    st.caption("Sending sensor data over a noisy radio link")

    message = st.text_area("Sensor message", value=DEFAULT_MESSAGE, height=80)
    p = st.slider(
        "Channel noise  p", 0.0, 0.15, 0.02, 0.001, format="%.3f",
        help="Chance that each bit gets flipped on the way. "
             "0 = perfect link, 0.15 = very noisy link.",
    )

    with st.expander("Advanced settings"):
        trials = st.number_input(
            "Runs per method (for averages)", 20, 2000, 200, 20,
            help="More runs give smoother charts but take longer.")
        max_retx = st.number_input(
            "Max resends for CRC + ARQ", 1, 20, DEFAULT_MAX_RETRANSMISSIONS, 1,
            help="How many times the sensor retries before giving up.")
        p_max = st.slider("Highest noise on charts", 0.02, 0.15, 0.10, 0.01)
        p_points = st.slider("Points on charts", 5, 31, 16, 1)

message = message.strip()


# --------------------------------------------------------------------------- #
# Header
# --------------------------------------------------------------------------- #

st.markdown("## Error-Resilient Communication for IoT Sensors")
st.caption("Compress → add protection → send through noise → decode → check")

if not message:
    st.warning("Type a sensor message in the sidebar to begin.")
    st.stop()

stats = huffman.analyze(message)

c1, c2, c3 = st.columns(3)
c1.metric("Original size", f"{stats.original_bits} bits")
c2.metric("After Huffman compression", f"{stats.compressed_bits} bits")
c3.metric("Bandwidth saved", f"{stats.savings_percent:.0f}%")

tab_demo, tab_compare = st.tabs(["🔬  Live Demo", "📊  Compare Methods"])


# --------------------------------------------------------------------------- #
# TAB 1 -- send the message once and watch each step
# --------------------------------------------------------------------------- #

with tab_demo:
    pick, go_col = st.columns([4, 1], vertical_alignment="bottom")
    with pick:
        scheme = st.radio(
            "Protection method", list(SCHEMES), index=2, horizontal=True,
            format_func=SCHEME_CHOICES.get,
        )
    with go_col:
        run_demo = st.button("▶  Send message", type="primary",
                             use_container_width=True)

    if run_demo:
        st.session_state.trial = run_trial(
            message, scheme, p,
            rng=random.Random(),
            max_retransmissions=int(max_retx),
        )

    trial = st.session_state.get("trial")
    if trial is None or (trial.scheme, trial.message, trial.p) != (scheme, message, p):
        st.info("Press **Send message** to send it once through the noisy "
                "channel and watch what happens at each step.")
    else:
        # Reveal the steps one by one only on the run that pressed the button,
        # not on every later rerun of the page.
        def pause() -> None:
            if run_demo:
                time.sleep(0.4)

        # -- Step 1: original ---------------------------------------------
        st.markdown(ui.stage_header(1, "Original message",
                                    f"{len(trial.message)} characters"),
                    unsafe_allow_html=True)
        st.code(trial.message, language=None)
        pause()

        # -- Step 2: Huffman ----------------------------------------------
        st.markdown(
            ui.stage_header(2, "Compressed with Huffman coding",
                            f"{stats.original_bits} → {stats.compressed_bits} bits"),
            unsafe_allow_html=True)
        st.markdown(ui.render_bits(trial.source_bits), unsafe_allow_html=True)
        with st.expander("Huffman details"):
            st.markdown(
                f"Entropy **{stats.entropy:.3f}** bits/symbol · "
                f"average code length **{stats.avg_code_length:.3f}** bits/symbol · "
                f"efficiency **{stats.efficiency * 100:.1f}%**")
            st.caption("Frequent characters get shorter codes:")
            st.markdown(ui.render_codebook(trial.codes,
                                           huffman.build_frequency(message)),
                        unsafe_allow_html=True)
        pause()

        # -- Step 3: protection -------------------------------------------
        added = len(trial.encoded_bits) - len(trial.source_bits)
        protection_note = {
            "RAW": "nothing added — sent as is",
            "CRC_ARQ": f"+{added} check bits added at the end",
            "HAMMING": f"+{added} repair bits (every 4 bits become 7)",
        }[trial.scheme]
        st.markdown(ui.stage_header(3, "Protection added", protection_note),
                    unsafe_allow_html=True)
        st.markdown(ui.render_bits(trial.encoded_bits), unsafe_allow_html=True)
        pause()

        # -- Step 4: noisy channel ----------------------------------------
        n_flips = len(trial.flipped_indices)
        st.markdown(
            ui.stage_header(4, "After the noisy channel",
                            f"{n_flips} bit{'s' if n_flips != 1 else ''} flipped "
                            f"(shown in red)"),
            unsafe_allow_html=True)
        if trial.scheme == "CRC_ARQ" and len(trial.attempts) > 1:
            pills = "".join(
                f'<span class="attempt-pill {"ok" if a.accepted else "bad"}">'
                f'Try {a.index + 1}: '
                f'{"✓ passed" if a.accepted else "✗ error found → resend"}</span>'
                for a in trial.attempts
            )
            st.markdown(f"<div>{pills}</div>", unsafe_allow_html=True)
        st.markdown(
            ui.render_bits(trial.received_bits, highlight=trial.flipped_indices),
            unsafe_allow_html=True)
        pause()

        # -- Step 5: result -----------------------------------------------
        st.markdown(ui.stage_header(5, "Decoded result"), unsafe_allow_html=True)
        if trial.gave_up:
            st.error(f"Still failing after {int(max_retx)} resends — "
                     f"the sensor gave up and the message was lost.")
        st.markdown(ui.diff_text(trial.message, trial.decoded),
                    unsafe_allow_html=True)

        detail = f"{trial.bits_transmitted} bits sent"
        if trial.scheme == "CRC_ARQ":
            detail += f" · {trial.retransmissions} resend(s)"
        if trial.scheme == "HAMMING":
            detail += f" · {trial.blocks_corrected} block(s) repaired automatically"
        st.markdown(
            ui.verdict_banner(trial.success, trial.decoded, trial.message, detail),
            unsafe_allow_html=True)
        if trial.undetected_error:
            st.warning("The CRC check passed but the data was still damaged — "
                       "an 8-bit checksum can occasionally miss errors.")


# --------------------------------------------------------------------------- #
# TAB 2 -- run all three methods many times and compare
# --------------------------------------------------------------------------- #

with tab_compare:
    st.markdown(f"#### All three methods at noise p = {p:.3f}")
    st.caption(f"Each method sends the message {int(trials)} times; "
               f"the table shows the averages.")

    point = {
        s: run_scheme(message, s, p, int(trials), seed=1234,
                      max_retransmissions=int(max_retx))
        for s in SCHEMES
    }
    st.dataframe(
        [
            {
                "Method": SCHEME_LABELS[s],
                "Delivered correctly": f"{point[s].success_rate * 100:.1f}%",
                "Bits sent": f"{point[s].avg_bits:.0f}",
                "Resends": f"{point[s].avg_retransmissions:.2f}",
            }
            for s in SCHEMES
        ],
        use_container_width=True, hide_index=True,
    )

    best = max(SCHEMES, key=lambda s: (point[s].success_rate, -point[s].avg_bits))
    if point[best].success_rate > 0:
        st.success(
            f"**{SCHEME_LABELS[best]}** delivered the most messages "
            f"({point[best].success_rate * 100:.0f}%) while sending "
            f"{point[best].avg_bits:.0f} bits on average.")

    p_values = [round(i * p_max / (p_points - 1), 5) for i in range(int(p_points))]
    cache_key = (message, tuple(p_values), int(trials), int(max_retx))
    if st.session_state.get("sweep_key") != cache_key:
        with st.spinner("Simulating across noise levels…"):
            st.session_state.sweep = sweep(
                message, p_values, SCHEMES, int(trials), seed=42,
                max_retransmissions=int(max_retx))
            st.session_state.sweep_key = cache_key
    results = st.session_state.sweep

    def line_chart(attr: str, title: str, ylabel: str,
                   percent: bool = False) -> go.Figure:
        fig = go.Figure()
        for s, series in results.items():
            fig.add_trace(go.Scatter(
                x=[r.p for r in series],
                y=[getattr(r, attr) * (100 if percent else 1) for r in series],
                name=SCHEME_LABELS[s],
                mode="lines+markers",
                line=dict(color=SCHEME_COLORS[s], width=3),
                marker=dict(size=6),
                hovertemplate=(f"<b>{SCHEME_LABELS[s]}</b><br>"
                               f"p = %{{x:.3f}}<br>{ylabel} = %{{y:.1f}}"
                               f"<extra></extra>"),
            ))
        fig.update_layout(
            title=dict(text=title, font=dict(size=15)),
            xaxis_title="Channel noise  p",
            yaxis_title=ylabel,
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=360,
            margin=dict(l=10, r=10, t=50, b=10),
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                        xanchor="left", x=0),
        )
        fig.update_xaxes(gridcolor="#232833", zeroline=False)
        fig.update_yaxes(gridcolor="#232833", zeroline=False)
        if percent:
            fig.update_yaxes(range=[-3, 103])
        return fig

    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            line_chart("success_rate", "Messages delivered correctly",
                       "Delivered (%)", percent=True),
            use_container_width=True)
    with g2:
        st.plotly_chart(
            line_chart("avg_bits", "Bits sent (battery cost)", "Bits per message"),
            use_container_width=True)

    with st.expander("⬇️  Download results"):
        rows = sweep_to_rows(results)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        csv_text = buf.getvalue()

        e1, e2, e3 = st.columns(3)
        with e3:
            st.download_button(
                "Data (.csv)", use_container_width=True,
                data=csv_text, file_name="iotguard_results.csv", mime="text/csv")
        if EXPORT_AVAILABLE:
            # Passed as functions so the files are only built when clicked,
            # not on every slider move.
            with e1:
                st.download_button(
                    "PDF report", use_container_width=True,
                    data=lambda: make_plots.export_pdf(
                        message, stats, results, int(trials)),
                    file_name="iotguard_report.pdf", mime="application/pdf")
            with e2:
                st.download_button(
                    "Charts (.zip)", use_container_width=True,
                    data=lambda: make_plots.export_png_bundle(
                        message, stats, results, int(trials), csv_text),
                    file_name="iotguard_charts.zip", mime="application/zip")
        else:
            st.caption("PDF and chart downloads work when the app is run "
                       "locally (`./run.sh`).")
