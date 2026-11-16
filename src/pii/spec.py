"""Load the language-neutral entity spec (spec/entities.yaml).

The spec is the single source of truth, versioned at the repo root in
``spec/entities.yaml``. ``src/pii/entities.yaml`` is a symlink to it, so the file
ships inside the wheel as package data (no copy, no drift). Resolution order:

1. an explicit ``path`` argument (tests, alternate specs);
2. the packaged copy via :mod:`importlib.resources` (installed wheel);
3. the repo-root ``spec/entities.yaml`` (editable checkout / ``PYTHONPATH=src``).
"""

from __future__ import annotations

import functools
from importlib import resources
from pathlib import Path

import yaml

from .types import EntitySpec, Policy


def repo_root() -> Path:
    """Repo root, resolved from this file (src/pii/spec.py -> repo root)."""
    return Path(__file__).resolve().parents[2]


def spec_path() -> Path:
    """Best-effort filesystem path to the spec (packaged copy, else repo root).

    Returns the packaged ``pii/entities.yaml`` when it exists (installed wheel or
    checkout via the symlink), falling back to the repo-root SSOT.
    """
    try:
        packaged = resources.files("pii") / "entities.yaml"
        if packaged.is_file():
            return Path(str(packaged))
    except (ModuleNotFoundError, FileNotFoundError):
        pass

    return repo_root() / "spec" / "entities.yaml"


@functools.lru_cache(maxsize=8)
def load_entities(path: str | None = None) -> tuple[EntitySpec, ...]:
    """Parse the Tier-1 entities from the spec. Tier-2 entities are reference-only
    here (no regex), so they are skipped by detectors but available via raw()."""
    raw = _load_raw(path)
    out: list[EntitySpec] = []
    for item in raw.get("entities", []):
        out.append(
            EntitySpec(
                name=item["name"],
                tier=int(item.get("tier", 1)),
                default_policy=Policy(item["default_policy"]),
                regex=item.get("regex"),
                validator=item.get("validator"),
                description=item.get("description", ""),
                requires_context=bool(item.get("requires_context", False)),
                context_keywords=tuple(item.get("context_keywords") or ()),
                context_window=int(item.get("context_window", 0)),
            )
        )
    return tuple(out)


def _load_raw(path: str | None) -> dict:
    p = Path(path) if path else spec_path()
    with p.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)
