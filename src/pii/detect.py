"""Detector protocol and a regex-only baseline.

A Detector is anything that maps text -> list[Finding]. The baseline applies the
spec's broad regexes WITHOUT the validators, so it over-matches (e.g. it flags
card-shaped numbers that fail the Luhn check). It exists to make the bench
runnable today and to give the Tier-1 detector a baseline to beat: adding the
validators should raise precision without hurting recall.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from .context import fold, has_keyword_before
from .spec import load_entities
from .types import EntitySpec, Finding
from .validators import VALIDATORS


@runtime_checkable
class Detector(Protocol):
    name: str

    def detect(self, text: str) -> list[Finding]:
        """Return every PII occurrence found in text."""
        ...


class RegexBaselineDetector:
    """Regex-only, validator-free. Deliberately naive."""

    name = "regex-baseline"

    def __init__(self, entities: tuple[EntitySpec, ...] | None = None) -> None:
        self._entities = entities or load_entities()
        self._compiled: list[tuple[str, re.Pattern[str]]] = [
            (e.name, re.compile(e.regex))
            for e in self._entities
            if e.regex
        ]

    def detect(self, text: str) -> list[Finding]:
        findings: list[Finding] = []
        for entity, pattern in self._compiled:
            for match in pattern.finditer(text):
                findings.append(
                    Finding(
                        entity=entity,
                        start=match.start(),
                        end=match.end(),
                        value=match.group(),
                        score=1.0,
                        tier=1,
                        detector=self.name,
                    )
                )
        return findings


def resolve_overlaps(findings: list[Finding]) -> list[Finding]:
    """Earliest start wins; at equal start, the longer (then higher-scored) match
    wins; at an exact tie the earlier finding wins, and the Tier-1 detector emits
    findings in spec order. Drop anything overlapping a kept finding. Mirrors Go's
    resolveOverlaps, so a checksum-validated identifier beats a fragment matched
    inside it, or the same digits read as a phone."""
    ordered = sorted(findings, key=lambda f: (f.start, -(f.end - f.start), -f.score))
    kept: list[Finding] = []
    last_end = -1
    for f in ordered:
        if f.start < last_end:
            continue
        kept.append(f)
        last_end = f.end
    return kept


class Tier1Detector:
    """Regex + checksum/structure validators: the high-precision Tier-1 detector.

    For each entity it applies the spec regex, then the named validator from the
    VALIDATORS registry, keeping only matches that pass. Entities marked
    ``requires_context`` also need one of their keywords just before the match
    (see :mod:`pii.context`). Overlaps are resolved so a validated identifier wins
    over a looser match inside it. This is what the baseline (validator-free)
    detector is meant to be beaten by on precision.
    """

    name = "tier1"

    def __init__(
        self,
        entities: tuple[EntitySpec, ...] | None = None,
        strict_phone: bool = False,
    ) -> None:
        """``strict_phone`` opts into the libphonenumber-backed phone validator.
        It is off by default so the default detector -- and the
        cross-language golden corpus scored against it -- stays deterministic and
        matches the Go implementation, which has no libphonenumber equivalent."""
        self._entities = entities or load_entities()
        self._compiled = []
        for e in self._entities:
            if not e.regex:
                continue
            validator = e.validator
            if strict_phone and e.name == "PHONE" and validator == "phone_digits":
                validator = "phone_digits_strict"
            gate = None
            if e.requires_context:
                gate = (tuple(fold(k) for k in e.context_keywords), e.context_window)
            self._compiled.append((e.name, re.compile(e.regex), validator, gate))

    def detect(self, text: str) -> list[Finding]:
        raw: list[Finding] = []
        for entity, pattern, validator, gate in self._compiled:
            check = VALIDATORS.get(validator) if validator else None
            for match in pattern.finditer(text):
                value = match.group()
                if check is not None and not check(value):
                    continue
                if gate is not None and not has_keyword_before(text, match.start(), *gate):
                    continue
                # Phone has no checksum, so it carries lower confidence than the
                # checksum-validated entities.
                score = 0.85 if validator == "phone_digits" else 1.0
                raw.append(
                    Finding(
                        entity=entity,
                        start=match.start(),
                        end=match.end(),
                        value=value,
                        score=score,
                        tier=1,
                        detector=self.name,
                    )
                )
        return resolve_overlaps(raw)
