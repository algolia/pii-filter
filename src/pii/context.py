"""Keyword gate for context-required ("Tier 1.5") entities.

Some identifiers carry a checksum too weak to stand alone (a 9-digit SIREN passes
Luhn one time in ten). The spec marks them ``requires_context: true`` with a list
of ``context_keywords`` and a ``context_window``: a match is reported only when a
keyword lies whole inside the ``context_window`` characters before it.

Matching is case-insensitive and accent-insensitive through an explicit fold
table rather than Unicode normalization, so the Go implementation (context.go)
can reproduce it character for character. Keep the two tables identical.
Combining marks (U+0300-U+036F) are dropped, so decomposed (NFD) accents fold
like precomposed ones.
"""

from __future__ import annotations

_FOLD = {
    **dict.fromkeys("àáâãäåā", "a"),
    "æ": "ae",
    "ç": "c",
    **dict.fromkeys("èéêëē", "e"),
    **dict.fromkeys("ìíîïī", "i"),
    "ñ": "n",
    **dict.fromkeys("òóôõöøō", "o"),
    "œ": "oe",
    **dict.fromkeys("ùúûüū", "u"),
    **dict.fromkeys("ýÿ", "y"),
    "ß": "ss",
    **dict.fromkeys("‘’ʼ", "'"),
}


# Explicit, so both languages agree (str.isspace and Go's unicode.IsSpace differ
# on control characters). U+202F is the narrow no-break space French puts before ":".
_SPACES = frozenset(" \t\n\r\f\v\u00a0\u2009\u202f")


def _is_word_char(ch: str) -> bool:
    return ch.isalpha() or ch.isdecimal()


def fold(text: str) -> str:
    """Lowercase, strip the common Latin accents and every combining mark, unify
    apostrophes, and collapse every whitespace run to one space."""
    out: list[str] = []
    in_space = False
    for ch in text:
        if "\u0300" <= ch <= "\u036f":
            continue
        if ch in _SPACES:
            if not in_space:
                out.append(" ")
            in_space = True
            continue
        in_space = False
        low = ch.lower()
        if len(low) != 1:  # e.g. U+0130 lowercases to two code points; keep it as is
            low = ch
        out.append(_FOLD.get(low, low))
    return "".join(out)


def has_keyword_before(text: str, start: int, keywords: tuple[str, ...], window: int) -> bool:
    """True when a keyword, as a whole word, lies in the ``window`` characters
    before ``start``. ``keywords`` must already be folded (see :func:`fold`)."""
    lo = max(0, start - window)
    haystack = fold(text[lo:start])
    # A keyword at the very start of the window must not be the tail of a longer
    # word the window cut through.
    cut_word = lo > 0 and _is_word_char(text[lo - 1])
    for kw in keywords:
        pos = haystack.find(kw)
        while pos != -1:
            end = pos + len(kw)
            left_ok = (not cut_word) if pos == 0 else not _is_word_char(haystack[pos - 1])
            right_ok = end == len(haystack) or not _is_word_char(haystack[end])
            if left_ok and right_ok:
                return True
            pos = haystack.find(kw, pos + 1)
    return False
