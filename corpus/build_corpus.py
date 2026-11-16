#!/usr/bin/env python3
"""Deterministically build the golden corpus JSONL files.

All data is SYNTHETIC. Every value is invented, constructed in a band that is
not issued, or taken from a published reserved/test range:
- Emails: only RFC 2606 / RFC 6761 names (example.com/.org/.net, *.test).
- IPs: RFC 1918 private ranges and RFC 5737 documentation ranges
  (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24).
- Payment cards: published gateway test numbers only. Stripe (docs.stripe.com/
  testing): 4242 4242 4242 4242, 5555 5555 5555 4444, 4000 0566 5566 5556,
  378282246310005. PayPal / Braintree: 4012888888881881. First Data Payeezy
  (and other gateway sandboxes): Diners 36438999960016, see synth_ids.py.
  Card-shaped negatives fail Luhn or carry no issuable IIN.
- IBANs: the SWIFT IBAN Registry examples (ISO 13616 registry, release 102,
  June 2026), plus GB82WEST12345698765432, the fictitious UK example used in
  ECBS and Wikipedia material. IBAN-shaped negatives fail mod-97.

Phone numbers come only from ranges a regulator reserves for fiction:
- France: ARCEP numbering plan, art. 2.5.12 "Numeros pour oeuvres
  audiovisuelles" (decision 2018-0881, Legifrance JORFARTI000037263033): roots
  01 99 00, 02 61 91, 03 53 01, 04 65 71, 05 36 49 (06 39 98 is also reserved
  but libphonenumber rejects it, so it is not used). The Spanish-text row uses a
  French fiction number: Spain publishes no fiction range.
- Germany: Bundesnetzagentur "Drama Numbers", Berlin (0)30 23125 000-999
  (bundesnetzagentur.de, Nummerierung/DramaNumbers).
- United Kingdom: Ofcom drama numbers, London 020 7946 0000-0999.
- North America: NANPA 555-0100 to 555-0199, reserved for fiction
  (nanpa.com/numbering/555-line-numbers).
Phone-shaped digit groups that are really mistyped IDs (a grouped NIR with a
wrong key, a grouped SIREN) are not dialable numbers.

Spans are computed, never hand-typed: an example is a list of "parts" where a
(TYPE, value) tuple marks a labeled span and a plain string is carrier text.
This makes text[start:end] == value true by construction.

National identifiers (FR_NIR, FR_TAX_ID, FR_SIREN, FR_SIRET, ES_DNI, ES_NIE)
come from corpus/synth_ids.py: bodies drawn inside unissued bands (listed in its
header) with the check derived from the public algorithm, one seeded RNG per
file, so a rerun reproduces every row. Checksum negatives change one digit
inside the band, never the band prefix. FR_TAX_ID has no known unissued band:
its bodies are sequential, see synth_ids.py.

Run:  python3 corpus/build_corpus.py
Emits: corpus/{emails,phones,credit_cards,ibans,ips,mixed,negatives,dev_tooling,
       fr_nir,fr_tax_id,fr_siren,fr_siret,es_dni,es_nie,eu_overlaps}.jsonl
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import synth_ids as ids  # noqa: E402


def build(parts: list) -> dict:
    text = ""
    entities = []
    for part in parts:
        if isinstance(part, tuple):
            etype, value = part
            start = len(text)
            text += value
            entities.append({"type": etype, "start": start, "end": len(text), "value": value})
        else:
            text += part
    return {"text": text, "entities": entities}


def neg(text: str) -> dict:
    return {"text": text, "entities": []}


# --- EMAIL -------------------------------------------------------------------
EMAILS = [
    build(["Please email ", ("EMAIL", "jane.doe@example.com"), " for access."]),
    build(["Forward it to ", ("EMAIL", "ops+alerts@mail.example.org"), " today."]),
    build([("EMAIL", "a_b@sub.example.org"), " is the shared inbox."]),
    build(["Reach support at ", ("EMAIL", "support@example.co.test"), "."]),
    build(["cc ", ("EMAIL", "r.marsh@example.net"), " on the thread"]),
    build(["billing: ", ("EMAIL", "invoices123@example-corp.test")]),
    # hard negatives: look like emails but are not
    neg("Visit example dot com for more information."),
    neg("Use the @channel mention to ping everyone."),
    neg("The ratio was 3@5 in that odd notation."),
]

# --- PHONE -------------------------------------------------------------------
PHONES = [
    build(["Call ", ("PHONE", "+33 1 99 00 12 34"), " after noon."]),
    build(["US line: ", ("PHONE", "+1 (415) 555-0142")]),
    build(["fr line ", ("PHONE", "05.36.49.56.78"), " ok"]),
    build(["London office ", ("PHONE", "+44 20 7946 0958")]),
    build(["reach me on ", ("PHONE", "+49 30 23125 042")]),
    build([("PHONE", "+1-202-555-0188"), " is the hotline."]),
    # hard negatives
    neg("See RFC 2616 section 4.2 for details."),
    neg("The build finished at 2026-06-29 in CI."),
    neg("Only 42 seats remain in room 204."),
]

# --- CREDIT_CARD -------------------------------------------------------------
# Well-known test numbers (Luhn-valid). Hard negatives flip a digit so Luhn fails.
CREDIT_CARDS = [
    build(["Card on file: ", ("CREDIT_CARD", "4242 4242 4242 4242"), "."]),
    build(["pay with ", ("CREDIT_CARD", "5555 5555 5555 4444")]),
    build([("CREDIT_CARD", "4012888888881881"), " was charged."]),
    build(["amex ", ("CREDIT_CARD", "378282246310005"), " expires soon"]),
    build(["visa ", ("CREDIT_CARD", "4000 0566 5566 5556")]),
    # hard negatives: card-shaped but Luhn-INVALID (regex matches, validator rejects)
    neg("Ref 4242 4242 4242 4241 is not a card."),
    neg("Order 1234 5678 9012 3456 shipped."),
    neg("Tracking 1111 2222 3333 4444 today."),
]

# --- IBAN --------------------------------------------------------------------
IBANS = [
    build(["Wire to ", ("IBAN", "DE89370400440532013000"), " please."]),
    build(["account ", ("IBAN", "GB82WEST12345698765432")]),
    build([("IBAN", "FR1420041010050500013M02606"), " is the FR account."]),
    build(["NL test ", ("IBAN", "NL91ABNA0417164300")]),
    # Countries added to the length table: SWIFT IBAN Registry examples whose mod-97
    # checksum and per-country length both validate (release 102, June 2026; each
    # string checked against the registry text). These prove the length table
    # accepts a well-formed IBAN from each country, not just that it rejects
    # wrong-length fakes. Registry examples are format samples, not accounts.
    build(["Burundi account ", ("IBAN", "BI4210000100010000332045181"), "."]),
    build(["Djibouti wire ", ("IBAN", "DJ2100010000000154000100186")]),
    build([("IBAN", "FK88SC123456789012"), " is the Falklands account."]),
    build(["Honduras ", ("IBAN", "HN88CABF00000000000250005469"), " on file"]),
    build(["Mongolia ", ("IBAN", "MN121234123456789123")]),
    build(["Nicaragua refund to ", ("IBAN", "NI45BAPR00000013000003558124")]),
    build(["Oman ", ("IBAN", "OM810180000001299123456"), " please."]),
    build(["Russia ", ("IBAN", "RU0304452522540817810538091310419")]),
    build(["Sudan ", ("IBAN", "SD2129010501234001")]),
    build(["Somalia ", ("IBAN", "SO211000001001000100141")]),
    build(["Yemen ", ("IBAN", "YE15CBYE0001018861234567891234"), " account"]),
    # Printed 4-character groups (ISO 13616 paper format), each separator the spec
    # allows, and lowercase. BE68539007547034 is the registry's Belgian example.
    build(["Bank details: ", ("IBAN", "DE89 3704 0044 0532 0130 00"), "."]),
    build(["IBAN ", ("IBAN", "GB82 WEST 1234 5698 7654 32"), " (sort code on file)"]),
    build(["RIB : ", ("IBAN", "FR14\u00a02004\u00a01010\u00a00505\u00a00001\u00a03M02\u00a0606"), " merci."]),
    build(["NL ", ("IBAN", "NL91\u2009ABNA\u20090417\u20091643\u200900"), " ok"]),
    build(["iban: ", ("IBAN", "NL91.ABNA.0417.1643.00")]),
    build(["Wire to ", ("IBAN", "DE89-3704-0044-0532-0130-00"), " today."]),
    build(["lowercase ", ("IBAN", "gb82west12345698765432"), " pasted from a form"]),
    build(["iban ", ("IBAN", "de89 3704 0044 0532 0130 00"), " in lowercase"]),
    # A 16-character IBAN ends on a full group, so the next word is read as one
    # more group and cut back off at the country length.
    build(["Pay ", ("IBAN", "BE68 5390 0754 7034"), " from the shared account."]),
    build(["Old ", ("IBAN", "BE68 5390 0754 7034"), " new ", ("IBAN", "NL91 ABNA 0417 1643 00"), "."]),
    build(["Accounts ", ("IBAN", "BE68 5390 0754 7034"), " ", ("IBAN", "NL91 ABNA 0417 1643 00"), "."]),
    # hard negatives: IBAN-shaped but mod-97 INVALID
    neg("Code DE00000000000000000000 is a placeholder."),
    neg("Token GB00WEST12345698765432 is fake."),
    neg("Printed DE00 3704 0044 0532 0130 00 has a bad check."),
    # Grouped, but two separator kinds: not the printed format.
    neg("Mixed DE89 3704-0044 0532 0130 00 separators."),
    # Mixed case reads as a token (base62 id, API key), not an IBAN.
    neg("Token De89370400440532013000 in the log."),
    # Passes mod-97, but QQ is no IBAN country: only the uppercase compact form
    # keeps the unknown-country fallback.
    neg("Lowercase qq51abcd0123456789012 is not tabled."),
]

# --- IP ----------------------------------------------------------------------
IPS = [
    build(["Server at ", ("IP", "192.168.1.42"), " is down."]),
    build(["ping ", ("IP", "10.0.0.1")]),
    build([("IP", "203.0.113.8"), " resolves fine."]),
    build(["gateway ", ("IP", "172.16.254.1")]),
    # hard negatives: dotted-quad but octet out of range (regex matches, validator rejects)
    neg("Tried 192.168.1.300 but it failed."),
    neg("The value 999.1.1.1 is invalid."),
    neg("Build 256.0.0.1 is not reachable."),
]

# --- MIXED (multiple entities per text) --------------------------------------
MIXED = [
    build(["Contact ", ("EMAIL", "jane.doe@example.com"), " or call ",
           ("PHONE", "+33 4 65 71 23 45"), "."]),
    build(["From ", ("IP", "10.0.0.1"), ", card ", ("CREDIT_CARD", "4242 4242 4242 4242"),
           " was used."]),
    build(["Send the refund to ", ("IBAN", "DE89370400440532013000"),
           " and email ", ("EMAIL", "invoices123@example-corp.test"), "."]),
]

# --- PURE NEGATIVES (no PII at all) ------------------------------------------
NEGATIVES = [
    neg("The festival opens at 3pm and the gates close at 11pm."),
    neg("Bring a tent, a water bottle, and good vibes."),
    neg("Section 12.4 of the guide covers accessibility."),
    neg("We sold 1,250 tickets across 3 days last year."),
    neg("Meet at the main stage near checkpoint 7."),
]

# --- DEV-TOOLING NEGATIVES (structured-but-non-personal text) ----------------
# Regression fixtures for false-positive classes seen when scrubbing developer-tool
# output (logs, shell sessions, citations). Each is text that MUST
# pass through untouched: dev-tool output is a domain no published PII benchmark
# covers, and its structured tokens (code symbols, paths, month names, citation
# ids) are exactly what pattern/heuristic matchers over-fire on. All entities: [].
DEV_TOOLING = [
    # Month abbreviation in a git-style date: a calendar token is carrier text,
    # not a PERSON mention.
    neg("Committed on Mon Jun 13 in the release branch."),
    # Public identifiers: repo link, go.mod import path, install URL. A published
    # module/repo path carries no PII by virtue of being a path.
    neg("See github.com/algolia/pii-filter for the source."),
    neg("require github.com/algolia/pii-filter v0.1.0"),
    neg("go get github.com/algolia/pii-filter/cmd/pii"),
    # Capitalized method call in a code echo: a .Method() token is a symbol, not a
    # name. The dot + parens context is a hard pass-through signal.
    neg("The handler calls logger.Info() before returning."),
    # CamelCase identifier in a grep/pattern echo: splitting it and tagging the
    # prefix as PERSON mangles a code symbol.
    neg("Matched pattern PatientRecord in the grep echo."),
    # arXiv identifier NNNN.NNNNN: not a dialable number. A digit-count phone
    # heuristic accepts its 9 digits; the arXiv guard (validators._is_arxiv_id /
    # Go isArxivID) rejects it. 21 such ids appear in docs/research-sota-2026-07.md.
    neg("See arXiv:2506.12345 for the benchmark."),
    neg("Reference 2506.12345 in the notes."),
    # git author / shortlog line: an author NAME must pass through (PERSON is
    # Tier-2, not Tier-1). No email here, so the line has zero Tier-1 findings.
    neg("Robin Marsh committed the migration on the feature branch."),
    # git commit SHA: a 40-hex string is not PII.
    neg("Fixed in commit a51519bc9f2e1d3c4b5a6f7e8d9c0b1a2f3e4d5c today."),
    # Semantic version: dotted digits are not a phone (too few digits) nor an IP.
    neg("Upgraded to version 1.2.3 and rebuilt."),
]

# --- NATIONAL IDENTIFIERS ----------------------------------------------------
# Per entity: positives in varied forms and carrier languages, checksum
# negatives (valid shape, one digit or the letter changed), and near misses
# (order numbers, timestamps, barcodes, phone numbers, lookalike lengths). For
# the keyword-gated SIREN/SIRET, the same valid numbers appear with no keyword,
# with the keyword too far before, and with the keyword after.
SEED = "algolia-pii-0.2.0"


def rng_for(name: str) -> random.Random:
    return random.Random(f"{SEED}/{name}")


def pos(entity: str, template: str, value: str) -> dict:
    pre, post = template.split("{}")
    return build([pre, (entity, value), post])


def negt(template: str, value: str) -> dict:
    return neg(template.replace("{}", value))


def gated_far(keyword_text: str, value: str) -> dict:
    """Keyword, then more than the 40-character window of filler, then value."""
    filler = " -- voir la fiche jointe, mise a jour le mois dernier : "
    text = keyword_text + filler + value
    assert len(filler) > 40
    return neg(text)


def _fmt_nir(v: str, i: int) -> str:
    return [v, ids.group_nir(v), ids.group_nir(v, "."), ids.group_nir(v, "-"), v[:13] + " " + v[13:]][i % 5]


def build_fr_nir() -> list[dict]:
    rng = rng_for("FR_NIR")
    carriers = [
        "Numéro de sécurité sociale : {}",
        "NIR {} (assuré principal)",
        "Mon numéro de sécu est le {}, merci.",
        "social security number: {}",
        "N° SS {}.",
        "Carte Vitale de l'assuré : {}",
        "Assuré {} remboursé en mars.",
        "{} est le numéro du bénéficiaire.",
        "Please update the record for {} today.",
        "numero de securite sociale {}",
        "INSEE {} / régime général",
        "Le patient ({}) a appelé.",
    ]
    rows = []
    values = [ids.nir(rng) for _ in range(16)]
    values += [ids.nir(rng, dept="2A"), ids.nir(rng, dept="2B"), ids.nir(rng, dept="2A"), ids.nir(rng, dept="2B")]
    values += [ids.nir(rng, sex="7"), ids.nir(rng, sex="8")]
    for i, v in enumerate(values):
        rows.append(pos("FR_NIR", carriers[i % len(carriers)], _fmt_nir(v, i)))
    # Corsica typed in lowercase still validates.
    corsica = ids.nir(rng, dept="2B")
    rows.append(pos("FR_NIR", "nir corse : {}", ids.group_nir(corsica).lower()))
    # Checksum negatives: compact (a grouped one is phone-shaped, see eu_overlaps).
    for i in range(10):
        v = ids.nir(rng)
        bad = ids.change_one_digit(rng, v, 5, 15)  # keep yy and the 14-19 month
        assert not ids.nir_ok(bad)
        rows.append(negt(carriers[i % len(carriers)], bad))
    # Near misses.
    for _ in range(3):  # 15 digits, first digit not a NIR sex digit
        rows.append(negt("Commande n° {} expédiée.", rng.choice("34569") + ids.digits(rng, 14)))
    rows.append(neg("Horodatage 20261116093015 dans le journal."))
    rows.append(neg("Le 2026-11-16 à 09:30:15, la synchronisation a échoué."))
    rows.append(neg("Montant : 1 234 567,89 euros, échéance 15/12."))
    while True:  # 13-digit NIR body without its key; also TAX_ID-shaped, so fail that too
        body = ids.nir(rng)[:13]
        if not ids.tax_ok(body):
            break
    rows.append(negt("Ticket {} en attente.", body))
    rows.append(negt("Référence {} (16 chiffres).", "1" + ids.digits(rng, 15)))
    phone = ids.fr_fiction_phone(rng)
    rows.append(build(["Tél. ", ("PHONE", phone), " pour le dossier."]))
    return rows


def build_fr_tax_id() -> list[dict]:
    rng = rng_for("FR_TAX_ID")
    carriers = [
        "Numéro fiscal : {}",
        "N° fiscal {}",
        "SPI {} (déclarant 1)",
        "numero fiscal de reference {}",
        "Tax ID {}",
        "Identifiant fiscal : {}.",
        "Votre numéro fiscal ({}) figure en haut de l'avis.",
        "{} est le numéro fiscal du foyer.",
        "Déclarant : {}",
        "Référence {} à rappeler.",
    ]
    rows = []
    for i in range(24):
        v = ids.tax_id(i + 1)
        form = [v, ids.group_tax(v), v, ids.group_tax(v, ".")][i % 4]
        rows.append(pos("FR_TAX_ID", carriers[i % len(carriers)], form))
    for i in range(10):
        v = ids.tax_id(25 + i)
        bad = ids.change_one_digit(rng, v, 10, 13)
        assert not ids.tax_ok(bad)
        rows.append(negt(carriers[i % len(carriers)], bad))
    # Near misses: EAN-13 barcodes with a French GS1 prefix (30-37) start with 3,
    # epoch-millisecond timestamps start with 1; both are 13 digits.
    for _ in range(5):
        while True:
            body = "3" + rng.choice("01234567") + ids.digits(rng, 10)
            check = (10 - sum(int(d) * (3 if k % 2 else 1) for k, d in enumerate(body)) % 10) % 10
            ean = body + str(check)
            if not ids.tax_ok(ean):
                break
        rows.append(negt("Code-barres EAN {} au rayon frais.", ean))
    for _ in range(3):
        while True:
            ms = "17" + ids.digits(rng, 11)
            if not ids.tax_ok(ms):
                break
        rows.append(negt("event timestamp={} ms", ms))
    rows.append(negt("Commande {} validée.", rng.choice("456789") + ids.digits(rng, 12)))
    rows.append(negt("Dossier {} (12 chiffres).", rng.choice("0123") + ids.digits(rng, 11)))
    return rows


SIREN_CARRIERS = [
    "SIREN : {}",
    "Siren {}",
    "N° SIREN {}",
    "RCS Paris {}",
    "RCS Lyon B {}",
    "Numéro d'entreprise : {}",
    "NUMÉRO D'IDENTIFICATION {}",
    "numero d’identification {}",
    "Immatriculation : {}",
    "Company number {}",
    "company registration: {}",
    "Business ID {}",
    "Société au capital de 10 000 euros, SIREN {}",
    "sirene {}",
    "SIRET/SIREN : {}",
    "inscrite au registre du commerce sous le {}",
]
NO_KEYWORD_CARRIERS = [
    "Commande {} expédiée.",
    "Order {} shipped today.",
    "Ticket #{} ouvert.",
    "Le colis {} est arrivé.",
    "ref {}",
]


def build_fr_siren() -> list[dict]:
    rng = rng_for("FR_SIREN")
    rows = []
    for i in range(20):
        v = ids.siren(rng)
        form = [v, ids.group_siren(v), v, ids.group_siren(v, ".")][i % 4]
        rows.append(pos("FR_SIREN", SIREN_CARRIERS[i % len(SIREN_CARRIERS)], form))
    for i in range(10):  # valid SIREN, no keyword (compact: grouped is phone-shaped)
        rows.append(negt(NO_KEYWORD_CARRIERS[i % len(NO_KEYWORD_CARRIERS)], ids.siren(rng)))
    for kw in ("SIREN", "RCS Nanterre", "Numéro d'entreprise"):
        rows.append(gated_far(kw, ids.siren(rng)))
    rows.append(negt("{} est notre siren.", ids.siren(rng)))
    rows.append(negt("{} (siren)", ids.siren(rng)))
    for i in range(8):
        bad = ids.change_one_digit(rng, ids.siren(rng), 3, 9)
        assert not ids.luhn_ok(bad)
        rows.append(negt(SIREN_CARRIERS[i % len(SIREN_CARRIERS)], bad))
    rows.append(negt("SIREN : {} (10 chiffres)", "4" + ids.digits(rng, 9)))
    rows.append(negt("RCS {} incomplet", ids.digits(rng, 8)))
    rows.append(neg("SIREN demandé le 16/11/2026, toujours en attente."))
    phone = ids.fr_fiction_phone(rng)
    rows.append(build(["Company number? Call ", ("PHONE", phone), " instead."]))
    return rows


SIRET_CARRIERS = [
    "SIRET : {}",
    "N° SIRET {}",
    "Siret {}",
    "Numéro d'établissement : {}",
    "NUMÉRO D'ÉTABLISSEMENT {}",
    "SIRET du siège : {}",
    "company registration {}",
    "siret de l'établissement principal : {}",
    "RCS / SIRET {}",
    "sirene {}",
]


def _no_card(rng: random.Random) -> str:
    while True:
        v = ids.siret(rng)
        if not v.startswith(ids.DINERS_14):
            return v


def build_fr_siret() -> list[dict]:
    rng = rng_for("FR_SIRET")
    rows = []
    values = [ids.siret(rng) for _ in range(16)] + [ids.la_poste_siret(rng) for _ in range(4)]
    for i, v in enumerate(values):
        form = [v, ids.group_siret(v), v[:9] + " " + v[9:], v][i % 4]
        rows.append(pos("FR_SIRET", SIRET_CARRIERS[i % len(SIRET_CARRIERS)], form))
    for i in range(10):  # valid SIRET, no keyword, not card-shaped
        rows.append(negt(NO_KEYWORD_CARRIERS[i % len(NO_KEYWORD_CARRIERS)], _no_card(rng)))
    rows.append(gated_far("SIRET", _no_card(rng)))
    rows.append(gated_far("Numéro d'établissement", _no_card(rng)))
    rows.append(negt("{} est le siret du siège.", _no_card(rng)))
    rows.append(negt("{} (SIRET)", _no_card(rng)))
    for i in range(6):
        bad = ids.change_one_digit(rng, ids.siret(rng), 3, 14)
        assert not ids.siret_ok(bad)
        rows.append(negt(SIRET_CARRIERS[i % len(SIRET_CARRIERS)], bad))
    for i in range(2):  # La Poste, digit-sum rule broken
        bad = ids.change_one_digit(rng, ids.la_poste_siret(rng), 9, 14)
        assert not ids.siret_ok(bad)
        rows.append(negt(SIRET_CARRIERS[i], bad))
    while True:  # timestamp after the keyword, Luhn-invalid
        ts = "2026" + ids.digits(rng, 10)
        if not ids.siret_ok(ts):
            break
    rows.append(negt("SIRET mis à jour {}", ts))
    rows.append(negt("SIRET {} (13 chiffres)", rng.choice("456789") + ids.digits(rng, 12)))
    rows.append(negt("N° SIRET {} (15 chiffres)", rng.choice("3456") + ids.digits(rng, 14)))
    for _ in range(2):  # all 14 digits pass Luhn, the embedded SIREN does not
        while True:
            head = rng.choice("12457") + ids.digits(rng, 8)
            if not ids.luhn_ok(head):
                break
        bad = ids.luhn_complete(head + ids.digits(rng, 4))
        assert ids.luhn_ok(bad) and not ids.siret_ok(bad)
        rows.append(negt("SIRET : {}", bad))
    return rows


DNI_CARRIERS = [
    "DNI {}",
    "DNI: {}",
    "Mi DNI es {}.",
    "Documento nacional de identidad {}",
    "NIF {}",
    "titular con DNI {} y domicilio en Madrid",
    "ID card {}",
    "pièce d'identité espagnole {}",
    "{} (DNI del cliente)",
    "El cliente {} firmó el contrato.",
]


def build_es_dni() -> list[dict]:
    rng = rng_for("ES_DNI")
    rows = []
    for i in range(20):
        v = ids.dni(rng)
        form = [v, v[:8] + "-" + v[8], f"{v[:2]}.{v[2:5]}.{v[5:8]}-{v[8]}", v[:8] + " " + v[8]][i % 4]
        rows.append(pos("ES_DNI", DNI_CARRIERS[i % len(DNI_CARRIERS)], form))
    for i in range(5):
        bad = ids.other_letter(rng, ids.dni(rng))
        assert not ids.dni_ok(bad)
        rows.append(negt(DNI_CARRIERS[i % len(DNI_CARRIERS)], bad))
    for i in range(3):
        bad = ids.change_one_digit(rng, ids.dni(rng), 2, 8)
        assert not ids.dni_ok(bad)
        rows.append(negt(DNI_CARRIERS[(i + 5) % len(DNI_CARRIERS)], bad))
    v = ids.dni(rng)
    rows.append(negt("Pedido {} más tarde.", v[:8] + " " + v[8].lower()))  # lowercase letter: prose
    rows.append(neg(f"Pedido 99{ids.digits(rng, 6)} y 99{ids.digits(rng, 6)} enviados."))
    rows.append(neg("Matrícula 4821 BCD aparcada en la calle."))
    for letter in "IOU":  # never a DNI control letter
        rows.append(negt("Ref {} en almacén.", "99" + ids.digits(rng, 6) + letter))
    rows.append(negt("SKU {} agotado.", "99" + ids.digits(rng, 7) + "Z"))
    rows.append(negt("Código postal y código {} sin letra.", "99" + ids.digits(rng, 6)))
    return rows


NIE_CARRIERS = [
    "NIE {}",
    "NIE: {}",
    "Número de identidad de extranjero {}",
    "foreigner id (NIE) {}",
    "Tarjeta de residencia {}",
    "{} es mi NIE.",
    "Titular: {}",
]


def build_es_nie() -> list[dict]:
    rng = rng_for("ES_NIE")
    rows = []
    for i in range(15):
        v = ids.nie(rng, "XYZ"[i % 3])
        form = [v, f"{v[0]}-{v[1:8]}-{v[8]}", v, f"{v[0]} {v[1:8]} {v[8]}", v][i % 5]
        rows.append(pos("ES_NIE", NIE_CARRIERS[i % len(NIE_CARRIERS)], form))
    for i in range(6):
        bad = ids.other_letter(rng, ids.nie(rng, "XYZ"[i % 3]))
        assert not ids.nie_ok(bad)
        rows.append(negt(NIE_CARRIERS[i % len(NIE_CARRIERS)], bad))
    rows.append(negt("Permiso {} caducado.", "W0000000L"))
    rows.append(negt("NIE {} incompleto.", "X000000L"))
    v = ids.nie(rng, "Y")
    rows.append(negt("nie en minúsculas {}", v.lower()))
    rows.append(negt("Modelo {} sin letra final.", "X0000000"))
    return rows


def build_eu_overlaps() -> list[dict]:
    """Overlap resolution, pinned: which entity owns digits two detectors read."""
    rng = rng_for("EU_OVERLAPS")
    rows = []
    # A grouped NIR is also phone-shaped (15 digits): the checksum reading wins.
    nir_g = ids.group_nir(ids.nir(rng))
    rows.append(build(["NIR ", ("FR_NIR", nir_g), " sur la feuille de soins."]))
    # A grouped NIR with a wrong key is still a 15-digit phone-shaped number.
    while True:
        bad = ids.group_nir(ids.change_one_digit(rng, ids.nir(rng), 5, 15))
        if not ids.nir_ok(bad):
            break
    rows.append(build(["NIR ", ("PHONE", bad), " illisible."]))
    tax_g = ids.group_tax(ids.tax_id(35))
    rows.append(build(["Numéro fiscal ", ("FR_TAX_ID", tax_g), " sur l'avis."]))
    # A Luhn-valid 14-digit number starting 36 is also a Diners card: after a
    # SIRET keyword the spec order gives it to FR_SIRET, without one it is a card.
    diners = ids.DINERS_TEST_CARD
    rows.append(build(["SIRET ", ("FR_SIRET", diners), " (siège)"]))
    rows.append(build(["Carte ", ("CREDIT_CARD", diners), " expirée."]))
    siren_g = ids.group_siren(ids.siren(rng))
    rows.append(build(["SIREN ", ("FR_SIREN", siren_g), " au registre."]))
    rows.append(build(["Appelez le ", ("PHONE", ids.group_siren(ids.siren(rng))), " demain."]))
    siret_g = ids.group_siret(ids.siret(rng))
    rows.append(build(["SIRET : ", ("FR_SIRET", siret_g), "."]))
    bad_siret = ids.group_siret(ids.change_one_digit(rng, ids.siret(rng), 9, 14))
    rows.append(build(["SIRET : ", ("PHONE", bad_siret), "."]))
    rows.append(build(["Assuré ", ("FR_NIR", ids.nir(rng)), ", tél. ", ("PHONE", ids.fr_fiction_phone(rng)),
                       ", mail ", ("EMAIL", "assure@example.org"), "."]))
    rows.append(build(["SIREN et IBAN : ", ("IBAN", ids.FR_IBAN_EXAMPLE), " pour le virement."]))
    rows.append(build(["SIRET ", ("CREDIT_CARD", "4242 4242 4242 4242"), " n'est pas un siret."]))
    rows.append(build(["DNI ", ("ES_DNI", ids.dni(rng)), " o llame al ", ("PHONE", "+33 2 61 91 34 56"), "."]))
    return rows


FILES = {
    "emails.jsonl": EMAILS,
    "phones.jsonl": PHONES,
    "credit_cards.jsonl": CREDIT_CARDS,
    "ibans.jsonl": IBANS,
    "ips.jsonl": IPS,
    "mixed.jsonl": MIXED,
    "negatives.jsonl": NEGATIVES,
    "dev_tooling.jsonl": DEV_TOOLING,
    "fr_nir.jsonl": build_fr_nir(),
    "fr_tax_id.jsonl": build_fr_tax_id(),
    "fr_siren.jsonl": build_fr_siren(),
    "fr_siret.jsonl": build_fr_siret(),
    "es_dni.jsonl": build_es_dni(),
    "es_nie.jsonl": build_es_nie(),
    "eu_overlaps.jsonl": build_eu_overlaps(),
}


def main() -> None:
    for name, rows in FILES.items():
        path = HERE / name
        with path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        n_ent = sum(len(r["entities"]) for r in rows)
        print(f"  {name:18} {len(rows):3} examples, {n_ent:3} labeled spans")


if __name__ == "__main__":
    main()
