"""National identifiers (FR, ES): validators, shapes, and overlap with PHONE/CARD.

Test numbers are computed here from the public algorithms (forward: pick a body,
derive the check), never copied from another library's test vectors. The golden
corpus (corpus/build_corpus.py) holds the bulk of the cases, shared with Go.
"""

from __future__ import annotations

import pytest

from pii import Tier1Detector, load_entities, spec_policy
from pii.validators import ES_ID_LETTERS, es_dni, es_nie, fr_nir, fr_siren, fr_siret, fr_tax_id, luhn


def _found(text: str) -> list[tuple[str, str]]:
    return [(f.entity, f.value) for f in Tier1Detector().detect(text)]


def test_spec_policy_matches_the_spec() -> None:
    assert spec_policy() == {e.name: e.default_policy for e in load_entities()}


# --- FR_NIR ------------------------------------------------------------------
def nir(body13: str) -> str:
    """Append the NIR key to a 13-character body (2A/2B read as 19/18)."""
    dept = body13[5:7].upper()
    digits = body13[:5] + {"2A": "19", "2B": "18"}.get(dept, dept) + body13[7:]
    return body13 + f"{97 - int(digits) % 97:02d}"


def test_nir_key_compact_and_grouped() -> None:
    value = nir("2931612345678")
    assert fr_nir(value)
    grouped = f"{value[0]} {value[1:3]} {value[3:5]} {value[5:7]} {value[7:10]} {value[10:13]} {value[13:]}"
    assert fr_nir(grouped)
    assert fr_nir(grouped.replace(" ", "."))
    assert fr_nir(grouped.replace(" ", "-"))


def test_nir_corsica_substitution() -> None:
    for dept in ("2A", "2B"):
        value = nir(f"19115{dept}004017")
        assert fr_nir(value), value
        assert fr_nir(value.lower())
    # The same key does not validate under the other Corsican code.
    assert not fr_nir(nir("191152A004017").replace("2A", "2B"))


def test_nir_rejects_a_changed_digit_and_a_bad_first_digit() -> None:
    value = nir("1661599123456")
    assert fr_nir(value)
    changed = value[:8] + str((int(value[8]) + 1) % 10) + value[9:]
    assert not fr_nir(changed)
    assert not fr_nir("3" + value[1:])  # sex digit must be 1, 2, 7 or 8


def test_grouped_nir_is_not_reported_as_phone() -> None:
    value = nir("2711864231009")
    grouped = f"{value[0]} {value[1:3]} {value[3:5]} {value[5:7]} {value[7:10]} {value[10:13]} {value[13:]}"
    # The grouped form is also phone-shaped (15 digits); the checksum reading wins.
    assert _found(f"NIR : {grouped}.") == [("FR_NIR", grouped)]


def test_nir_inside_a_longer_digit_run_is_not_claimed() -> None:
    value = nir("2711864231009")
    assert _found(f"ref 9{value}") == []
    assert _found(f"ref {value}7") == []
    assert ("FR_NIR", value) not in _found(f"ref 12 {value}")


# --- FR_TAX_ID ---------------------------------------------------------------
def tax_id(head10: str) -> str:
    return head10 + f"{int(head10) % 511:03d}"


def test_tax_id_check_and_first_digit() -> None:
    value = tax_id("0000000042")
    assert fr_tax_id(value)
    assert fr_tax_id(f"{value[:2]} {value[2:4]} {value[4:7]} {value[7:10]} {value[10:]}")
    assert not fr_tax_id(value[:12] + str((int(value[12]) + 1) % 10))
    assert not fr_tax_id(tax_id("4000000042"))  # first digit must be 0-3


def test_grouped_tax_id_is_not_reported_as_phone() -> None:
    value = tax_id("0000000043")
    grouped = f"{value[:2]} {value[2:4]} {value[4:7]} {value[7:10]} {value[10:]}"
    assert _found(f"numéro fiscal {grouped}") == [("FR_TAX_ID", grouped)]


# --- FR_SIREN / FR_SIRET (keyword-gated) -------------------------------------
def luhn_complete(body: str) -> str:
    """Append the digit that makes body Luhn-valid."""
    return next(body + d for d in "0123456789" if luhn(body + d))


def la_poste_siret(nic4: str) -> str:
    body = "356000000" + nic4
    return next(body + d for d in "0123456789" if sum(map(int, body + d)) % 5 == 0)


def test_siren_and_siret_checksums() -> None:
    siren = luhn_complete("00012345")
    assert fr_siren(siren) and fr_siren(f"{siren[:3]} {siren[3:6]} {siren[6:]}")
    assert not fr_siren(siren[:8] + str((int(siren[8]) + 1) % 10))
    siret = luhn_complete(siren + "0001")
    assert fr_siret(siret)
    assert not fr_siret(siret[:13] + str((int(siret[13]) + 1) % 10))


def test_la_poste_siret_uses_the_digit_sum_rule() -> None:
    siret = la_poste_siret("1234")
    assert not luhn(siret)  # this one fails Luhn, yet is a valid La Poste SIRET
    assert fr_siret(siret)
    assert not fr_siret(siret[:13] + str((int(siret[13]) + 1) % 10))


def test_siret_needs_a_luhn_valid_siren() -> None:
    bad_siren = "000123450"
    assert not luhn(bad_siren)
    siret = luhn_complete(bad_siren + "0001")
    assert luhn(siret) and not fr_siret(siret)
    assert _found(f"SIRET {siret}") == []


def test_la_poste_head_office_siret_passes_on_luhn() -> None:
    siret = luhn_complete("3560000000001")
    assert sum(map(int, siret)) % 5 != 0  # only the Luhn rule accepts it
    assert fr_siret(siret)


def test_siren_needs_a_keyword() -> None:
    siren = luhn_complete("00012345")
    assert _found(f"SIREN {siren}") == [("FR_SIREN", siren)]
    assert _found(f"Numéro d'identification : {siren}") == [("FR_SIREN", siren)]
    assert _found(f"order {siren} shipped") == []
    assert _found(f"{siren} is our siren") == []  # the keyword must come first


def test_siren_keyword_typed_decomposed_opens_the_gate() -> None:
    siren = luhn_complete("00012345")
    nfd = "Nume\u0301ro d'entreprise"  # e + U+0301, as some keyboards and PDFs emit
    assert _found(f"{nfd} : {siren}") == [("FR_SIREN", siren)]


def test_siren_keyword_must_fit_inside_the_window() -> None:
    # The whole keyword must lie in the 40 characters before the number.
    siren = luhn_complete("00012345")
    assert _found("siren" + " " * 35 + siren) == [("FR_SIREN", siren)]
    assert _found("siren" + " " * 36 + siren) == []


def test_siret_wins_over_its_own_siren_prefix() -> None:
    siren = luhn_complete("00012345")
    siret = luhn_complete(siren + "0001")
    grouped = f"{siret[:3]} {siret[3:6]} {siret[6:9]} {siret[9:]}"
    assert _found(f"SIRET : {grouped}") == [("FR_SIRET", grouped)]
    # A checksum-invalid SIRET does not degrade into a SIREN match on its prefix;
    # grouped, it is phone-shaped and the phone heuristic keeps it.
    bad = grouped[:-1] + str((int(grouped[-1]) + 1) % 10)
    assert _found(f"SIRET : {bad}") == [("PHONE", bad)]
    assert _found(f"SIRET : {bad.replace(' ', '')}") == []


def test_siret_with_a_card_issuer_prefix_is_siret_after_a_keyword() -> None:
    # A Luhn-valid 14-digit number starting 30/36/38 is also a Diners card. After
    # a SIRET keyword the spec order breaks the tie for FR_SIRET; without one, it
    # stays a card. A published gateway test card whose first nine digits also
    # pass Luhn (see corpus/synth_ids.py).
    siret = "36438999960016"
    assert fr_siret(siret) and luhn(siret)
    assert _found(f"siret {siret}") == [("FR_SIRET", siret)]
    assert _found(f"ref {siret}") == [("CREDIT_CARD", siret)]


# --- ES_DNI / ES_NIE ---------------------------------------------------------
def dni(number8: str) -> str:
    return number8 + ES_ID_LETTERS[int(number8) % 23]


def nie(prefix: str, number7: str) -> str:
    return prefix + number7 + ES_ID_LETTERS[int(str("XYZ".index(prefix)) + number7) % 23]


def _other_letter(value: str) -> str:
    return value[:-1] + ("A" if value[-1] != "A" else "B")


def test_dni_letter_and_forms() -> None:
    value = dni("99151623")
    for form in (value, f"{value[:8]}-{value[8]}", f"{value[:2]}.{value[2:5]}.{value[5:8]}-{value[8]}"):
        assert es_dni(form), form
    assert not es_dni(_other_letter(value))
    assert _found(f"DNI {value}") == [("ES_DNI", value)]


def test_dni_lowercase_letter_is_prose_not_an_id() -> None:
    value = dni("99151623")
    assert _found(f"el pedido {value[:8]} {value[8].lower()} más") == []


# X and Y bodies are fully issued; 0000000 is the only body no one holds. Z is
# still being issued from the bottom, so a body starting with 9 is unissued.
NIE_BODIES = {"X": "0000000", "Y": "0000000", "Z": "9481516"}


def test_nie_prefixes() -> None:
    for prefix, body in NIE_BODIES.items():
        value = nie(prefix, body)
        assert es_nie(value) and es_nie(f"{prefix}-{body}-{value[-1]}")
        assert not es_nie(_other_letter(value))
        assert _found(f"NIE: {value}.") == [("ES_NIE", value)]
    # The prefix is part of the number: 10**7 mod 23 != 0, so X and Y never share a letter.
    assert not es_nie("Y" + nie("X", "0000000")[1:])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
