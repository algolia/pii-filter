"""log_safe: the one-call log-safe telemetry helper.

log_safe is the packaged form of the README's log-safe recipe (Tier1Detector +
apply_policy with a redact-everything policy). These tests assert the contract that
matters for a logging path: every Tier-1 identifier is masked, clean text survives
untouched, a custom policy still applies, and the helper never raises on odd input.

Inputs are pulled from the golden corpus at runtime (never hardcoded), so the tests
exercise the same real values the detector is scored against.
"""

from __future__ import annotations

import pytest

from pii import Policy, Tier1Detector, log_safe, spec_policy
from pii.bench import load_corpus

TIER1_ENTITIES = ["EMAIL", "PHONE", "CREDIT_CARD", "IBAN", "IP"]


def _example_with(entity: str) -> str:
    """First corpus text whose gold labels include ``entity`` (skip if none)."""
    for ex in load_corpus():
        if any(g.entity == entity for g in ex.entities):
            return ex.text
    pytest.skip(f"corpus has no example containing {entity}")


@pytest.mark.parametrize("entity", TIER1_ENTITIES)
def test_each_tier1_entity_is_redacted(entity: str) -> None:
    text = _example_with(entity)
    out = log_safe(text)

    # The typed mask is present and every raw value of this entity is gone.
    assert f"[{entity}]" in out
    for g in Tier1Detector().detect(text):
        if g.entity == entity:
            assert g.value not in out


def test_clean_text_passes_through_unchanged() -> None:
    negatives = [ex.text for ex in load_corpus() if not ex.entities]
    assert negatives, "corpus should carry negative (PII-free) examples"
    for text in negatives:
        assert log_safe(text) == text


def test_custom_policy_override_hashes_instead_of_redacting() -> None:
    text = _example_with("EMAIL")
    out = log_safe(text, policy={"EMAIL": Policy.HASH})

    assert "[EMAIL:" in out  # hashed form, not the plain [EMAIL] mask
    for g in Tier1Detector().detect(text):
        if g.entity == "EMAIL":
            assert g.value not in out


def test_reject_policy_is_downgraded_to_redact_never_raises() -> None:
    # spec_policy() REJECTs cards/IBANs; a logging helper must not raise or drop the
    # line, so log_safe downgrades REJECT to REDACT.
    text = _example_with("CREDIT_CARD")
    out = log_safe(text, policy=spec_policy())
    assert "[CREDIT_CARD]" in out
    for g in Tier1Detector().detect(text):
        if g.entity == "CREDIT_CARD":
            assert g.value not in out


def test_empty_string_returns_empty() -> None:
    assert log_safe("") == ""


def test_idempotent() -> None:
    for ex in load_corpus():
        once = log_safe(ex.text)
        assert log_safe(once) == once


def test_never_raises_on_non_string_input() -> None:
    # None-guard via type: coerced, not raised. None -> "".
    assert log_safe(None) == ""  # type: ignore[arg-type]
    assert log_safe(12345) == "12345"  # type: ignore[arg-type]


def test_handles_huge_string() -> None:
    email_text = _example_with("EMAIL")
    huge = ("x " * 200_000) + email_text
    out = log_safe(huge)
    assert "[EMAIL]" in out
