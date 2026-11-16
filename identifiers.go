package pii

import (
	"regexp"
	"strconv"
	"strings"
)

// National identifiers (FR, ES): checksum-bearing numbers, the Go side of the
// spec entries FR_NIR and the rest. The spec regexes refuse to start or end
// inside a longer separated digit run with lookarounds; RE2 has none, so the
// patterns below are the spec regexes minus the lookarounds and boundedDetector
// applies the same boundary in code. Each pattern has at most one match length per
// start offset, so retrying from the next offset after a refused boundary finds
// exactly the matches Python's lookaround regex finds.

const (
	EntityFRNIR   Entity = "FR_NIR"
	EntityFRTaxID Entity = "FR_TAX_ID"
	EntityFRSIRET Entity = "FR_SIRET"
	EntityFRSIREN Entity = "FR_SIREN"
	EntityESDNI   Entity = "ES_DNI"
	EntityESNIE   Entity = "ES_NIE"
)

var (
	frNIRRe   = regexp.MustCompile(`[1278][ .\-]?[0-9]{2}[ .\-]?[0-9]{2}[ .\-]?(?:[0-9]{2}|2[ABab])[ .\-]?[0-9]{3}[ .\-]?[0-9]{3}[ .\-]?[0-9]{2}`)
	frTaxIDRe = regexp.MustCompile(`[0-3][0-9][ .\-]?[0-9]{2}[ .\-]?[0-9]{3}[ .\-]?[0-9]{3}[ .\-]?[0-9]{3}`)
	frSIRETRe = regexp.MustCompile(`[0-9]{3}[ .\-]?[0-9]{3}[ .\-]?[0-9]{3}[ .\-]?[0-9]{5}`)
	frSIRENRe = regexp.MustCompile(`[0-9]{3}[ .\-]?[0-9]{3}[ .\-]?[0-9]{3}`)
	esDNIRe   = regexp.MustCompile(`(?:[0-9]{8}|[0-9]{2}\.[0-9]{3}\.[0-9]{3})[ \-]?[A-Z]`)
	esNIERe   = regexp.MustCompile(`[XYZ][ \-]?[0-9]{7}[ \-]?[A-Z]`)
)

// esIDLetters are the Spanish DNI/NIE control letters, indexed by number mod 23.
const esIDLetters = "TRWAGMYFPDXBNJZSQVHLCKE"

// frCompanyKeywords and frCompanyWindow gate FR_SIRET and FR_SIREN (spec
// context_keywords / context_window; TestContextGatesMatchSpec keeps them equal).
var frCompanyKeywords = []string{
	"siren",
	"sirene",
	"siret",
	"rcs",
	"registre du commerce",
	"numéro d'entreprise",
	"numéro d'établissement",
	"numéro d'identification",
	"immatriculation",
	"company number",
	"company registration",
	"business id",
}

const frCompanyWindow = 40

// laPosteSIREN is La Poste's SIREN; its SIRET numbers use digit sum mod 5 == 0
// instead of Luhn.
const laPosteSIREN = "356000000"

// boundary decides whether text[start:end] may stand as a match.
type boundary func(text string, start, end int) bool

// boundedDetector is regexDetector plus a boundary check, scanning so that a
// refused candidate does not hide a valid match starting inside it.
type boundedDetector struct {
	entity   Entity
	re       *regexp.Regexp
	bound    boundary
	validate func(match string) bool
}

func (d boundedDetector) Entity() Entity { return d.entity }

func (d boundedDetector) Find(text string) []Finding {
	var out []Finding

	pos := 0
	for pos <= len(text) {
		loc := d.re.FindStringIndex(text[pos:])
		if loc == nil {
			break
		}

		start, end := pos+loc[0], pos+loc[1]
		if !d.bound(text, start, end) {
			// Python's lookaround regex would not match here at all; it tries the
			// next offset. Patterns start on an ASCII byte, so +1 is a rune step.
			pos = start + 1

			// Every bound refuses a start glued to a letter or digit, so skip
			// those offsets: a long digit run would otherwise cost one regex
			// search per byte.
			for pos < len(text) && isASCIIAlnum(text[pos-1]) {
				pos++
			}

			continue
		}

		// Like Python's finditer, a regex match is consumed whether or not the
		// validator accepts it.
		pos = end

		if d.validate(text[start:end]) {
			out = append(out, Finding{Entity: d.entity, Start: start, End: end, Score: 1.0, Tier: Tier1, Text: text[start:end]})
		}
	}

	return out
}

func isASCIIAlnum(b byte) bool {
	return isASCIIDigit(b) || (b >= 'A' && b <= 'Z') || (b >= 'a' && b <= 'z')
}

func isIDSep(b byte) bool { return b == ' ' || b == '.' || b == '-' }

// alnumBounded: not glued to an ASCII letter or digit on either side.
func alnumBounded(text string, start, end int) bool {
	if start > 0 && isASCIIAlnum(text[start-1]) {
		return false
	}

	return end == len(text) || !isASCIIAlnum(text[end])
}

// digitRunBounded: alnumBounded, and not one group of a longer separated digit
// run (the spec's (?<![0-9][ .-]) and (?![ .-][0-9])).
func digitRunBounded(text string, start, end int) bool {
	if !alnumBounded(text, start, end) {
		return false
	}

	if start >= 2 && isIDSep(text[start-1]) && isASCIIDigit(text[start-2]) {
		return false
	}

	return !(end+1 < len(text) && isIDSep(text[end]) && isASCIIDigit(text[end+1]))
}

func compactID(s string) string {
	var b strings.Builder

	for i := 0; i < len(s); i++ {
		if !isIDSep(s[i]) {
			b.WriteByte(s[i])
		}
	}

	return b.String()
}

func allASCIIDigits(s string) bool { return s != "" && countDigits(s) == len(s) }

func newFRNIRDetector() Detector {
	return boundedDetector{entity: EntityFRNIR, re: frNIRRe, bound: digitRunBounded, validate: validFRNIR}
}

// validFRNIR: 13 characters then a 2-digit key, key = 97 - (first13 mod 97).
// Corsica's 2A and 2B department codes read as 19 and 18 for the arithmetic.
func validFRNIR(match string) bool {
	s := strings.ToUpper(compactID(match))
	if len(s) != 15 || !strings.ContainsRune("1278", rune(s[0])) {
		return false
	}

	body, key := s[:13], s[13:]

	switch body[5:7] {
	case "2A":
		body = body[:5] + "19" + body[7:]
	case "2B":
		body = body[:5] + "18" + body[7:]
	}

	if !allASCIIDigits(body) || !allASCIIDigits(key) {
		return false
	}

	n, _ := strconv.ParseUint(body, 10, 64) // 13 digits always fit
	k, _ := strconv.Atoi(key)

	return 97-int(n%97) == k
}

func newFRTaxIDDetector() Detector {
	return boundedDetector{entity: EntityFRTaxID, re: frTaxIDRe, bound: digitRunBounded, validate: validFRTaxID}
}

// validFRTaxID: French numero fiscal (SPI), 13 digits, first digit 0-3, and the
// last three digits equal the first ten taken as an integer, mod 511.
func validFRTaxID(match string) bool {
	s := compactID(match)
	if len(s) != 13 || !allASCIIDigits(s) || s[0] > '3' {
		return false
	}

	head, _ := strconv.ParseUint(s[:10], 10, 64)
	tail, _ := strconv.ParseUint(s[10:], 10, 64)

	return head%511 == tail
}

func newFRSIRETDetector() Detector {
	d := boundedDetector{entity: EntityFRSIRET, re: frSIRETRe, bound: digitRunBounded, validate: validFRSIRET}

	return withContext(d, frCompanyKeywords, frCompanyWindow)
}

func newFRSIRENDetector() Detector {
	d := boundedDetector{entity: EntityFRSIREN, re: frSIRENRe, bound: digitRunBounded, validate: validFRSIREN}

	return withContext(d, frCompanyKeywords, frCompanyWindow)
}

// validFRSIREN: 9 digits, Luhn.
func validFRSIREN(match string) bool {
	s := compactID(match)

	return len(s) == 9 && allASCIIDigits(s) && luhnValid(s)
}

// validFRSIRET: a Luhn-valid SIREN + 5-digit NIC, Luhn over the 14 digits. La Poste
// establishments may use digit sum mod 5 == 0 instead; its Luhn-valid numbers
// (the head office) stay valid.
func validFRSIRET(match string) bool {
	s := compactID(match)
	if len(s) != 14 || !allASCIIDigits(s) {
		return false
	}

	if s[:9] == laPosteSIREN {
		sum := 0
		for i := 0; i < len(s); i++ {
			sum += int(s[i] - '0')
		}

		return luhnValid(s) || sum%5 == 0
	}

	return luhnValid(s[:9]) && luhnValid(s)
}

func newESDNIDetector() Detector {
	return boundedDetector{entity: EntityESDNI, re: esDNIRe, bound: alnumBounded, validate: validESDNI}
}

func newESNIEDetector() Detector {
	return boundedDetector{entity: EntityESNIE, re: esNIERe, bound: alnumBounded, validate: validESNIE}
}

// validESDNI: 8 digits, then the letter at esIDLetters[number mod 23].
func validESDNI(match string) bool {
	s := compactID(match)
	if len(s) != 9 || !allASCIIDigits(s[:8]) {
		return false
	}

	n, _ := strconv.Atoi(s[:8])

	return esIDLetters[n%23] == s[8]
}

// validESNIE: X/Y/Z read as 0/1/2, 7 digits, then the DNI letter rule.
func validESNIE(match string) bool {
	s := compactID(match)
	if len(s) != 9 || !allASCIIDigits(s[1:8]) {
		return false
	}

	prefix := strings.IndexByte("XYZ", s[0])
	if prefix < 0 {
		return false
	}

	n, _ := strconv.Atoi(strconv.Itoa(prefix) + s[1:8])

	return esIDLetters[n%23] == s[8]
}
