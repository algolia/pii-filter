#!/usr/bin/env python3
"""CPU latency + memory bench for Tier-2 PII NER candidates.

The decision-critical datum missing from every published source: how long a Tier-2 NER
forward pass takes on CPU per ~KB of text, and its memory footprint. We measure it here
so the inline-vs-async question is settled with real numbers, not priors.

Protocol per (model x input-size x thread-setting):
  - 5 warmup passes (excluded), then >=50 timed passes
  - report p50 / p95 latency, absolute and per-KB
  - cold-start (first model construction + first inference) measured separately
  - peak process RSS (psutil) after the run
Thread settings: "default" (library picks) and "1thread" (OMP/torch/onnxruntime intra-op
pinned to 1) -- a host shared with other work cares about the single-thread number.

Results are appended as JSON lines (one object per completed measurement) so a crash
never loses finished work. Run the two thread settings as separate processes:
  OMP_NUM_THREADS unset      -> --threads default
  OMP_NUM_THREADS=1 taskset  -> --threads 1thread   (pin before Python starts)

Usage:
  python bench_latency.py --model gliner2 --threads default --out results_latency.jsonl
  python bench_latency.py --model edge --edge-dir <dir> --threads 1thread --out ...
"""
from __future__ import annotations

import argparse
import gc
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Representative French e-commerce/support content with PII embedded, ~1 KB unit.
# Names and addresses are invented (communes are not in the official commune list).
# We tile / truncate this to hit 256 B, 1 KB, 4 KB targets.
_UNIT = (
    "Bonjour, je m'appelle Camille Moreau et je vous contacte au sujet de ma commande "
    "numero 48213 passee la semaine derniere. Le colis devait etre livre au 14 rue de la "
    "Forge, 48100 Valcombre, mais il n'est jamais arrive. J'ai deja essaye de joindre le "
    "service de livraison sans succes. Pouvez-vous verifier le suivi et me dire si une "
    "nouvelle expedition est possible a la meme adresse ? Je souhaite aussi ajouter une "
    "adresse secondaire chez M. Bernard, 8 avenue des Fleurs a Castelverine, pour les "
    "prochains envois. Merci d'avance pour votre aide et votre reactivite. "
)


def make_text(target_bytes: int) -> str:
    s = _UNIT
    while len(s.encode("utf-8")) < target_bytes:
        s += _UNIT
    # truncate to roughly the target on a word boundary
    b = s.encode("utf-8")[:target_bytes]
    return b.decode("utf-8", errors="ignore")


def pin_single_thread() -> None:
    """Best-effort intra-op pin to 1 thread across the stack."""
    import os

    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS"):
        os.environ[var] = "1"
    try:
        import torch

        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
    except Exception:
        pass


def peak_rss_mb() -> float:
    import resource

    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is KB on Linux, bytes on macOS
    return ru / 1024.0 if sys.platform != "darwin" else ru / 1024.0 / 1024.0


def build_model(kind: str, edge_dir: str | None, edge_onnx: str):
    t = time.perf_counter()
    if kind == "gliner2":
        from models import GLiNER2PII

        m = GLiNER2PII()
    elif kind == "edge":
        from models import GLiNERPIIEdge

        assert edge_dir, "--edge-dir required for edge"
        m = GLiNERPIIEdge(edge_dir, onnx_file=edge_onnx)
    else:
        raise ValueError(kind)
    return m, time.perf_counter() - t


def timed(model, text: str, n_warm: int, n_iter: int) -> tuple[list[float], float]:
    for _ in range(n_warm):
        model.detect(text)
    xs = []
    first = None
    for i in range(n_iter):
        t = time.perf_counter()
        model.detect(text)
        dt = (time.perf_counter() - t) * 1000.0
        if first is None:
            first = dt
        xs.append(dt)
    return xs, first or 0.0


def pctl(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", choices=["gliner2", "edge"], required=True)
    ap.add_argument("--threads", choices=["default", "1thread"], required=True)
    ap.add_argument("--edge-dir", type=str, default=None)
    ap.add_argument("--edge-onnx", type=str, default="onnx/model_quint8.onnx")
    ap.add_argument("--sizes", type=int, nargs="+", default=[256, 1024, 4096])
    ap.add_argument("--warmup", type=int, default=5)
    ap.add_argument("--iters", type=int, default=50)
    ap.add_argument("--out", type=Path, default=HERE / "results_latency.jsonl")
    ap.add_argument("--hardware", type=str, default="")
    args = ap.parse_args()

    if args.threads == "1thread":
        pin_single_thread()

    # cold start: construction + first inference on a 1 KB text
    m, load_s = build_model(args.model, args.edge_dir, args.edge_onnx)
    cold_text = make_text(1024)
    t = time.perf_counter()
    m.detect(cold_text)
    cold_infer_ms = (time.perf_counter() - t) * 1000.0

    with open(args.out, "a", encoding="utf-8") as fh:
        # record cold-start as its own line
        fh.write(json.dumps({
            "kind": "cold_start", "model": args.model, "threads": args.threads,
            "load_s": round(load_s, 3), "cold_infer_ms": round(cold_infer_ms, 2),
            "hardware": args.hardware, "ts": time.time(),
        }) + "\n")
        fh.flush()

        for size in args.sizes:
            text = make_text(size)
            kb = len(text.encode("utf-8")) / 1024.0
            xs, _ = timed(m, text, args.warmup, args.iters)
            p50 = statistics.median(xs)
            p95 = pctl(xs, 0.95)
            rec = {
                "kind": "latency", "model": args.model, "threads": args.threads,
                "target_bytes": size, "actual_kb": round(kb, 3), "iters": len(xs),
                "p50_ms": round(p50, 3), "p95_ms": round(p95, 3),
                "p50_ms_per_kb": round(p50 / kb, 3), "p95_ms_per_kb": round(p95 / kb, 3),
                "mean_ms": round(statistics.mean(xs), 3),
                "peak_rss_mb": round(peak_rss_mb(), 1),
                "hardware": args.hardware, "ts": time.time(),
            }
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(f"{args.model}/{args.threads}/{size}B: "
                  f"p50 {p50:.1f}ms p95 {p95:.1f}ms ({p50/kb:.1f}/{p95/kb:.1f} per KB) "
                  f"RSS {rec['peak_rss_mb']}MB")
            gc.collect()

    print(f"cold: load {load_s:.1f}s, first infer {cold_infer_ms:.1f}ms")


if __name__ == "__main__":
    main()
