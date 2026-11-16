package pii

import (
	_ "embed"
	"encoding/json"
	"regexp"
	"strings"
)

// regexDetector is a Tier-1 detector: a compiled pattern plus an optional
// checksum/structure validator. Findings are emitted only when validate passes,
// which keeps precision high for checksum-bearing identifiers.
type regexDetector struct {
	entity   Entity
	re       *regexp.Regexp
	score    float64
	validate func(match string) bool
}

func (d regexDetector) Entity() Entity { return d.entity }

func (d regexDetector) Find(text string) []Finding {
	var out []Finding

	for _, loc := range d.re.FindAllStringIndex(text, -1) {
		match := text[loc[0]:loc[1]]
		if d.validate != nil && !d.validate(match) {
			continue
		}

		out = append(out, Finding{
			Entity: d.entity,
			Start:  loc[0],
			End:    loc[1],
			Score:  d.score,
			Tier:   Tier1,
			Text:   match,
		})
	}

	return out
}

// Patterns. RE2-compatible (no lookaround); boundary conditions the spec
// expresses with lookbehind are enforced in code (see phoneDetector) or by \b.
var (
	emailRe = regexp.MustCompile(`[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}`)
	// Candidate phone: optional +CC, optional (area), then digit groups joined by
	// a single separator. Validated by digit count + boundary checks.
	phoneRe = regexp.MustCompile(`(?:\+\d{1,3}[ .\-]?)?(?:\(\d{1,4}\)[ .\-]?)?\d{1,8}(?:[ .\-]\d{1,8}){1,6}`)
	// Card: 13-19 digits, optionally separated by single spaces/hyphens, ending
	// on a digit (no trailing separator). Validated by Luhn.
	creditCardRe = regexp.MustCompile(`\b\d(?:[ \-]?\d){12,18}\b`)
	// IBAN: 2 letters, 2 check digits, 11-30 alphanumerics. Validated mod-97.
	ibanRe = regexp.MustCompile(`\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b`)
	// IPv4 with octet ranges baked into the pattern (0-255 per octet).
	ipv4Re = regexp.MustCompile(`\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b`)
)

func newEmailDetector() Detector {
	return regexDetector{entity: EntityEmail, re: emailRe, score: 1.0}
}

func newCreditCardDetector() Detector {
	return regexDetector{entity: EntityCreditCard, re: creditCardRe, score: 1.0, validate: validCreditCard}
}

func newIBANDetector() Detector {
	return regexDetector{entity: EntityIBAN, re: ibanRe, score: 1.0, validate: validIBAN}
}

func newIPDetector() Detector {
	return regexDetector{entity: EntityIP, re: ipv4Re, score: 1.0}
}

func newPhoneDetector() Detector { return phoneDetector{} }

// phoneDetector handles the boundary + digit-count rules the spec's lookbehind
// regex encodes, which RE2 cannot express. Phone has no checksum, so its score
// is below the checksum-validated entities.
type phoneDetector struct{}

func (phoneDetector) Entity() Entity { return EntityPhone }

func (phoneDetector) Find(text string) []Finding {
	var out []Finding

	for _, loc := range phoneRe.FindAllStringIndex(text, -1) {
		start, end := loc[0], loc[1]

		// Boundary: not glued to an adjacent digit (the spec's (?<!\d)/(?!\d)).
		if start > 0 && isASCIIDigit(text[start-1]) {
			continue
		}

		if end < len(text) && isASCIIDigit(text[end]) {
			continue
		}

		match := text[start:end]

		// Anything shaped like a dotted quad (a.b.c.d) is an IP attempt, not a
		// phone: if it is a valid IPv4 the IP detector owns it; if not (e.g.
		// 192.168.1.300) it is nothing. Either way phone must not claim it.
		if isIPv4Shaped(strings.TrimSpace(match)) {
			continue
		}

		// An arXiv identifier (NNNN.NNNNN, e.g. 2506.12345) is a citation token,
		// not a dialable number, but its 9 digits pass the E.164 count. Reject it
		// so dev-tool / academic text stays clean.
		if isArxivID(strings.TrimSpace(match)) {
			continue
		}

		// E.164 allows 9..15 significant digits; this also rejects dates and
		// short grouped numbers.
		if n := countDigits(match); n < 9 || n > 15 {
			continue
		}

		out = append(out, Finding{
			Entity: EntityPhone,
			Start:  start,
			End:    end,
			Score:  0.85,
			Tier:   Tier1,
			Text:   match,
		})
	}

	return out
}

// --- Validators ---

// validCreditCard strips separators and requires BOTH a valid Luhn checksum AND
// a recognized card-network IIN prefix + length. Luhn alone is insufficient:
// e.g. "1111 2222 3333 4444" passes Luhn but is not issuable by any network
// (no valid IIN), so it must not be flagged. (Confirmed by the validators
// research; see SPEC.md.)
func validCreditCard(match string) bool {
	digits := stripNonDigits(match)
	if len(digits) < 13 || len(digits) > 19 {
		return false
	}

	return luhnValid(digits) && validCardNetwork(digits)
}

// validCardNetwork reports whether the digits match a known issuer IIN prefix
// and an allowed length for that network (Visa, Mastercard, Amex, Discover,
// Diners, JCB).
func validCardNetwork(d string) bool {
	n := len(d)

	switch {
	case d[0] == '4': // Visa
		return n == 13 || n == 16 || n == 19
	case d[:2] >= "51" && d[:2] <= "55" && n == 16: // Mastercard
		return true
	case n >= 4 && d[:4] >= "2221" && d[:4] <= "2720" && n == 16: // Mastercard 2-series
		return true
	case (d[:2] == "34" || d[:2] == "37") && n == 15: // Amex
		return true
	case n >= 4 && d[:4] == "6011" && (n == 16 || n == 19): // Discover
		return true
	case d[:2] == "65" && (n == 16 || n == 19): // Discover
		return true
	case (d[:2] == "36" || d[:2] == "38" || d[:2] == "30") && n >= 14 && n <= 19: // Diners
		return true
	case n >= 4 && d[:4] >= "3528" && d[:4] <= "3589" && n >= 16 && n <= 19: // JCB
		return true
	default:
		return false
	}
}

// luhnValid runs the Luhn checksum (ISO/IEC 7812-1) on a digit string.
func luhnValid(digits string) bool {
	sum := 0
	double := false

	for i := len(digits) - 1; i >= 0; i-- {
		d := int(digits[i] - '0')
		if double {
			d *= 2
			if d > 9 {
				d -= 9
			}
		}

		sum += d
		double = !double
	}

	return sum%10 == 0
}

// ibanLengths is the official IBAN length per country (ISO 13616 / SWIFT IBAN
// Registry). An IBAN's length is fixed per country, so a string whose length is
// wrong for its country code is not an IBAN even if it satisfies mod-97.
// Countries absent here fall back to the generic 15..34 bound (graceful
// degradation: never drop a real IBAN from a country we haven't tabled yet).
//
// The table is loaded from iban_lengths.json, the SAME file the Python
// implementation loads (89 countries, cross-checked against Wikipedia's IBAN
// registry table and iban.com/structure; see
// docs/research-deterministic-validators.md). One SSOT, so the two languages
// cannot drift.
//
//go:embed src/pii/iban_lengths.json
var ibanLengthsJSON []byte

var ibanLengths = mustLoadIBANLengths()

func mustLoadIBANLengths() map[string]int {
	var m map[string]int
	if err := json.Unmarshal(ibanLengthsJSON, &m); err != nil {
		panic("pii: cannot parse embedded iban_lengths.json: " + err.Error())
	}
	return m
}

// validIBAN checks the per-country length (ISO 13616) and the mod-97 checksum
// (ISO 7064 MOD 97-10). Length is checked against the country code first.
func validIBAN(match string) bool {
	s := strings.ToUpper(strings.ReplaceAll(match, " ", ""))
	if len(s) < 15 || len(s) > 34 {
		return false
	}

	if want, ok := ibanLengths[s[:2]]; ok && len(s) != want {
		return false
	}

	rearranged := s[4:] + s[:4] // move the first four chars to the end

	remainder := 0

	for _, r := range rearranged {
		var n int

		switch {
		case r >= '0' && r <= '9':
			n = int(r - '0')
		case r >= 'A' && r <= 'Z':
			n = int(r-'A') + 10
		default:
			return false
		}

		if n > 9 {
			remainder = (remainder*100 + n) % 97
		} else {
			remainder = (remainder*10 + n) % 97
		}
	}

	return remainder == 1
}

func stripNonDigits(s string) string {
	var b strings.Builder

	for i := 0; i < len(s); i++ {
		if isASCIIDigit(s[i]) {
			b.WriteByte(s[i])
		}
	}

	return b.String()
}

func countDigits(s string) int {
	n := 0

	for i := 0; i < len(s); i++ {
		if isASCIIDigit(s[i]) {
			n++
		}
	}

	return n
}

func isASCIIDigit(b byte) bool { return b >= '0' && b <= '9' }

// isArxivID reports whether s is an arXiv identifier NNNN.NNNNN: a 4-digit YYMM,
// a single dot, then a 4-5 digit sequence (e.g. "2506.12345"). Mirrors the Python
// _is_arxiv_id guard so both languages keep the same dev-tool negative green.
func isArxivID(s string) bool {
	dot := strings.IndexByte(s, '.')
	if dot < 0 || strings.IndexByte(s[dot+1:], '.') >= 0 {
		return false
	}

	left, right := s[:dot], s[dot+1:]
	if len(left) != 4 || len(right) < 4 || len(right) > 5 {
		return false
	}

	return countDigits(left) == len(left) && countDigits(right) == len(right)
}

// isIPv4Shaped reports whether s is exactly four dot-separated all-digit groups
// (a.b.c.d), regardless of whether the octets are in range.
func isIPv4Shaped(s string) bool {
	parts := strings.Split(s, ".")
	if len(parts) != 4 {
		return false
	}

	for _, p := range parts {
		if p == "" {
			return false
		}

		for i := 0; i < len(p); i++ {
			if !isASCIIDigit(p[i]) {
				return false
			}
		}
	}

	return true
}
