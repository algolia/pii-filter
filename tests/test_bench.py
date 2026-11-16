"""Tests for the spec, corpus integrity, scorer math, and Wilson intervals."""

from __future__ import annotations

import math

import pytest

from pii import RegexBaselineDetector, load_entities
from pii.bench import load_corpus, score_detector, wilson_interval
from pii.types import Example, Finding


# --- spec --------------------------------------------------------------------
def test_spec_loads_tier1_entities():
    entities = {e.name: e for e in load_entities()}
    assert {"EMAIL", "PHONE", "CREDIT_CARD", "IBAN", "IP"} <= set(entities)
    assert entities["CREDIT_CARD"].validator == "luhn"
    assert entities["EMAIL"].regex  # has a pattern
    assert all(e.tier == 1 for e in load_entities())


# --- corpus integrity --------------------------------------------------------
def test_corpus_spans_align_to_text():
    examples = load_corpus()
    assert examples, "corpus should not be empty"
    total_spans = 0
    for ex in examples:
        for g in ex.entities:
            assert ex.text[g.start : g.end] == g.value, (ex.source, g)
            total_spans += 1
    assert total_spans > 20  # we authored ~31


def test_corpus_has_positives_and_negatives():
    examples = load_corpus()
    with_pii = [e for e in examples if e.entities]
    without_pii = [e for e in examples if not e.entities]
    assert with_pii and without_pii  # both classes present (FP resistance matters)


# --- Wilson interval ---------------------------------------------------------
def test_wilson_zero_total_is_uninformative():
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_wilson_one_of_one():
    lo, hi = wilson_interval(1, 1)
    assert math.isclose(lo, 0.2065, abs_tol=1e-3)  # textbook 95% Wilson for 1/1
    assert hi == 1.0


def test_wilson_centered_for_half():
    lo, hi = wilson_interval(50, 100)
    assert lo < 0.5 < hi
    assert math.isclose((lo + hi) / 2, 0.5, abs_tol=0.02)


# --- scorer math -------------------------------------------------------------
class FixedDetector:
    name = "fixed"

    def __init__(self, by_text: dict[str, list[Finding]]):
        self._by_text = by_text

    def detect(self, text: str) -> list[Finding]:
        return self._by_text.get(text, [])


def test_scorer_counts_tp_fp_fn():
    examples = [
        Example(text="A", entities=(Finding("EMAIL", 0, 1, "A"),)),  # will be TP
        Example(text="B", entities=(Finding("IP", 0, 1, "B"),)),     # missed -> FN
        Example(text="C", entities=()),                              # spurious -> FP
    ]
    detector = FixedDetector(
        {
            "A": [Finding("EMAIL", 0, 1, "A")],
            "C": [Finding("PHONE", 0, 1, "C")],
        }
    )
    board = score_detector(detector, examples)

    assert board.overall.tp == 1
    assert board.overall.fp == 1
    assert board.overall.fn == 1
    assert math.isclose(board.overall.precision, 0.5)
    assert math.isclose(board.overall.recall, 0.5)
    assert math.isclose(board.overall.f1, 0.5)

    assert board.per_entity["EMAIL"].tp == 1
    assert board.per_entity["IP"].fn == 1
    assert board.per_entity["PHONE"].fp == 1


def test_wrong_span_is_not_a_match():
    examples = [Example(text="abcd", entities=(Finding("EMAIL", 0, 4, "abcd"),))]
    detector = FixedDetector({"abcd": [Finding("EMAIL", 0, 2, "ab")]})  # off span
    board = score_detector(detector, examples)
    assert board.overall.tp == 0
    assert board.overall.fp == 1  # the off-span prediction
    assert board.overall.fn == 1  # the gold it missed


# --- baseline detector sanity ------------------------------------------------
def test_baseline_detects_email_exactly():
    detector = RegexBaselineDetector()
    findings = detector.detect("ping jane.doe@example.com now")
    emails = [f for f in findings if f.entity == "EMAIL"]
    assert len(emails) == 1
    assert emails[0].value == "jane.doe@example.com"


def test_baseline_overmatches_invalid_card_by_design():
    # Luhn-invalid 16-digit number: regex-only baseline matches it (a false positive
    # that the Tier-1 validator will later reject). This documents the gap.
    detector = RegexBaselineDetector()
    findings = detector.detect("Order 1234 5678 9012 3456 shipped.")
    assert any(f.entity == "CREDIT_CARD" for f in findings)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
