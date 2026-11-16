package pii

import (
	_ "embed"
	"encoding/json"
	"regexp"
	"strings"
	"unicode/utf8"
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
	// The spec's left lookbehind exists to stop backtracking; RE2 scans in linear
	// time without it and reports the same leftmost matches.
	emailRe = regexp.MustCompile(`[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}`)
	// Candidate phone: optional +CC, optional (area), then digit groups joined by
	// a single separator. Validated by digit count + boundary checks.
	phoneRe = regexp.MustCompile(`(?:\+\d{1,3}[ .\-]?)?(?:\(\d{1,4}\)[ .\-]?)?\d{1,8}(?:[ .\-]\d{1,8}){1,6}`)
	// E.164 written compact or with one separator after the country code: the
	// spec's first PHONE alternative, boundaries checked in phoneDetector.
	phoneE164Re = regexp.MustCompile(`\+[1-9][0-9]{0,2}[ .\-]?[0-9]{6,14}`)
	// Card: a whole digit run of 13+ digits, single spaces/hyphens between
	// digits. creditCardDetector reports the run or its valid windows of whole
	// groups (Python card_spans). Validated by Luhn + IIN + length.
	creditCardRe = regexp.MustCompile(`[0-9](?:[ \-]?[0-9]){12,}`)
	// IBAN: 2 letters, 2 check digits, then 11-30 alphanumerics, or 4-character
	// groups joined by a separator (space, NBSP, thin space, narrow NBSP, dot,
	// hyphen), either case. The trailing class stands in for the spec's
	// (?![A-Za-z0-9]) lookahead and is trimmed off; ibanDetector checks the
	// left boundary. Validated by validIBAN (length + mod-97), cut by ibanSpan.
	ibanRe = regexp.MustCompile(`[A-Za-z]{2}[0-9]{2}(?:[A-Za-z0-9]{11,30}|(?:[ \x{00A0}\x{2009}\x{202F}.\-][A-Za-z0-9]{4}){2,7}(?:[ \x{00A0}\x{2009}\x{202F}.\-][A-Za-z0-9]{1,4})?)(?:[^A-Za-z0-9]|$)`)
	// IPv4 with octet ranges baked into the pattern (0-255 per octet).
	ipv4Re = regexp.MustCompile(`\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b`)
)

func newEmailDetector() Detector {
	return regexDetector{entity: EntityEmail, re: emailRe, score: 1.0}
}

func newCreditCardDetector() Detector { return creditCardDetector{} }

// creditCardDetector mirrors Python's card_spans: the digit run when it
// validates, otherwise windows of whole groups holding 13-19 digits (earliest
// start, then the longest valid window), so an expiry, CVV or short reference
// in the same run no longer hides the card. A compact run of 20+ digits has no
// group boundary inside and yields nothing.
type creditCardDetector struct{}

func (creditCardDetector) Entity() Entity { return EntityCreditCard }

func (creditCardDetector) Find(text string) []Finding {
	var out []Finding

	for _, loc := range creditCardRe.FindAllStringIndex(text, -1) {
		// The spec's (?<![0-9]): a maximal run never starts right after a digit,
		// but keep the guard explicit.
		if loc[0] > 0 && isASCIIDigit(text[loc[0]-1]) {
			continue
		}

		for _, sp := range cardWindows(text, loc[0], loc[1]) {
			out = append(out, Finding{Entity: EntityCreditCard, Start: sp[0], End: sp[1], Score: 1.0, Tier: Tier1, Text: text[sp[0]:sp[1]]})
		}
	}

	return out
}

// cardShape mirrors Python's _card_shape: one compact group, 4-digit groups
// with a shorter last one, or Amex/Diners 4-6-5 and 4-6-4.
func cardShape(sizes []int) bool {
	if len(sizes) == 1 {
		return true
	}

	if len(sizes) == 3 && sizes[0] == 4 && sizes[1] == 6 && (sizes[2] == 5 || sizes[2] == 4) {
		return true
	}

	for _, n := range sizes[:len(sizes)-1] {
		if n != 4 {
			return false
		}
	}

	last := sizes[len(sizes)-1]

	return last >= 1 && last <= 4
}

func cardWindows(text string, start, end int) [][2]int {
	var groups [][2]int

	for i := start; i < end; {
		j := i
		for j < end && isASCIIDigit(text[j]) {
			j++
		}

		groups = append(groups, [2]int{i, j})
		i = j + 1 // skip the single separator
	}

	sizes := make([]int, len(groups))
	for i, gr := range groups {
		sizes[i] = gr[1] - gr[0]
	}

	var spans [][2]int

	for g := 0; g < len(groups); {
		if c := text[groups[g][0]]; c < '2' || c > '6' { // no issuer prefix starts otherwise
			g++

			continue
		}

		best := -1
		digits := make([]byte, 0, 19)

		for k := g; k < len(groups); k++ {
			digits = append(digits, text[groups[k][0]:groups[k][1]]...)
			if len(digits) > 19 {
				break
			}

			whole := g == 0 && k == len(groups)-1
			if len(digits) >= 13 && (whole || cardShape(sizes[g:k+1])) && validCreditCard(string(digits)) {
				best = k
			}
		}

		if best < 0 {
			g++

			continue
		}

		spans = append(spans, [2]int{groups[g][0], groups[best][1]})
		g = best + 1
	}

	return spans
}

func newIBANDetector() Detector { return ibanDetector{} }

// ibanDetector reproduces the spec IBAN regex (lookbehind and lookahead on
// ASCII letters and digits) and Python's iban_spans: a grouped match that fails
// is cut back to its country's length at a group boundary, and the scan resumes
// at the cut so a following IBAN is still found.
type ibanDetector struct{}

func (ibanDetector) Entity() Entity { return EntityIBAN }

func (ibanDetector) Find(text string) []Finding {
	var out []Finding

	pos := 0
	for pos < len(text) {
		loc := ibanRe.FindStringIndex(text[pos:])
		if loc == nil {
			break
		}

		start, end := pos+loc[0], pos+loc[1]
		if r, size := utf8.DecodeLastRuneInString(text[start:end]); r >= utf8.RuneSelf || !isASCIIAlnum(byte(r)) {
			end -= size // the lookahead stand-in, not part of the IBAN
		}

		if start > 0 && isASCIIAlnum(text[start-1]) {
			pos = start + 1
			for pos < len(text) && isASCIIAlnum(text[pos-1]) {
				pos++
			}

			continue
		}

		spanEnd, resume := ibanSpan(text, start, end)
		if spanEnd > start {
			out = append(out, Finding{Entity: EntityIBAN, Start: start, End: spanEnd, Score: 1.0, Tier: Tier1, Text: text[start:spanEnd]})
		}

		pos = resume
	}

	return out
}

// ibanSpan mirrors Python's iban_spans: the end of the IBAN inside the regex
// match text[start:end] (or -1), and where the scan resumes.
func ibanSpan(text string, start, end int) (int, int) {
	value := text[start:end]
	if validIBAN(value) {
		return end, end
	}

	want, ok := ibanLengths[strings.ToUpper(value[:2])]
	if !ok || !strings.ContainsFunc(value, isIBANSep) {
		return -1, end
	}

	seen := 0

	for i, r := range value {
		if isIBANSep(r) {
			continue
		}

		seen++
		if seen == want {
			cut := i + utf8.RuneLen(r)
			if cut < len(value) {
				next, _ := utf8.DecodeRuneInString(value[cut:])
				if isIBANSep(next) && validIBAN(value[:cut]) {
					return start + cut, start + cut
				}
			}

			break
		}
	}

	return -1, end
}

// isIBANSep reports the separators allowed between printed IBAN groups.
func isIBANSep(r rune) bool {
	return r == ' ' || r == '\u00A0' || r == '\u2009' || r == '\u202F' || r == '.' || r == '-'
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

	// The E.164 alternative: whenever it matches, the grouped pattern could only
	// match the same span, so a separate scan finds what Python's alternation
	// finds (overlap resolution drops the duplicate).
	for _, loc := range phoneE164Re.FindAllStringIndex(text, -1) {
		start, end := loc[0], loc[1]
		if start > 0 && isASCIIDigit(text[start-1]) {
			continue
		}

		if end < len(text) && isASCIIDigit(text[end]) {
			continue
		}

		if end+1 < len(text) && isIDSep(text[end]) && isASCIIDigit(text[end+1]) {
			continue // another digit group follows: the grouped reading owns it
		}

		if n := countDigits(text[start:end]); n < 9 || n > 15 {
			continue
		}

		out = append(out, Finding{Entity: EntityPhone, Start: start, End: end, Score: 0.85, Tier: Tier1, Text: text[start:end]})
	}

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

	return validCardNetwork(digits) && luhnValid(digits)
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
// Grouped or lowercase input must use one separator kind, must not mix cases,
// and needs a country in the length table (Python iban_mod97).
func validIBAN(match string) bool {
	var (
		b                  strings.Builder
		sep                rune = -1
		hasUpper, hasLower bool
	)

	for _, r := range match {
		if isIBANSep(r) {
			if sep != -1 && r != sep {
				return false
			}

			sep = r

			continue
		}

		switch {
		case r >= 'a' && r <= 'z':
			hasLower = true
		case r >= 'A' && r <= 'Z':
			hasUpper = true
		}

		b.WriteRune(r)
	}

	if hasUpper && hasLower {
		return false // mixed case reads as a token, not an IBAN
	}

	s := strings.ToUpper(b.String())
	if len(s) < 15 || len(s) > 34 {
		return false
	}

	want, ok := ibanLengths[s[:2]]
	if !ok && (sep != -1 || hasLower) {
		return false
	}

	if ok && len(s) != want {
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
