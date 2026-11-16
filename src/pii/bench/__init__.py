"""Evaluation harness: load the golden corpus, score a detector, report with CIs.

Needs the optional ``bench`` extra (matplotlib, for the charts). The core
``import pii`` never touches this package, so a production install without the
extra stays matplotlib-free; importing ``pii.bench`` without it fails loudly here
instead of deep inside a chart call.
"""

from importlib.util import find_spec

if find_spec("matplotlib") is None:
    raise ImportError(
        "pii.bench needs the optional 'bench' extra (matplotlib). Install it with "
        "pip install 'algolia-pii[bench]' or poetry install --extras bench. "
        "Detection and policy (import pii) do not need it."
    )

from .corpus import load_corpus  # noqa: E402
from .score import EntityScore, Scoreboard, score_detector, wilson_interval  # noqa: E402

__all__ = ["load_corpus", "EntityScore", "Scoreboard", "score_detector", "wilson_interval"]
