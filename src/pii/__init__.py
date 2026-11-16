"""algolia-pii: PII detection + policy, with a shared spec and a calibrated bench."""

from .anonymize import Rejected, apply_policy, block_if_detected, log_safe, spec_policy
from .detect import Detector, RegexBaselineDetector, Tier1Detector, resolve_overlaps
from .spec import load_entities
from .tier2 import NullTier2, Tier2Backend
from .types import EntitySpec, Example, Finding, Policy

__all__ = [
    "Detector",
    "RegexBaselineDetector",
    "Tier1Detector",
    "resolve_overlaps",
    "apply_policy",
    "block_if_detected",
    "log_safe",
    "spec_policy",
    "Rejected",
    "Tier2Backend",
    "NullTier2",
    "load_entities",
    "EntitySpec",
    "Example",
    "Finding",
    "Policy",
]
