"""Synthetic national identifiers for the golden corpus, built from the public
algorithms with a seeded RNG.

Every number here is generated forward (pick a body, derive the check) from the
algorithm descriptions: INSEE's NIR structure with the mod-97 key, the numero
fiscal mod-511 check, Luhn (ISO/IEC 7812-1) for SIREN/SIRET with La Poste's
digit-sum rule, and the Spanish DNI/NIE letter table. Nothing is copied from
another library's code or test vectors, and nothing imports the pii package, so
the corpus does not grade the detectors with their own code.

Bodies are built inside bands real numbers do not come from, as far as public
descriptions let us tell. None was looked up one by one, and nothing here proves
a number is unissued; where a band is only unlikely, we say so. Checksum
negatives change one digit inside the band, never the band prefix.

- FR_NIR: birth month 14-19. Published month codes are 01-12, 20 and 30-42 or
  50-99 (DSN rule); one description also lists 13, so we skip it. The detector
  does not check the month, so these still match. Strongest construction here.
- ES_DNI: numbers 99 000 000 and up. Numbers are handed out in blocks and an
  unofficial estimate puts issuance at 55-60 million, so this band is unlikely
  to be in use. Unlikely, not impossible. DNI-shaped near misses use it too.
- ES_NIE: the X and Y series were issued through, so X and Y rows use only the
  body 0000000 (variety comes from the written form: compact, dashes, spaces).
  Z numbers start with 9, the far end of the series issued since about 2019.
- FR_SIREN / FR_SIRET: SIRENs start with 000. INSEE calls the number
  non-significant; one non-official source says a SIREN never starts with 0.
  Unlikely, not impossible. Two exceptions: La Poste's 356000000 (a public
  legal entity whose SIRET rule needs it) and the overlap row that needs a
  card prefix, which uses a published Diners test card (DINERS_TEST_CARD).
- FR_TAX_ID: plainly sequential bodies 0000000001, 0000000002, ... with the
  mod-511 check derived. We know of no published unissued range, so this is not
  provably unissued; a run of leading zeros is only an implausible real number.
  Checksum negatives change a check digit, so the body stays sequential.
"""

from __future__ import annotations

import random

ES_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def luhn_complete(body: str) -> str:
    return next(body + d for d in "0123456789" if luhn_ok(body + d))


def digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def change_one_digit(rng: random.Random, value: str, lo: int, hi: int) -> str:
    """Replace one digit in value[lo:hi] by a different digit."""
    positions = [i for i in range(lo, hi) if value[i].isdigit()]
    i = rng.choice(positions)
    new = rng.choice([d for d in "0123456789" if d != value[i]])
    return value[:i] + new + value[i + 1 :]


# --- FR_NIR ------------------------------------------------------------------
def nir_key(body13: str) -> str:
    dept = body13[5:7].upper()
    numeric = body13[:5] + {"2A": "19", "2B": "18"}.get(dept, dept) + body13[7:]
    return f"{97 - int(numeric) % 97:02d}"


def nir_ok(value: str) -> bool:
    s = value.replace(" ", "").replace(".", "").replace("-", "").upper()
    return len(s) == 15 and s[0] in "1278" and nir_key(s[:13]) == s[13:]


def nir(rng: random.Random, sex: str | None = None, dept: str | None = None) -> str:
    """15-character compact NIR: sex, yy, mm, dept (2), commune (3), order (3), key."""
    sex = sex or rng.choice("12")
    yy = f"{rng.randrange(100):02d}"
    mm = f"{rng.randrange(14, 20):02d}"  # never a real birth month code, see the header
    if dept is None:
        dept = rng.choice(["75", "69", "13", "33", "59", "44", "67", "31", "06", "35", "97", "99"])
    commune = f"{rng.randrange(1, 1000):03d}"
    order = f"{rng.randrange(1, 1000):03d}"
    body = sex + yy + mm + dept + commune + order
    return body + nir_key(body)


def group_nir(v: str, sep: str = " ") -> str:
    return sep.join([v[:1], v[1:3], v[3:5], v[5:7], v[7:10], v[10:13], v[13:]])


# --- FR_TAX_ID ---------------------------------------------------------------
def tax_ok(value: str) -> bool:
    s = value.replace(" ", "").replace(".", "").replace("-", "")
    return len(s) == 13 and s.isdigit() and s[0] in "0123" and int(s[:10]) % 511 == int(s[10:])


def tax_id(n: int) -> str:
    """The n-th sequential tax ID: 10-digit body n, then the mod-511 check."""
    return f"{n:010d}{n % 511:03d}"  # see the header


def group_tax(v: str, sep: str = " ") -> str:
    return sep.join([v[:2], v[2:4], v[4:7], v[7:10], v[10:]])


# --- FR_SIREN / FR_SIRET -----------------------------------------------------
LA_POSTE = "356000000"
# A Luhn-valid 14-digit number with one of these prefixes is also a Diners card.
DINERS_14 = ("30", "36", "38")


def siren(rng: random.Random) -> str:
    return luhn_complete("000" + digits(rng, 5))  # see the header


def siren_ok(value: str) -> bool:
    s = value.replace(" ", "").replace(".", "").replace("-", "")
    return len(s) == 9 and s.isdigit() and luhn_ok(s)


def siret_ok(value: str) -> bool:
    s = value.replace(" ", "").replace(".", "").replace("-", "")
    if len(s) != 14 or not s.isdigit():
        return False
    if s[:9] == LA_POSTE:
        return luhn_ok(s) or sum(map(int, s)) % 5 == 0
    return luhn_ok(s[:9]) and luhn_ok(s)


def siret(rng: random.Random, siren_value: str | None = None) -> str:
    base = siren_value or siren(rng)
    return luhn_complete(base + f"{rng.randrange(1, 1000):04d}")


def la_poste_siret(rng: random.Random) -> str:
    body = LA_POSTE + f"{rng.randrange(1, 10000):04d}"
    return next(body + d for d in "0123456789" if sum(map(int, body + d)) % 5 == 0)


def group_siren(v: str, sep: str = " ") -> str:
    return sep.join([v[:3], v[3:6], v[6:9]])


def group_siret(v: str, sep: str = " ") -> str:
    return sep.join([v[:3], v[3:6], v[6:9], v[9:]])


# --- ES_DNI / ES_NIE ---------------------------------------------------------
def dni_ok(value: str) -> bool:
    s = value.replace(" ", "").replace(".", "").replace("-", "")
    return len(s) == 9 and s[:8].isdigit() and ES_LETTERS[int(s[:8]) % 23] == s[8]


def dni(rng: random.Random) -> str:
    n = "99" + digits(rng, 6)  # see the header
    return n + ES_LETTERS[int(n) % 23]


def nie_ok(value: str) -> bool:
    s = value.replace(" ", "").replace("-", "")
    if len(s) != 9 or s[0] not in "XYZ" or not s[1:8].isdigit():
        return False
    return ES_LETTERS[int(str("XYZ".index(s[0])) + s[1:8]) % 23] == s[8]


def nie(rng: random.Random, prefix: str) -> str:
    n = ("9" + digits(rng, 6)) if prefix == "Z" else "0000000"  # see the header
    return prefix + n + ES_LETTERS[int(str("XYZ".index(prefix)) + n) % 23]


def other_letter(rng: random.Random, value: str) -> str:
    return value[:-1] + rng.choice([c for c in ES_LETTERS if c != value[-1]])


# --- Published examples (for overlap rows) ------------------------------------
# SWIFT IBAN Registry example for France (release 102, June 2026).
FR_IBAN_EXAMPLE = "FR1420041010050500013M02606"
# Diners Club test card published by First Data / Payeezy and other gateway
# sandboxes. 14 digits, Luhn-valid, and its first nine digits are Luhn-valid too,
# so after a SIRET keyword it also reads as a SIRET. That SIREN (364389999) was
# not in the public SIRENE register (recherche-entreprises.api.gouv.fr) on
# 2026-11-16. Stripe's, Adyen's and PayPal's 14-digit Diners test numbers fail
# the SIREN Luhn, so none of them can pin the SIRET-over-card precedence.
DINERS_TEST_CARD = "36438999960016"


# ARCEP numbering plan, art. 2.5.12 "Numeros pour oeuvres audiovisuelles" (decision
# 2018-0881): six roots ARCEP never assigns, for use in fiction. 06 39 98 is left out:
# libphonenumber rejects it (it sits in the Mayotte mobile block), and the `phone`
# extra may validate.
FR_FICTION_ROOTS = ("01 99 00", "02 61 91", "03 53 01", "04 65 71", "05 36 49")


def fr_fiction_phone(rng: random.Random) -> str:
    return rng.choice(FR_FICTION_ROOTS) + " " + digits(rng, 2) + " " + digits(rng, 2)
