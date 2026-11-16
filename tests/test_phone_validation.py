"""Optional libphonenumber-backed phone validation.

Phone is the lowest-precision Tier-1 entity: the deterministic validator gates on
an E.164 digit count (9-15) and "not a dotted quad", which accepts digit strings
that are not dialable. The optional ``phonenumbers`` extra tightens this WITHOUT
becoming a hard dependency.

Design under test:
- The default detector keeps the deterministic heuristic, so its behavior (and the
  cross-language golden corpus scored against it) is environment-independent and
  matches Go, which has no libphonenumber equivalent.
- ``Tier1Detector(strict_phone=True)`` opts into libphonenumber. When the extra is
  absent it transparently falls back to the heuristic; when present it rejects
  impossible numbers the heuristic accepts, but never drops a number it cannot
  parse region-free.

The strict-path assertions skip when the extra is not installed, so the core
(no-extra) install stays green.
"""

from __future__ import annotations

import pytest

from pii import Tier1Detector
from pii.validators import (
    PHONENUMBERS_AVAILABLE,
    phone_digits,
    phone_digits_strict,
)

# Digit strings the deterministic heuristic ACCEPTS (9-15 digits, not a dotted
# quad) but that libphonenumber rejects as not dialable. These are the cases that
# prove the extra earns its keep.
IMPOSSIBLE_BUT_HEURISTIC_PASSES = [
    "+1 111 111 1111",     # NANP area code 111 is unassigned
    "+1 2345678901234",    # 13 national digits: impossible NANP length
]

# Valid-shaped numbers the extra must keep, all from published fiction ranges.
VALID_NUMBERS = [
    "+1 202 555 0187",     # NANP
    "+33 1 99 00 42 68",   # FR landline, ARCEP fiction block
]

# A bare national number (no country code): the heuristic accepts it and
# libphonenumber cannot parse it region-free, so strict validation must fall back
# to the heuristic rather than drop it. This is a golden-corpus phone positive.
REGIONLESS_NATIONAL = "05.36.49.56.78"


def _phone_findings(detector: Tier1Detector, text: str) -> list:
    return [f for f in detector.detect(text) if f.entity == "PHONE"]


def test_heuristic_accepts_impossible_numbers():
    """Precondition: the deterministic heuristic alone cannot tell these apart."""
    for num in IMPOSSIBLE_BUT_HEURISTIC_PASSES:
        assert phone_digits(num) is True


def test_default_detector_is_unchanged_by_the_extra():
    """Core behavior is the heuristic regardless of whether the extra is installed:
    the default detector still flags an impossible number as PHONE (exactly as
    today), so the extra is genuinely optional and the corpus stays deterministic."""
    default = Tier1Detector()
    assert _phone_findings(default, "Call +1 111 111 1111 now.")


def test_strict_falls_back_to_heuristic_when_extra_absent(monkeypatch):
    """With the extra unavailable, phone_digits_strict == phone_digits (no drop),
    proving genuine optionality without needing to uninstall the package."""
    monkeypatch.setattr("pii.validators.phonenumbers", None)
    for num in IMPOSSIBLE_BUT_HEURISTIC_PASSES + VALID_NUMBERS + [REGIONLESS_NATIONAL]:
        assert phone_digits_strict(num) == phone_digits(num)


@pytest.mark.skipif(not PHONENUMBERS_AVAILABLE, reason="requires algolia-pii[phone]")
def test_strict_rejects_impossible_numbers():
    """The extra rejects impossible numbers the heuristic accepts, at both the
    validator and the detector level."""
    for num in IMPOSSIBLE_BUT_HEURISTIC_PASSES:
        assert phone_digits(num) is True          # heuristic accepts
        assert phone_digits_strict(num) is False  # libphonenumber rejects

    strict = Tier1Detector(strict_phone=True)
    default = Tier1Detector()
    text = "Call +1 111 111 1111 now."
    assert _phone_findings(default, text)          # heuristic-based default: flagged
    assert not _phone_findings(strict, text)       # strict: rejected


@pytest.mark.skipif(not PHONENUMBERS_AVAILABLE, reason="requires algolia-pii[phone]")
def test_strict_keeps_valid_numbers():
    for num in VALID_NUMBERS:
        assert phone_digits_strict(num) is True

    strict = Tier1Detector(strict_phone=True)
    assert _phone_findings(strict, "Call +1 202 555 0187 now.")


@pytest.mark.skipif(not PHONENUMBERS_AVAILABLE, reason="requires algolia-pii[phone]")
def test_strict_keeps_regionless_national_number():
    """A number with no country code cannot be validated region-free; strict
    validation must keep the heuristic's decision, not drop it."""
    assert phone_digits(REGIONLESS_NATIONAL) is True
    assert phone_digits_strict(REGIONLESS_NATIONAL) is True
