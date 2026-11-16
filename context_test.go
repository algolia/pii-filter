package pii

import "testing"

// Mirrors tests/test_context_gate.py: the gate is exercised on a test-only
// context-required EMAIL detector, independent of any shipped keyword list.

func gatedEmails(text string) []string {
	d := withContext(newEmailDetector(), []string{"contact", "numéro d'entreprise"}, 20)

	var out []string
	for _, f := range NewAnalyzer(d).Analyze(text) {
		out = append(out, f.Text)
	}

	return out
}

func TestFold(t *testing.T) {
	cases := map[string]string{
		"NUMÉRO  d’Entreprise":               "numero d'entreprise",
		"Ça va":                              "ca va",
		"ŒUVRE Straße":                       "oeuvre strasse",
		"Nume\u0301ro d'e\u0301tablissement": "numero d'etablissement", // NFD
	}

	for in, want := range cases {
		if got := fold(in); got != want {
			t.Errorf("fold(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestContextGate(t *testing.T) {
	pad := func(n int) string {
		b := make([]byte, n)
		for i := range b {
			b[i] = ' '
		}

		return string(b)
	}

	cases := []struct {
		text string
		hit  bool
	}{
		{"contact: jane@example.com", true},
		{"write to jane@example.com", false},
		{"CONTACT jane@example.com", true},
		{"Numero d'entreprise jane@example.com", true},
		{"NUMÉRO D’ENTREPRISE jane@example.com", true},
		{"jane@example.com is my contact", false},
		{"contact" + pad(20) + "jane@example.com", false},
		{"contact" + pad(5) + "jane@example.com", true},
		{"contacts jane@example.com", false},
		{"recontact jane@example.com", false},
		{"xcontact" + pad(12) + "jane@example.com", false},
		{" contact" + pad(12) + "jane@example.com", true},
		// the window counts characters, not bytes: 6 accented runes are 12 bytes
		{"contact éééééé jane@example.com", true},
	}

	for _, c := range cases {
		got := gatedEmails(c.text)
		if hit := len(got) == 1 && got[0] == "jane@example.com"; hit != c.hit {
			t.Errorf("%q: got %v, want hit=%v", c.text, got, c.hit)
		}
	}
}
