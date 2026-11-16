# Deterministic PII Identifier Detection — Validation Algorithms & False-Positive Mitigation

> Research output (2026). Grounds the Tier-1 detectors in `detectors.go` and
> `src/pii/validators.py`. Tier-1 = highest precision, lowest false positives.
> Guiding principle: a checksum lets a false positive be caught by math, not just
> by pattern rarity. Identifiers with checksums can sit in Tier-1 unconditionally;
> regex-only identifiers need context signals or a lower tier.

## 1. Credit Cards — Luhn + IIN

### Luhn (ISO/IEC 7812 check digit, mod 10)

```
function luhn_valid(number):
    digits = [int(c) for c in number]
    n = len(digits); total = 0
    for i in range(n):
        d = digits[n - 1 - i]      # right-to-left
        if i % 2 == 1:             # every second digit from the right
            d *= 2
            if d > 9: d -= 9
        total += d
    return total % 10 == 0
```

### Luhn alone is NOT sufficient

Luhn only catches transcription errors. `4111111111111111` passes Luhn but is a
published test number; `1111 2222 3333 4444` also passes Luhn yet has no issuable
IIN. Tier-1 must require **Luhn pass + IIN prefix match + length match**.

### IIN prefix / length table

| Network | Prefixes | Lengths |
|---|---|---|
| Visa | `4` | 13, 16, 19 |
| Mastercard | `51–55`, `2221–2720` | 16 |
| Amex | `34`, `37` | 15 |
| Discover | `6011`, `622126–622925`, `644–649`, `65` | 16 |
| UnionPay | `62` | 16–19 |
| JCB | `3528–3589` | 16–19 |
| Maestro | `50`, `56–58`, `6` | 12–19 |
| Diners | `300–305`, `36`, `54–55` | 14–16 |

Maestro / Discover / UnionPay share the `6x` space — match Discover/UnionPay
prefixes first, then fall through to Maestro (ordered prefix priority).

## 2. IBAN — ISO 13616 structure + ISO 7064 mod-97

Structure `[CC][KK][BBAN]`: 2-char ISO 3166-1 alpha-2 country code, 2 check
digits, country-specific BBAN. Total length fixed per country, 15 (Norway) to 33
(Russia).

```
function iban_valid(iban):
    s = iban.replace(" ", "").upper()
    if len(s) != EXPECTED_LENGTH[s[0:2]]: return false   # per-country length
    rearranged = s[4:] + s[0:4]                           # first 4 -> end
    numeric = ""                                          # A=10 .. Z=35
    for c in rearranged: numeric += str(ord(c)-55) if c.isalpha() else c
    remainder = 0
    for chunk in chunks_of(numeric, 9):                   # avoid bigint overflow
        remainder = int(str(remainder) + chunk) % 97
    return remainder == 1
```

Process the ~70-digit numeric string in 9-digit chunks prepending the running
remainder; never cast the whole string to an integer at once. Per-country length
table: 89 countries (SWIFT/ISO 13616 registry); e.g. NO=15, NL/DK/FI=18, DE/GB=22,
FR/IT=27, RU=33.

## 3. US SSN — regex-only, HIGH false-positive risk

Structure `AAA-GG-SSSS`: Area 001–899 (never `000`/`666`/`900–999`), Group 01–99
(never `00`), Serial 0001–9999 (never `0000`). Since 2011-06-25 the SSA randomizes assignment, so
geographic heuristics are dead. **No checksum exists** — any 9-digit string that
passes the narrow exclusions collides with ZIP+4, phone, account IDs. Mitigation:
format exclusions + mandatory keyword context ("SSN", "social security", "TIN") +
strip known test numbers. (We omit SSN from the unconditional Tier-1 set for this
reason.)

## 4. Phone — ITU-T E.164, HIGH false-positive risk (raw)

Canonical `+[country_code][subscriber]`, ≤15 digits, no checksum. `+` plus 7–15
digits matches a large fraction of digit runs (invoices, ZIP+4, codes). Mitigation:
`libphonenumber.isValidNumber()` (allocated ranges) + require `+` or country
context + keyword proximity. FP risk: VERY HIGH raw → MEDIUM-LOW with
libphonenumber + context. (Our Tier-1 uses a digit-count + boundary + not-IP-shape
gate; it is a tripwire, not libphonenumber-grade validation.)

## 5. IPv4 + IPv6

IPv4: octet-constrained regex (`25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d`); naive `\d{1,3}`
matches `999.999.999.999`. Optionally exclude private/reserved if only public IPs
count as PII (`10/8`, `172.16/12`, `192.168/16`, `127/8`, `169.254/16`,
`100.64/10`). IPv6 (RFC 4291): 8 hex groups, `::` collapses one zero run; exclude
`::1/128`, `fe80::/10`, `fd00::/8`, `ff00::/8`. Trust the stdlib (`net.ParseIP`,
`ipaddress`) for `::` expansion; regex only finds candidates.

## 6. Precision Taxonomy — Checksum vs Regex-Only

| Entity | Checksum? | Algorithm | FP risk | Tier-1 gate |
|---|---|---|---|---|
| IBAN | YES | ISO 7064 mod-97 | VERY LOW | mod-97 + country length |
| Credit card | YES | Luhn (mod 10) | LOW | Luhn + IIN prefix + length |
| French INSEE/NIR | YES | `97 - (NIR13 mod 97)` | LOW | mod-97 complement |
| NPI (US provider) | YES | modified Luhn (`80840`) | LOW | modified Luhn |
| IPv4 (public) | Partial | octet range 0–255 | LOW-MED | octet validation + private filter |
| IPv6 (public) | Partial | group range + `::` rules | LOW | stdlib parse + private filter |
| Email | NO | RFC 5321/5322 syntax | MEDIUM | syntax regex (+ optional DNS) |
| SSN | NO | exclusion rules only | HIGH | range filter + mandatory context |
| Phone (E.164) | NO | libphonenumber ranges | HIGH raw | `isValidNumber()` + context |

## Recommended Tier-1 entity list

Unconditional (checksum-validated): IBAN (mod-97 + length), Credit card
(Luhn + IIN + length), French INSEE/NIR (mod-97 complement), NPI (modified Luhn).
Near-deterministic with a private-range filter: IPv4/IPv6 public. Regex-only —
keep OUT of unconditional Tier-1 or gate behind context: Email (tractable, MEDIUM),
SSN (HIGH), Phone (HIGH raw).

**Calibrated bottom line:** only IBAN / card / INSEE / NPI are truly
"deterministic high-precision." IPs are close (validation is exact) but private
ranges need a filter. Email/SSN/phone are structurally regex-only.

Tooling: Go — pure Luhn, `net.ParseIP`, `github.com/nyaruka/phonenumbers`.
Python — `python-stdnum` (IBAN/Luhn/NPI/INSEE/SSN), `phonenumbers`, `ipaddress`.

## Table audit (2026-06-29)

The IBAN length and card IIN tables were cross-checked against two independent
public sources each (the prior caveat was: aggregator sources, not paywalled
ISO/EMVCo primaries — now verified to the extent free sources allow).

**IBAN lengths** — verified against Wikipedia's IBAN registry table and
`iban.com/structure`. The two sources agree on all 89 countries with **zero
value mismatches**. The implementation table was extended from 78 to the full 89
(added BI, DJ, FK, HN, MN, NI, OM, RU, SD, SO, YE — recent SWIFT-registry
additions). Untabled country codes still fall back to the generic 15..34 bound,
so the change only tightens precision, never drops a real IBAN.

**Card IIN ranges** — verified against the Payment-card-number IIN/BIN tables.
Exact match for Visa (`4`, len 13/16/19), Mastercard (`51–55` + `2221–2720`,
len 16), Amex (`34/37`, len 15), and JCB (`3528–3589`, len 16–19). Two
deliberate scope limits remain, both **recall-side** (a missed rare card, never
a false positive), and both left as-is because no corpus example exercises them
— we don't ship untested validator branches:

- Diners covers `30/36/38` but not `39` (routed via Discover since 2009).
- Discover covers `6011` and `65` but not the `644–649` or `622126–622925`
  (UnionPay co-brand) sub-ranges, and accepts lengths {16,19} rather than the
  full 16–19. Real Discover cards are overwhelmingly 16-digit.

When such a card shows up in real data, add the fixture and the range together.

## Sources

- https://en.wikipedia.org/wiki/Luhn_algorithm — Luhn mod-10 algorithm steps and check-digit position.
- https://en.wikipedia.org/wiki/Payment_card_number — IIN/BIN prefix ranges and lengths per card network.
- https://neapay.com/post/bin-list-range-for-mastercard-visa-amex-diners-discover-jcb-cup_94.html — detailed BIN/IIN ranges (Mastercard 2-series, Discover sub-ranges, UnionPay, JCB).
- https://en.wikipedia.org/wiki/International_Bank_Account_Number — IBAN structure (ISO 13616) and mod-97 (ISO 7064) validation.
- https://www.iban.com/structure — per-country IBAN length table (full 89-country registry).
- https://medium.com/@matlabb/iban-structure-and-mod-97-validation-algorithm-719e3d4db5f2 — worked example of chunked mod-97.
- https://en.wikipedia.org/wiki/Social_Security_number — SSN structure, invalid ranges, Woolworth number, ITIN overlap.
- https://www.ssa.gov/employer/randomizationfaqs.html — SSA 2011 randomization.
- https://en.wikipedia.org/wiki/E.164 — E.164 format, max-15-digit rule, country-code structure.
- https://libphonenumber.org/ — libphonenumber validity vs possibility distinction.
- https://datatracker.ietf.org/doc/html/rfc1918 — IPv4 private ranges.
- https://www.rfc-editor.org/rfc/rfc4291 — IPv6 addressing, `::`, reserved prefixes.
- https://www.eclaims.com/articles/how-to-calculate-the-npi-check-digit/ — NPI modified-Luhn check digit.
- https://compteassurance.com/calculer-la-cle-de-securite-sociale-nir/ — French NIR/INSEE mod-97-complement key.
