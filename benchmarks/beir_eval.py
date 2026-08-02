"""
BEIR benchmark for the doclex retrieval pipeline.

Exercises the real segmentation layer (segment()) + BM25X index.
Extraction (Kreuzberg) is bypassed — BEIR docs are plain text.

Pipeline per document:
    BEIR text → ExtractedDoc → segment() → segments → BM25X

At query time, segment scores are aggregated to doc level (max score)
before evaluation so results are comparable against BEIR qrels.

Usage:
    uv run python benchmarks/beir_eval.py
    uv run python benchmarks/beir_eval.py --label v2_tree --top-k 100
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import tracemalloc
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bm25x import BM25
from ranx import Qrels, Run, evaluate
from tqdm import tqdm

from doclex.metadata.models import ExtractedDoc, Segment
from doclex.segmentation.segmenter import segment

# ------------------------------------------------------------------ #
# Paths & constants
# ------------------------------------------------------------------ #

_BENCH_DIR = Path(__file__).parent
DATA_DIR = _BENCH_DIR / "data"
RESULTS_DIR = _BENCH_DIR / "results"

BEIR_BASE_URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets"

DEFAULT_DATASET = "nfcorpus"
DEFAULT_TOP_K = 100
DEFAULT_SPLIT = "test"
# Fetch extra segments per query before collapsing to doc level.
# Accounts for multiple segments per doc occupying BM25 slots.
_SEGMENT_FETCH_MULTIPLIER = 5

METRICS = [
    "ndcg@1",
    "ndcg@5",
    "ndcg@10",
    "map@100",
    "precision@1",
    "precision@5",
    "precision@10",
    "recall@10",
    "recall@100",
]


# ------------------------------------------------------------------ #
# Download
# ------------------------------------------------------------------ #

def download_dataset(name: str) -> Path:
    dataset_dir = DATA_DIR / name
    if dataset_dir.exists():
        print(f"Dataset '{name}' already cached at {dataset_dir}")
        return dataset_dir

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = DATA_DIR / f"{name}.zip"
    url = f"{BEIR_BASE_URL}/{name}.zip"

    print(f"Downloading {name} …")
    with tqdm(unit="B", unit_scale=True, unit_divisor=1024, miniters=1, desc=name) as bar:
        def _reporthook(block_num: int, block_size: int, total_size: int) -> None:
            if total_size > 0 and bar.total is None:
                bar.total = total_size
            bar.update(block_size)

        urllib.request.urlretrieve(url, zip_path, reporthook=_reporthook)

    print("Extracting …")
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(DATA_DIR)
    zip_path.unlink()

    return dataset_dir


# ------------------------------------------------------------------ #
# Loaders
# ------------------------------------------------------------------ #

def _load_corpus(dataset_dir: Path) -> tuple[list[str], list[str]]:
    """Returns (doc_ids, texts). Text = title + body."""
    doc_ids, texts = [], []
    with open(dataset_dir / "corpus.jsonl", encoding="utf-8") as f:
        for line in f:
            doc = json.loads(line)
            title = doc.get("title", "").strip()
            body = doc.get("text", "").strip()
            text = f"{title}\n\n{body}".strip() if title else body
            doc_ids.append(doc["_id"])
            texts.append(text)
    return doc_ids, texts


def _load_queries(dataset_dir: Path) -> tuple[list[str], list[str]]:
    qids, qtexts = [], []
    with open(dataset_dir / "queries.jsonl", encoding="utf-8") as f:
        for line in f:
            q = json.loads(line)
            qids.append(q["_id"])
            qtexts.append(q["text"])
    return qids, qtexts


def _load_qrels(dataset_dir: Path, split: str) -> dict[str, dict[str, int]]:
    qrels: dict[str, dict[str, int]] = {}
    with open(dataset_dir / "qrels" / f"{split}.tsv", encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            score = int(row["score"])
            if score > 0:
                qrels.setdefault(row["query-id"], {})[row["corpus-id"]] = score
    return qrels


# ------------------------------------------------------------------ #
# Segmentation + Index
# ------------------------------------------------------------------ #

def _segment_corpus(doc_ids: list[str], texts: list[str]) -> tuple[list[Segment], list[str]]:
    """
    Run the real segment() on every BEIR doc.

    Uses '.txt' suffix so the segmenter takes the text/heading path.
    Returns (all_segments, bm25_slot_to_doc_id) where the list index
    matches the BM25X internal doc id assigned by add().
    """
    all_segments: list[Segment] = []

    for doc_id, text in tqdm(zip(doc_ids, texts), total=len(doc_ids), desc="Segmenting"):
        # Use doc_id as path with .txt suffix → triggers _segment_text()
        extracted = ExtractedDoc(path=f"{doc_id}.txt", text=text, mime_type="text/plain")
        segs = segment(extracted)

        if not segs:
            # segment() returned nothing (very short text) — index as-is
            segs = [Segment(
                id=doc_id,
                file_path=f"{doc_id}.txt",
                content=text,
                location_type="block",
                location_label="Document",
                location_index=0,
            )]

        all_segments.extend(segs)

    # bm25_slot_to_doc_id[i] = BEIR doc_id for the segment at BM25X slot i
    bm25_slot_to_doc_id = [Path(seg.file_path).stem for seg in all_segments]
    return all_segments, bm25_slot_to_doc_id


def _build_index(
    segments: list[Segment],
    doc_ids: list[str],
) -> tuple[BM25, dict]:
    """Index all segments. Returns (index, stats)."""
    texts = [seg.content for seg in segments]
    n_docs = len(doc_ids)
    n_segs = len(segments)

    tracemalloc.start()
    index = BM25()
    t0 = time.perf_counter()
    index.add(texts)
    elapsed = time.perf_counter() - t0
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return index, {
        "docs_indexed": n_docs,
        "segments_total": n_segs,
        "segments_per_doc": round(n_segs / n_docs, 2),
        "index_time_sec": round(elapsed, 4),
        "docs_per_sec": round(n_docs / elapsed, 1),
        "segments_per_sec": round(n_segs / elapsed, 1),
        "peak_memory_mb": round(peak_bytes / 1024 / 1024, 2),
    }


# ------------------------------------------------------------------ #
# Retrieval
# ------------------------------------------------------------------ #

def _retrieve(
    index: BM25,
    bm25_slot_to_doc_id: list[str],
    query_ids: list[str],
    query_texts: list[str],
    top_k: int,
) -> tuple[dict[str, dict[str, float]], dict]:
    """
    Query the index. Aggregates segment scores to doc level (max score)
    before returning top_k docs per query.
    """
    run: dict[str, dict[str, float]] = {}
    # Fetch more segments than top_k to ensure enough unique docs after collapse
    fetch_k = min(top_k * _SEGMENT_FETCH_MULTIPLIER, len(bm25_slot_to_doc_id))

    t0 = time.perf_counter()
    for qid, qtext in zip(query_ids, query_texts):
        hits = index.search(qtext, fetch_k)

        # Aggregate: max score per doc across its segments
        doc_scores: dict[str, float] = {}
        for bm25_id, score in hits:
            doc_id = bm25_slot_to_doc_id[bm25_id]
            s = float(score)
            if s > doc_scores.get(doc_id, -1.0):
                doc_scores[doc_id] = s

        # Keep top_k docs by score
        run[qid] = dict(
            sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        )

    elapsed = time.perf_counter() - t0
    n = len(query_ids)
    return run, {
        "num_queries": n,
        "query_time_sec": round(elapsed, 4),
        "queries_per_sec": round(n / elapsed, 2),
        "ms_per_query": round(elapsed / n * 1000, 3),
    }


# ------------------------------------------------------------------ #
# Main evaluation
# ------------------------------------------------------------------ #

def run_evaluation(dataset: str, label: str, top_k: int, split: str) -> dict:
    dataset_dir = download_dataset(dataset)

    print("\nLoading corpus …")
    doc_ids, texts = _load_corpus(dataset_dir)
    query_ids_all, query_texts_all = _load_queries(dataset_dir)
    qrels = _load_qrels(dataset_dir, split)

    pairs = [(qid, qt) for qid, qt in zip(query_ids_all, query_texts_all) if qid in qrels]
    query_ids = [p[0] for p in pairs]
    query_texts = [p[1] for p in pairs]

    print(f"  corpus : {len(doc_ids):,} docs")
    print(f"  queries: {len(query_ids):,} (split={split})")

    print("\nSegmenting …")
    all_segments, bm25_slot_to_doc_id = _segment_corpus(doc_ids, texts)

    print(f"\nIndexing {len(all_segments):,} segments …")
    index, index_stats = _build_index(all_segments, doc_ids)
    print(f"  {index_stats['docs_per_sec']:,.0f} docs/sec  "
          f"({index_stats['segments_per_doc']:.2f} segs/doc, "
          f"{index_stats['index_time_sec']:.2f}s, "
          f"{index_stats['peak_memory_mb']:.1f} MB peak)")

    print("\nRetrieving …")
    run_dict, query_stats = _retrieve(
        index, bm25_slot_to_doc_id, query_ids, query_texts, top_k
    )
    print(f"  {query_stats['queries_per_sec']:.1f} queries/sec  "
          f"({query_stats['ms_per_query']:.2f} ms/query)")

    print("\nEvaluating …")
    scores = evaluate(Qrels(qrels), Run(run_dict), METRICS)

    result = {
        "label": label,
        "dataset": dataset,
        "split": split,
        "top_k": top_k,
        "timestamp": datetime.now().isoformat(),
        "index": index_stats,
        "query": query_stats,
        "metrics": {k: round(v, 4) for k, v in scores.items()},
    }

    _print_table(result)
    _save(result, label, dataset)
    return result


# ------------------------------------------------------------------ #
# Output helpers
# ------------------------------------------------------------------ #

def _print_table(r: dict) -> None:
    W = 54
    print("\n" + "=" * W)
    print(f"  {r['dataset'].upper()}  |  split={r['split']}  |  top_k={r['top_k']}")
    print(f"  label: {r['label']}")
    print("-" * W)
    print("  INDEXING")
    idx = r["index"]
    print(f"    docs             {idx['docs_indexed']:>14,}")
    print(f"    segments         {idx['segments_total']:>14,}")
    print(f"    segs/doc         {idx['segments_per_doc']:>14.2f}")
    print(f"    docs/sec         {idx['docs_per_sec']:>14,.0f}")
    print(f"    segments/sec     {idx['segments_per_sec']:>14,.0f}")
    print(f"    time (s)         {idx['index_time_sec']:>14.2f}")
    print(f"    memory (MB)      {idx['peak_memory_mb']:>14.1f}")
    print("-" * W)
    print("  QUERY")
    q = r["query"]
    print(f"    queries/sec      {q['queries_per_sec']:>14.1f}")
    print(f"    ms/query         {q['ms_per_query']:>14.2f}")
    print("-" * W)
    print("  QUALITY")
    for metric, val in r["metrics"].items():
        print(f"    {metric:<20} {val:.4f}")
    print("=" * W)


def _save(r: dict, label: str, dataset: str) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = RESULTS_DIR / f"{label}__{dataset}__{ts}.json"
    fname.write_text(json.dumps(r, indent=2, ensure_ascii=False))
    print(f"\nSaved → {fname.relative_to(_BENCH_DIR.parent)}")


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def main() -> None:
    p = argparse.ArgumentParser(description="BEIR benchmark for the doclex pipeline")
    p.add_argument("--dataset", default=DEFAULT_DATASET)
    p.add_argument("--label", default="run", help="e.g. baseline, v2_tree")
    p.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p.add_argument("--split", default=DEFAULT_SPLIT)
    args = p.parse_args()

    run_evaluation(args.dataset, args.label, args.top_k, args.split)


if __name__ == "__main__":
    main()
