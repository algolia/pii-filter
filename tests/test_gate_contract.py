"""block_if_detected: the one-call pre-LLM gate contract.

block_if_detected is the packaged form of the README pre-LLM gate recipe
(Tier1Detector + apply_policy with spec_policy). These tests pin the contract that
matters before text leaves for a third-party provider: REJECT entities raise
Rejected (carrying the entity), REDACT entities come back masked, clean text
survives, a custom policy still applies, and -- unlike log_safe -- raising is the
feature, never swallowed, never coerced.

Inputs are pulled from the golden corpus at runtime (never hardcoded), so the tests
exercise the same real values the detector is scored against.
"""

from __future__ import annotations

import pytest

from pii import (
    Policy,
    Rejected,
    Tier1Detector,
    apply_policy,
    block_if_detected,
    log_safe,
    spec_policy,
)
from pii.bench import load_corpus

REJECT_ENTITIES = ["CREDIT_CARD", "IBAN"]  # spec_policy() rejects these
REDACT_ENTITIES = ["EMAIL", "PHONE"]  # spec_policy() redacts these


def _example_with(entity: str) -> str:
    """First corpus text whose gold labels include ``entity`` (skip if none)."""
    for ex in load_corpus():
        if any(g.entity == entity for g in ex.entities):
            return ex.text
    pytest.skip(f"corpus has no example containing {entity}")


@pytest.mark.parametrize("entity", REJECT_ENTITIES)
def test_reject_entity_raises_with_correct_entity(entity: str) -> None:
    text = _example_with(entity)
    with pytest.raises(Rejected) as exc:
        block_if_detected(text)
    assert exc.value.entity == entity


@pytest.mark.parametrize("entity", REDACT_ENTITIES)
def test_redact_entity_returns_masked_text(entity: str) -> None:
    text = _example_with(entity)
    out = block_if_detected(text)
    assert f"[{entity}]" in out
    for g in Tier1Detector().detect(text):
        if g.entity == entity:
            assert g.value not in out


def test_clean_text_passes_through_unchanged() -> None:
    negatives = [ex.text for ex in load_corpus() if not ex.entities]
    assert negatives, "corpus should carry negative (PII-free) examples"
    for text in negatives:
        assert block_if_detected(text) == text


def test_custom_policy_override_can_allow_what_spec_rejects() -> None:
    # A caller may pass a laxer policy; the gate honors it instead of spec_policy().
    text = _example_with("CREDIT_CARD")
    out = block_if_detected(text, policy={"CREDIT_CARD": Policy.REDACT})
    assert "[CREDIT_CARD]" in out


def test_custom_policy_override_can_reject_what_spec_redacts() -> None:
    # And a stricter policy: EMAIL is REDACT under spec, REJECT here.
    text = _example_with("EMAIL")
    with pytest.raises(Rejected) as exc:
        block_if_detected(text, policy={"EMAIL": Policy.REJECT})
    assert exc.value.entity == "EMAIL"


def test_ip_is_flagged_not_removed() -> None:
    # spec_policy() FLAGs IPs: pass through, left in place, no raise.
    text = _example_with("IP")
    out = block_if_detected(text)
    for g in Tier1Detector().detect(text):
        if g.entity == "IP":
            assert g.value in out


def test_empty_string_returns_empty() -> None:
    assert block_if_detected("") == ""


def test_non_string_input_raises_type_error() -> None:
    # Unlike log_safe, the gate must NOT coerce -- silent coercion is a hole.
    with pytest.raises(TypeError):
        block_if_detected(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        block_if_detected(12345)  # type: ignore[arg-type]


def test_log_safe_and_gate_asymmetry_on_a_reject_entity() -> None:
    # Same input, opposite behavior by design: log_safe masks and returns; the gate
    # raises so the caller cannot forward card data.
    text = _example_with("CREDIT_CARD")

    masked = log_safe(text)
    assert "[CREDIT_CARD]" in masked  # log_safe downgrades REJECT to REDACT

    with pytest.raises(Rejected):
        block_if_detected(text)  # gate refuses instead


def test_matches_manual_recipe_under_the_hood() -> None:
    # The documented equivalence: block_if_detected == the hand-written recipe.
    text = _example_with("EMAIL")
    manual = apply_policy(text, Tier1Detector().detect(text), spec_policy())
    assert block_if_detected(text) == manual
