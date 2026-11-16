#!/usr/bin/env python3
"""Render the Tier-2 French e-commerce mini-eval F1 chart (first in-house measurement).

Story: on clean French e-commerce/search text, GLiNER2-PII nails PERSON far above the
out-of-distribution 0.32-0.47 prediction, but ADDRESS confirms the "weakest entity"
finding -- exact-span F1 collapses while partial-overlap stays decent, i.e. the model
finds the address region but rarely nails its boundaries. Bootstrap 95% CIs (10k
resamples, n=200) are drawn as caps: with a small set the honesty is the point.

Reads bench/tier2/results_eval.json. F1 axis runs the FULL 0-1.0 range, never truncated.
"""
from pathlib import Path
import json

import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[2]
RESULTS = REPO / "bench/tier2/results_eval.json"

# ---- design tokens (match render_sota_f1.py, light surface) ------------------
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
BLUE = "#2a78d6"       # exact-match F1
BLUE_LT = "#9dc3ee"    # partial-overlap F1
BANDCOL = "#b0413f"    # OOD prediction band from the research report

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Arial", "Liberation Sans"],
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
})

data = json.loads(RESULTS.read_text(encoding="utf-8"))
model = next(m for m in data["models"] if m["model"] == "gliner2-pii")
ENTS = ["PERSON", "ADDRESS"]

# rows top->bottom: PERSON exact, PERSON partial, ADDRESS exact, ADDRESS partial
rows = []  # (label, f1, ci, color, entity)
for e in ENTS:
    ex = model["per_entity"][e]["exact"]
    pa = model["per_entity"][e]["partial"]
    rows.append((f"{e}  ·  exact span", ex["f1"], ex["f1_ci"], BLUE, e))
    rows.append((f"{e}  ·  partial overlap", pa["f1"], pa["f1_ci"], BLUE_LT, e))

ys = list(range(len(rows)))[::-1]  # top-first

fig, ax = plt.subplots(figsize=(11.5, 6.2), dpi=150)
fig.subplots_adjust(left=0.235, right=0.965, top=0.80, bottom=0.155)

# OOD prediction band 0.32-0.47 from the report
ax.axvspan(0.32, 0.47, color=BANDCOL, alpha=0.08, zorder=0)
ax.axvline(0.32, color=BANDCOL, lw=1.0, ls=(0, (4, 3)), alpha=0.5, zorder=1)
ax.axvline(0.47, color=BANDCOL, lw=1.0, ls=(0, (4, 3)), alpha=0.5, zorder=1)

BAR_H = 0.62
for y, (label, f1, ci, col, e) in zip(ys, rows):
    lo, hi = ci
    ax.barh(y, f1, height=BAR_H, color=col, edgecolor="none", zorder=3)
    # CI cap
    ax.plot([lo, hi], [y, y], color=INK, lw=1.4, zorder=4)
    for x in (lo, hi):
        ax.plot([x, x], [y - 0.12, y + 0.12], color=INK, lw=1.4, zorder=4)
    txt = f"{f1:.3f}  [{lo:.2f}, {hi:.2f}]"
    if f1 >= 0.55:  # long bar: label inside, right-aligned, white
        ax.text(f1 - 0.015, y, txt, va="center", ha="right",
                fontsize=10, color="white", fontweight="semibold", zorder=5)
    else:           # short bar: label to the right of the CI cap
        ax.text(hi + 0.02, y, txt, va="center", ha="left",
                fontsize=10, color=INK, fontweight="semibold", zorder=5)

ax.set_yticks(ys)
ax.set_yticklabels([r[0] for r in rows], fontsize=10.5, color=INK2)
ax.tick_params(axis="y", length=0, pad=8)

ax.set_xlim(0, 1.0)
ax.set_ylim(-0.7, len(rows) - 0.3)
ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
ax.set_xticklabels(["0", "0.2", "0.4", "0.6", "0.8", "1.0"], fontsize=10, color=MUTED)
ax.set_xlabel("Span-level F1  (0 – 1.0, full range)", fontsize=11, color=INK2, labelpad=8)
ax.tick_params(axis="x", length=0)
ax.xaxis.grid(True, color=GRID, lw=1.0, zorder=0)
ax.set_axisbelow(True)

for side in ("top", "right"):
    ax.spines[side].set_visible(False)
ax.spines["left"].set_color(BASELINE)
ax.spines["bottom"].set_color(BASELINE)

# band label
ax.text(0.395, len(rows) - 0.35, "report's OOD prediction\n(F1 0.32–0.47)",
        ha="center", va="bottom", fontsize=8.5, color=BANDCOL, linespacing=1.2)

n_person = model["per_entity"]["PERSON"]["exact"]["n_gold"]
n_addr = model["per_entity"]["ADDRESS"]["exact"]["n_gold"]
pf = model["person_recall_by_form"]

fig.text(0.235, 0.955,
         "Tier-2 GLiNER2-PII on French e-commerce text",
         ha="left", va="top", fontsize=15, fontweight="bold", color=INK)
fig.text(0.235, 0.905,
         f"First in-house measurement, n=200 (PERSON gold={n_person}, ADDRESS gold={n_addr}).  "
         "Caps = 95% bootstrap CI (10k resamples).",
         ha="left", va="top", fontsize=10, color=INK2)
fig.text(0.235, 0.868,
         f"PERSON recall holds on partial mentions (\"M. Dupont\"): full-form {pf['full']['recall']:.2f} "
         f"vs partial-form {pf['partial']['recall']:.2f}.",
         ha="left", va="top", fontsize=9.5, color=MUTED)

fig.text(0.235, 0.03,
         "Synthetic clean templates (common names + invented addresses) inflate absolute "
         "F1 vs real messy text.  Proxy hardware.  See bench/tier2/.",
         ha="left", va="bottom", fontsize=8, color=MUTED)

out = REPO / "docs/assets/tier2-eval-f1-2026-07.png"
fig.savefig(out, dpi=150, facecolor=SURFACE)
print(f"wrote {out}")
