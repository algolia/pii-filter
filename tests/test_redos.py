"""Super-linear regex guard: every Tier-1 pattern stays fast on 100k adversarial text.

A server-side gate runs the detector on caller-controlled text, so one pattern that
backtracks quadratically is a denial of service. The EMAIL pattern once had no left
boundary and took about 5 s on 100k letters with no '@'; every other entity took a
few milliseconds. The thresholds are deliberately generous (a slow CI runner must
not flake), yet far below what a quadratic pattern costs at this size.
"""

from __future__ import annotations

import re
import time

import pytest

from pii import Tier1Detector, load_entities

N = 100_000

ADVERSARIAL = {
    "letters": "a" * N,
    "digits": "1" * N,
    "dots": "." * N,
    "alnum": "a1" * (N // 2),
    "upper-alnum": "A1" * (N // 2),
    "digit-space": "1 " * (N // 2),
    "digit-dash": "1-" * (N // 2),
    "digit-dot": "1." * (N // 2),
    "visa-digit-space": "4 " * (N // 2),
    "email-local": "a." * (N // 2),
    "email-domain": "a@" + "b." * (N // 2),
    "at-signs": "a@" * (N // 2),
    "word-space": "ab " * (N // 3),
    "iban-groups": "AB12 " * (N // 5),
    "card-groups": "4242 " * (N // 5),
    "plus-digits": "+1" * (N // 2),
}

PATTERN_BUDGET_S = 0.5
DETECT_BUDGET_S = 2.0


def _elapsed(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


@pytest.mark.parametrize("entity", [e for e in load_entities() if e.regex], ids=lambda e: e.name)
def test_every_spec_pattern_is_linear_on_adversarial_input(entity) -> None:
    pattern = re.compile(entity.regex)
    for name, text in ADVERSARIAL.items():
        took = _elapsed(lambda: list(pattern.finditer(text)))
        assert took < PATTERN_BUDGET_S, f"{entity.name} took {took:.2f} s on 100k {name}"


@pytest.mark.parametrize("name", list(ADVERSARIAL))
def test_full_detector_is_fast_on_adversarial_input(name: str) -> None:
    detector = Tier1Detector()
    took = _elapsed(lambda: detector.detect(ADVERSARIAL[name]))
    assert took < DETECT_BUDGET_S, f"Tier1Detector took {took:.2f} s on 100k {name}"


def test_email_lookbehind_keeps_the_same_matches() -> None:
    # The boundary only removes starts inside a local-part run; such a start
    # reaches the same '@' as the run's head, so the match set is unchanged.
    text = "x jane.doe@example.com, a@b@example.org; .lead@example.net -dash@example.test"
    found = [f.value for f in Tier1Detector().detect(text) if f.entity == "EMAIL"]
    assert found == ["jane.doe@example.com", "b@example.org", ".lead@example.net", "-dash@example.test"]
