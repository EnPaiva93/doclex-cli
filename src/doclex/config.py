from __future__ import annotations

import os
from pathlib import Path


class Config:
    def __init__(self) -> None:
        folder_env = os.environ.get("DOCSEARCH_FOLDER")
        if not folder_env:
            raise ValueError("DOCSEARCH_FOLDER environment variable is required")

        self.folder = Path(folder_env).expanduser().resolve()
        if not self.folder.is_dir():
            raise ValueError(f"DOCSEARCH_FOLDER is not a directory: {self.folder}")

        cache_env = os.environ.get("DOCSEARCH_CACHE_DIR")
        self.cache_dir = (
            Path(cache_env).expanduser().resolve()
            if cache_env
            else self.folder / ".docsearch"
        )

        db_env = os.environ.get("DOCSEARCH_DB_PATH")
        self.db_path = (
            Path(db_env).expanduser().resolve()
            if db_env
            else self.cache_dir / "docsearch.db"
        )

        self.bm25_index_dir = self.cache_dir / "bm25_index"

        self.top_k = int(os.environ.get("DOCSEARCH_TOP_K", "10"))
        self.debounce_secs = float(os.environ.get("DOCSEARCH_DEBOUNCE", "1.0"))

    def ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".txt", ".md", ".docx", ".xlsx", ".csv"}
)
