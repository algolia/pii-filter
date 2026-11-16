#!/usr/bin/env python3
"""Render the PII-detection SOTA F1 chart (mid-2026 research synthesis).

Story: independent / out-of-distribution F1 for PII detectors clusters BELOW 0.5
(the Sikkema anchor), while vendor self-reported in-domain numbers sit far higher.
The gap is the point.
"""
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Patch
import matplotlib.transforms as mtransforms

# ---- design tokens (dataviz skill, light surface) ----------------------------
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
BLUE = "#2a78d6"      # open-source detector, independent / OOD
ORANGE = "#eb6834"    # frontier LLM, independent benchmark
VENDOR_EDGE = "#d03b3b"   # vendor self-reported (hatched, hollow)
VENDOR_FILL = "#fbeceb"
ANCHOR = "#b0413f"    # Sikkema reference line

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Arial", "Liberation Sans"],
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "svg.fonttype": "none",
})

# ---- data --------------------------------------------------------------------
# kind: "detector" (blue solid) | "llm" (orange solid) | "vendor" (hatched hollow)
GROUPS = [
    ("SPY benchmark  ·  OOD, n=200 docs  ·  exact-match span F1", [
        ("GLiNER2-PII (0.3B)", 0.471, "detector"),
        ("nvidia/gliner-PII", 0.391, "detector"),
        ("urchade/gliner_multi_pii_v1", 0.384, "detector"),
        ("OpenAI Privacy Filter", 0.373, "detector"),
        ("knowledgator/gliner-pii-base", 0.368, "detector"),
    ]),
    ("REDACT  ·  25 languages, 51 entity types, n=1000  ·  partial-overlap micro-F1", [
        ("Claude Sonnet 4.6", 0.636, "llm"),
        ("GPT-4.1", 0.597, "llm"),
        ("OpenAI Privacy Filter", 0.512, "detector"),
        ("GLiNER-multi (zero-shot)", 0.320, "detector"),
        ("Presidio", 0.195, "detector"),
    ]),
    ("PIIBench  ·  per-entity PERSON, n=437 mentions", [
        ("spaCy en_core_web_lg", 0.264, "detector"),
        ("Presidio", 0.264, "detector"),
    ]),
    ("Vendor self-reported  ·  in-domain synthetic  ·  knowledgator HF model card", [
        ("gliner-pii-large", 0.833, "vendor"),
        ("gliner-pii-edge (197MB INT8)", 0.755, "vendor"),
    ]),
]

# ---- layout: assign y positions top -> bottom -------------------------------
BAR_STEP = 1.0
GROUP_GAP = 1.4
rows = []          # (y, label, value, kind)
group_headers = []  # (y_header, text)

y = 0.0
for gi, (header, systems) in enumerate(GROUPS):
    if gi > 0:
        y -= GROUP_GAP
    group_headers.append((y + 0.85, header))
    for label, val, kind in systems:
        rows.append((y, label, val, kind))
        y -= BAR_STEP
y_bottom = y

# ---- figure ------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(13.5, 10.2), dpi=150)
fig.subplots_adjust(left=0.30, right=0.965, top=0.885, bottom=0.115)

BAR_H = 0.62
for yv, label, val, kind in rows:
    if kind == "detector":
        ax.barh(yv, val, height=BAR_H, color=BLUE, edgecolor="none", zorder=3)
    elif kind == "llm":
        ax.barh(yv, val, height=BAR_H, color=ORANGE, edgecolor="none", zorder=3)
    else:  # vendor: hollow + hatch
        ax.barh(yv, val, height=BAR_H, facecolor=VENDOR_FILL,
                edgecolor=VENDOR_EDGE, linewidth=1.4, hatch="////", zorder=3)

    # value label at the tip
    ax.text(val + 0.012, yv, f"{val:.3f}", va="center", ha="left",
            fontsize=10.5, color=INK, fontweight="semibold")

    # LLM annotation
    if kind == "llm":
        ax.text(val + 0.088, yv, "LLM · not CPU-viable inline", va="center",
                ha="left", fontsize=8.5, color=MUTED, style="italic")

# ---- y ticks = system names --------------------------------------------------
ax.set_yticks([r[0] for r in rows])
ax.set_yticklabels([r[1] for r in rows], fontsize=10.5, color=INK2)
ax.tick_params(axis="y", length=0, pad=8)

# ---- group headers (bold, at left spine, above each cluster) -----------------
blend = mtransforms.blended_transform_factory(ax.transAxes, ax.transData)
for yh, text in group_headers:
    ax.text(0.0, yh, text, transform=blend, ha="left", va="center",
            fontsize=10.5, fontweight="bold", color=INK)

# ---- x axis: F1, FULL RANGE 0..1.0 ------------------------------------------
ax.set_xlim(0, 1.0)
ax.set_ylim(y_bottom - 0.4, group_headers[0][0] + 0.9)
ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
ax.set_xticklabels(["0", "0.2", "0.4", "0.6", "0.8", "1.0"], fontsize=10, color=MUTED)
ax.set_xlabel("F1 score  (0 – 1.0, full range)", fontsize=11, color=INK2, labelpad=8)
ax.tick_params(axis="x", length=0)

# vertical hairline gridlines, recessive, behind bars
ax.xaxis.grid(True, color=GRID, linewidth=1.0, zorder=0)
ax.set_axisbelow(True)

# ---- Sikkema anchor at 0.5 ---------------------------------------------------
ax.axvline(0.5, color=ANCHOR, linewidth=1.6, linestyle=(0, (5, 3)), zorder=4)
# horizontal callout in the empty right-of-line corridor of the SPY group
# (SPY bars all fall short of 0.5, so x>0.5 is clear across these rows)
ax.text(0.5 + 0.012, rows[3][0], "0.5",
        va="center", ha="left", fontsize=10.5, color=ANCHOR, fontweight="bold")
ax.text(0.5 + 0.052, rows[3][0],
        "Sikkema anchor\n(realistic-setting ceiling, open-source)",
        va="center", ha="left", fontsize=9, color=ANCHOR, linespacing=1.25)

# ---- spines ------------------------------------------------------------------
for side in ("top", "right"):
    ax.spines[side].set_visible(False)
ax.spines["left"].set_color(BASELINE)
ax.spines["bottom"].set_color(BASELINE)

# ---- legend (provenance) -----------------------------------------------------
legend_handles = [
    Patch(facecolor=BLUE, edgecolor="none",
          label="Open-source detector — independent / OOD benchmark"),
    Patch(facecolor=ORANGE, edgecolor="none",
          label="Frontier LLM — independent benchmark (not CPU-viable inline)"),
    Patch(facecolor=VENDOR_FILL, edgecolor=VENDOR_EDGE, linewidth=1.4, hatch="////",
          label="Vendor self-reported, in-domain — expect deflation to ~0.37–0.47 OOD"),
]
leg = ax.legend(handles=legend_handles, loc="upper right",
                bbox_to_anchor=(0.997, 0.49), frameon=True,
                fontsize=9.5, borderpad=0.9, labelspacing=0.7,
                handlelength=1.6, handleheight=1.2)
leg.get_frame().set_facecolor(SURFACE)
leg.get_frame().set_edgecolor(GRID)
leg.get_frame().set_linewidth(1.0)
for txt in leg.get_texts():
    txt.set_color(INK2)

# ---- title / subtitle / footnote --------------------------------------------
fig.text(0.30, 0.965,
         "PII detection F1, mid-2026: out-of-distribution reality vs vendor claims",
         ha="left", va="top", fontsize=16, fontweight="bold", color=INK)
fig.text(0.30, 0.925,
         "Independent + OOD benchmarks cluster below 0.5 for open-source detectors; "
         "frontier LLMs reach only ~0.6.",
         ha="left", va="top", fontsize=10.5, color=INK2)

fig.text(0.30, 0.038,
         "Sources: arXiv 2605.09973, 2606.19881, 2604.15776; knowledgator HF model card.  "
         "n varies per benchmark — see report.",
         ha="left", va="bottom", fontsize=8.5, color=MUTED)

# ---- save --------------------------------------------------------------------
out = Path(__file__).resolve().parent / "sota-f1-2026-07.png"
out.parent.mkdir(parents=True, exist_ok=True)
fig.savefig(out, dpi=150, facecolor=SURFACE)
print(f"wrote {out}")
