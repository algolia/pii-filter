# `algolia/pii-filter` — a shared PII detection and policy library

Status: **design document**. Describes the shared spec both implementations
follow.

## Summary

A single, versioned PII capability for two kinds of consumers: ingestion
pipelines (Go) and inference-time services (Python). It detects
personal data, reports it as structured findings, and applies a configurable
policy (reject / redact / hash / tokenize / flag). It is built as a **shared spec
plus two native libraries**, not one cross-language binary.

## Motivation

PII handling tends to be bespoke and per-project:

- Ingestion pipelines may redact credentials but rarely detect PII per record,
  so emails, phone numbers and names can flow through to downstream stores.
- Inference-time services (conversation memory, model output) face the same
  data and usually have no shared tool for it.

Both want the same primitive. Reimplementing it twice guarantees drift and uneven
coverage. A shared capability with one spec and one test corpus fixes that.

## Non-goals

- **Not a compliance guarantee.** Regex and NER are tripwires, not proofs. This
  library reduces exposure; it does not certify a dataset PII-free.
- **Not a replacement for "do not fetch."** The strongest control remains never
  ingesting personal data in the first place. This library is defense in depth
  behind that.

## Architecture: shared spec, two native libraries

Go and Python cannot share a library directly. Three options exist; we recommend
the first and use the second only for the ML tier.

| Option | Shape | Use |
|--------|-------|-----|
| **Shared spec + native impls** | One versioned spec (entity types, regexes, validators, policies) + a golden test corpus; Go and Python each implement it | **Default.** No runtime coupling, idiomatic both sides, spec + tests prevent drift |
| **Service** | One implementation behind HTTP/gRPC | ML tier only, or low-QPS callers. Fatal on the ingestion hot path (per-record network hop) |
| **FFI / WASM core** | One Rust core, PyO3 + cgo/WASM bindings | Escalation only, if bitwise-identical behavior is ever required. Significant ownership cost |

### The single source of truth

A language-neutral package:

```
spec/
  entities.yaml      # entity types, regexes, validators, default policies
  corpus/            # golden test cases: input -> expected findings
    emails.jsonl
    phones.jsonl
    names.jsonl
    ...
```

Both the Go and Python implementations are tested against `spec/corpus`. A change
to detection behavior is a change to the corpus first. This is what keeps two
implementations honest.

## Two tiers of detection

### Tier 1 — deterministic (structured identifiers)

Emails, phone numbers, credit cards (with Luhn check), IBANs, IP addresses.
Regex plus checksum. Identical logic in both languages, cheap to maintain,
in-process, fast.

Since 0.2.0 it also holds national identifiers with a public check: the French
NIR (social security number, mod-97 key with Corsica's 2A/2B read as 19/18), the
French numero fiscal (first digit 0-3, first ten digits mod 511 equal the last
three), and the Spanish DNI and NIE (mod-23 control letter, the NIE's X/Y/Z read
as 0/1/2). SIREN and SIRET are Tier 1.5 (below). When two detectors claim the
same span, the higher score wins, then the earlier entity in `spec/entities.yaml`;
the national identifiers are listed before PHONE and CREDIT_CARD for that reason.

For CREDIT_CARD and IBAN a regex match is a candidate run, not the span. A card
is the longest Luhn/IIN-valid 13-19-digit window starting at a digit group (a
window shorter than the run must be card-shaped). A grouped IBAN that fails as a
whole is cut back to its country's length. Scanning resumes after the reported
span, and both languages apply the same rule (`card_spans`/`iban_spans` in
`src/pii/validators.py`, `cardWindows`/`ibanSpan` in `detectors.go`).

SSNs are deliberately **not** in this set. A US SSN has no checksum (the SSA
randomized assignment in 2011), so a bare regex is high-false-positive and would
undermine the calibrated-precision story this tier rests on. It belongs to a
later context-gated detector (regex + mandatory nearby keyword, Presidio-style),
not the unconditional Tier-1 set. See `docs/research-deterministic-validators.md`.

Both Go and Python implement Tier 1 natively from the shared spec.

### Tier 1.5 — keyword-gated deterministic entities

Some identifiers have a checksum too weak to stand alone: a 9-digit number passes
Luhn one time in ten, so a bare SIREN detector would fire on order numbers. Such an
entity sets `requires_context: true` in `spec/entities.yaml`, with a
`context_keywords` list and a `context_window` (characters before the match). The
Tier-1 detector reports a validated match only when one of the keywords, as a whole
word, lies whole inside that window: the window is the `context_window` characters
just before the match, so a keyword that starts before it does not count. Combining
marks are dropped, so a keyword typed decomposed (NFD) matches too. Keywords match case-insensitively and
accent-insensitively (`NUMÉRO`, `numero` and `Numéro` are one keyword) through an
explicit fold table kept identical in `src/pii/context.py` and `context.go`; the Go
window counts runes, so both languages search the same text.

The gate narrows where a detector fires; it does not make it probabilistic.
Findings keep `tier: 1` and the checksum score. The schema of the spec file is
`spec/schema/entities.schema.json` (keywords without `requires_context` are
rejected, and so is a gate without keywords or a window).

**Dev-tool text is pass-through by contract.** Structured-but-non-personal tokens
common in dev-session output must produce zero findings: code-identifier contexts
(`.Method()` calls, CamelCase symbols), public paths (`go.mod`/import paths, repo
and install URLs), month tokens in dates, git author/shortlog lines and commit
SHAs, semantic versions, and arXiv identifiers (`NNNN.NNNNN`). A detector that
fires on these regresses precision. This contract is locked by the golden corpus
(`corpus/dev_tooling.jsonl`), gated in both languages by
`test_tier1_exactly_matches_corpus` (Python) and `TestCorpus` (Go). The arXiv case
is the one that required a validator guard: `NNNN.NNNNN` passes the digit-count
phone heuristic, so the phone validator rejects it explicitly in both languages.

**Optional libphonenumber-backed phone validation (Python only).** Phone is the
lowest-precision Tier-1 entity: its deterministic validator gates on an E.164
digit count (9-15) and "not a dotted quad", which accepts digit strings that are
not dialable. Python exposes an optional `phone` extra
(`pip install "algolia-pii[phone]"`); with it installed,
`Tier1Detector(strict_phone=True)` layers Google's libphonenumber
`is_valid_number` on top of the heuristic, rejecting impossible national numbers
and unassigned area codes. The extra is genuinely optional: detection never
hard-requires it, and it only ever raises precision (a number the heuristic
rejects stays rejected; a number that cannot be parsed region-free keeps the
heuristic's decision).

This is a deliberate **Go/Python asymmetry**: Go stays on the digit-count
heuristic (no native libphonenumber, and the binary-size / maintenance cost is not
justified for the lowest-precision entity). To keep the two implementations
exact-matching on the golden corpus, the extra is **off by default** — the default
detector both languages score against uses the deterministic heuristic, so the
corpus result is environment-independent. The precision gain is proven in
`tests/test_phone_validation.py` (skipped when the extra is absent), not by
diverging the shared corpus.

### Tier 2 — probabilistic (contextual)

Names, addresses, handles, free-text PII. Requires NER / ML.

**SOTA differs sharply by language.** Python owns the ecosystem (Microsoft
Presidio's analyzer/anonymizer split, spaCy and transformer NER, GLiNER). Go has
no native transformer-NER equivalent.

Therefore:

- **Python** implements Tier 2 directly (wrap or follow Presidio).
- **Go** reaches Tier 2 through an interface, choosing per latency budget: a small
  inference service, ONNX via cgo, or a cloud DLP API. Go does not pretend to do
  native NER.

## Detection and policy are separate

Detection returns structured findings; policy decides what to do. This mirrors
Presidio's analyzer/anonymizer split.

```
Finding {
  entity:     "EMAIL" | "PHONE" | "PERSON" | "ADDRESS" | ...
  span:       [start, end]
  score:      0.0 - 1.0       // 1.0 for deterministic detectors
  tier:       1 | 2
}

Policy (per call, caller-driven):
  reject    // drop the record, alert     <- default for public indices
  redact    // replace span with a mask
  hash       // stable hash (for joins without raw value)
  tokenize  // reversible token (vault-backed)
  flag      // pass through, annotate for human review
  allow      // explicit allowlist (for example, a public contact address)
```

"Counts / metadata" (the text -> counts use case) is just findings aggregated:
per-entity counts, hotspots, a `hasPII` boolean.

## GDPR special categories (Article 9)

Race, religion, health, political opinion, sexual orientation, biometric, genetic,
union membership. These are **not regex-detectable and only weakly NER-detectable**,
with high false-positive rates. Reliable detection is an open problem.

Scope honestly:

- **v1**: identifiers — Tier 1 plus names/addresses via Tier 2.
- **Article 9**: `flag` for human review, never an automated-removal promise.

A library that *claims* to remove special-category PII is more dangerous than one
that says "I find identifiers; a human reviews the rest." Sell the tripwire as a
tripwire.

## Consumers

**Ingestion pipelines (Go).** Scrubbing at ingestion time runs on the hot path,
once per record, so it must be in-process: a per-record network hop to a PII
service costs more than the detection itself. The Go library serves that
in-process path, as a config-driven policy step before records are written.

**Inference-time services (Python).** Scrub user input before it is stored,
or model output before it is returned. Low QPS, so the Python library
in-process (or a small service) is fine.
