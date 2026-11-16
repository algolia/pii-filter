# Integrating `algolia/pii-filter` (Tier-1)

How to depend on the library from a Go or Python project today. It ships **Tier-1**
(deterministic identifiers: EMAIL, PHONE, CREDIT_CARD, IBAN, IP, and since 0.2.0
the French and Spanish national identifiers FR_NIR, FR_TAX_ID, FR_SIREN,
FR_SIRET, ES_DNI, ES_NIE). Tier-2
(PERSON / ADDRESS via NER) is an interface only, not yet model-backed —
see [Tier boundary](#what-you-get-today) below.

## Go (in-process, ingestion-time)

The Go module is the repo root: `github.com/algolia/pii-filter`. No runtime files, no
network hop — detection and policy run in-process.

```bash
go get github.com/algolia/pii-filter@v0.2.0   # or @latest
```

```go
import "github.com/algolia/pii-filter"

findings := pii.DefaultAnalyzer().Analyze(record)   // all Tier-1 detectors
clean, err := pii.SpecPolicy().Apply(record, findings)
if errors.Is(err, pii.ErrRejected) {
    // a reject-policy entity (card / IBAN) was found -> drop the record + alert
    return
}
// clean has email/phone masked, IPs left in place (flag) per the spec defaults
```

Metadata-only use (the "text -> counts" view), no mutation:

```go
findings := pii.DefaultAnalyzer().Analyze(record)
counts := pii.Counts(findings)   // map[Entity]int
has := pii.HasPII(findings)      // bool
```

## Python (inference-time, model input/output)

Package `algolia-pii`, imported as `pii`. The entity spec ships **inside the
wheel**, so a plain install is self-contained — no checkout required.

```bash
pip install "git+https://github.com/algolia/pii-filter@v0.2.0"
```

```toml
# or poetry, in pyproject.toml
[tool.poetry.dependencies]
algolia-pii = { git = "https://github.com/algolia/pii-filter.git", tag = "v0.2.0" }
```

```python
from pii import Tier1Detector, apply_policy, spec_policy, Rejected

text = "reach me at jane.doe@example.com"
findings = Tier1Detector().detect(text)        # list[Finding]
try:
    clean = apply_policy(text, findings, spec_policy())
except Rejected:
    ...   # a reject-policy entity was found -> drop it
```

Pin a release tag (as above) rather than a branch.

### The `bench` extra (matplotlib is optional since 0.2.0)

The core install depends on `pyyaml` only. `import pii`, detection and policy never
import matplotlib, so a production image stays small. The bench harness
(`pii.bench`, the `pii-bench` CLI, the README charts) needs the `bench` extra:

```bash
pip install "algolia-pii[bench] @ git+https://github.com/algolia/pii-filter@v0.2.0"
poetry install --extras bench          # inside a checkout of this repo
```

Without it, `import pii.bench` raises an `ImportError` that names the extra.
Upgrading from 0.1.0: a consumer that used `pii.bench` must add the extra; one that
only detects and redacts needs no change and drops matplotlib and numpy from its
install.

## What you get today

| Entity | Tier | Detection | Default policy |
|---|---|---|---|
| EMAIL | 1 | regex | redact |
| PHONE | 1 | regex + digit-count, not-an-IP; grouped or compact E.164 | redact |
| CREDIT_CARD | 1 | regex + Luhn + IIN + length, card windows inside longer runs | reject |
| IBAN | 1 | regex + mod-97, compact or 4-char groups, any case | reject |
| IP | 1 | regex + octet range | flag |
| FR_NIR | 1 | regex + mod-97 key (Corsica 2A/2B) | redact |
| FR_TAX_ID | 1 | regex + first digit 0-3, mod 511 | redact |
| FR_SIREN | 1.5 | regex + Luhn, keyword before it | redact |
| FR_SIRET | 1.5 | regex + Luhn (La Poste digit sum), keyword before it | redact |
| ES_DNI | 1 | regex + mod-23 letter | redact |
| ES_NIE | 1 | regex + X/Y/Z prefix, mod-23 letter | redact |
| PERSON | 2 | NER — **not shipped** (interface only) | flag |
| ADDRESS | 2 | NER — **not shipped** (interface only) | flag |

Tier 1.5 findings are ordinary Tier-1 findings (`tier` 1, score 1.0); the gate only
decides whether the number is reported. FR_SIREN and FR_SIRET need one of their
`context_keywords` (`SIREN`, `SIRET`, `RCS`, `numéro d'entreprise`, `company
number`, …, the full list is in `spec/entities.yaml`) to lie whole inside the 40
characters before the number. A company number without one is not reported. Some
keywords are generic (`rcs`, `business id`, `company number`). After a keyword, a
Luhn-valid 14-digit number starting 30, 36 or 38 (Diners-shaped) is reported as
FR_SIRET (`redact`), not CREDIT_CARD (`reject`); pass `{"FR_SIRET":
Policy.REJECT}` (Go: a policy with `ActionReject` for `EntityFRSIRET`) if you
need reject-on-card semantics there.

**New redactions when upgrading from 0.1.0.** FR_NIR, FR_TAX_ID and ES_DNI are
not keyword-gated, so they also fire on lookalikes that earlier versions never
flagged (measured on 200,000 random strings each): about 0.09% of 13-digit
millisecond timestamps and French EAN-13 barcodes read as FR_TAX_ID, about 1.0%
of 15-digit numbers starting 1/2/7/8 as FR_NIR, about 3.9% of "8 digits +
capital letter" codes as ES_DNI. To opt out, map the entity to `allow` (or
`flag`) in your policy, or keyword-gate the findings downstream.

If your project needs names or addresses, Tier-1 will **not** find them yet. Go
reaches Tier-2 through the `Tier2` interface; Python through `Tier2Backend`. Both
default to a no-op (`NullTier2`) until a model is wired in.

## Policy actions

Detection answers *what and where*; policy answers *what to do*. Same six actions
both languages, configurable per entity:

- `reject` — drop the record and signal it (Go: `ErrRejected`; Python: `Rejected`). Safe default for a public index.
- `redact` — replace the span with a typed mask, `[EMAIL]`.
- `hash` — stable short hash, `[EMAIL:9f86d081]` (join without the raw value).
- `tokenize` — typed placeholder, `[EMAIL_TOKEN]`. **Not reversible here** — a reversible token needs a vault.
- `flag` — leave the text untouched, report only (audit mode).
- `allow` — explicit allowlist (e.g. a public contact address).

`SpecPolicy()` / `spec_policy()` returns the per-entity defaults from the spec
(cards & IBANs reject, email, phone and the national identifiers redact, IP flag;
reject for anything else).
Build your own with `RejectAll()` / `RedactAll()` / `FlagAll()` (Go) or a plain
`{entity: Policy}` map (Python).

## The `Finding` shape

Identical fields across languages (byte offsets, `tier` marks how it was found):

```
Finding { entity, start, end, score, tier, value/text }
```

Tier-1 findings score `1.0`. Tier-2 findings carry the model's confidence.

## Honest limits (read before you trust it)

- **Not a compliance guarantee.** Regex + checksum is a high-precision tripwire
  for identifiers, not a proof a dataset is PII-free. The strongest control
  remains never ingesting personal data.
- **Calibrated on a small, clean corpus** (n=355 examples, 207 spans). Span-level
  precision/recall is `1.00` point estimate, `0.98` overall Wilson floor and
  `0.80`-`0.87` per national-ID entity (15-25 spans each). That is a tripwire demonstrated on
  curated data, not a field-accuracy claim. See the bench in [`../README.md`](../README.md).
- **A valid checksum proves shape, not issuance.** Nothing here looks a number up,
  and the national-ID checks are weak (a random number of the right shape passes
  the NIR key 1 time in 100, the DNI letter 1 in 23).
- **Python and Go agree on the corpus, not everywhere.** Cards and IBANs agree
  on the fuzz runs; known pre-existing PHONE disagreements remain (about 20 per
  20,000 random strings, more on strings built from digit groups and `+` signs).
- **Compact national phone numbers are not detected** (`0` plus 9-10 digits, no
  separator): about 9% of random 10- and 11-digit ids share that shape.
- **GDPR Article 9** (special categories) is intentionally out of scope — never an
  inference model. See [`../SPEC.md`](../SPEC.md).

## Verify your wiring

```bash
# Go
go test github.com/algolia/pii-filter/...
# Python
python -c "from pii import Tier1Detector; print(Tier1Detector().detect('a@example.com'))"
```
