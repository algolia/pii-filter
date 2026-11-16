"""Span-level scoring with calibrated uncertainty.

A predicted Finding is a true positive when a gold Finding has the same entity
type AND the same [start, end) span. Unmatched predictions are false positives;
unmatched golds are false negatives.

Precision and recall are binomial proportions, so we report a 95% Wilson score
interval alongside each point estimate. With a small corpus the intervals are
wide on purpose: that honesty is the point. F1 is reported as a point estimate
(the harmonic mean of the two), with no interval.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

from ..detect import Detector
from ..types import Example, Finding

Z_95 = 1.959963984540054  # standard normal quantile for a 95% interval


def wilson_interval(successes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """95% Wilson score interval for a proportion successes/total.

    Returns (lo, hi). For total == 0 the proportion is undefined; we return
    (0.0, 1.0) to signal "no information" rather than a false point.
    """
    if total == 0:
        return (0.0, 1.0)
    p_hat = successes / total
    denom = 1.0 + z * z / total
    center = (p_hat + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p_hat * (1 - p_hat) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


@dataclass(frozen=True, slots=True)
class EntityScore:
    entity: str
    tp: int
    fp: int
    fn: int

    @property
    def n_gold(self) -> int:
        return self.tp + self.fn

    @property
    def n_pred(self) -> int:
        return self.tp + self.fp

    @property
    def precision(self) -> float:
        return self.tp / self.n_pred if self.n_pred else 0.0

    @property
    def recall(self) -> float:
        return self.tp / self.n_gold if self.n_gold else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def precision_ci(self) -> tuple[float, float]:
        return wilson_interval(self.tp, self.n_pred)

    @property
    def recall_ci(self) -> tuple[float, float]:
        return wilson_interval(self.tp, self.n_gold)


@dataclass(frozen=True, slots=True)
class Scoreboard:
    detector: str
    n_examples: int
    per_entity: dict[str, EntityScore]
    overall: EntityScore  # micro-averaged across all entities


def _key(f: Finding) -> tuple[str, int, int]:
    return (f.entity, f.start, f.end)


def score_detector(detector: Detector, examples: list[Example]) -> Scoreboard:
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)

    for ex in examples:
        gold_remaining: dict[tuple[str, int, int], int] = defaultdict(int)
        for g in ex.entities:
            gold_remaining[_key(g)] += 1

        for pred in detector.detect(ex.text):
            k = _key(pred)
            if gold_remaining.get(k, 0) > 0:
                gold_remaining[k] -= 1
                tp[pred.entity] += 1
            else:
                fp[pred.entity] += 1

        for (entity, _, _), count in gold_remaining.items():
            if count > 0:
                fn[entity] += count

    entities = sorted(set(tp) | set(fp) | set(fn))
    per_entity = {
        e: EntityScore(entity=e, tp=tp[e], fp=fp[e], fn=fn[e]) for e in entities
    }
    overall = EntityScore(
        entity="OVERALL",
        tp=sum(tp.values()),
        fp=sum(fp.values()),
        fn=sum(fn.values()),
    )
    return Scoreboard(
        detector=getattr(detector, "name", type(detector).__name__),
        n_examples=len(examples),
        per_entity=per_entity,
        overall=overall,
    )
