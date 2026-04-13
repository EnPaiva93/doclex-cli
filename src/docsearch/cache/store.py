from __future__ import annotations

import hashlib
import json
import re
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
                text="",  # content lives in index nodes
                mime_type=data["mime_type"],
                metadata=data.get("metadata", {}),
            )
            segments = _flatten_index(data.get("index", {}), data["path"])
            return doc, segments
        except (KeyError, json.JSONDecodeError):
            return None

    def put(self, doc: ExtractedDoc, segments: list[Segment]) -> None:
        """Write extracted doc and its segments as a unified index tree."""
        cache_file = self._cache_path(doc.path)
        data = {
            "path": doc.path,
            "mime_type": doc.mime_type,
            "metadata": doc.metadata,
            "index": _build_index(Path(doc.path).stem, segments),
        }
        cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def delete(self, doc_path: str) -> None:
        cache_file = self._cache_path(doc_path)
        if cache_file.exists():
            cache_file.unlink()


# ------------------------------------------------------------------
# Index tree builder
# ------------------------------------------------------------------

def _build_index(title: str, segments: list[Segment]) -> dict:
    """Build a unified PageIndex-style tree from flat segments."""
    root: dict = {"title": title, "nodes": []}

    has_hierarchy = any(s.level > 0 for s in segments)
    if not has_hierarchy:
        root["nodes"] = [_seg_to_node(s) for s in segments]
        return root

    stack: list[tuple[int, dict]] = [(0, root)]
    for seg in segments:
        node = _seg_to_node(seg)
        if seg.level > 0:
            # heading node: pop continuations (level=0) and same/deeper headings
            while len(stack) > 1 and (stack[-1][0] == 0 or stack[-1][0] >= seg.level):
                stack.pop()
            stack[-1][1]["nodes"].append(node)
            stack.append((seg.level, node))
        else:
            if stack[-1][0] == 0:
                # previous was also a continuation — nest inside it
                stack[-1][1]["nodes"].append(node)
            else:
                # first continuation after a heading — create a parent node from heading
                title, _ = _extract_heading(node.get("content", ""))
                if title:
                    _, body = _extract_heading(node.get("content", ""))
                    node["content"] = body
                    parent_node: dict = {
                        "id": node["id"] + "_group",
                        "title": title,
                        "location_type": node.get("location_type", "section"),
                        "content": "",
                        "bm25_doc_id": None,
                        "nodes": [node],
                    }
                    stack[-1][1]["nodes"].append(parent_node)
                    stack.append((0, parent_node))
                else:
                    stack[-1][1]["nodes"].append(node)
                    stack.append((0, node))

    _drop_redundant_titles(root)
    return root


def _extract_heading(content: str) -> tuple[str, str]:
    """Extract the first markdown heading from content, return (title, remaining_body)."""
    lines = content.split("\n", 1)
    first_line = lines[0].strip()
    m = re.match(r"^#{1,3} (.+)", first_line)
    if not m:
        return "", content
    title = m.group(1).strip()
    body = lines[1].strip() if len(lines) > 1 else ""
    return title, body


def _drop_redundant_titles(node: dict) -> None:
    """Remove title from heading leaf nodes — it's already the first line of content."""
    for child in node.get("nodes", []):
        _drop_redundant_titles(child)
    if not node.get("nodes") and node.get("level", 0) > 0:
        node.pop("title", None)


def _seg_to_node(seg: Segment) -> dict:
    node: dict = {
        "id": seg.id,
        "title": seg.location_label,
        "location_type": seg.location_type,
        "content": seg.content,
        "bm25_doc_id": seg.bm25_doc_id,
        "nodes": [],
    }
    if seg.level > 0:
        node["level"] = seg.level
    return node


# ------------------------------------------------------------------
# Index tree flattener (get)
# ------------------------------------------------------------------

def _flatten_index(index: dict, file_path: str) -> list[Segment]:
    """Flatten a unified index tree back to a list of Segment objects."""
    segments: list[Segment] = []

    def walk(nodes: list, section_id: str | None, index: int) -> int:
        for node in nodes:
            node_id = node["id"]
            level = node.get("level", 0)
            seg = Segment(
                id=node_id,
                file_path=file_path,
                content=node["content"],
                location_type=node.get("location_type", "block"),
                location_label=node.get("title") or node["content"].splitlines()[0].lstrip("#").strip()[:80],
                location_index=index,
                char_count=len(node["content"]),
                bm25_doc_id=node.get("bm25_doc_id"),
                section_id=node_id if level > 0 else section_id,
                level=level,
            )
            segments.append(seg)
            index = walk(node.get("nodes", []), seg.section_id, index + 1)
        return index

    walk(index.get("nodes", []), None, 0)
    return segments
