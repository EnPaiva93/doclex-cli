# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.1] - 2026-08-02

### Fixed

- Search result snippets now anchor on the window with the highest density of query-term matches instead of the first occurrence of the first term, so the snippet favors where the query actually clusters rather than an early, isolated mention.

## [0.1.0] - 2026-08-02

First release — CLI MVP (Fase 1): local, embeddings-free document search over PDF, DOCX, XLSX, CSV, Markdown and TXT files.

### Added

- Local document search CLI (`doclex`) — BM25 lexical search, no embeddings, no vector DB, no cloud.
- Ingestion pipeline: folder scanning with hash-based change detection, Kreuzberg-based text extraction, structural segmentation per file type (pages, sheets, sections, blocks), BM25X indexing, SQLite metadata store, and a local extraction cache.
- Real-time incremental updates via Watchdog file monitoring, plus full reconciliation on startup.
- `doclex add`/`projects`/`remove` — named project registry mapping folder paths to project names, rejecting overlapping/nested folders.
- `doclex index --project <name> [--file ...] [--force]` — incremental or forced full reindexing, with per-file targeting.
- `doclex search <query> --project <name> [--top] [--full]` — top-k BM25 search with citations (file, location, score, snippet).
- `doclex status --project <name> [--file ...] [--all] [--filter]` — corpus/index status, file listing, and per-file inspection.
- OCR support (`--ocr`) for scanned PDFs, and layout-aware segmentation via Kreuzberg.
- Recursive character-based splitter keeping segments within a 1024-character limit while preserving semantic boundaries.

### Changed

- CLI output migrated to Rich (progress bars, tables) instead of plain text.
- Segmentation cache replaced with a unified page-index-style tree; split sub-segments now nest under their extracted heading parent.
- `list`/`reindex` merged into `index`/`status` flags; cache directory renamed from `.cache` to `.doclex`.
- Layout-aware PDF segmentation made the default (removed the `--precise` flag).

### Fixed

- Ghost BM25 index entries left behind after a forced reindex (index and SQLite are now rebuilt fully in sync).
- `status`/`search` no longer create the index directory before a project has actually been indexed.
- Search result snippets now tokenize the query the same way BM25X tokenizes documents (splitting on punctuation, not just whitespace) and snap to word boundaries instead of cutting words mid-way.
