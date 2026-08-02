# DocSearch

Local document search for AI agents — BM25 lexical search over your files, no embeddings, no vector DB, no cloud.

Point it at a folder of PDFs, DOCX, XLSX, CSV, Markdown or TXT files and get precise, citable search results in milliseconds.

## Why

Most "search your docs" tools reach for embeddings and a vector database. DocSearch doesn't:

- **Local-first** — everything runs on your machine, nothing leaves it.
- **Deterministic** — BM25 lexical scoring, no black-box similarity.
- **Traceable** — every result cites its file, page/sheet/section, and score.
- **Incremental** — only reprocesses files that actually changed.

## Install

Requires Python ≥3.12 and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo-url>
cd SearchDocs
uv sync
```

## Quickstart

```bash
# register a folder as a project
uv run docsearch project add mydocs ./path/to/documents

# build the index
uv run docsearch index --project mydocs

# search it
uv run docsearch search "quarterly budget" --project mydocs
```

```
[1] budget_2024.pdf — page 3  (score: 4.812)
    "...the quarterly budget was approved with a 12% increase in..."

[2] notes.md — Planning  (score: 2.107)
    "...need to revisit the budget assumptions before..."
```

## Projects

Every command operates on a **registered project** — a name bound to a folder — instead of a raw `--folder` flag. This keeps folder resolution unambiguous and lets DocSearch reject overlapping folders (a subfolder registered as its own project would silently duplicate indexing and caching):

```bash
docsearch project add mydocs ./path/to/documents
docsearch project add mydocs ./other       # error: name already exists
docsearch project add sub ./path/to/documents/subdir   # error: overlaps with 'mydocs'
docsearch project remove mydocs            # deregisters and purges its cache/index
```

## Commands

| Command | Description |
|---|---|
| `docsearch project add <name> <folder>` | Register a folder under a project name |
| `docsearch project list` | List registered projects |
| `docsearch project remove <name>` | Remove a project and purge its cache/index |
| `docsearch index --project <name>` | Scan and index (incremental by default) |
| `docsearch search <query> --project <name>` | Search and print results with citations |
| `docsearch status --project <name>` | Show corpus/index status |

Run `docsearch <command> --help` for all flags and examples.

### More examples

```bash
# force a full re-extraction
docsearch index --project mydocs --force

# reindex specific files after editing them
docsearch index --project mydocs --file report.pdf --file notes.docx

# more results, full segment text instead of a snippet
docsearch search "risk assessment" --project mydocs --top 20 --full

# list every indexed file and its status
docsearch status --project mydocs --list --filter error
```

## Architecture

```
folder → scan/watch → extract (Kreuzberg) → segment → BM25X index
                                                  ↕
                                          SQLite (files, segments)
```

| Layer | Responsibility |
|---|---|
| **Ingestion** | Scans a project's folder, hashes files to detect new/modified/deleted ones, skips its own cache directory |
| **Extraction** | Delegates to [Kreuzberg](https://github.com/Goldziher/kreuzberg) to turn each file into plain text, normalized to an internal format |
| **Segmentation** | Splits text along the file's natural structure — never blind fixed-size chunking (PDF → page, XLSX → sheet, DOCX → section, TXT/MD → block) |
| **Index** | Indexes segments (not whole files) with BM25X; supports incremental add/update/delete |
| **Metadata** | SQLite tracks each file's hash, mtime, size, MIME type, and indexing status, plus which segments belong to it |

A local cache stores extracted text and generated segments per file, so unchanged files are never reprocessed.

## Supported file types

PDF · TXT · Markdown · DOCX · XLSX · CSV

## Design principles

DocSearch is built to be local-first, incremental, explainable, deterministic, and cheap to run. It deliberately does **not**:

- use embeddings or a vector database
- upload files anywhere
- depend on external services to search
- run OCR by default
- generate answers — it retrieves evidence; answering is the agent's job

## Roadmap

- [x] **Phase 1 — CLI**: scanning, extraction, segmentation, BM25 indexing, incremental updates, local cache, SQLite state *(done)*
- [ ] **Phase 2 — MCP server**: expose the same pipeline as MCP tools (search, list, inspect, force reindex) for AI agents
- [ ] **Phase 3 — optional**: OCR, advanced filters, query expansion/rewriting, multi-step search

## Stack

Python · [Typer](https://typer.tiangolo.com/) · [Kreuzberg](https://github.com/Goldziher/kreuzberg) · BM25X · Watchdog · SQLite

## Development

```bash
uv sync --extra dev
uv run pytest
```
