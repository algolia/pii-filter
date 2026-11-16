#!/usr/bin/env python3
"""Render the Tier-2 CPU latency chart (first in-house measurement).

Story: the datum missing from every published source. A GLiNER2-PII forward pass on CPU
costs hundreds of ms at 1 KB (seconds at 4 KB, worse single-threaded) -- one to two orders
of magnitude above any inline budget. This is the hard number behind the report's
"asynchronous, never inline" recommendation. The footprint-lean edge ONNX is far
faster per pass, but its detections are non-functional in the current gliner runtime
(timing shown for footprint context only, hatched).

Reads bench/tier2/results_latency.jsonl. Log y-axis (latencies span ~30 ms to ~seconds).
"""
from pathlib import Path
import json
from collections import defaultdict

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "bench/tier2/results_latency.jsonl"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
BLUE = "#2a78d6"     # GLiNER2-PII
ORANGE = "#eb6834"   # gliner-pii-edge (quint8 ONNX)
BUDGET = "#5a9e5a"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Arial", "Liberation Sans"],
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
})

# ---- load ---------------------------------------------------------------------
# First occurrence per (model, threads, size) wins: the JSONL is append-only and later
# lines may come from ad-hoc re-runs whose thread pinning is not guaranteed.
lat = defaultdict(dict)   # (model, threads) -> {bytes: (p50, p95)}
cold = {}                 # (model, threads) -> (load_s, cold_infer_ms)
for line in RESULTS.read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    key = (r["model"], r["threads"])
    if r["kind"] == "latency":
        lat[key].setdefault(r["target_bytes"], (r["p50_ms"], r["p95_ms"]))
    elif r["kind"] == "cold_start":
        cold.setdefault(key, (r["load_s"], r["cold_infer_ms"]))

SIZES = [256, 1024, 4096]
XLAB = {256: "256 B", 1024: "1 KB", 4096: "4 KB"}
xs = list(range(len(SIZES)))

STYLE = {
    ("gliner2", "default"): (BLUE, "-", "o", "GLiNER2-PII · default"),
    ("gliner2", "1thread"): (BLUE, "--", "s", "GLiNER2-PII · 1 thread"),
    ("edge", "default"): (ORANGE, "-", "o", "edge quint8 · default *"),
    ("edge", "1thread"): (ORANGE, "--", "s", "edge quint8 · 1 thread *"),
}

fig, ax = plt.subplots(figsize=(12.5, 6.6), dpi=150)
fig.subplots_adjust(left=0.09, right=0.735, top=0.80, bottom=0.13)

# inline-budget band (tens of ms)
ax.axhspan(1, 50, color=BUDGET, alpha=0.10, zorder=0)
ax.text(0.02, 46, "inline budget  (tens of ms)", fontsize=9, color=BUDGET,
        va="top", ha="left", style="italic")

handles = []
for key, (col, ls, mk, label) in STYLE.items():
    if key not in lat:
        continue
    p50s = [lat[key].get(s, (None, None))[0] for s in SIZES]
    p95s = [lat[key].get(s, (None, None))[1] for s in SIZES]
    ax.plot(xs, p50s, ls=ls, marker=mk, color=col, lw=2.0, ms=7, zorder=3)
    # p95 as upward whisker
    for x, p50, p95 in zip(xs, p50s, p95s):
        if p50 is not None and p95 is not None:
            ax.plot([x, x], [p50, p95], color=col, lw=1.2, alpha=0.6, zorder=2)
    # value labels for p50
    for x, p50 in zip(xs, p50s):
        if p50 is not None:
            txt = f"{p50:.0f} ms" if p50 >= 10 else f"{p50:.1f} ms"
            ax.annotate(txt, (x, p50), textcoords="offset points", xytext=(6, 6),
                        fontsize=8.5, color=col, fontweight="bold")
    handles.append(Line2D([0], [0], color=col, ls=ls, marker=mk, lw=2.0, label=label))

ax.set_yscale("log")
ax.set_xticks(xs)
ax.set_xticklabels([XLAB[s] for s in SIZES], fontsize=11, color=INK2)
ax.set_xlabel("Input size (UTF-8)", fontsize=11, color=INK2, labelpad=8)
ax.set_ylabel("Latency per forward pass (ms, log scale)", fontsize=11, color=INK2)
ax.set_xlim(-0.25, len(SIZES) - 0.75)
ax.tick_params(length=0)
ax.yaxis.grid(True, color=GRID, lw=1.0, zorder=0)
ax.set_axisbelow(True)
for side in ("top", "right"):
    ax.spines[side].set_visible(False)
ax.spines["left"].set_color(BASELINE)
ax.spines["bottom"].set_color(BASELINE)

# legend outside right
leg = ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1.0),
                frameon=True, fontsize=9, borderpad=0.8, labelspacing=0.7, title="p50, p95 whisker")
leg.get_frame().set_facecolor(SURFACE)
leg.get_frame().set_edgecolor(GRID)
leg.get_title().set_color(INK2)
for t in leg.get_texts():
    t.set_color(INK2)

# cold-start annotation box
cold_lines = ["Cold start (load + first infer):"]
for key in (("gliner2", "default"), ("edge", "default")):
    if key in cold:
        ld, ci = cold[key]
        nm = "GLiNER2-PII" if key[0] == "gliner2" else "edge quint8"
        cold_lines.append(f"  {nm}:\n    load {ld:.1f} s, 1st pass {ci:.0f} ms")
cold_lines.append("\nPeak RSS:\n  GLiNER2-PII ~2.9 GB\n  edge quint8 ~0.5–0.7 GB")
fig.text(0.75, 0.52, "\n".join(cold_lines), fontsize=8.5, color=INK2, va="top",
         linespacing=1.5)

fig.text(0.09, 0.955,
         "Tier-2 PII NER CPU latency: hundreds of ms/pass — one to two orders above inline",
         ha="left", va="top", fontsize=14.5, fontweight="bold", color=INK)
fig.text(0.09, 0.905,
         "First in-house measurement. p50 marker, p95 whisker; 50 iters at 256 B / 1 KB, "
         "20 at 4 KB, 5 warmup.",
         ha="left", va="top", fontsize=10, color=INK2)

fig.text(0.09, 0.03,
         "* edge quint8 ONNX detections are non-functional in gliner 0.2.27 (near-random logits);\n"
         "   its timings are forward-pass cost for footprint context only.  "
         "Intel i9-13900H, torch 2.13.0+cpu — proxy hardware.",
         ha="left", va="bottom", fontsize=7.8, color=MUTED)

out = REPO / "docs/assets/tier2-latency-2026-07.png"
fig.savefig(out, dpi=150, facecolor=SURFACE)
print(f"wrote {out}")
