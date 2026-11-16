"""Tier-1 validators: checksum / structure tests that turn broad regex matches
into high-precision findings.

Names match the ``validator`` keys in ``spec/entities.yaml``. These mirror the Go
implementation in ``detectors.go`` so both languages agree on the golden corpus.
Grounded in ``docs/research-deterministic-validators.md``.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

try:  # optional extra: pip install "algolia-pii[phone]"
    import phonenumbers
except ImportError:  # pragma: no cover - exercised by the no-extra install path
    phonenumbers = None  # type: ignore[assignment]

#: True when Google's libphonenumber backing is importable. Detection never
#: hard-requires it; it only tightens phone precision when explicitly enabled
#: (see ``phone_digits_strict`` and ``Tier1Detector(strict_phone=True)``). The Go
#: implementation has no equivalent and stays on the digit-count heuristic.
PHONENUMBERS_AVAILABLE: bool = phonenumbers is not None


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def luhn(number_digits: str) -> bool:
    """Luhn checksum (ISO/IEC 7812-1) over a digit string."""
    total = 0
    double = False
    for ch in reversed(number_digits):
        d = ord(ch) - ord("0")
        if double:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        double = not double
    return total % 10 == 0


def _valid_card_network(d: str) -> bool:
    """Recognized issuer IIN prefix + allowed length. Luhn alone is insufficient:
    e.g. '1111222233334444' passes Luhn but has no issuable IIN."""
    n = len(d)
    p2, p4 = d[:2], d[:4]
    if d[0] == "4":  # Visa
        return n in (13, 16, 19)
    if "51" <= p2 <= "55" and n == 16:  # Mastercard
        return True
    if len(d) >= 4 and "2221" <= p4 <= "2720" and n == 16:  # Mastercard 2-series
        return True
    if p2 in ("34", "37") and n == 15:  # Amex
        return True
    if p4 == "6011" and n in (16, 19):  # Discover
        return True
    if p2 == "65" and n in (16, 19):  # Discover
        return True
    if p2 in ("36", "38", "30") and 14 <= n <= 19:  # Diners
        return True
    if len(d) >= 4 and "3528" <= p4 <= "3589" and 16 <= n <= 19:  # JCB
        return True
    return False


def valid_credit_card(match: str) -> bool:
    """Luhn + IIN prefix + length (the spec key 'luhn' means this full check)."""
    d = _digits(match)
    if not (13 <= len(d) <= 19):
        return False
    return _valid_card_network(d) and luhn(d)


def _card_shape(sizes: list[int]) -> bool:
    """Group sizes of a printed card: one compact group, 4-digit groups with a
    shorter last one (4-4-4-4, 4-4-4-4-3), or Amex/Diners 4-6-5 and 4-6-4."""
    if len(sizes) == 1 or sizes in ([4, 6, 5], [4, 6, 4]):
        return True
    return all(n == 4 for n in sizes[:-1]) and 1 <= sizes[-1] <= 4


def card_spans(text: str, start: int, end: int) -> tuple[list[tuple[int, int]], int]:
    """Card spans inside the digit run text[start:end] (spec CREDIT_CARD regex).

    The run as a whole when it validates (any grouping, as before); otherwise
    windows of whole digit groups holding 13-19 digits and printed like a card
    (_card_shape), so a trailing expiry or CVV, or a leading short reference, no
    longer hides the card. From each group the longest valid window wins, and the
    scan moves past it. A compact run of 20+ digits (a long id) has no window, and
    the shape rule keeps runs of small numbers from yielding one."""
    groups: list[tuple[int, int]] = []
    i = start
    while i < end:
        j = i
        while j < end and "0" <= text[j] <= "9":
            j += 1
        groups.append((i, j))
        i = j + 1  # skip the single separator
    sizes = [b - a for a, b in groups]
    spans: list[tuple[int, int]] = []
    g = 0
    while g < len(groups):
        best = -1
        digits = ""
        if text[groups[g][0]] not in "23456":  # no issuer prefix starts otherwise
            g += 1
            continue
        for k in range(g, len(groups)):
            digits += text[groups[k][0] : groups[k][1]]
            if len(digits) > 19:
                break
            whole = g == 0 and k == len(groups) - 1
            if (
                len(digits) >= 13
                and _valid_card_network(digits)
                and (whole or _card_shape(sizes[g : k + 1]))
                and luhn(digits)
            ):
                best = k
        if best < 0:
            g += 1
            continue
        spans.append((groups[g][0], groups[best][1]))
        g = best + 1
    return spans, end


# Official IBAN length per country (ISO 13616 / SWIFT IBAN Registry). An IBAN's
# length is fixed per country, so a string whose length is wrong for its country
# code is not an IBAN even if it happens to satisfy mod-97. Countries absent from
# the table fall back to the generic 15..34 bound (graceful degradation: we never
# drop a real IBAN from a country we simply haven't tabled yet).
#
# The table is a single cross-language SSOT: ``iban_lengths.json`` (89 countries,
# cross-checked against Wikipedia's IBAN registry table and iban.com/structure;
# see docs/research-deterministic-validators.md). Go embeds the SAME file via
# //go:embed, so the two implementations cannot drift. Loaded once at import.


def _load_iban_lengths() -> dict[str, int]:
    """Load the country->length table from the packaged JSON (installed wheel),
    falling back to the repo-root SSOT for an editable checkout."""
    try:
        packaged = resources.files("pii") / "iban_lengths.json"
        if packaged.is_file():
            return json.loads(packaged.read_text(encoding="utf-8"))
    except (ModuleNotFoundError, FileNotFoundError):
        pass

    fallback = Path(__file__).resolve().parents[2] / "spec" / "iban_lengths.json"
    return json.loads(fallback.read_text(encoding="utf-8"))


IBAN_LENGTHS: dict[str, int] = _load_iban_lengths()


#: Separators allowed between the printed 4-character IBAN groups: space, no-break
#: space, thin space, narrow no-break space, dot, hyphen (spec IBAN regex).
IBAN_SEPARATORS = "\u0020\u00a0\u2009\u202f.-"


def iban_mod97(match: str) -> bool:
    """IBAN validation: per-country length (ISO 13616) + mod-97 checksum
    (ISO 7064 MOD 97-10). Length is checked against the country code first, so a
    wrong-length string is rejected before the (more expensive) checksum.

    Grouped or lowercase input is a looser shape, so it must use one separator
    kind, must not mix cases, and needs a country in the length table."""
    seps = {ch for ch in match if ch in IBAN_SEPARATORS}
    if len(seps) > 1:
        return False
    raw = "".join(ch for ch in match if ch not in IBAN_SEPARATORS)
    if raw != raw.upper() and raw != raw.lower():
        return False  # mixed case reads as a token (base62 id, key), not an IBAN
    s = raw.upper()
    if not (15 <= len(s) <= 34):
        return False
    expected = IBAN_LENGTHS.get(s[:2])
    if expected is None and (seps or raw != s):
        return False
    if expected is not None and len(s) != expected:
        return False
    rearranged = s[4:] + s[:4]  # move the first four chars to the end
    remainder = 0
    for ch in rearranged:
        if ch.isdigit():
            n = ord(ch) - ord("0")
        elif "A" <= ch <= "Z":
            n = ord(ch) - ord("A") + 10
        else:
            return False
        remainder = (remainder * 100 + n) % 97 if n > 9 else (remainder * 10 + n) % 97
    return remainder == 1


def iban_spans(text: str, start: int, end: int) -> tuple[list[tuple[int, int]], int]:
    """Spans of the IBAN regex match text[start:end], and where to resume scanning.

    A grouped match may have swallowed trailing 4-character groups that are not
    part of the IBAN (a word, or a second IBAN after a 16-character one). When the
    whole match fails, cut it at the country's IBAN length, but only where a
    separator follows, so the cut drops whole groups. Scanning resumes at the cut,
    so an IBAN that follows is still found."""
    value = text[start:end]
    if iban_mod97(value):
        return [(start, end)], end
    expected = IBAN_LENGTHS.get(value[:2].upper())
    if expected is None or not any(ch in IBAN_SEPARATORS for ch in value):
        return [], end
    seen = 0
    for i, ch in enumerate(value):
        if ch not in IBAN_SEPARATORS:
            seen += 1
            if seen == expected:
                cut = i + 1
                if cut < len(value) and value[cut] in IBAN_SEPARATORS and iban_mod97(value[:cut]):
                    return [(start, start + cut)], start + cut
                break
    return [], end


def ipv4_octets(match: str) -> bool:
    """Each of four dot-separated octets is in 0..255."""
    parts = match.strip().split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        if not p.isdigit() or not (0 <= int(p) <= 255):
            return False
    return True


def _is_ipv4_shaped(s: str) -> bool:
    """Exactly four dot-separated all-digit groups (valid range or not)."""
    parts = s.strip().split(".")
    return len(parts) == 4 and all(p.isdigit() and p != "" for p in parts)


def _is_arxiv_id(s: str) -> bool:
    """arXiv identifier ``NNNN.NNNNN`` (e.g. 2506.12345): a 4-digit YYMM, a single
    dot, then a 4-5 digit sequence. Not a dialable number, but a digit-count phone
    heuristic accepts it (9 digits, not a dotted quad). See corpus dev_tooling.jsonl."""
    left, sep, right = s.strip().partition(".")
    if not sep or "." in right:
        return False
    return left.isdigit() and right.isdigit() and len(left) == 4 and 4 <= len(right) <= 5


def phone_digits(match: str) -> bool:
    """E.164 allows 9..15 significant digits. A dotted quad is an IP, not a phone,
    and an arXiv identifier (NNNN.NNNNN) is a citation token, not a phone."""
    if _is_ipv4_shaped(match):
        return False
    if _is_arxiv_id(match):
        return False
    n = len(_digits(match))
    return 9 <= n <= 15


def phone_digits_strict(match: str) -> bool:
    """Optional libphonenumber-backed phone validation.

    Layered on top of the deterministic heuristic so it can only *raise* precision:

    1. The digit-count heuristic (``phone_digits``) is the floor. If it rejects,
       so do we -- the extra never widens recall.
    2. If the ``phonenumbers`` extra is absent, the heuristic result stands
       (genuine optionality: core install behaves exactly as today).
    3. If present and the candidate parses (E.164 ``+CC`` form, or otherwise
       region-determinable), require ``is_valid_number`` -- this rejects
       digit-strings the heuristic accepts but that are not dialable (impossible
       national length, unassigned area code, ...).
    4. If present but the candidate cannot be parsed region-free (a bare national
       number with no country code, e.g. ``05.36.49.56.78``), fall back to the
       heuristic result rather than drop a number we cannot judge.

    Enabled only via ``Tier1Detector(strict_phone=True)``; the default detector
    (and therefore the cross-language golden corpus) keeps the deterministic
    ``phone_digits`` so its result stays environment-independent and matches Go.
    """
    if not phone_digits(match):
        return False
    if phonenumbers is None:
        return True
    try:
        parsed = phonenumbers.parse(match, None)
    except phonenumbers.NumberParseException:
        return True  # not region-determinable -> keep the heuristic's decision
    return bool(phonenumbers.is_valid_number(parsed))


def _compact(match: str) -> str:
    """Drop the separators the national-identifier regexes allow."""
    return "".join(ch for ch in match if ch not in " .-")


def _ascii_digits(s: str) -> bool:
    return s != "" and all("0" <= ch <= "9" for ch in s)


def fr_nir(match: str) -> bool:
    """French NIR: 13 characters then a 2-digit key, key = 97 - (first13 mod 97).

    Structure per INSEE (definition c1409): sex, year, month, place (5), order (3),
    key (2). For the arithmetic, Corsica's 2A and 2B department codes read as 19
    and 18. The first digit is 1 or 2, or 7 or 8 for temporary numbers.
    """
    s = _compact(match).upper()
    if len(s) != 15 or s[0] not in "1278":
        return False
    body, key = s[:13], s[13:]
    dept = body[5:7]
    if dept == "2A":
        body = body[:5] + "19" + body[7:]
    elif dept == "2B":
        body = body[:5] + "18" + body[7:]
    if not (_ascii_digits(body) and _ascii_digits(key)):
        return False
    return 97 - int(body) % 97 == int(key)


def fr_tax_id(match: str) -> bool:
    """French numero fiscal (SPI): 13 digits, first digit 0-3, and the last three
    digits equal the first ten taken as an integer, mod 511."""
    s = _compact(match)
    if len(s) != 13 or not _ascii_digits(s) or s[0] not in "0123":
        return False
    return int(s[:10]) % 511 == int(s[10:])


#: La Poste's SIREN. Its establishments' SIRET numbers do not satisfy Luhn; the
#: rule for them is that the 14 digits sum to a multiple of 5.
LA_POSTE_SIREN = "356000000"


def fr_siren(match: str) -> bool:
    """French SIREN: 9 digits, Luhn."""
    s = _compact(match)
    return len(s) == 9 and _ascii_digits(s) and luhn(s)


def fr_siret(match: str) -> bool:
    """French SIRET: a Luhn-valid SIREN + 5-digit NIC, Luhn over the 14 digits.
    La Poste establishments may use digit sum mod 5 == 0 instead; its Luhn-valid
    numbers (the head office) stay valid."""
    s = _compact(match)
    if len(s) != 14 or not _ascii_digits(s):
        return False
    if s[:9] == LA_POSTE_SIREN:
        return luhn(s) or sum(int(ch) for ch in s) % 5 == 0
    return luhn(s[:9]) and luhn(s)


#: Spanish DNI/NIE control letters, indexed by the number mod 23 (Spanish
#: Ministry of the Interior's published table).
ES_ID_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def es_dni(match: str) -> bool:
    """Spanish DNI: 8 digits, then the letter at ES_ID_LETTERS[number mod 23]."""
    s = _compact(match)
    if len(s) != 9 or not _ascii_digits(s[:8]):
        return False
    return ES_ID_LETTERS[int(s[:8]) % 23] == s[8]


def es_nie(match: str) -> bool:
    """Spanish NIE: X/Y/Z read as 0/1/2, 7 digits, then the DNI letter rule."""
    s = _compact(match)
    if len(s) != 9 or s[0] not in "XYZ" or not _ascii_digits(s[1:8]):
        return False
    return ES_ID_LETTERS[int(str("XYZ".index(s[0])) + s[1:8]) % 23] == s[8]


# Registry keyed by the names used in spec/entities.yaml.
VALIDATORS = {
    "luhn": valid_credit_card,
    "iban_mod97": iban_mod97,
    "ipv4_octets": ipv4_octets,
    "phone_digits": phone_digits,
    "phone_digits_strict": phone_digits_strict,
    "fr_nir": fr_nir,
    "fr_tax_id": fr_tax_id,
    "fr_siret": fr_siret,
    "fr_siren": fr_siren,
    "es_dni": es_dni,
    "es_nie": es_nie,
}

#: Span refiners, keyed by validator name. A refiner turns one regex match into the
#: spans to report (each already validated) and the offset where the scan resumes;
#: the Tier-1 detector uses it in place of the plain validator.
SPANNERS = {
    "luhn": card_spans,
    "iban_mod97": iban_spans,
}
