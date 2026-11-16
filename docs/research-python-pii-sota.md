# State of the Art: PII Detection in Python (2025-2026)

> Research output (2026). Grounds the Tier-2 (NER) roadmap for the Python side.
> Calibration note up front: every "0.97+ F1" figure in this space is
> **in-distribution** on synthetic test sets; the only independent cross-domain
> benchmark found puts every open-source tool below ~0.55 average F1. Treat
> vendor accuracy claims as ceilings, not expectations.

## 1. Microsoft Presidio

**Version & license:** `presidio-analyzer` / `presidio-anonymizer` v2.2.x (2026),
**MIT**, actively maintained. Install: `pip install presidio-analyzer presidio-anonymizer`.

**Architecture (analyzer/anonymizer split):**
- **AnalyzerEngine**: `RecognizerRegistry` + `NlpEngine` (tokenization + NER) +
  `ContextAwareEnhancer` (keyword-proximity score boost). Output: typed spans with
  confidence + char offsets.
- **AnonymizerEngine**: pluggable operators `replace`, `redact`, `mask`,
  `encrypt`, `hash`, `custom`.
- Adjacent: `presidio-image-redactor` (incl. DICOM), `presidio-structured`
  (DataFrames/JSON).
- Recent additions for a Tier-2 design: `SlimSpacyNlpEngine` (drop spaCy NER,
  delegate to GLiNER), `HuggingFaceNerRecognizer`, ONNX backend for GLiNER,
  configurable regex timeout.

**Built-in recognizers:** CREDIT_CARD, CRYPTO, DATE_TIME, EMAIL_ADDRESS,
IBAN_CODE, IP_ADDRESS, MAC_ADDRESS, NRP (nationality/religion/political — pattern),
LOCATION, PERSON, PHONE_NUMBER, MEDICAL_LICENSE, URL; US set (SSN, ITIN, NPI,
passport, bank, driver license, MBI); 40+ country recognizers (UK NHS/NINO, DE tax
ID, ES, IT, PL PESEL, IN Aadhaar/PAN, KR RRN, CA SIN, SE, ZA, …); opt-in medical
NER (disease, medication, procedure, …).

**NER backends:** spaCy default (`en_core_web_lg` / `_trf`); Stanza; any HF
token-classification model; first-class GLiNER via `GlinerRecognizer`. No
transformer model ships by default — the user configures it.

## 2. GLiNER and Transformer-Based PII NER

| Model | Params | License | In-dist F1 | Notes |
|---|---|---|---|---|
| `Isotonic/deberta-v3...ai4privacy_v2` | 0.2B | **CC-BY-NC-4.0** | 0.9757 | 54 types; non-commercial |
| `iiiorg/piiranha-v1` (mDeBERTa) | ~0.3B | **CC-BY-NC-ND-4.0** | 0.9827 tok | 17 types/6 langs; blocked |
| `nvidia/gliner-PII` | 0.57B | NVIDIA Open + Apache 2.0 | 0.64–0.87 | 55+ types incl. PHI; GPU |
| `knowledgator/gliner-bi-large-v1.0` | 0.21B | **Apache 2.0** | ~0.535 avg | zero-shot; most stable; Presidio-ready |
| GLiNER2 `fastino/...PII-multi` | 0.205B | **Apache 2.0** | 0.478 avg | nested spans, multi-task |
| GLiNER Guard (Omni) | 0.21B | CC BY 4.0 | 0.844 avg dom | PII+safety; 193 req/s ONNX |

**Accuracy-inflation problem (load-bearing):** headline 0.97+ F1 comes from test
splits sharing the training distribution (ai4privacy synthetic). The one
independent cross-domain study (Sikkema, 2026; 4 datasets) reports avg F1:
Piiranha 0.542, GLiNER v1 0.535, Presidio 0.481, GLiNER v2 0.478, raw regex 0.171.
Pairwise differences **not statistically significant (p ≫ 0.10, n=4)**. Presidio's
pattern-based EMAIL beats every NER model (0.93–0.99) and is 8–11× faster on CPU.
Domain fine-tuning closes the gap (GLiNER on EHR → F1 0.980).

## 3. Entity-Type Reliability: NER vs Regex

- **Reliable via regex/checksum (use built-ins):** EMAIL (0.93–0.99, best of any
  method), CREDIT_CARD, SSN, IBAN, IP, passports, national IDs, crypto.
- **Moderate via NER:** PERSON (0.45–0.78 by domain; over-flags ORG/products; weak
  on non-Western names), ADDRESS/LOCATION (~0.48–0.68), DATE_TIME (pattern wins).
- **Low via any OSS tool:** PHONE in free text, credentials in prose, gender.

Regex owns structured PII; NER is mandatory for names/addresses/medical but treat
scores < 0.85 as low-confidence and expect ~0.55 cross-domain F1, not 0.97.

## 4. GDPR Article 9 Special-Category Data

Eight categories: racial/ethnic origin, political opinions, religious/philosophical
beliefs, trade-union membership, genetic, biometric, health, sex life/orientation.
**Health** is the only well-covered category (clinical models, Presidio opt-in
medical NER; reliable within clinical text, poor in prose). Religion/ethnicity/
political: only Presidio's pattern-based NRP (weak). Sexual orientation, sex life,
trade union, genetic/biometric in text: **no reliable OSS NLP tool** — almost
always implied, not labeled.

**The design trap:** the CJEU has ruled data "liable indirectly to reveal" Art.9
characteristics is itself Art.9 data, explicitly including NLP inference. *Building
a classifier that infers religion/orientation creates the very Art.9 processing
liability you set out to detect.* A best-effort lexical flag for explicit mentions
is defensible; an inference model is a legal hazard. The library must document this
incompleteness loudly and must not claim Art.9 "compliance coverage."

## Recommendation: WRAP vs BUILD for `algolia/pii-filter` Tier-2

- **WRAP — Presidio** as the framework backbone (best regex catalog, MIT,
  pluggable). Use `SlimSpacyNlpEngine`; keep the NER model configurable.
- **WRAP — GLiNER v1 (`knowledgator/gliner-bi-large-v1.0`, Apache 2.0)** as the
  default NER backend (best cross-domain stability, zero-shot, clean license,
  Presidio-wired).
- **AVOID for a shipped product:** ai4privacy DeBERTa (CC-BY-NC), Piiranha
  (CC-BY-NC-ND), nvidia/gliner-PII (non-OSI, heavy).
- **BUILD (not wrappable):** fine-tuning pipeline on Algolia synthetic data;
  confidence-calibration layer; Art.9 explicit-keyword recognizer (lexical only,
  documented incomplete, never inference); reversibility handling for Presidio's
  ~36% tokenizer-misalignment reconstruction failures.

```
text -> Presidio AnalyzerEngine
          |- RegexRecognizers (email, SSN, IDs)     <- WRAP built-ins
          |- GlinerRecognizer(gliner-bi-large-v1.0)  <- WRAP GLiNER v1 (Apache 2.0)
          |- MedicalNERRecognizer (opt-in)           <- WRAP
          \- Art9KeywordRecognizer (lexical)          <- BUILD, documented incomplete
       -> confidence filter (default ~0.7)
       -> AnonymizerEngine (replace/redact/hash)     <- WRAP
```

Performance: Presidio CPU ~15ms/text; GLiNER ~118–197ms (8–11× slower). For
high-throughput indexing, ONNX-export GLiNER and scope NER to fields likely to hold
PERSON/ADDRESS/MEDICAL rather than scanning whole documents.

## Sources

- https://github.com/microsoft/presidio — repo, MIT license, four-module architecture, maturity.
- https://github.com/microsoft/presidio/blob/main/docs/supported_entities.md — built-in recognizer/entity list with method + country coverage.
- https://microsoft.github.io/presidio/analyzer/nlp_engines/transformers/ — HuggingFace transformer NER backends.
- https://raw.githubusercontent.com/microsoft/presidio/main/CHANGELOG.md — SlimSpacyNlpEngine, HuggingFaceNerRecognizer, MedicalNERRecognizer, ONNX/GLiNER.
- https://pypi.org/project/presidio-analyzer/ — PyPI release history, MIT license.
- https://microsoft.github.io/presidio/samples/python/gliner/ — official GLiNER-as-external-NER integration.
- https://albertsikkema.com/python/security/privacy/2026/06/01/benchmarking-open-source-pii-detection.html — independent cross-domain benchmark; statistical-insignificance finding.
- https://huggingface.co/nvidia/gliner-PII — NVIDIA GLiNER-PII: params, types, license, F1.
- https://huggingface.co/Isotonic/deberta-v3-base_finetuned_ai4privacy_v2 — DeBERTa ai4privacy: F1, types, CC-BY-NC.
- https://huggingface.co/iiiorg/piiranha-v1-detect-personal-information — Piiranha: mDeBERTa, license.
- https://arxiv.org/html/2507.18546v1 — GLiNER2: Apache 2.0, multi-task, CPU speed.
- https://arxiv.org/abs/2510.19346 — fine-tuned GLiNER on EHR reaching F1 0.980.
- https://arxiv.org/pdf/2504.12308 — "Unmasking the Reality of PII Masking Models": inflated-claims critique.
- https://www.insideprivacy.com/eu-data-protection/special-category-data-by-inference-cjeu-significantly-expands-the-scope-of-article-9-gdpr/ — CJEU: inferred Art.9 data is Art.9 (the design trap).
- https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/special-category-data/what-is-special-category-data/ — ICO definition of the eight categories.
- https://gdpr-info.eu/art-9-gdpr/ — Article 9 primary text.
