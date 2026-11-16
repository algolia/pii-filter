"""The committed corpus is exactly what corpus/build_corpus.py generates.

The national-identifier rows come from a seeded generator (corpus/synth_ids.py);
this pins the seed and the algorithms, so a hand edit to a JSONL file or a
generator change that is not regenerated fails here.
"""

from __future__ import annotations

import json
import runpy
from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent / "corpus"


def test_generator_reproduces_every_corpus_file() -> None:
    files = runpy.run_path(str(CORPUS / "build_corpus.py"), run_name="corpus_build")["FILES"]
    assert set(files) == {p.name for p in CORPUS.glob("*.jsonl")}
    for name, rows in files.items():
        expected = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        assert (CORPUS / name).read_text(encoding="utf-8") == expected, name


def test_generated_identifiers_pass_their_own_checks() -> None:
    ids = runpy.run_path(str(CORPUS / "synth_ids.py"))
    files = runpy.run_path(str(CORPUS / "build_corpus.py"), run_name="corpus_build")["FILES"]
    checks = {
        "FR_NIR": ids["nir_ok"],
        "FR_TAX_ID": ids["tax_ok"],
        "FR_SIREN": ids["siren_ok"],
        "FR_SIRET": ids["siret_ok"],
        "ES_DNI": ids["dni_ok"],
        "ES_NIE": ids["nie_ok"],
    }
    seen = 0
    for rows in files.values():
        for row in rows:
            for ent in row["entities"]:
                if ent["type"] in checks:
                    assert checks[ent["type"]](ent["value"]), ent
                    seen += 1
    assert seen >= 120


def test_generated_identifiers_stay_in_their_unissued_bands() -> None:
    # corpus/synth_ids.py explains each band and how strong it is.
    files = runpy.run_path(str(CORPUS / "build_corpus.py"), run_name="corpus_build")["FILES"]
    exceptions = 0
    for rows in files.values():
        for row in rows:
            for ent in row["entities"]:
                v = "".join(ch for ch in ent["value"] if ch.isalnum()).upper()
                if ent["type"] == "FR_NIR":
                    assert 14 <= int(v[3:5]) <= 19, ent
                elif ent["type"] == "ES_DNI":
                    assert v.startswith("99"), ent
                elif ent["type"] == "FR_TAX_ID":
                    assert v.startswith("00000000"), ent  # sequential bodies
                elif ent["type"] == "ES_NIE":
                    assert v[1] == "9" if v[0] == "Z" else v[1:8] == "0000000", ent
                elif ent["type"] in ("FR_SIREN", "FR_SIRET") and not v.startswith("000"):
                    assert v.startswith("356000000") or v == "36438999960016", ent  # La Poste, test card
                    exceptions += 1
    assert exceptions <= 6
