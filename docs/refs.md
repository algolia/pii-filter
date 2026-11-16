# References & Bibliography

Consolidated bibliography for `algolia/pii-filter`, grouped by topic. Per-document source
lists live in each `docs/research-*.md`; this is the merged index. Entries reflect
what was true when the research ran (2026); re-verify primaries before freezing a
compliance-sensitive release.

## Deterministic validators (Tier-1)

- [Luhn algorithm](https://en.wikipedia.org/wiki/Luhn_algorithm) — mod-10 check-digit steps and position.
- [Payment card number](https://en.wikipedia.org/wiki/Payment_card_number) — IIN/BIN prefixes and lengths per network.
- [neaPay BIN/IIN ranges](https://neapay.com/post/bin-list-range-for-mastercard-visa-amex-diners-discover-jcb-cup_94.html) — Mastercard 2-series, Discover sub-ranges, UnionPay, JCB.
- [IBAN (ISO 13616)](https://en.wikipedia.org/wiki/International_Bank_Account_Number) — structure and ISO 7064 mod-97 validation.
- [IBAN per-country length registry](https://www.iban.com/structure) — 89-country length table.
- [Chunked mod-97 worked example](https://medium.com/@matlabb/iban-structure-and-mod-97-validation-algorithm-719e3d4db5f2) — avoiding bigint overflow.
- [Social Security number](https://en.wikipedia.org/wiki/Social_Security_number) — structure, invalid ranges, Woolworth number, ITIN overlap.
- [SSA randomization FAQ](https://www.ssa.gov/employer/randomizationfaqs.html) — 2011 randomization; geographic heuristics dead.
- [E.164](https://en.wikipedia.org/wiki/E.164) — phone format, ≤15-digit rule, country codes.
- [libphonenumber](https://libphonenumber.org/) — validity vs possibility for phone FP mitigation.
- [RFC 1918](https://datatracker.ietf.org/doc/html/rfc1918) — IPv4 private ranges.
- [RFC 4291](https://www.rfc-editor.org/rfc/rfc4291) — IPv6 addressing, `::`, reserved prefixes.
- [NPI check digit](https://www.eclaims.com/articles/how-to-calculate-the-npi-check-digit/) — modified Luhn (`80840` prefix).
- [French NIR/INSEE key](https://compteassurance.com/calculer-la-cle-de-securite-sociale-nir/) — mod-97-complement.

## Python PII SOTA (Tier-2 NER)

- [Microsoft Presidio](https://github.com/microsoft/presidio) — MIT framework; analyzer/anonymizer; recognizers.
- [Presidio supported entities](https://github.com/microsoft/presidio/blob/main/docs/supported_entities.md) — built-in recognizers + detection method.
- [Presidio transformers NLP engine](https://microsoft.github.io/presidio/analyzer/nlp_engines/transformers/) — HF NER backends.
- [Presidio CHANGELOG](https://raw.githubusercontent.com/microsoft/presidio/main/CHANGELOG.md) — SlimSpacyNlpEngine, GLiNER/ONNX, medical NER.
- [presidio-analyzer on PyPI](https://pypi.org/project/presidio-analyzer/) — release cadence, MIT.
- [Presidio + GLiNER sample](https://microsoft.github.io/presidio/samples/python/gliner/) — `GlinerRecognizer` integration.
- [Independent cross-domain benchmark (Sikkema, 2026)](https://albertsikkema.com/python/security/privacy/2026/06/01/benchmarking-open-source-pii-detection.html) — ~0.55 avg F1; differences not significant.
- [nvidia/gliner-PII](https://huggingface.co/nvidia/gliner-PII) — params, types, license.
- [Isotonic DeBERTa ai4privacy](https://huggingface.co/Isotonic/deberta-v3-base_finetuned_ai4privacy_v2) — CC-BY-NC (avoid for product).
- [Piiranha v1](https://huggingface.co/iiiorg/piiranha-v1-detect-personal-information) — CC-BY-NC-ND (blocked).
- [GLiNER2 (arXiv)](https://arxiv.org/html/2507.18546v1) — Apache 2.0, multi-task.
- [Fine-tuned GLiNER on EHR (arXiv)](https://arxiv.org/abs/2510.19346) — F1 0.980 in-domain.
- ["Unmasking the Reality of PII Masking Models" (arXiv)](https://arxiv.org/pdf/2504.12308) — inflated-claims critique.

## GDPR Article 9

- [CJEU: special-category data by inference](https://www.insideprivacy.com/eu-data-protection/special-category-data-by-inference-cjeu-significantly-expands-the-scope-of-article-9-gdpr/) — inferred Art.9 data is itself Art.9 (the design trap).
- [ICO: what is special category data](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/special-category-data/what-is-special-category-data/) — the eight categories.
- [GDPR Article 9 (text)](https://gdpr-info.eu/art-9-gdpr/) — primary source.

## Go landscape (Tier-2 reach)

- [Go `net.ParseIP`](https://pkg.go.dev/net#ParseIP) — authoritative IP parsing.
- [Go `regexp`](https://pkg.go.dev/regexp) — RE2; no lookaround (corpus-as-contract rationale).
- [RE2 syntax](https://github.com/google/re2/wiki/Syntax) — supported/unsupported constructs.
- [nyaruka/phonenumbers](https://github.com/nyaruka/phonenumbers) — Go libphonenumber port.
- [GCP Sensitive Data Protection](https://cloud.google.com/sensitive-data-protection/docs) — managed DLP.
- [AWS Comprehend PII](https://docs.aws.amazon.com/comprehend/latest/dg/how-pii.html) — managed PII detection.
- [Azure AI Language PII](https://learn.microsoft.com/azure/ai-services/language-service/personally-identifiable-information/overview) — managed PII detection.
- [ONNX Runtime with Go](https://onnxruntime.ai/docs/get-started/with-go.html) — in-process NER via cgo.

## In this repository

- [`SPEC.md`](../SPEC.md) — the design RFC this library implements.
- [`docs/research-deterministic-validators.md`](research-deterministic-validators.md)
- [`docs/research-python-pii-sota.md`](research-python-pii-sota.md)
- [`docs/research-go-pii-landscape.md`](research-go-pii-landscape.md)
