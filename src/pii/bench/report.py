"""Render a Scoreboard as a markdown table and a PNG chart.

Per the calibrated-science rule, both views show uncertainty: the table prints
Wilson intervals next to precision/recall, and the chart draws them as error
bars. A point estimate without its interval is a half-truth on a small corpus.
"""

from __future__ import annotations

from pathlib import Path

from .score import EntityScore, Scoreboard


def _fmt_ci(point: float, ci: tuple[float, float], n: int) -> str:
    if n == 0:
        return "n/a"
    return f"{point:.2f} [{ci[0]:.2f}-{ci[1]:.2f}]"


def markdown_table(board: Scoreboard) -> str:
    lines = [
        f"### {board.detector}  (n={board.n_examples} examples)",
        "",
        "| Entity | gold | TP | FP | FN | Precision [95% CI] | Recall [95% CI] | F1 |",
        "|---|--:|--:|--:|--:|---|---|--:|",
    ]
    rows = list(board.per_entity.values()) + [board.overall]
    for s in rows:
        lines.append(
            f"| {s.entity} | {s.n_gold} | {s.tp} | {s.fp} | {s.fn} "
            f"| {_fmt_ci(s.precision, s.precision_ci, s.n_pred)} "
            f"| {_fmt_ci(s.recall, s.recall_ci, s.n_gold)} "
            f"| {s.f1:.2f} |"
        )
    return "\n".join(lines)


def save_chart(board: Scoreboard, out_path: str | Path) -> Path:
    """Grouped P/R/F1 bar chart per entity, with Wilson CI error bars on P and R."""
    import matplotlib

    matplotlib.use("Agg")  # headless
    import matplotlib.pyplot as plt

    scores: list[EntityScore] = list(board.per_entity.values())
    labels = [s.entity for s in scores]
    x = range(len(labels))
    width = 0.27

    prec = [s.precision for s in scores]
    rec = [s.recall for s in scores]
    f1 = [s.f1 for s in scores]
    prec_err = _asym_err(prec, [s.precision_ci for s in scores])
    rec_err = _asym_err(rec, [s.recall_ci for s in scores])

    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 1.5), 4.5))
    ax.bar([i - width for i in x], prec, width, label="Precision", yerr=prec_err,
           capsize=3, color="#4C72B0")
    ax.bar(list(x), rec, width, label="Recall", yerr=rec_err, capsize=3, color="#55A868")
    ax.bar([i + width for i in x], f1, width, label="F1", color="#C44E52")

    ax.set_ylim(0, 1.05)
    ax.set_ylabel("score")
    ax.set_title(f"{board.detector} — per-entity (n={board.n_examples}, 95% Wilson CI)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=20, ha="right")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def _asym_err(points: list[float], cis: list[tuple[float, float]]) -> list[list[float]]:
    """matplotlib yerr as [[below...],[above...]] from absolute CI bounds."""
    lower = [max(0.0, p - ci[0]) for p, ci in zip(points, cis)]
    upper = [max(0.0, ci[1] - p) for p, ci in zip(points, cis)]
    return [lower, upper]
