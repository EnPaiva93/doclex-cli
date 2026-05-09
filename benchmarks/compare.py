"""
Compare two benchmark result JSON files produced by beir_eval.py.

Usage:
    uv run python benchmarks/compare.py results/baseline__nfcorpus__*.json results/v2_tree__nfcorpus__*.json

    # Or point to specific files:
    uv run python benchmarks/compare.py results/a.json results/b.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _delta_str(va: float, vb: float, higher_is_better: bool = True) -> str:
    delta = vb - va
    if abs(delta) < 1e-9:
        return f"{'=':>10}"
    pct = (delta / va * 100) if va else 0
    arrow = "▲" if delta > 0 else "▼"
    # For ms_per_query lower is better, so flip the colour signal in the label
    if not higher_is_better:
        arrow = "▼" if delta > 0 else "▲"
    return f"{arrow} {abs(pct):>7.2f}%"


def compare(path_a: Path, path_b: Path) -> None:
    a = json.loads(path_a.read_text())
    b = json.loads(path_b.read_text())

    W = 62
    lbl_a = a["label"]
    lbl_b = b["label"]

    print("\n" + "=" * W)
    print(f"  {'Metric':<24} {lbl_a:>12} {lbl_b:>12}  {'Δ':>8}")
    print("-" * W)

    # Indexing
    print("  INDEXING")
    for key, hib in [
        ("docs_per_sec", True),
        ("index_time_sec", False),
        ("peak_memory_mb", False),
    ]:
        va = a["index"][key]
        vb = b["index"][key]
        print(f"    {key:<22} {va:>12.2f} {vb:>12.2f}  {_delta_str(va, vb, hib)}")

    # Query
    print("  QUERY")
    for key, hib in [
        ("queries_per_sec", True),
        ("ms_per_query", False),
    ]:
        va = a["query"][key]
        vb = b["query"][key]
        print(f"    {key:<22} {va:>12.2f} {vb:>12.2f}  {_delta_str(va, vb, hib)}")

    # Quality
    print("  QUALITY")
    all_metrics = sorted(set(a["metrics"]) | set(b["metrics"]))
    for metric in all_metrics:
        va = a["metrics"].get(metric, 0.0)
        vb = b["metrics"].get(metric, 0.0)
        delta = vb - va
        arrow = "▲" if delta > 1e-9 else ("▼" if delta < -1e-9 else "=")
        print(f"    {metric:<22} {va:>12.4f} {vb:>12.4f}  {arrow} {abs(delta):.4f}")

    print("=" * W)
    print(f"  A: {path_a.name}")
    print(f"  B: {path_b.name}")
    print("=" * W)


def main() -> None:
    p = argparse.ArgumentParser(description="Compare two beir_eval result files")
    p.add_argument("file_a", help="Baseline result JSON (glob patterns ok: results/baseline*.json)")
    p.add_argument("file_b", help="New result JSON")
    args = p.parse_args()

    # Support simple glob patterns for convenience
    def resolve(pattern: str) -> Path:
        paths = sorted(Path(".").glob(pattern))
        if not paths:
            return Path(pattern)   # let it fail naturally with a clear error
        return paths[-1]           # take the most recent if multiple match

    path_a = resolve(args.file_a)
    path_b = resolve(args.file_b)

    if not path_a.exists():
        raise SystemExit(f"File not found: {path_a}")
    if not path_b.exists():
        raise SystemExit(f"File not found: {path_b}")

    compare(path_a, path_b)


if __name__ == "__main__":
    main()
