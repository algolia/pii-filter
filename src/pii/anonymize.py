"""The anonymizer half: apply a policy to text given its findings.

Detection (detect.py) answers "what and where"; this answers "what to do".
Mirrors the Go policy.Apply: reject drops the whole record (raises Rejected),
redact/hash/tokenize substitute right-to-left so offsets stay valid, flag/allow
leave the text untouched.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping

from .types import Finding, Policy


class Rejected(Exception):
    """Raised when a finding's policy is REJECT: the record must be dropped."""

    def __init__(self, entity: str) -> None:
        super().__init__(f"record rejected: {entity}")
        self.entity = entity


PolicyMap = Mapping[str, Policy] | Callable[[str], Policy]


def _action_for(policy: PolicyMap, entity: str) -> Policy:
    if callable(policy):
        return policy(entity)
    return policy.get(entity, Policy.REJECT)


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def apply_policy(text: str, findings: list[Finding], policy: PolicyMap) -> str:
    """Return the transformed text, or raise Rejected if any finding rejects.

    ``policy`` is either a mapping entity->Policy (default REJECT for unlisted) or
    a callable entity->Policy.
    """
    for f in findings:
        if _action_for(policy, f.entity) == Policy.REJECT:
            raise Rejected(f.entity)

    out = text
    for f in sorted(findings, key=lambda f: f.start, reverse=True):
        action = _action_for(policy, f.entity)
        if action == Policy.REDACT:
            repl = f"[{f.entity}]"
        elif action == Policy.HASH:
            repl = f"[{f.entity}:{_short_hash(f.value)}]"
        elif action == Policy.TOKENIZE:
            repl = f"[{f.entity}_TOKEN]"
        else:  # FLAG, ALLOW: leave in place
            continue
        out = out[: f.start] + repl + out[f.end :]

    return out


def spec_policy() -> dict[str, Policy]:
    """Per-entity default_policy from the spec (cards/IBANs rejected, contact
    details and national identifiers redacted, IPs flagged). Default for unlisted
    entities is REJECT."""
    return {
        "EMAIL": Policy.REDACT,
        "FR_NIR": Policy.REDACT,
        "FR_TAX_ID": Policy.REDACT,
        "FR_SIRET": Policy.REDACT,
        "FR_SIREN": Policy.REDACT,
        "ES_DNI": Policy.REDACT,
        "ES_NIE": Policy.REDACT,
        "PHONE": Policy.REDACT,
        "CREDIT_CARD": Policy.REJECT,
        "IBAN": Policy.REJECT,
        "IP": Policy.FLAG,
    }


def _redact_all(entity: str) -> Policy:
    return Policy.REDACT


# Built lazily on first use so importing pii stays cheap and side-effect-free;
# reused across calls so log_safe does not re-read the spec on the hot path.
_log_safe_detector: object | None = None


def log_safe(text: str, *, policy: PolicyMap | None = None) -> str:
    """Return ``text`` with Tier-1 structural identifiers replaced by typed masks.

    The one-call form of the log-safe telemetry recipe: detect Tier-1 entities and
    redact every one, so ``"mail me at a@example.org"`` becomes ``"mail me at [EMAIL]"``.
    Meant for the logging/analytics path, so it is a pure, deterministic, no-I/O
    function that **never raises** -- a logging helper that throws is worse than
    useless. Non-string input is coerced (``None`` -> ``""``); any policy that would
    REJECT is downgraded to REDACT here, because masking is log_safe's job and
    dropping the line is not.

    Limitation, stated plainly: this masks **structural identifiers only** -- EMAIL,
    PHONE, CREDIT_CARD, IBAN, IP and the FR/ES national identifiers (regex +
    checksum, Tier-1, see spec/entities.yaml). It does not detect names,
    addresses, or health/special-category semantics, so it reduces exposure; it does
    **not** "remove PII". See the README Limitations section.

    Args:
        text: The string to mask. Non-strings are coerced; ``None`` becomes ``""``.
        policy: Optional per-entity policy, same Mapping/Callable shapes ``apply_policy``
            accepts (e.g. ``{"EMAIL": Policy.HASH}`` to hash instead of redact). Unlisted
            entities and any REJECT resolve to REDACT. Defaults to redact-everything.

    Returns:
        The masked string, safe to log. Idempotent: ``log_safe(log_safe(x)) == log_safe(x)``.
    """
    global _log_safe_detector
    if not isinstance(text, str):
        text = "" if text is None else str(text)

    base = _redact_all if policy is None else policy

    def _never_reject(entity: str) -> Policy:
        action = _action_for(base, entity)
        return Policy.REDACT if action == Policy.REJECT else action

    if _log_safe_detector is None:
        from .detect import Tier1Detector

        _log_safe_detector = Tier1Detector()

    findings = _log_safe_detector.detect(text)  # type: ignore[attr-defined]
    return apply_policy(text, findings, _never_reject)


# Same lazy pattern as _log_safe_detector: built once, reused so the gate does
# not re-read the spec on every call.
_gate_detector: object | None = None


def block_if_detected(text: str, *, policy: PolicyMap | None = None) -> str:
    """Gate ``text`` before it leaves for a third-party LLM: treat or refuse.

    The one-call, documented-contract form of the README pre-LLM gate recipe
    (detect Tier-1 entities, then ``apply_policy`` with :func:`spec_policy`). Under
    the hood it is exactly::

        apply_policy(text, Tier1Detector().detect(text), policy or spec_policy())

    THE CONTRACT:

    - If any finding maps to ``Policy.REJECT`` (cards and IBANs under the default
      spec policy), it **raises** :class:`Rejected` carrying the entity type. The
      caller must not forward the text -- that raise is the whole point of the gate.
    - Otherwise it **returns the treated text**: contact details and national
      identifiers redacted, IPs left
      in place but flagged, per the resolved policy.
    - Unlike :func:`log_safe`, raising is the *feature* here, not a failure mode:
      this function never swallows ``Rejected`` and never downgrades REJECT to
      REDACT. A gate that lets card data through is not a gate.
    - Deterministic and pure: no I/O, no clock, no randomness. Same input, same
      outcome.
    - Input must be ``str``. Non-string input raises :class:`TypeError` immediately
      -- a gate that silently coerces (``None`` -> ``""``, ``12345`` -> ``"12345"``)
      is a hole through which un-gated data reaches the provider.

    Limitation, stated plainly: this gates **structural identifiers only** -- EMAIL,
    PHONE, CREDIT_CARD, IBAN, IP and the FR/ES national identifiers (regex +
    checksum, Tier-1, see spec/entities.yaml). It does **not** detect
    health/special-category semantics, names, or addresses. It is one layer in the
    Swiss-cheese model, not a health-data posture on its own: that needs this gate
    **plus** routing/scoping decisions. See the README Limitations section.

    Args:
        text: The string to gate. Must be ``str``; anything else raises ``TypeError``.
        policy: Optional per-entity policy, the same Mapping/Callable shapes
            :func:`apply_policy` accepts (unlisted entities default to REJECT for a
            mapping). Defaults to :func:`spec_policy` (cards/IBAN REJECT, contact
            details and national identifiers REDACT, IP FLAG).

    Returns:
        The treated text, safe to forward, when nothing rejects.

    Raises:
        TypeError: if ``text`` is not a ``str``.
        Rejected: if any finding maps to ``Policy.REJECT``; ``exc.entity`` names it.
    """
    global _gate_detector
    if not isinstance(text, str):
        raise TypeError(f"block_if_detected requires str, got {type(text).__name__}")

    active_policy = spec_policy() if policy is None else policy

    if _gate_detector is None:
        from .detect import Tier1Detector

        _gate_detector = Tier1Detector()

    findings = _gate_detector.detect(text)  # type: ignore[attr-defined]
    return apply_policy(text, findings, active_policy)
