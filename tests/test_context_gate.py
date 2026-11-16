"""The keyword gate ("Tier 1.5") and the entity spec's shape.

The gate is exercised on a test-only spec (EMAIL made context-required) so these
tests pin the mechanism independently of any shipped entity's keyword list.
"""

from __future__ import annotations

import json

import jsonschema
import pytest
import yaml

from pii import Tier1Detector, load_entities
from pii.context import fold, has_keyword_before
from pii.spec import repo_root, spec_path
from pii.types import EntitySpec, Policy
from pii.validators import VALIDATORS

GATED_EMAIL = EntitySpec(
    name="EMAIL",
    tier=1,
    default_policy=Policy.REDACT,
    regex=r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}",
    requires_context=True,
    context_keywords=("contact", "numéro d'entreprise"),
    context_window=20,
)


def _emails(text: str) -> list[str]:
    return [f.value for f in Tier1Detector(entities=(GATED_EMAIL,)).detect(text)]


def test_fold_is_case_accent_and_space_insensitive() -> None:
    assert fold("NUMÉRO  d’Entreprise") == "numero d'entreprise"
    assert fold("Ça va") == "ca va"
    assert fold("ŒUVRE Straße") == "oeuvre strasse"
    assert fold("Nume\u0301ro d'e\u0301tablissement") == "numero d'etablissement"  # NFD


def test_gate_requires_a_keyword_before_the_match() -> None:
    assert _emails("contact: jane@example.com") == ["jane@example.com"]
    assert _emails("write to jane@example.com") == []


def test_gate_is_case_and_accent_insensitive() -> None:
    assert _emails("CONTACT jane@example.com") == ["jane@example.com"]
    assert _emails("Numero d'entreprise jane@example.com") == ["jane@example.com"]
    assert _emails("NUMÉRO D’ENTREPRISE jane@example.com") == ["jane@example.com"]


def test_keyword_after_the_match_does_not_count() -> None:
    assert _emails("jane@example.com is my contact") == []


def test_keyword_outside_the_window_does_not_count() -> None:
    assert _emails("contact" + " " * 20 + "jane@example.com") == []
    assert _emails("contact" + " " * 5 + "jane@example.com") == ["jane@example.com"]


def test_window_counts_characters() -> None:
    # Go measures the same window in runes; accented text must not shrink it.
    assert _emails("contact éééééé jane@example.com") == ["jane@example.com"]


def test_keyword_must_be_a_whole_word() -> None:
    assert _emails("contacts jane@example.com") == []
    assert _emails("recontact jane@example.com") == []


def test_window_edge_does_not_cut_a_word_into_a_keyword() -> None:
    text = "xcontact" + " " * 12 + "jane@example.com"  # window starts inside xcontact
    assert has_keyword_before(text, text.index("jane"), ("contact",), 20) is False
    assert has_keyword_before(" " + text[1:], text.index("jane"), ("contact",), 20) is True


def test_spec_matches_its_schema() -> None:
    schema = json.loads((repo_root() / "spec" / "schema" / "entities.schema.json").read_text())
    with spec_path().open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    jsonschema.validate(raw, schema)


def test_every_spec_validator_is_registered() -> None:
    for e in load_entities():
        if e.validator:
            assert e.validator in VALIDATORS, e.name


def test_schema_rejects_keywords_without_the_gate() -> None:
    schema = json.loads((repo_root() / "spec" / "schema" / "entities.schema.json").read_text())
    bad = {
        "version": 1,
        "entities": [
            {
                "name": "X",
                "tier": 1,
                "description": "",
                "regex": "x",
                "default_policy": "redact",
                "context_keywords": ["x"],
                "context_window": 10,
            }
        ],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
