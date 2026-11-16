#!/usr/bin/env python3
"""French e-commerce mini-eval: span-level PERSON / ADDRESS scoring with bootstrap CIs.

Runs each Tier-2 candidate over the deterministic dataset (see generate_dataset.py) and
reports span-level precision / recall / F1 per entity, in two matching regimes:

  exact   -- predicted [start,end) equals gold [start,end)
  partial -- predicted and gold of the same type overlap by >=1 char (relaxed)

Matching is greedy one-to-one (each gold and each prediction consumed at most once).
Every metric carries a 95% bootstrap CI (10k resamples over examples): no score is
reported without its uncertainty. PERSON recall is also sliced by mention form
(full "Marie Dupont" vs partial "M. Dupont" / "J. Martin") -- the slice where published
benchmarks show detectors collapse.

Usage:
  python eval.py --dataset dataset.json --edge-dir <dir> --out results_eval.json
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from models import GLiNER2PII, GLiNERPIIEdge, Span  # noqa: E402

ENTITIES = ("PERSON", "ADDRESS")


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def match(gold: list[dict], pred: list[Span], entity: str, mode: str) -> Counts:
    """Greedy one-to-one match of predictions to gold for one entity type."""
    golds = [(g["start"], g["end"]) for g in gold if g["entity"] == entity]
    preds = [(p.start, p.end) for p in pred if p.entity == entity]
    used_pred = [False] * len(preds)
    tp = 0
    for gs in golds:
        for i, ps in enumerate(preds):
            if used_pred[i]:
                continue
            hit = (ps == gs) if mode == "exact" else _overlap(ps, gs)
            if hit:
                used_pred[i] = True
                tp += 1
                break
    fn = len(golds) - tp
    fp = len(preds) - sum(used_pred)
    return Counts(tp=tp, fp=fp, fn=fn)


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def bootstrap_ci(per_example: list[Counts], seed: int = 12345,
                 n_boot: int = 10_000) -> dict:
    """95% bootstrap CI over examples for precision / recall / F1."""
    rng = random.Random(seed)
    n = len(per_example)
    tp0 = sum(c.tp for c in per_example)
    fp0 = sum(c.fp for c in per_example)
    fn0 = sum(c.fn for c in per_example)
    p0, r0, f0 = _prf(tp0, fp0, fn0)

    ps, rs, fs = [], [], []
    idx = range(n)
    for _ in range(n_boot):
        sample = [per_example[rng.choice(idx)] for _ in range(n)]
        tp = sum(c.tp for c in sample)
        fp = sum(c.fp for c in sample)
        fn = sum(c.fn for c in sample)
        p, r, f = _prf(tp, fp, fn)
        ps.append(p)
        rs.append(r)
        fs.append(f)

    def ci(v: list[float]) -> list[float]:
        v = sorted(v)
        lo = v[int(0.025 * len(v))]
        hi = v[int(0.975 * len(v)) - 1]
        return [round(lo, 4), round(hi, 4)]

    return {
        "tp": tp0, "fp": fp0, "fn": fn0, "n_gold": tp0 + fn0, "n_pred": tp0 + fp0,
        "precision": round(p0, 4), "precision_ci": ci(ps),
        "recall": round(r0, 4), "recall_ci": ci(rs),
        "f1": round(f0, 4), "f1_ci": ci(fs),
    }


def eval_model(model, samples: list[dict]) -> dict:
    # per-example, per-entity, per-mode counts
    per: dict[str, dict[str, list[Counts]]] = {
        e: {"exact": [], "partial": []} for e in ENTITIES
    }
    # PERSON recall by mention form (full vs partial), partial-match regime
    form_counts: dict[str, Counts] = {"full": Counts(), "partial": Counts()}

    latencies = []
    for s in samples:
        t = time.perf_counter()
        preds = model.detect(s["text"])
        latencies.append((time.perf_counter() - t) * 1000.0)
        for e in ENTITIES:
            for mode in ("exact", "partial"):
                per[e][mode].append(match(s["entities"], preds, e, mode))
        form = s.get("person_form", "none")
        if form in form_counts:
            c = match(s["entities"], preds, "PERSON", "partial")
            fc = form_counts[form]
            fc.tp += c.tp
            fc.fn += c.fn  # fp not meaningful per-form (predictions aren't form-tagged)

    result = {"model": model.name, "n_examples": len(samples), "per_entity": {}}
    for e in ENTITIES:
        result["per_entity"][e] = {
            "exact": bootstrap_ci(per[e]["exact"]),
            "partial": bootstrap_ci(per[e]["partial"]),
        }
    result["person_recall_by_form"] = {
        form: {
            "n_gold": c.tp + c.fn,
            "recall": round(c.tp / (c.tp + c.fn), 4) if (c.tp + c.fn) else None,
        }
        for form, c in form_counts.items()
    }
    result["infer_ms_median"] = round(statistics.median(latencies), 2)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", type=Path, default=HERE / "dataset.json")
    ap.add_argument("--edge-dir", type=str, default=None,
                    help="local dir with edge ONNX model; skip edge if omitted")
    ap.add_argument("--edge-onnx", type=str, default="onnx/model.onnx")
    ap.add_argument("--out", type=Path, default=HERE / "results_eval.json")
    ap.add_argument("--threshold", type=float, default=0.5)
    args = ap.parse_args()

    data = json.loads(args.dataset.read_text(encoding="utf-8"))
    samples = data["samples"]
    results = {"dataset_meta": data["meta"], "threshold": args.threshold, "models": []}

    print("loading gliner2-pii ...")
    results["models"].append(eval_model(GLiNER2PII(threshold=args.threshold), samples))
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("gliner2-pii done, saved partial")

    if args.edge_dir:
        print("loading gliner-pii-edge ...")
        edge = GLiNERPIIEdge(args.edge_dir, onnx_file=args.edge_onnx,
                             threshold=args.threshold)
        results["models"].append(eval_model(edge, samples))
        args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    print(f"wrote {args.out}")
    for m in results["models"]:
        print(f"\n== {m['model']} ==")
        for e in ENTITIES:
            ex = m["per_entity"][e]["exact"]
            pa = m["per_entity"][e]["partial"]
            print(f"  {e}: exact F1 {ex['f1']} {ex['f1_ci']} | "
                  f"partial F1 {pa['f1']} {pa['f1_ci']}")
        print(f"  PERSON recall by form: {m['person_recall_by_form']}")


if __name__ == "__main__":
    main()
