package pii

import (
	"strings"
	"unicode"
	"unicode/utf8"
)

// Keyword gate for context-required ("Tier 1.5") entities, the Go side of
// src/pii/context.py. Some identifiers carry a checksum too weak to stand alone
// (a 9-digit SIREN passes Luhn one time in ten), so spec/entities.yaml marks them
// requires_context with a keyword list and a window: a match is reported only
// when a keyword lies whole inside the window before it.
//
// The window counts characters (runes), not bytes, so it measures the same text
// as Python. Folding uses an explicit table rather than Unicode normalization;
// keep foldTable identical to Python's _FOLD. Combining marks (U+0300-U+036F) are
// dropped, so decomposed (NFD) accents fold like precomposed ones.

var foldTable = buildFoldTable()

func buildFoldTable() map[rune]string {
	m := map[rune]string{'æ': "ae", 'ç': "c", 'ñ': "n", 'œ': "oe", 'ß': "ss"}
	groups := map[string]string{
		"àáâãäåā": "a",
		"èéêëē":   "e",
		"ìíîïī":   "i",
		"òóôõöøō": "o",
		"ùúûüū":   "u",
		"ýÿ":      "y",
		"‘’ʼ":     "'",
	}

	for chars, repl := range groups {
		for _, r := range chars {
			m[r] = repl
		}
	}

	return m
}

// isFoldSpace mirrors Python's explicit _SPACES set (unicode.IsSpace differs from
// str.isspace on control characters).
func isFoldSpace(r rune) bool {
	switch r {
	case ' ', '\t', '\n', '\r', '\f', '\v', '\u00a0', '\u2009', '\u202f':
		return true
	default:
		return false
	}
}

func isWordRune(r rune) bool { return unicode.IsLetter(r) || unicode.IsDigit(r) }

// fold lowercases, strips the common Latin accents and every combining mark,
// unifies apostrophes and collapses whitespace runs to one space.
func fold(s string) string {
	var b strings.Builder

	inSpace := false

	for _, r := range s {
		if r >= '\u0300' && r <= '\u036f' {
			continue
		}

		if isFoldSpace(r) {
			if !inSpace {
				b.WriteByte(' ')
			}

			inSpace = true

			continue
		}

		inSpace = false

		low := r
		if r != 'İ' { // Python lowercases U+0130 to two code points and keeps it as is
			low = unicode.ToLower(r)
		}

		if repl, ok := foldTable[low]; ok {
			b.WriteString(repl)
		} else {
			b.WriteRune(low)
		}
	}

	return b.String()
}

// hasKeywordBefore reports whether a folded keyword, as a whole word, lies in the
// window runes before byte offset start.
func hasKeywordBefore(text string, start int, keywords []string, window int) bool {
	lo := start
	for i := 0; i < window && lo > 0; i++ {
		_, size := utf8.DecodeLastRuneInString(text[:lo])
		lo -= size
	}

	haystack := fold(text[lo:start])

	// A keyword at the very start of the window must not be the tail of a longer
	// word the window cut through.
	cutWord := false
	if lo > 0 {
		r, _ := utf8.DecodeLastRuneInString(text[:lo])
		cutWord = isWordRune(r)
	}

	for _, kw := range keywords {
		from := 0

		for {
			idx := strings.Index(haystack[from:], kw)
			if idx < 0 {
				break
			}

			pos := from + idx
			end := pos + len(kw)

			leftOK := !cutWord
			if pos > 0 {
				r, _ := utf8.DecodeLastRuneInString(haystack[:pos])
				leftOK = !isWordRune(r)
			}

			rightOK := end == len(haystack)
			if !rightOK {
				r, _ := utf8.DecodeRuneInString(haystack[end:])
				rightOK = !isWordRune(r)
			}

			if leftOK && rightOK {
				return true
			}

			_, size := utf8.DecodeRuneInString(haystack[pos:])
			from = pos + size
		}
	}

	return false
}

// contextDetector wraps a detector and keeps only the findings preceded by one of
// its keywords within the window (the spec's requires_context gate).
type contextDetector struct {
	inner    Detector
	keywords []string // folded
	window   int
}

// withContext gates d behind keywords (folded here) and a window in characters.
func withContext(d Detector, keywords []string, window int) Detector {
	folded := make([]string, len(keywords))
	for i, k := range keywords {
		folded[i] = fold(k)
	}

	return contextDetector{inner: d, keywords: folded, window: window}
}

func (d contextDetector) Entity() Entity { return d.inner.Entity() }

func (d contextDetector) Find(text string) []Finding {
	var out []Finding

	for _, f := range d.inner.Find(text) {
		if hasKeywordBefore(text, f.Start, d.keywords, d.window) {
			out = append(out, f)
		}
	}

	return out
}
