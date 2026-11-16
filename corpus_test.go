package pii

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// The Go detectors are validated against the SAME golden corpus the Python
// implementation uses (corpus/*.jsonl). The corpus is the cross-language
// contract: the spec regexes use lookbehind (which RE2 lacks), so the two impls
// cannot share regex strings, only behavior. This test proves the Go behavior
// matches the labeled spans.

type goldEntity struct {
	Type  string `json:"type"`
	Start int    `json:"start"`
	End   int    `json:"end"`
	Value string `json:"value"`
}

type goldExample struct {
	Text     string       `json:"text"`
	Entities []goldEntity `json:"entities"`
}

func loadCorpus(t *testing.T) []goldExample {
	t.Helper()

	files, err := filepath.Glob("corpus/*.jsonl")
	if err != nil {
		t.Fatalf("glob corpus: %v", err)
	}
	if len(files) == 0 {
		t.Skip("no corpus/*.jsonl found")
	}

	var examples []goldExample

	for _, f := range files {
		data, err := os.ReadFile(f)
		if err != nil {
			t.Fatalf("read %s: %v", f, err)
		}

		for _, line := range strings.Split(string(data), "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}

			var ex goldExample
			if err := json.Unmarshal([]byte(line), &ex); err != nil {
				t.Fatalf("parse %s: %v\nline: %s", f, err, line)
			}

			toByteOffsets(t, &ex)
			examples = append(examples, ex)
		}
	}

	return examples
}

// toByteOffsets converts the corpus spans, which count Unicode code points (the
// Python str indices the generator writes), into the byte offsets Go findings use.
// Identity on ASCII text.
func toByteOffsets(t *testing.T, ex *goldExample) {
	t.Helper()

	byteAt := make([]int, 0, len(ex.Text)+1)
	for i := range ex.Text {
		byteAt = append(byteAt, i)
	}

	byteAt = append(byteAt, len(ex.Text))

	for i := range ex.Entities {
		g := &ex.Entities[i]
		if g.Start < 0 || g.End >= len(byteAt) || g.Start > g.End {
			t.Fatalf("span [%d:%d] out of range in %q", g.Start, g.End, ex.Text)
		}

		g.Start, g.End = byteAt[g.Start], byteAt[g.End]
		if ex.Text[g.Start:g.End] != g.Value {
			t.Fatalf("span [%d:%d] is %q, label says %q", g.Start, g.End, ex.Text[g.Start:g.End], g.Value)
		}
	}
}

type spanKey struct {
	entity     string
	start, end int
}

// TestCorpus scores the default Tier-1 analyzer against the golden corpus at the
// span level and asserts an exact match (no false positives, no false negatives)
// on this curated set. It prints a per-entity precision/recall scorecard.
func TestCorpus(t *testing.T) {
	examples := loadCorpus(t)
	analyzer := DefaultAnalyzer()

	tp := map[string]int{}
	fp := map[string]int{}
	fn := map[string]int{}

	var fpDetail, fnDetail []string

	for _, ex := range examples {
		gold := map[spanKey]bool{}
		for _, g := range ex.Entities {
			gold[spanKey{g.Type, g.Start, g.End}] = true
		}

		got := map[spanKey]bool{}
		for _, f := range analyzer.Analyze(ex.Text) {
			got[spanKey{string(f.Entity), f.Start, f.End}] = true
		}

		for k := range got {
			if gold[k] {
				tp[k.entity]++
			} else {
				fp[k.entity]++
				fpDetail = append(fpDetail, fmt.Sprintf("%s [%d:%d] %q in %q", k.entity, k.start, k.end, ex.Text[k.start:k.end], ex.Text))
			}
		}

		for k := range gold {
			if !got[k] {
				fn[k.entity]++
				fnDetail = append(fnDetail, fmt.Sprintf("%s [%d:%d] %q in %q", k.entity, k.start, k.end, ex.Text[k.start:k.end], ex.Text))
			}
		}
	}

	printScorecard(t, len(examples), tp, fp, fn)

	if len(fpDetail) > 0 {
		t.Errorf("false positives (%d):\n  %s", len(fpDetail), strings.Join(fpDetail, "\n  "))
	}

	if len(fnDetail) > 0 {
		t.Errorf("false negatives (%d):\n  %s", len(fnDetail), strings.Join(fnDetail, "\n  "))
	}
}

func printScorecard(t *testing.T, n int, tp, fp, fn map[string]int) {
	t.Helper()

	entities := map[string]bool{}
	for e := range tp {
		entities[e] = true
	}
	for e := range fp {
		entities[e] = true
	}
	for e := range fn {
		entities[e] = true
	}

	names := make([]string, 0, len(entities))
	for e := range entities {
		names = append(names, e)
	}
	sort.Strings(names)

	var b strings.Builder
	fmt.Fprintf(&b, "\nGo Tier-1 scorecard over %d corpus examples\n", n)
	fmt.Fprintf(&b, "%-14s %4s %4s %4s  %6s %6s\n", "ENTITY", "TP", "FP", "FN", "PREC", "RECALL")

	var stp, sfp, sfn int

	for _, e := range names {
		p := ratio(tp[e], tp[e]+fp[e])
		r := ratio(tp[e], tp[e]+fn[e])
		fmt.Fprintf(&b, "%-14s %4d %4d %4d  %6.2f %6.2f\n", e, tp[e], fp[e], fn[e], p, r)
		stp += tp[e]
		sfp += fp[e]
		sfn += fn[e]
	}

	fmt.Fprintf(&b, "%-14s %4d %4d %4d  %6.2f %6.2f\n", "OVERALL", stp, sfp, sfn, ratio(stp, stp+sfp), ratio(stp, stp+sfn))
	t.Log(b.String())
}

func ratio(num, den int) float64 {
	if den == 0 {
		return 1.0
	}

	return float64(num) / float64(den)
}

func TestPolicyApply(t *testing.T) {
	text := "mail jane@example.com and ip 10.0.0.1"
	findings := DefaultAnalyzer().Analyze(text)

	// Redact email, flag IP (leaves it in place).
	pol := Policy{Default: ActionFlag, ByEntity: map[Entity]Action{EntityEmail: ActionRedact}}

	out, err := pol.Apply(text, findings)
	if err != nil {
		t.Fatalf("apply: %v", err)
	}

	if !strings.Contains(out, "[EMAIL]") {
		t.Errorf("email not redacted: %q", out)
	}

	if !strings.Contains(out, "10.0.0.1") {
		t.Errorf("flagged IP should remain: %q", out)
	}

	// Reject posture: a card in the text drops the record.
	cardText := "pay 4242 4242 4242 4242"
	cardFindings := DefaultAnalyzer().Analyze(cardText)

	if _, err := RejectAll().Apply(cardText, cardFindings); err != ErrRejected {
		t.Errorf("expected ErrRejected, got %v", err)
	}
}

func TestLuhnAndIBAN(t *testing.T) {
	if !luhnValid("4242424242424242") {
		t.Error("valid Visa test number failed Luhn")
	}

	if luhnValid("4242424242424241") {
		t.Error("invalid number passed Luhn")
	}

	if !validIBAN("GB82WEST12345698765432") {
		t.Error("valid IBAN failed mod-97")
	}

	if validIBAN("GB00WEST12345698765432") {
		t.Error("invalid IBAN passed mod-97")
	}

	// The length table is loaded from the shared iban_lengths.json (the same
	// file Python loads). The count guards against a truncated/corrupt file.
	if len(ibanLengths) != 89 {
		t.Errorf("ibanLengths has %d entries, want 89", len(ibanLengths))
	}

	if ibanLengths["RU"] != 33 {
		t.Errorf("RU length = %d, want 33 (shared SSOT not loaded?)", ibanLengths["RU"])
	}

	// Per-country length: these satisfy mod-97 but are the wrong length for
	// their country code, so they are not IBANs (ISO 13616).
	if validIBAN("NL14ABNA04171643001234") {
		t.Error("NL IBAN of length 22 (want 18) passed validation")
	}

	if validIBAN("DE863704004405320130") {
		t.Error("DE IBAN of length 20 (want 22) passed validation")
	}
}

func TestResolveOverlapsPrefersScoreAtEqualSpan(t *testing.T) {
	phone := Finding{Entity: EntityPhone, Start: 0, End: 10, Score: 0.85}
	strong := Finding{Entity: EntityIBAN, Start: 0, End: 10, Score: 1.0}

	got := resolveOverlaps([]Finding{phone, strong})
	if len(got) != 1 || got[0].Entity != EntityIBAN {
		t.Fatalf("equal span should go to the higher score, got %+v", got)
	}

	// At an exact tie (span and score) the earlier detector wins.
	a := Finding{Entity: EntityEmail, Start: 0, End: 4, Score: 1.0}
	b := Finding{Entity: EntityIP, Start: 0, End: 4, Score: 1.0}

	if got := resolveOverlaps([]Finding{a, b}); got[0].Entity != EntityEmail {
		t.Fatalf("exact tie should keep detector order, got %+v", got)
	}
}
