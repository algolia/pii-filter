"""`pii-bench` — score detectors against the golden corpus and report scores.

Usage:
    pii-bench score   [--detector tier1] [--corpus DIR] [--chart PATH]
    pii-bench compare [--corpus DIR] [--outdir docs]   # baseline vs tier1 + charts
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..detect import RegexBaselineDetector, Tier1Detector
from ..spec import repo_root
from .corpus import load_corpus
from .report import markdown_table, save_chart
from .score import score_detector

DETECTORS = {
    "baseline": RegexBaselineDetector,
    "tier1": Tier1Detector,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pii-bench")
    sub = parser.add_subparsers(dest="command", required=True)

    score = sub.add_parser("score", help="score one detector against the corpus")
    score.add_argument("--detector", choices=sorted(DETECTORS), default="tier1")
    score.add_argument("--corpus", default=None, help="corpus dir (default: repo corpus/)")
    score.add_argument("--chart", default="/tmp/pii_bench.png", help="PNG output path")
    score.add_argument("--no-chart", action="store_true", help="skip the chart")

    compare = sub.add_parser("compare", help="baseline vs tier1, with charts")
    compare.add_argument("--corpus", default=None, help="corpus dir (default: repo corpus/)")
    compare.add_argument("--outdir", default=str(repo_root() / "docs"), help="chart output dir")

    hero = sub.add_parser("hero", help="render the README hero dataviz")
    hero.add_argument("--corpus", default=None, help="corpus dir (default: repo corpus/)")
    hero.add_argument("--out", default=str(repo_root() / "docs" / "hero.png"),
                      help="hero PNG output path")

    args = parser.parse_args(argv)

    if args.command == "score":
        return _run_score(args)
    if args.command == "compare":
        return _run_compare(args)
    if args.command == "hero":
        return _run_hero(args)
    parser.error(f"unknown command: {args.command}")
    return 2


def _run_score(args: argparse.Namespace) -> int:
    examples = load_corpus(args.corpus)
    if not examples:
        print("no corpus examples found", file=sys.stderr)
        return 1

    board = score_detector(DETECTORS[args.detector](), examples)
    print(markdown_table(board))

    if not args.no_chart:
        print(f"\nchart: {save_chart(board, args.chart)}")

    return 0


def _run_compare(args: argparse.Namespace) -> int:
    examples = load_corpus(args.corpus)
    if not examples:
        print("no corpus examples found", file=sys.stderr)
        return 1

    outdir = Path(args.outdir)
    boards = {}
    for key in ("baseline", "tier1"):
        board = score_detector(DETECTORS[key](), examples)
        boards[key] = board
        print(markdown_table(board))
        print()
        try:
            path = save_chart(board, outdir / f"bench-{key}.png")
            print(f"chart: {path}\n")
        except Exception as exc:  # matplotlib optional at runtime
            print(f"(chart skipped: {exc})\n")

    base, tier1 = boards["baseline"].overall, boards["tier1"].overall
    print(
        f"Tier-1 lifts precision {base.precision:.2f} -> {tier1.precision:.2f} "
        f"at recall {base.recall:.2f} -> {tier1.recall:.2f} "
        f"(small corpus, n={boards['tier1'].n_examples}; see the 95% CIs above)."
    )
    return 0


def _run_hero(args: argparse.Namespace) -> int:
    from .hero import build_hero

    path = build_hero(args.out, args.corpus)
    print(f"hero: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
