from __future__ import annotations

import re

from doclex.metadata.models import DocumentResult


def clean_label(label: str) -> str:
    """Turn an internal location label into a citation a reader can use.

    Drops markdown carried over from extraction, and the trailing "> N" that the
    size splitter appends: that number is the index of an internal chunk, not a
    page or a section, so it means nothing to whoever reads the result.
    """
    label = re.sub(r"\s*›\s*\d+\s*$", "", label)
    label = label.replace("**", "").replace("#", "")
    return " ".join(label.split())


def results_to_dict(
    query: str,
    results: list[DocumentResult],
    include_content: bool = False,
) -> dict:
    """Search results as plain data, the shape every client emits."""
    return {
        "query": query,
        "total": len(results),
        "results": [
            {
                "file_id": doc.file_id,
                "filename": doc.filename,
                "path": doc.file_path,
                "mime_type": doc.mime_type,
                "score": round(doc.score, 4),
                "passages": [
                    {
                        "segment_id": p.segment_id,
                        "score": round(p.score, 4),
                        "location_type": p.location_type,
                        "location_label": clean_label(p.location_label),
                        "location_index": p.location_index,
                        "snippet": p.snippet.text,
                        "highlights": [
                            {"start": h.start, "end": h.end} for h in p.snippet.highlights
                        ],
                        **({"content": p.content} if include_content else {}),
                    }
                    for p in doc.passages
                ],
            }
            for doc in results
        ],
    }
