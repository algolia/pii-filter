"""Load the golden corpus into Example objects."""

from __future__ import annotations

import json
from pathlib import Path

from ..spec import repo_root
from ..types import Example, Finding


def corpus_dir() -> Path:
    return repo_root() / "corpus"


def load_corpus(directory: str | Path | None = None) -> list[Example]:
    """Load every corpus/*.jsonl file into a flat list of Examples.

    Each line is {"text": str, "entities": [{"type","start","end","value"}, ...]}.
    """
    base = Path(directory) if directory else corpus_dir()
    examples: list[Example] = []
    for path in sorted(base.glob("*.jsonl")):
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                golds = tuple(
                    Finding(
                        entity=e["type"],
                        start=e["start"],
                        end=e["end"],
                        value=e["value"],
                    )
                    for e in row.get("entities", [])
                )
                examples.append(Example(text=row["text"], entities=golds, source=path.name))
    return examples
