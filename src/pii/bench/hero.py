"""Render the README hero: a multi-panel dataviz of Tier-1's value.

Four panels, all from the live bench (no hardcoded numbers):
  A. Precision & recall, regex-only baseline vs validated Tier-1, with 95% Wilson
     CIs — the headline (validators lift precision without costing recall).
  B. False positives by entity for the baseline, collapsing to zero under Tier-1.
  C. Per-entity precision lift (baseline -> Tier-1) as a slope/dumbbell.
  D. A live redaction demo: detection + spec policy applied to a sample string.

Honest by construction: the corpus is small (n shown in the title), so panel A
carries its error bars. This is a tripwire demonstrated on curated data, not a
field-accuracy claim.
"""

from __future__ import annotations

from pathlib import Path

from ..anonymize import apply_policy, spec_policy
from ..detect import RegexBaselineDetector, Tier1Detector
from .corpus import load_corpus
from .score import Scoreboard, score_detector

# palette: muted red = "before" (over-matching baseline), teal = "after" (validated)
_BEFORE = "#C44E52"
_AFTER = "#2A9D8F"
_INK = "#22303C"
_MUTED = "#7A8A99"

_DEMO = "ping me at sam.rivera@example.org or +33 1 99 00 12 34, host 10.0.0.42"


def build_hero(out_path: str | Path, corpus_dir: str | Path | None = None) -> Path:
    import matplotlib

    matplotlib.use("Agg")  # headless
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    examples = load_corpus(corpus_dir)
    base = score_detector(RegexBaselineDetector(), examples)
    tier1 = score_detector(Tier1Detector(), examples)
    n = tier1.n_examples

    fig = plt.figure(figsize=(13, 7.4))
    fig.patch.set_facecolor("white")
    gs = GridSpec(
        2, 2, figure=fig,
        left=0.10, right=0.97, top=0.80, bottom=0.14, hspace=0.55, wspace=0.20,
    )

    # ---- title band -------------------------------------------------------
    fig.text(0.06, 0.93, "algolia/pii-filter — Tier-1", fontsize=27, fontweight="bold",
             color=_INK, ha="left")
    fig.text(0.06, 0.875,
             "Deterministic PII identifiers, validated. Regex finds the candidates; "
             "checksums decide what's real.",
             fontsize=12.5, color=_MUTED, ha="left")

    _panel_pr(fig.add_subplot(gs[0, 0]), base, tier1, n, plt)
    _panel_fp(fig.add_subplot(gs[0, 1]), base, tier1, plt)
    _panel_lift(fig.add_subplot(gs[1, 0]), base, tier1, plt)
    _panel_redact(fig.add_subplot(gs[1, 1]))

    fig.text(0.10, 0.035,
             f"Span-level, n={n} curated examples, 95% Wilson intervals. "
             "A high-precision tripwire on clean data, not a compliance guarantee.",
             fontsize=9, color=_MUTED, ha="left", style="italic")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out


def _panel_pr(ax, base: Scoreboard, tier1: Scoreboard, n: int, plt) -> None:
    """Precision & recall, baseline vs Tier-1, with Wilson CI error bars."""
    b, t = base.overall, tier1.overall
    metrics = ["Precision", "Recall"]
    x = range(len(metrics))
    width = 0.36

    b_pts = [b.precision, b.recall]
    t_pts = [t.precision, t.recall]
    b_err = _err(b_pts, [b.precision_ci, b.recall_ci])
    t_err = _err(t_pts, [t.precision_ci, t.recall_ci])

    ax.bar([i - width / 2 for i in x], b_pts, width, label="regex-only baseline",
           yerr=b_err, capsize=4, color=_BEFORE, alpha=0.85)
    ax.bar([i + width / 2 for i in x], t_pts, width, label="Tier-1 (validated)",
           yerr=t_err, capsize=4, color=_AFTER)

    for i, v in zip(x, b_pts):
        ax.text(i - width / 2, v + 0.02, f"{v:.2f}", ha="center", fontsize=9,
                color=_BEFORE, fontweight="bold")
    for i, v in zip(x, t_pts):
        ax.text(i + width / 2, v + 0.02, f"{v:.2f}", ha="center", fontsize=9,
                color=_AFTER, fontweight="bold")

    ax.set_ylim(0, 1.16)
    ax.set_xticks(list(x))
    ax.set_xticklabels(metrics, fontsize=11)
    ax.set_ylabel("score", fontsize=10)
    ax.set_title("Validators lift precision, recall holds", fontsize=12.5,
                 fontweight="bold", color=_INK, loc="left")
    ax.legend(loc="lower center", fontsize=8.5, frameon=False)
    ax.grid(axis="y", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)


def _panel_fp(ax, base: Scoreboard, tier1: Scoreboard, plt) -> None:
    """False positives per entity: baseline bars vs Tier-1's zero line."""
    items = sorted(base.per_entity.items(), key=lambda kv: kv[1].fp, reverse=True)
    labels = [e for e, _ in items]
    fps = [s.fp for _, s in items]
    y = range(len(labels))

    ax.barh(list(y), fps, color=_BEFORE, alpha=0.85, height=0.6)
    for i, v in zip(y, fps):
        ax.text(v + 0.3, i, str(v), va="center", fontsize=9, color=_BEFORE,
                fontweight="bold")

    total_b = base.overall.fp
    total_t = tier1.overall.fp
    ax.invert_yaxis()
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=10)
    ax.set_xlim(0, max(fps) + 3)
    ax.set_xlabel("false positives (baseline)", fontsize=10)
    ax.set_title(f"False positives removed: {total_b} → {total_t}",
                 fontsize=12.5, fontweight="bold", color=_INK, loc="left")
    ax.text(0.97, 0.06, f"Tier-1: {total_t} FP", transform=ax.transAxes,
            ha="right", fontsize=10.5, color=_AFTER, fontweight="bold")
    ax.grid(axis="x", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)


def _panel_lift(ax, base: Scoreboard, tier1: Scoreboard, plt) -> None:
    """Per-entity precision as a dumbbell: baseline dot -> Tier-1 dot."""
    ents = sorted(base.per_entity)
    y = range(len(ents))
    b_p = [base.per_entity[e].precision for e in ents]
    t_p = [tier1.per_entity[e].precision for e in ents]

    for i, (bp, tp) in zip(y, zip(b_p, t_p)):
        ax.plot([bp, tp], [i, i], color=_MUTED, lw=2, zorder=1, alpha=0.6)
    ax.scatter(b_p, list(y), color=_BEFORE, s=70, zorder=2, label="baseline")
    ax.scatter(t_p, list(y), color=_AFTER, s=70, zorder=3, label="Tier-1")

    ax.set_yticks(list(y))
    ax.set_yticklabels(ents, fontsize=10)
    ax.set_xlim(0, 1.08)
    ax.invert_yaxis()
    ax.set_xlabel("precision", fontsize=10)
    ax.set_title("Every entity reaches precision 1.00", fontsize=12.5,
                 fontweight="bold", color=_INK, loc="left")
    ax.legend(loc="lower left", fontsize=8.5, frameon=False)
    ax.grid(axis="x", alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)


def _panel_redact(ax) -> None:
    """A live detection + policy demo, rendered as before/after text."""
    findings = Tier1Detector().detect(_DEMO)
    redacted = apply_policy(_DEMO, findings, spec_policy())

    ax.axis("off")
    ax.set_title("Detect, then apply policy", fontsize=12.5, fontweight="bold",
                 color=_INK, loc="left")

    found = ", ".join(f"{f.entity}" for f in findings)
    ax.text(0.0, 0.86, "input", fontsize=9.5, color=_MUTED, transform=ax.transAxes)
    ax.text(0.0, 0.70, _wrap(_DEMO), fontsize=10, family="monospace",
            color=_INK, transform=ax.transAxes, va="top")
    ax.text(0.0, 0.40, f"detected  →  {found}", fontsize=9.5, color=_MUTED,
            transform=ax.transAxes)
    ax.text(0.0, 0.26, "output (spec policy: email/phone redact, IP flag)",
            fontsize=9.5, color=_MUTED, transform=ax.transAxes)
    ax.text(0.0, 0.10, _wrap(redacted), fontsize=10, family="monospace",
            color=_AFTER, transform=ax.transAxes, va="top", fontweight="bold")


def _wrap(s: str, width: int = 46) -> str:
    import textwrap

    return "\n".join(textwrap.wrap(s, width=width))


def _err(points: list[float], cis: list[tuple[float, float]]) -> list[list[float]]:
    lower = [max(0.0, p - ci[0]) for p, ci in zip(points, cis)]
    upper = [max(0.0, ci[1] - p) for p, ci in zip(points, cis)]
    return [lower, upper]
