// Package pii is Algolia's shared PII detection and policy library.
//
// It detects personal data, reports it as structured findings, and applies a
// configurable policy (reject / redact / hash / tokenize / flag). This is the Go
// implementation of Tier 1 (deterministic, regex + checksum detectors). Tier 2
// (probabilistic NER for names/addresses) is reached through the Tier2 interface
// (see tier2.go) so Go can call a service or ONNX/cloud backend without a native
// ML dependency.
//
// Entity names and default policies follow the language-neutral SSOT in
// spec/entities.yaml; both this package and the Python implementation are tested
// against the same golden corpus (corpus/*.jsonl). The corpus is the contract:
// the spec regexes use lookbehind, which Go's RE2 does not support, so the Go
// detectors use RE2-compatible patterns plus boundary checks that reproduce the
// same matches. See corpus_test.go.
//
// Detection and policy are deliberately separate (mirroring Presidio's
// analyzer/anonymizer split): Analyze finds, Policy.Apply decides what to do.
//
// This package is NOT a compliance guarantee. Regex + checksum detection is a
// high-precision tripwire for identifiers; it does not certify a dataset
// PII-free. The strongest control remains never ingesting personal data.
package pii

import "sort"

// Entity is a category of personal data. Values match spec/entities.yaml.
type Entity string

const (
	EntityEmail      Entity = "EMAIL"
	EntityPhone      Entity = "PHONE"
	EntityCreditCard Entity = "CREDIT_CARD"
	EntityIBAN       Entity = "IBAN"
	EntityIP         Entity = "IP"

	// Tier-2 entities (probabilistic / NER). Detected via the Tier2 interface,
	// never by this package's deterministic detectors.
	EntityPerson  Entity = "PERSON"
	EntityAddress Entity = "ADDRESS"
)

// Tier marks how a finding was produced.
type Tier int

const (
	// Tier1 is deterministic: regex + checksum/structure validation.
	Tier1 Tier = 1
	// Tier2 is probabilistic: NER / ML. Score is the model's confidence.
	Tier2 Tier = 2
)

// Finding is a single detected span of personal data.
type Finding struct {
	Entity Entity  `json:"entity"`
	Start  int     `json:"start"` // byte offset, inclusive
	End    int     `json:"end"`   // byte offset, exclusive
	Score  float64 `json:"score"` // 0..1
	Tier   Tier    `json:"tier"`
	Text   string  `json:"text"` // the matched substring
}

// Detector finds occurrences of one entity in text.
type Detector interface {
	Entity() Entity
	Find(text string) []Finding
}

// Analyzer runs a set of detectors over text and merges their findings.
type Analyzer struct {
	detectors []Detector
}

// NewAnalyzer builds an Analyzer from the given detectors.
func NewAnalyzer(detectors ...Detector) *Analyzer {
	return &Analyzer{detectors: detectors}
}

// DefaultAnalyzer returns an Analyzer with all Tier-1 deterministic detectors.
func DefaultAnalyzer() *Analyzer {
	// Same order as spec/entities.yaml: at an exact overlap tie the earlier
	// detector wins (TestDefaultAnalyzerFollowsSpecOrder).
	return NewAnalyzer(
		newEmailDetector(),
		newFRNIRDetector(),
		newFRTaxIDDetector(),
		newFRSIRETDetector(),
		newFRSIRENDetector(),
		newESDNIDetector(),
		newESNIEDetector(),
		newPhoneDetector(),
		newCreditCardDetector(),
		newIBANDetector(),
		newIPDetector(),
	)
}

// Analyze returns the findings in text, sorted by start offset, with overlaps
// resolved. See resolveOverlaps.
func (a *Analyzer) Analyze(text string) []Finding {
	var all []Finding
	for _, d := range a.detectors {
		all = append(all, d.Find(text)...)
	}

	return resolveOverlaps(all)
}

// resolveOverlaps sorts findings (earliest start first; at equal start, longest
// match first; at equal span, highest score first; then detector order, which
// DefaultAnalyzer keeps equal to the spec order) and greedily drops any that
// overlap one already kept. This lets a structured identifier (e.g. an IBAN) win
// over a fragment that a looser detector might match inside it, and a checksum
// identifier win over the same digits read as a phone. Mirrors Python's
// resolve_overlaps. Used by both Analyzer and the Tier-1/Tier-2 fusion.
func resolveOverlaps(all []Finding) []Finding {
	sort.SliceStable(all, func(i, j int) bool {
		if all[i].Start != all[j].Start {
			return all[i].Start < all[j].Start
		}

		li, lj := all[i].End-all[i].Start, all[j].End-all[j].Start
		if li != lj {
			return li > lj
		}

		return all[i].Score > all[j].Score
	})

	kept := make([]Finding, 0, len(all))
	lastEnd := -1

	for _, f := range all {
		if f.Start < lastEnd {
			continue // overlaps a finding we already kept
		}

		kept = append(kept, f)
		lastEnd = f.End
	}

	return kept
}

// Counts aggregates findings per entity (the "text -> counts" metadata view).
func Counts(findings []Finding) map[Entity]int {
	out := make(map[Entity]int)
	for _, f := range findings {
		out[f.Entity]++
	}

	return out
}

// HasPII reports whether any finding was made.
func HasPII(findings []Finding) bool {
	return len(findings) > 0
}
