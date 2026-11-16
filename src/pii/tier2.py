"""Tier-2 (probabilistic / NER) interface and roadmap.

Tier-2 covers entities that have no checksum or stable structure -- names,
addresses, free-text and special-category PII -- where detection is a model's job,
not a regex's. This module defines the seam; the model-backed implementation is a
later phase.

Recommendation (see docs/research-python-pii-sota.md), calibrated to the finding
that open-source PII NER is ~0.55 cross-domain F1, not the advertised 0.97+:

  - WRAP Microsoft Presidio (MIT) as the framework backbone (analyzer/anonymizer,
    best regex catalog, pluggable recognizers).
  - WRAP GLiNER v1 (knowledgator/gliner-bi-large-v1.0, Apache-2.0) as the default
    NER backend (best cross-domain stability, zero-shot, clean license).
  - BUILD a fine-tuning pipeline on synthetic data + a confidence
    calibration layer (OOD generalization is the real bottleneck).
  - Art.9 special categories: a LEXICAL keyword recognizer only, documented as
    incomplete. Never an inference model: the CJEU treats inferred Art.9 data as
    Art.9 data, so an inference classifier creates the very liability it detects.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .types import Finding


@runtime_checkable
class Tier2Backend(Protocol):
    """A probabilistic detector. Implementations return Findings with tier=2 and a
    model confidence in score (< 1.0). The Go side reaches an equivalent backend
    over a sidecar / ONNX / cloud DLP (see docs/research-go-pii-landscape.md)."""

    name: str

    def detect(self, text: str) -> list[Finding]:
        ...


class NullTier2(Tier2Backend):
    """Placeholder backend: detects nothing. Lets callers wire the Tier-1 + Tier-2
    fusion path before a real model is integrated."""

    name = "null-tier2"

    def detect(self, text: str) -> list[Finding]:  # noqa: ARG002
        return []
