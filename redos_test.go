package pii

import (
	"strings"
	"testing"
	"time"
)

// TestAnalyzeIsFastOnAdversarialInput mirrors tests/test_redos.py: a server-side
// gate runs on caller-controlled text, so no detector may go super-linear. RE2 is
// linear per scan, but the scan loops around it (boundary retries) are ours. The
// budget is generous so a slow CI runner does not flake.
func TestAnalyzeIsFastOnAdversarialInput(t *testing.T) {
	if testing.Short() {
		t.Skip("timing test")
	}

	const n = 100000

	inputs := map[string]string{
		"letters":          strings.Repeat("a", n),
		"digits":           strings.Repeat("1", n),
		"dots":             strings.Repeat(".", n),
		"alnum":            strings.Repeat("a1", n/2),
		"upper-alnum":      strings.Repeat("A1", n/2),
		"digit-space":      strings.Repeat("1 ", n/2),
		"digit-dash":       strings.Repeat("1-", n/2),
		"digit-dot":        strings.Repeat("1.", n/2),
		"visa-digit-space": strings.Repeat("4 ", n/2),
		"email-local":      strings.Repeat("a.", n/2),
		"email-domain":     "a@" + strings.Repeat("b.", n/2),
		"at-signs":         strings.Repeat("a@", n/2),
		"word-space":       strings.Repeat("ab ", n/3),
		"iban-groups":      strings.Repeat("AB12 ", n/5),
		"card-groups":      strings.Repeat("4242 ", n/5),
		"plus-digits":      strings.Repeat("+1", n/2),
	}

	const budget = 2 * time.Second

	analyzer := DefaultAnalyzer()

	for name, text := range inputs {
		start := time.Now()
		analyzer.Analyze(text)

		if took := time.Since(start); took > budget {
			t.Errorf("Analyze took %v on 100k %s (budget %v)", took, name, budget)
		}
	}
}
