package pii

import "context"

// Tier2Backend is the seam to probabilistic / NER detection (names, addresses,
// free-text PII). Go has no native transformer-NER ecosystem, so this package
// does NOT implement Tier 2 in-process. Instead a Tier2Backend wraps an external
// backend, chosen per latency budget:
//
//   - a Python inference sidecar (e.g. Presidio) over gRPC/HTTP,
//   - ONNX Runtime via cgo,
//   - a cloud DLP API (GCP Sensitive Data Protection, AWS Comprehend, Azure).
//
// For the ingestion hot path, prefer an in-process or co-located backend; a
// per-record network hop will throttle throughput.
//
// The Python side of algolia/pii-filter implements Tier 2 directly (it owns the ML
// ecosystem); this interface is how Go consumes equivalent capability.
type Tier2Backend interface {
	// Detect returns probabilistic findings (Tier == Tier2, Score < 1.0).
	Detect(ctx context.Context, text string) ([]Finding, error)
}

// CombinedAnalyzer fuses Tier-1 (deterministic, in-process) with a Tier-2
// backend. Tier-1 always runs; Tier-2 runs only if a backend is set.
type CombinedAnalyzer struct {
	tier1 *Analyzer
	tier2 Tier2Backend
}

// NewCombinedAnalyzer wires the default Tier-1 analyzer to a Tier-2 backend.
// Pass nil for tier2 to run Tier-1 only.
func NewCombinedAnalyzer(tier2 Tier2Backend) *CombinedAnalyzer {
	return &CombinedAnalyzer{tier1: DefaultAnalyzer(), tier2: tier2}
}

// Analyze runs Tier-1, then Tier-2 if configured, and merges with the same
// overlap resolution as Analyzer (Tier-1 identifiers win ties by being longer
// or earlier; callers can re-rank by Score if they prefer).
func (c *CombinedAnalyzer) Analyze(ctx context.Context, text string) ([]Finding, error) {
	findings := c.tier1.Analyze(text)

	if c.tier2 != nil {
		t2, err := c.tier2.Detect(ctx, text)
		if err != nil {
			return nil, err
		}

		// Fuse Tier-1 + Tier-2 with the same overlap resolution as Analyze, so
		// a checksum-validated identifier wins over an overlapping NER guess.
		return resolveOverlaps(append(findings, t2...)), nil
	}

	return findings, nil
}
