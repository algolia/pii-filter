"""Tier-1 detector vs the golden corpus, and the anonymizer.

The headline cross-language claim: the Python Tier-1 detector matches the same
corpus the Go detectors do (corpus_test.go), span-for-span. We assert exact match
(no false positives, no false negatives) on this curated set, and that the
regex-only baseline is strictly less precise (the validators earn their keep).
"""

from __future__ import annotations

import pytest

from pii import (
    Finding,
    Policy,
    RegexBaselineDetector,
    Rejected,
    Tier1Detector,
    apply_policy,
    spec_policy,
)
from pii.bench import load_corpus, score_detector


def test_tier1_exactly_matches_corpus():
    examples = load_corpus()
    board = score_detector(Tier1Detector(), examples)
    assert board.overall.fp == 0, f"Tier-1 false positives: {board.overall.fp}"
    assert board.overall.fn == 0, f"Tier-1 false negatives: {board.overall.fn}"
    assert board.overall.precision == 1.0
    assert board.overall.recall == 1.0


def test_baseline_is_less_precise_than_tier1():
    examples = load_corpus()
    base = score_detector(RegexBaselineDetector(), examples)
    tier1 = score_detector(Tier1Detector(), examples)
    # The validators must catch false positives the regex-only baseline emits
    # (Luhn/IIN-invalid cards, out-of-range IPs, invalid IBANs, date-like phones).
    assert base.overall.fp > tier1.overall.fp
    assert base.overall.precision < tier1.overall.precision


def test_luhn_iin_rejects_valid_luhn_without_issuer():
    # 1111 2222 3333 4444 passes Luhn but has no card-network IIN -> not a card.
    findings = Tier1Detector().detect("Tracking 1111 2222 3333 4444 today.")
    assert not [f for f in findings if f.entity == "CREDIT_CARD"]


def test_iban_lengths_table_loads_from_shared_ssot():
    from pii.validators import IBAN_LENGTHS

    # Loaded from iban_lengths.json (the same file Go embeds). The count guards
    # against a truncated/corrupt shared file; the spot-checks against transcription.
    assert len(IBAN_LENGTHS) == 89
    assert IBAN_LENGTHS["DE"] == 22
    assert IBAN_LENGTHS["NL"] == 18
    assert IBAN_LENGTHS["RU"] == 33  # a recently-added registry entry


def test_iban_rejects_valid_checksum_wrong_country_length():
    from pii.validators import iban_mod97

    # Both satisfy mod-97 but carry the wrong length for their country code
    # (NL is 18, DE is 22), so per ISO 13616 they are not IBANs.
    assert not iban_mod97("NL14ABNA04171643001234")  # len 22, NL wants 18
    assert not iban_mod97("DE863704004405320130")  # len 20, DE wants 22
    # A correctly-shaped NL IBAN still validates.
    assert iban_mod97("NL91ABNA0417164300")


def test_phone_does_not_claim_invalid_ip():
    findings = Tier1Detector().detect("Tried 192.168.1.300 but it failed.")
    assert findings == []  # not a valid IP, not a phone


def test_anonymizer_redact_hash_flag_reject():
    text = "mail jane@example.com from 10.0.0.1"
    findings = Tier1Detector().detect(text)

    policy = {"EMAIL": Policy.REDACT, "IP": Policy.FLAG}
    out = apply_policy(text, findings, policy)
    assert "[EMAIL]" in out
    assert "10.0.0.1" in out  # flagged, left in place

    hashed = apply_policy(text, findings, {"EMAIL": Policy.HASH, "IP": Policy.FLAG})
    assert "[EMAIL:" in hashed

    with pytest.raises(Rejected):
        apply_policy("pay 4242 4242 4242 4242", Tier1Detector().detect("pay 4242 4242 4242 4242"), spec_policy())


def test_finding_spans_are_consistent():
    f = Finding(entity="EMAIL", start=0, end=4, value="abcd")
    assert f.span == (0, 4)
