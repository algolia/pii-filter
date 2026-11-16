"""Tier-2 candidate model wrappers, normalised to PERSON / ADDRESS char spans.

Both candidates emit their own fine-grained PII taxonomy. This toolkit's Tier-2 gold
is two coarse entities (PERSON, ADDRESS), so we map and merge:

  GLiNER2-PII (fastino/gliner2-privacy-filter-PII-multi):
    person, full_name                              -> PERSON
    address, street_address, city, postal_code     -> ADDRESS
  gliner-pii-edge (knowledgator/gliner-pii-edge-v1.0, UINT8 ONNX):
    person, full name                              -> PERSON
    address, street address, city, postal code     -> ADDRESS

Overlapping/adjacent predicted spans of the same coarse type are merged into their union
(the fine labels frequently co-fire on nested sub-spans of one mention). Taxonomy mapping
is explicit and documented here so a mismatch never silently deflates a score — the mistake
that deflated Presidio in published benchmarks.

Requires: gliner2[local], gliner, onnxruntime, torch (CPU). See requirements.txt.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Span:
    entity: str  # "PERSON" | "ADDRESS"
    start: int
    end: int
    score: float = 1.0


def _merge(spans: list[Span]) -> list[Span]:
    """Merge overlapping/adjacent same-entity spans into their union (max score)."""
    out: list[Span] = []
    for ent in ("PERSON", "ADDRESS"):
        items = sorted((s for s in spans if s.entity == ent), key=lambda s: s.start)
        cur: Span | None = None
        for s in items:
            if cur is None:
                cur = s
            elif s.start <= cur.end:  # overlap or touching
                cur = Span(ent, cur.start, max(cur.end, s.end), max(cur.score, s.score))
            else:
                out.append(cur)
                cur = s
        if cur is not None:
            out.append(cur)
    return out


GLINER2_MAP = {
    "person": "PERSON", "full_name": "PERSON",
    "address": "ADDRESS", "street_address": "ADDRESS",
    "city": "ADDRESS", "postal_code": "ADDRESS",
}
GLINER2_LABELS = list(GLINER2_MAP.keys())

EDGE_MAP = {
    "person": "PERSON", "full name": "PERSON",
    "address": "ADDRESS", "street address": "ADDRESS",
    "city": "ADDRESS", "postal code": "ADDRESS",
}
EDGE_LABELS = list(EDGE_MAP.keys())


class GLiNER2PII:
    """Accuracy-lean candidate. 0.3B, mdeberta-v3-base encoder, PyTorch CPU."""

    name = "gliner2-pii"
    repo = "fastino/gliner2-privacy-filter-PII-multi"

    def __init__(self, threshold: float = 0.5) -> None:
        from gliner2 import GLiNER2

        self.threshold = threshold
        self.model = GLiNER2.from_pretrained(self.repo)

    def detect(self, text: str) -> list[Span]:
        res = self.model.extract_entities(
            text, GLINER2_LABELS, threshold=self.threshold, include_spans=True,
            include_confidence=True,
        )
        raw: list[Span] = []
        for label, items in res.get("entities", {}).items():
            coarse = GLINER2_MAP.get(label)
            if not coarse:
                continue
            for it in items:
                raw.append(Span(coarse, int(it["start"]), int(it["end"]),
                                float(it.get("confidence", 1.0))))
        return _merge(raw)


class GLiNERPIIEdge:
    """Footprint-lean candidate. UINT8 ONNX (~46 MB weights), onnxruntime CPU."""

    name = "gliner-pii-edge"
    repo = "knowledgator/gliner-pii-edge-v1.0"

    def __init__(self, model_dir: str, onnx_file: str = "onnx/model_quint8.onnx",
                 threshold: float = 0.5) -> None:
        from gliner import GLiNER

        self.threshold = threshold
        self.model = GLiNER.from_pretrained(
            model_dir, load_onnx_model=True, load_tokenizer=True,
            onnx_model_file=onnx_file,
        )

    def detect(self, text: str) -> list[Span]:
        preds = self.model.predict_entities(text, EDGE_LABELS, threshold=self.threshold)
        raw: list[Span] = []
        for p in preds:
            coarse = EDGE_MAP.get(str(p["label"]).lower())
            if not coarse:
                continue
            raw.append(Span(coarse, int(p["start"]), int(p["end"]),
                            float(p.get("score", 1.0))))
        return _merge(raw)
