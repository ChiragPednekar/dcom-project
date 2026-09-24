# IoTGuard

**Error-Resilient Communication for Low-Power IoT Sensor Networks**

A simulation and live-demo tool for a Digital Communication course project. It
traces a sensor reading through the complete communication chain and shows where
each error-control strategy survives, where it breaks, and what it costs.

```
sensor text → Huffman compression → channel coding → noisy radio (BSC) → decode → verify
```

## Running it

```bash
./run.sh
```

That creates the virtualenv on first run and opens the app in your browser. Or
manually:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

To verify the simulation core:

```bash
.venv/bin/python test_iotguard.py
```

## The three schemes

| Scheme | Mechanism | Overhead | Retransmits? |
|---|---|---|---|
| **RAW** | none — baseline | 0 | no |
| **CRC-8 + ARQ** | detect damage, ask for a resend | 8 bits/frame | yes, unboundedly as noise rises |
| **Hamming(7,4)** | locate and repair 1 bit per block | 1.75× fixed | no |

## The result to demonstrate

At **p = 0.02** on a 32-character sensor message:

| Scheme | Success rate | Avg bits on air | Avg retransmissions |
|---|---|---|---|
| RAW | 8.0 % | 137 | 0.00 |
| CRC-8 + ARQ | 30.0 % | 745 | 4.14 |
| Hamming(7,4) | **75.5 %** | **245** | **0.00** |

Hamming delivers the message more than twice as often as CRC+ARQ while putting
**a third as many bits** on the air. For a battery-powered node, bits on air is
energy — ARQ's retransmissions are paid for out of battery life and latency.

Push p high enough and everything fails: Hamming(7,4) has minimum distance 3, so
once two errors land in the same 7-bit block it "corrects" the wrong bit. That
bend in the green curve is a real property of the code, not a simulation
artefact.

## Interface

- **Live Demo** — one transmission, stage by stage. Bits the channel flipped are
  painted red, and you can watch them disappear between the received stream and
  the Hamming-corrected payload. Ends in a green check or a red cross.
- **Comparison & Charts** — statistical averages over many trials, a
  side-by-side table, and interactive success/overhead/retransmission curves
  swept across p.
- **How It Works** — plain-language explanation of each stage.
- **Export** — PDF report, PNG bundle (`.zip`), or raw CSV.

## Deploying to Vercel

Streamlit is a stateful server and **cannot run on Vercel's serverless
runtime**. Instead this repo ships a [stlite](https://github.com/whitphx/stlite)
build: the same Python modules run inside the browser via WebAssembly
(Pyodide), producing a purely static site that Vercel serves directly.

```bash
vercel --prod
```

`vercel.json` runs `build.sh` (which copies the Python modules into `public/`)
and publishes `public/` as a static site. No server, no Python runtime on
Vercel's side — the visitor's browser does all the work.

There is one source of truth for the algorithms: edit `app.py` and friends at
the repo root, and `build.sh` copies them into the bundle. The `public/*.py`
copies are generated and git-ignored.

Two caveats for the hosted build:

- **First load takes 15–30 seconds** while the browser downloads the Python
  runtime and Plotly. It is cached afterwards.
- **PDF/PNG export is disabled** — it needs matplotlib, which is a large wheel
  and is omitted to keep load times reasonable. The CSV export still works, and
  running locally (`./run.sh`) restores the full export. The app detects this
  and disables those buttons cleanly rather than erroring.

If you would rather have the full-fat version with export working, deploy to
[Streamlit Community Cloud](https://share.streamlit.io) instead — it runs this
repo unmodified.

## Files

| File | Responsibility |
|---|---|
| `huffman.py` | Huffman tree, encode/decode, entropy, compression ratio |
| `error_control.py` | CRC-8 generate/check, Hamming(7,4) encode/decode |
| `channel.py` | Binary Symmetric Channel, Shannon capacity |
| `pipeline.py` | End-to-end trials, multi-trial averaging, p-sweeps |
| `make_plots.py` | matplotlib figures for the PDF/PNG export |
| `ui_helpers.py` | HTML/CSS rendering helpers for the GUI |
| `app.py` | Streamlit interface — contains no algorithms |
| `public/index.html` | stlite loader for the static WebAssembly build |
| `build.sh` | Assembles the `public/` bundle for Vercel |
| `test_iotguard.py` | 48 correctness checks on the simulation core |

## Modelling assumptions

- The Huffman codebook is shared out-of-band, so only the payload is modelled on
  the air. Transmitting the codebook would add a fixed cost to every scheme
  equally and would not change the comparison.
- The BSC is memoryless — real interference is often bursty, which would favour
  ARQ somewhat relative to Hamming.
- ARQ acknowledgements are assumed instantaneous and error-free; only the
  forward frames are counted.
