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
from typing import Dict, List

import plotly.graph_objects as go
import streamlit as st

import huffman
# matplotlib is only needed for the PDF/PNG export. In a WebAssembly build
# (stlite/Pyodide) it may be unavailable or slow to load, so treat it as
# optional rather than letting an import failure take the whole app down.
try:
    import make_plots
    EXPORT_AVAILABLE = True
except Exception as _export_err:  # pragma: no cover - environment dependent
    make_plots = None
    EXPORT_AVAILABLE = False
    _EXPORT_ERROR = _export_err
import ui_helpers as ui
from channel import channel_capacity, expected_block_success
from error_control import CRC8_WIDTH, hamming_overhead_ratio
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

PRESETS = {
    "Temperature + humidity": "temperature: 24.5C humidity: 60%",
    "GPS fix": "lat:19.0760 lon:72.8777 alt:14m fix:3D",
    "Battery telemetry": "node:A7 batt:3.71V rssi:-82dBm uptime:1841s",
    "Repetitive stream": "AAAA BBBB AAAA BBBB AAAA BBBB AAAA BBBB",
    "Alarm packet": "ALERT smoke=TRUE zone=3 ts=1712049912",
}

st.set_page_config(
    page_title="IoTGuard — Error-Resilient IoT Communication",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(ui.CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Sidebar: every control lives here so the main pane stays uncluttered
# --------------------------------------------------------------------------- #

with st.sidebar:
    st.markdown("### 📡 IoTGuard")
    st.caption("Digital Communication — source coding, channel coding, and noise")
    st.divider()

    st.markdown("#### 1 · Sensor message")
    preset = st.selectbox(
        "Preset payload", ["— custom —"] + list(PRESETS),
        help="Sample payloads a real sensor node might send. Pick one, or "
             "choose 'custom' and type your own below.",
    )
    default_msg = PRESETS.get(preset, PRESETS["Temperature + humidity"])
    message = st.text_area(
        "Message to transmit", value=default_msg, height=80,
        help="This is the data the IoT node wants to get to the gateway. "
             "Longer and more repetitive messages compress better.",
    )

    st.markdown("#### 2 · Channel quality")
    p = st.slider(
        "Bit-error probability  p", 0.0, 0.15, 0.02, 0.001, format="%.3f",
        help="Chance that any individual bit flips in transit. p=0 is a perfect "
             "link; p=0.15 is a badly degraded one. Higher p stands in for "
             "longer range, interference, or lower transmit power.",
    )
    st.caption(
        f"Shannon capacity at this p: **{channel_capacity(p):.3f}** bits per "
        f"channel use — the hard ceiling no scheme can beat."
    )

    st.markdown("#### 3 · Protection scheme")
    scheme_choice = st.radio(
        "Error-control strategy",
        ["RAW", "CRC_ARQ", "HAMMING", "COMPARE"],
        format_func=lambda s: {
            "RAW": "RAW — no protection",
            "CRC_ARQ": "CRC-8 + ARQ — detect & resend",
            "HAMMING": "Hamming(7,4) — correct in place",
            "COMPARE": "Compare all three",
        }[s],
        help="RAW is the baseline. CRC+ARQ detects damage and asks for a "
             "retransmission. Hamming adds enough redundancy to repair a "
             "single-bit error per block without any round trip.",
    )

    st.markdown("#### 4 · Statistics")
    trials = st.number_input(
        "Trials per data point", 20, 2000, 200, 20,
        help="Each trial is one independent run through the noisy channel. "
             "More trials means smoother, more trustworthy curves — but a "
             "slower sweep.",
    )
    max_retx = st.number_input(
        "ARQ retransmission limit", 1, 20, DEFAULT_MAX_RETRANSMISSIONS, 1,
        help="How many times CRC+ARQ will retry before the node gives up and "
             "drops the message. A real battery-powered node cannot retry "
             "forever.",
    )
    with st.expander("Sweep range", expanded=False):
        p_max = st.slider("Maximum p on the charts", 0.02, 0.15, 0.10, 0.01)
        p_points = st.slider("Number of points", 5, 31, 16, 1)

    st.divider()
    st.caption(
        "Huffman codebook is assumed shared out-of-band, so only the payload "
        "is modelled on the air."
    )

message = message.strip()


# --------------------------------------------------------------------------- #
# Header + source-coding stats (always visible)
# --------------------------------------------------------------------------- #

st.markdown("## Error-Resilient Communication for Low-Power IoT Sensors")
st.caption(
    "A message travels sensor → compression → error-control coding → noisy "
    "radio channel → decoder → verification. Watch where it survives and "
    "where it breaks."
)

if not message:
    st.warning("Enter a sensor message in the sidebar to begin.")
    st.stop()

stats = huffman.analyze(message)
freq = huffman.build_frequency(message)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Entropy (bits/symbol)", f"{stats.entropy:.3f}",
          help="Shannon entropy — the theoretical minimum bits per character "
               "for any lossless code on this message.")
c2.metric("Avg code length (bits/symbol)", f"{stats.avg_code_length:.3f}",
          help="What Huffman actually achieved. It can never beat entropy, "
               "and gets within 1 bit of it.")
c3.metric("Coding efficiency", f"{stats.efficiency * 100:.1f}%",
          help="Entropy ÷ average code length. Closer to 100% means Huffman "
               "is squeezing out nearly all the redundancy available.")
c4.metric("Compressed size", f"{stats.compressed_bits} bits",
          f"−{stats.original_bits - stats.compressed_bits} vs raw ASCII",
          help=f"Uncompressed this message is {stats.original_bits} bits "
               f"(8 bits per character).")
c5.metric("Compression ratio", f"{stats.compression_ratio:.2f}×",
          f"{stats.savings_percent:.1f}% saved",
          help="Every bit not sent is radio-on time not spent, which is "
               "battery not drained.")

tab_demo, tab_compare, tab_theory = st.tabs(
    ["🔬  Live Demo", "📊  Comparison & Charts", "📖  How It Works"]
)


# --------------------------------------------------------------------------- #
# TAB 1 -- Live step-by-step demo
# --------------------------------------------------------------------------- #

with tab_demo:
    demo_scheme = scheme_choice if scheme_choice != "COMPARE" else "HAMMING"
    left, right = st.columns([3, 2])
    with left:
        st.markdown(
            f"#### Single transmission — **{SCHEME_LABELS[demo_scheme]}** at "
            f"**p = {p:.3f}**"
        )
        if scheme_choice == "COMPARE":
            st.caption(
                "'Compare all three' is a statistical mode; the live demo "
                "shows one scheme at a time, so it is using Hamming here. "
                "Pick a specific scheme in the sidebar to trace that one."
            )
    with right:
        b1, b2 = st.columns(2)
        run_demo = b1.button("▶  Run transmission", type="primary",
                             use_container_width=True)
        animate = b2.toggle("Animate", value=True,
                            help="Reveal each stage in sequence — better for "
                                 "presenting live.")

    if run_demo:
        st.session_state.trial = run_trial(
            message, demo_scheme, p,
            rng=random.Random(),
            max_retransmissions=int(max_retx),
        )
        st.session_state.animate = animate

    trial = st.session_state.get("trial")
    if trial is None:
        st.info(
            "Press **Run transmission** to send this message across the noisy "
            "channel once and watch every stage of the pipeline."
        )
    else:
        do_animate = st.session_state.get("animate", False)
        slots = [st.container() for _ in range(7)]

        def pause(seconds: float = 0.45) -> None:
            if do_animate:
                time.sleep(seconds)

        # -- Stage 1: the original text --------------------------------
        with slots[0]:
            st.markdown(ui.stage_header(1, "Original sensor reading",
                                        f"{len(trial.message)} characters"),
                        unsafe_allow_html=True)
            st.code(trial.message, language=None)
        pause()

        # -- Stage 2: plain ASCII bits ---------------------------------
        with slots[1]:
            st.markdown(
                ui.stage_header(2, "Uncompressed binary (8 bits per character)",
                                f"{stats.original_bits} bits — this is what we "
                                f"are trying to avoid sending"),
                unsafe_allow_html=True)
            st.markdown(ui.render_text_bits(trial.message), unsafe_allow_html=True)
        pause()

        # -- Stage 3: Huffman ------------------------------------------
        with slots[2]:
            st.markdown(
                ui.stage_header(3, "Source coding — Huffman compression",
                                f"{stats.original_bits} → {stats.compressed_bits} "
                                f"bits ({stats.savings_percent:.1f}% saved)"),
                unsafe_allow_html=True)
            with st.expander("Codebook — frequent characters get shorter codes",
                             expanded=False):
                st.markdown(ui.render_codebook(trial.codes, freq),
                            unsafe_allow_html=True)
            st.markdown(ui.render_bits(trial.source_bits), unsafe_allow_html=True)
        pause()

        # -- Stage 4: channel coding -----------------------------------
        added = len(trial.encoded_bits) - len(trial.source_bits)
        subtitle = {
            "RAW": "nothing added — the payload goes out bare",
            "CRC_ARQ": f"+{CRC8_WIDTH} CRC bits appended as a checksum",
            "HAMMING": f"+{added} parity bits ({hamming_overhead_ratio():.2f}× "
                       f"expansion, 4 data bits → 7 coded bits)",
        }[trial.scheme]
        with slots[3]:
            st.markdown(
                ui.stage_header(4, "Channel coding — adding protection",
                                subtitle),
                unsafe_allow_html=True)
            if trial.scheme == "CRC_ARQ":
                st.markdown(
                    ui.render_bits(trial.encoded_bits,
                                   highlight=range(len(trial.source_bits),
                                                   len(trial.encoded_bits))),
                    unsafe_allow_html=True)
                st.caption("The 8 highlighted bits at the end are the CRC-8 "
                           "checksum, not errors.")
            else:
                st.markdown(ui.render_bits(trial.encoded_bits),
                            unsafe_allow_html=True)
        pause()

        # -- Stage 5: the channel --------------------------------------
        n_flips = len(trial.flipped_indices)
        with slots[4]:
            st.markdown(
                ui.stage_header(
                    5, "Binary Symmetric Channel — noise strikes",
                    f"{n_flips} bit{'s' if n_flips != 1 else ''} flipped out of "
                    f"{len(trial.encoded_bits)} on the final attempt"),
                unsafe_allow_html=True)

            if trial.scheme == "CRC_ARQ" and len(trial.attempts) > 1:
                pills = "".join(
                    f'<span class="attempt-pill {"ok" if a.accepted else "bad"}">'
                    f'attempt {a.index + 1}: {len(a.flipped)} '
                    f'flip{"" if len(a.flipped) == 1 else "s"} — '
                    f'{"CRC passed" if a.accepted else "CRC failed, resend"}</span>'
                    for a in trial.attempts
                )
                st.markdown(f"<div>{pills}</div>", unsafe_allow_html=True)
                st.caption(
                    f"{trial.retransmissions} retransmission"
                    f"{'s' if trial.retransmissions != 1 else ''} were needed — "
                    f"{trial.bits_transmitted} bits total went over the air."
                )
            st.markdown(
                ui.render_bits(trial.received_bits, highlight=trial.flipped_indices),
                unsafe_allow_html=True)
            if n_flips:
                st.caption("Red bits were corrupted by the channel.")
        pause()

        # -- Stage 6: error control does its job -----------------------
        with slots[5]:
            if trial.scheme == "HAMMING":
                sub = (f"{trial.blocks_corrected} block"
                       f"{'s' if trial.blocks_corrected != 1 else ''} had a "
                       f"syndrome and were repaired in place — no retransmission")
                title = "Forward error correction — repairing the damage"
            elif trial.scheme == "CRC_ARQ":
                title = "Error detection — checking the CRC"
                sub = ("frame accepted" if not trial.gave_up
                       else f"gave up after {trial.retransmissions} retries")
            else:
                title = "No error control — nothing to repair with"
                sub = "the corrupted bits go straight to the decoder"
            st.markdown(ui.stage_header(6, title, sub), unsafe_allow_html=True)

            if trial.gave_up:
                st.error(
                    f"Retransmission budget of {int(max_retx)} exhausted — the "
                    f"node dropped the message. On a real sensor this is both a "
                    f"lost reading and a flat battery."
                )
            else:
                # Which payload bits are still wrong after error control ran?
                residual = [
                    i for i, (a, b) in enumerate(
                        zip(trial.corrected_bits, trial.source_bits))
                    if a != b
                ]
                st.markdown(ui.render_bits(trial.corrected_bits, highlight=residual),
                            unsafe_allow_html=True)
                if residual:
                    st.caption(
                        f"{len(residual)} bit(s) are still wrong — red marks "
                        f"damage the scheme could not undo.")
                elif trial.scheme == "HAMMING" and trial.blocks_corrected:
                    st.caption("Every corrupted bit was located and flipped "
                               "back. The payload is bit-identical to what was "
                               "sent.")
                else:
                    st.caption("Payload matches what was transmitted.")
        pause()

        # -- Stage 7: verdict ------------------------------------------
        with slots[6]:
            st.markdown(ui.stage_header(7, "Decode and verify"),
                        unsafe_allow_html=True)
            st.markdown(ui.diff_text(trial.message, trial.decoded),
                        unsafe_allow_html=True)

            detail = f"{trial.bits_transmitted} bits transmitted"
            if trial.scheme == "CRC_ARQ":
                detail += f" · {trial.retransmissions} retransmission(s)"
            if trial.scheme == "HAMMING":
                detail += f" · {trial.blocks_corrected} block(s) corrected"
            if trial.undetected_error:
                detail += " · CRC passed on a corrupted frame (undetected error)"

            st.markdown(
                ui.verdict_banner(trial.success, trial.decoded, trial.message, detail),
                unsafe_allow_html=True)

            if trial.undetected_error:
                st.warning(
                    "**Undetected error.** The CRC-8 check passed even though "
                    "the payload was damaged. An 8-bit checksum cannot catch "
                    "every possible error pattern — roughly 1 in 256 random "
                    "corruptions slips through. This is the fundamental "
                    "weakness of pure detection."
                )


# --------------------------------------------------------------------------- #
# TAB 2 -- Statistical comparison and charts
# --------------------------------------------------------------------------- #

with tab_compare:
    active = list(SCHEMES) if scheme_choice == "COMPARE" else [scheme_choice]

    st.markdown(f"#### Results at p = {p:.3f} · {int(trials)} trials each")
    point_results = {
        s: run_scheme(message, s, p, int(trials), seed=1234,
                      max_retransmissions=int(max_retx))
        for s in active
    }

    cols = st.columns(len(active))
    for col, s in zip(cols, active):
        r = point_results[s]
        with col:
            st.markdown(f"**{SCHEME_LABELS[s]}**")
            st.metric("Success rate", f"{r.success_rate * 100:.1f}%")
            st.metric("Avg bits on air", f"{r.avg_bits:.0f}",
                      f"{r.avg_bits - stats.compressed_bits:+.0f} vs payload")
            if s == "CRC_ARQ":
                st.metric("Avg retransmissions", f"{r.avg_retransmissions:.2f}")
                if r.undetected_error_rate:
                    st.caption(
                        f"⚠️ {r.undetected_error_rate * 100:.1f}% undetected errors")
                if r.give_up_rate:
                    st.caption(f"⚠️ {r.give_up_rate * 100:.1f}% dropped after retries")
            else:
                st.metric("Avg retransmissions", "0.00",
                          help="This scheme never retransmits.")

    if len(active) > 1:
        st.markdown("##### Side-by-side")
        st.dataframe(
            [
                {
                    "Scheme": SCHEME_LABELS[s],
                    "Success rate": f"{point_results[s].success_rate * 100:.1f}%",
                    "Avg bits transmitted": f"{point_results[s].avg_bits:.0f}",
                    "Avg retransmissions": f"{point_results[s].avg_retransmissions:.2f}",
                    "Undetected errors": f"{point_results[s].undetected_error_rate * 100:.1f}%",
                    "Dropped messages": f"{point_results[s].give_up_rate * 100:.1f}%",
                }
                for s in active
            ],
            use_container_width=True, hide_index=True,
        )

    st.divider()
    st.markdown(f"#### Sweep across the channel — p from 0 to {p_max:.2f}")

    p_values = [round(i * p_max / (p_points - 1), 5) for i in range(int(p_points))]
    cache_key = (message, tuple(p_values), tuple(active), int(trials), int(max_retx))

    if st.session_state.get("sweep_key") != cache_key:
        with st.spinner(f"Running {len(p_values) * len(active) * int(trials):,} "
                        f"simulated transmissions…"):
            st.session_state.sweep = sweep(
                message, p_values, active, int(trials), seed=42,
                max_retransmissions=int(max_retx))
            st.session_state.sweep_key = cache_key
    results = st.session_state.sweep

    def line_chart(attr: str, title: str, ylabel: str, percent: bool = False,
                   analytic: bool = False) -> go.Figure:
        fig = go.Figure()
        for s, series in results.items():
            fig.add_trace(go.Scatter(
                x=[r.p for r in series],
                y=[getattr(r, attr) * (100 if percent else 1) for r in series],
                name=SCHEME_LABELS[s],
                mode="lines+markers",
                line=dict(color=SCHEME_COLORS[s], width=3),
                marker=dict(size=7),
                hovertemplate=(f"<b>{SCHEME_LABELS[s]}</b><br>"
                               f"p = %{{x:.3f}}<br>{ylabel} = %{{y:.2f}}"
                               f"<extra></extra>"),
            ))
        if analytic:
            fig.add_trace(go.Scatter(
                x=p_values,
                y=[expected_block_success(stats.compressed_bits, pv) * 100
                   for pv in p_values],
                name="Theory: (1−p)^n, unprotected",
                mode="lines",
                line=dict(color="#7d8590", width=2, dash="dot"),
                hovertemplate="theory %{y:.2f}%<extra></extra>",
            ))
        fig.update_layout(
            title=dict(text=title, font=dict(size=15)),
            xaxis_title="Bit-error probability  p",
            yaxis_title=ylabel,
            template="plotly_dark",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            height=380,
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

    st.plotly_chart(
        line_chart("success_rate", "Message success rate vs channel noise",
                   "Success rate (%)", percent=True, analytic=True),
        use_container_width=True)
    st.caption(
        "The dotted grey line is the analytical (1−p)ⁿ prediction for an "
        "unprotected payload — the RAW curve should track it closely, which is "
        "a good sanity check that the simulator is behaving."
    )

    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            line_chart("avg_bits", "Bits transmitted — the battery cost",
                       "Average bits per message"),
            use_container_width=True)
    with g2:
        st.plotly_chart(
            line_chart("avg_retransmissions", "Retransmissions — the latency cost",
                       "Average retransmissions"),
            use_container_width=True)

    st.divider()
    st.markdown("#### Export for your report")
    rows = sweep_to_rows(results)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    csv_text = buf.getvalue()

    e1, e2, e3 = st.columns(3)
    with e1:
        if EXPORT_AVAILABLE:
            st.download_button(
                "📄  PDF report", type="primary", use_container_width=True,
                data=make_plots.export_pdf(message, stats, results, int(trials)),
                file_name="iotguard_report.pdf", mime="application/pdf",
                help="Cover page with all the numbers, followed by the three "
                     "comparison charts.")
        else:
            st.button("📄  PDF report", disabled=True, use_container_width=True,
                      help="Needs matplotlib, which isn't available in this "
                           "browser build. Run the app locally to export a PDF.")
    with e2:
        if EXPORT_AVAILABLE:
            st.download_button(
                "🖼️  PNG bundle (.zip)", use_container_width=True,
                data=make_plots.export_png_bundle(message, stats, results,
                                                  int(trials), csv_text),
                file_name="iotguard_charts.zip", mime="application/zip",
                help="High-resolution PNGs of every chart plus the raw "
                     "results CSV.")
        else:
            st.button("🖼️  PNG bundle (.zip)", disabled=True,
                      use_container_width=True,
                      help="Needs matplotlib, which isn't available in this "
                           "browser build. Run the app locally to export PNGs.")
    with e3:
        st.download_button(
            "📈  Raw data (.csv)", use_container_width=True,
            data=csv_text, file_name="iotguard_results.csv", mime="text/csv",
            help="Every data point behind the charts.")

    if not EXPORT_AVAILABLE:
        st.caption(
            "Chart image export is disabled in this hosted build — the plotting "
            "library isn't available in the browser runtime. The CSV above has "
            "every number behind the charts, and running the app locally "
            "(`./run.sh`) restores the full PDF and PNG export."
        )


# --------------------------------------------------------------------------- #
# TAB 3 -- Explainer, aimed at someone seeing this cold
# --------------------------------------------------------------------------- #

with tab_theory:
    st.markdown("#### The problem")
    st.markdown(
        "A battery-powered sensor has two enemies: **noise**, which corrupts "
        "what it sends, and **energy**, which every transmitted bit consumes. "
        "Those pull in opposite directions — the obvious fix for noise is to "
        "send more bits, and the obvious fix for energy is to send fewer. "
        "IoTGuard simulates that trade-off end to end."
    )

    a, b, c = st.columns(3)
    with a:
        st.markdown("##### 1 · Source coding")
        st.markdown(
            "**Huffman compression.** Characters that appear often get short "
            "codes, rare ones get long codes. Nothing is lost, but the message "
            "shrinks — here by "
            f"**{stats.savings_percent:.0f}%**.\n\n"
            "Fewer bits means less radio-on time, which is the single biggest "
            "power draw on a sensor node."
        )
    with b:
        st.markdown("##### 2 · Channel coding")
        st.markdown(
            "**CRC-8 + ARQ** appends an 8-bit checksum. The receiver "
            "recomputes it; on a mismatch it asks for the whole frame again. "
            "Cheap when the link is clean, ruinous when it is not.\n\n"
            "**Hamming(7,4)** sends 7 bits for every 4, arranged so any single "
            "flipped bit in a block can be located and fixed by the receiver "
            "alone — no round trip at all."
        )
    with c:
        st.markdown("##### 3 · The channel")
        st.markdown(
            "**Binary Symmetric Channel.** Every bit independently flips with "
            "probability *p*, 0→1 and 1→0 equally likely.\n\n"
            f"At the current p = {p:.3f}, Shannon's capacity is "
            f"**{channel_capacity(p):.3f}** bits per channel use — an absolute "
            "ceiling on what any code could achieve."
        )

    st.divider()
    st.markdown("#### What the charts should show")
    st.markdown(
        "- **RAW collapses first.** With no protection, a single flipped bit "
        "anywhere usually destroys the whole message. Success follows "
        "(1−p)ⁿ, which falls off a cliff.\n"
        "- **CRC+ARQ holds on, but pays in bandwidth.** Its success rate stays "
        "high while the link is decent, but look at the bits-transmitted "
        "chart: as p rises, retransmissions multiply and the bits sent climb "
        "steeply. On a real node that is battery burned and latency added.\n"
        "- **Hamming stays flat and cheap.** It pays a fixed 1.75× overhead up "
        "front and never retransmits, so its bits-on-air line is perfectly "
        "level. It keeps working at noise levels where ARQ is thrashing.\n"
        "- **Everything fails eventually.** Hamming(7,4) has minimum distance "
        "3, so it fixes one bit per 7-bit block and no more. Once two errors "
        "land in the same block it 'corrects' the wrong bit and makes things "
        "worse. That is why even the green curve bends down."
    )

    st.divider()
    st.markdown("#### Reading the live demo")
    st.markdown(
        "Red bits are ones the channel flipped. Watch stage 5 → stage 6: with "
        "Hamming, red bits present in the received stream are gone from the "
        "corrected payload. With CRC+ARQ you instead see the attempt pills "
        "stack up as the frame is sent over and over. With RAW, the red bits "
        "simply pass through to the decoder and wreck it."
    )

    st.divider()
    st.markdown("#### Module map")
    st.markdown(
        "| File | Responsibility |\n"
        "|---|---|\n"
        "| `huffman.py` | Huffman tree, encode/decode, entropy, compression ratio |\n"
        "| `error_control.py` | CRC-8 generation/check, Hamming(7,4) encode/decode |\n"
        "| `channel.py` | Binary Symmetric Channel, Shannon capacity |\n"
        "| `pipeline.py` | End-to-end trials, multi-trial averaging, p-sweeps |\n"
        "| `make_plots.py` | matplotlib figures for the PDF/PNG export |\n"
        "| `app.py` | This interface — no algorithms live here |\n"
    )
