"""Core data types for algolia-pii.

These mirror the language-neutral shapes in spec/schema/. Detection produces
Findings; a Policy decides what happens to each. The two are deliberately
separate (analyzer / anonymizer split): detection answers "what and where",
policy answers "what to do about it".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Policy(str, Enum):
    """What to do with a detected entity. The default per entity lives in the spec."""

    REJECT = "reject"      # drop the whole record, alert. Safest for public indices.
    REDACT = "redact"      # replace the span with a mask
    HASH = "hash"          # stable hash (joins without the raw value)
    TOKENIZE = "tokenize"  # reversible token (vault-backed)
    FLAG = "flag"          # pass through, annotate for human review
    ALLOW = "allow"        # explicit allowlist (e.g. a public contact address)


@dataclass(frozen=True, slots=True)
class Finding:
    """A single detected entity occurrence in a text.

    span is [start, end) over the ORIGINAL text (Python str indices), so
    text[start:end] == value. score is 1.0 for deterministic (Tier-1) detectors
    and < 1.0 for probabilistic (Tier-2) ones.
    """

    entity: str
    start: int
    end: int
    value: str
    score: float = 1.0
    tier: int = 1
    detector: str = ""

    @property
    def span(self) -> tuple[int, int]:
        return (self.start, self.end)


@dataclass(frozen=True, slots=True)
class EntitySpec:
    """One entity type from spec/entities.yaml."""

    name: str
    tier: int
    default_policy: Policy
    regex: str | None = None
    validator: str | None = None
    description: str = ""
    # Keyword gate ("Tier 1.5"): when requires_context is true, a match counts only
    # if one of context_keywords ends within context_window characters before it.
    requires_context: bool = False
    context_keywords: tuple[str, ...] = ()
    context_window: int = 0


@dataclass(frozen=True, slots=True)
class Example:
    """One labeled corpus example: a text and the entities it truly contains."""

    text: str
    entities: tuple[Finding, ...] = field(default_factory=tuple)
    source: str = ""  # which corpus file it came from
