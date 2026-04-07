from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from docsearch.metadata.models import ExtractedDoc, Segment


class CacheStore:
    """JSON file cache: one file per document, keyed by sha256 of the path."""

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, doc_path: str) -> Path:
        key = hashlib.sha256(doc_path.encode()).hexdigest()
        return self._dir / f"{key}.json"

    def get(self, doc_path: str) -> tuple[ExtractedDoc, list[Segment]] | None:
        """Return cached (doc, segments) or None if not present."""
        cache_file = self._cache_path(doc_path)
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            doc = ExtractedDoc(
                path=data["path"],
                text=data["extracted_text"],
                mime_type=data["mime_type"],
                metadata=data.get("metadata", {}),
            )
            segments = [
                Segment(
                    id=s["id"],
                    file_path=s["file_path"],
                    content=s["content"],
                    location_type=s["location_type"],
                    location_label=s["location_label"],
                    location_index=s["location_index"],
                    char_count=s["char_count"],
                    bm25_doc_id=s.get("bm25_doc_id"),
                )
                for s in data.get("segments", [])
            ]
            return doc, segments
        except (KeyError, json.JSONDecodeError):
            return None

    def put(self, doc: ExtractedDoc, segments: list[Segment]) -> None:
        """Write extracted doc and its segments to cache."""
        cache_file = self._cache_path(doc.path)
        data = {
            "path": doc.path,
            "mime_type": doc.mime_type,
            "extracted_text": doc.text,
            "metadata": doc.metadata,
            "segments": [asdict(s) for s in segments],
        }
        cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def delete(self, doc_path: str) -> None:
        cache_file = self._cache_path(doc_path)
        if cache_file.exists():
            cache_file.unlink()
