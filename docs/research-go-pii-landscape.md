# PII Detection in Go — Landscape & How Go Reaches Tier-2

> Design note (2026), written from first principles and canonical sources rather
> than a full survey: treat the library recommendations as starting points to
> verify. It grounds `tier2.go` (the `Tier2Backend` seam).

## The shape of the problem

Go is excellent for Tier-1 deterministic detection — regex (RE2) plus checksums
(Luhn, IBAN mod-97) run in-process at ingestion speed with no model. Go is weak for
Tier-2 probabilistic NER (names, addresses, free-text PII): there is **no native
Go transformer-NER ecosystem** comparable to Python's Presidio/spaCy/HuggingFace
stack. So a Go service must *reach out* for Tier-2.

A second, RE2-specific constraint shapes Tier-1 itself: **RE2 has no lookbehind or
lookahead.** The spec regexes (`spec/entities.yaml`) use `(?<!\d)` / `(?!\d)`; the
Go detectors cannot consume those strings verbatim and instead reproduce the same
*behavior* with `\b` and in-code boundary checks (see `phoneDetector`). The golden
corpus is therefore the cross-language contract, not the regex source.

## Tier-1 tooling that exists in Go

- **Luhn / IBAN mod-97 / IPv4 octet checks** — trivial to hand-write (this repo
  does), no dependency needed.
- **`net.ParseIP`** (stdlib) — authoritative IPv4/IPv6 parsing, including `::`
  expansion; use it to confirm regex candidates rather than trusting a pattern.
- **`github.com/nyaruka/phonenumbers`** — a Go port of Google's libphonenumber;
  `IsValidNumber` checks allocated ranges, far stronger than a digit-count regex.
  Worth adopting if phone precision matters (our current Tier-1 uses a
  digit-count + boundary + not-IP-shape tripwire instead).
- **`github.com/nbutton23/zxcvbn-go`**, assorted `go-... /pii` repos — small,
  uneven maintenance; treat as references, not dependencies.

## Tier-2: three ways for Go to reach NER, by latency budget

| Option | What | Latency | Ops | Cost shape | Fit for ingestion hot path |
|---|---|---|---|---|---|
| **Python sidecar** | Presidio+GLiNER in a co-located service over gRPC/HTTP | network hop (sub-ms LAN + model ~15–200ms) | run + scale a service | compute you own | OK if co-located + batched; a remote hop per record is fatal |
| **ONNX Runtime via cgo** | export GLiNER to ONNX, call `onnxruntime` C API (e.g. yalue/`onnxruntime_go`) | in-process, no network | cgo build, ship the model + runtime | compute you own | best raw throughput; heaviest build/integration |
| **Cloud DLP API** | GCP Sensitive Data Protection / AWS Comprehend PII + Macie / Azure AI Language PII | network hop + provider latency | none (managed) | **per-request, scales with volume** | convenient; per-record cost + egress + a hard dependency make it poor for bulk ingestion |

### Recommendation

- **Tier-1 stays pure Go, in-process** (this repo). No network, full ingestion
  throughput. This is where an ingestion-time scrubbing step gets its value.
- **Tier-2 is opt-in behind `Tier2Backend`.** For the ingestion hot path, prefer a
  **co-located Python sidecar (Presidio + GLiNER v1)** with request batching, or an
  **ONNX-in-process** path if the cgo/build cost is acceptable and latency is
  critical. Reserve **cloud DLP** for low-volume / inference-time callers, not bulk
  reindex.
- Do **not** put a per-record network hop on a bulk ingestion path. Scope Tier-2 to
  fields likely to hold PERSON/ADDRESS, and run it asynchronously where possible.

## Calibration

The Python SOTA research (see `research-python-pii-sota.md`) shows Tier-2 NER is
~0.55 cross-domain F1 at best — so the Go cost of reaching it should be matched to
that modest payoff. A heavy ONNX/cgo integration is only worth it where Tier-2
recall genuinely matters and volume forbids a service. When in doubt, ship Tier-1
in Go and a sidecar for Tier-2.

## Sources

- https://pkg.go.dev/net#ParseIP — Go stdlib authoritative IP parsing (IPv4/IPv6, `::`).
- https://pkg.go.dev/regexp — Go RE2 engine; documents the absence of lookaround/backreferences.
- https://github.com/google/re2/wiki/Syntax — RE2 supported syntax (no lookbehind/lookahead), the constraint behind the corpus-as-contract design.
- https://github.com/nyaruka/phonenumbers — Go port of libphonenumber (`IsValidNumber`).
- https://github.com/microsoft/presidio — the Python framework a Go sidecar would wrap (see Python SOTA doc).
- https://cloud.google.com/sensitive-data-protection/docs — GCP managed DLP (infoType detection) as a cloud Tier-2 option.
- https://docs.aws.amazon.com/comprehend/latest/dg/how-pii.html — AWS Comprehend PII detection API.
- https://learn.microsoft.com/azure/ai-services/language-service/personally-identifiable-information/overview — Azure AI Language PII.
- https://onnxruntime.ai/docs/get-started/with-go.html — ONNX Runtime usage from Go (cgo) for an in-process NER path.
