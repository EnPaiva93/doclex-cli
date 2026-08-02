# Doclex

*English · [Español](README.es.md)*

A CLI that turns a local folder of documents into a searchable, citable corpus. Point it at a folder; extraction, segmentation, indexing, and change tracking happen automatically.

## Why

[Kreuzberg](https://github.com/Goldziher/kreuzberg) extracts text. BM25X indexes strings. Neither knows what a "file" is, when it changed, or how to turn a match back into a citation. Doclex is the orchestration layer that ties them together so you never have to think about the pipeline yourself:

- **Plug and play** — point it at a folder. Extraction, structural segmentation, indexing, and change tracking all happen automatically; there's no pipeline to wire up.
- **SQLite is the source of truth** — every file's hash, mtime, and indexing status live in one place, so Doclex always knows exactly what changed and reprocesses only that.
- **Local-first** — everything runs on your machine, nothing leaves it. No embeddings, no vector database, no cloud.
- **Deterministic** — BM25 lexical scoring, no black-box similarity.
- **Traceable** — every result cites its file, page/sheet/section, and score.
- **Incremental** — only reprocesses files that actually changed.

## Install

Requires Python ≥3.12 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/EnPaiva93/doclex-cli.git
cd doclex-cli
uv sync
```

## Quickstart

```bash
# register a folder as a project
uv run doclex add mydocs ./path/to/documents

# build the index
uv run doclex index --project mydocs

# search it
uv run doclex search "quarterly budget" --project mydocs
```

```
[1] budget_2024.pdf — page 3  (score: 4.812)
    "...the quarterly budget was approved with a 12% increase in..."

[2] notes.md — Planning  (score: 2.107)
    "...need to revisit the budget assumptions before..."
```

## Walkthrough

A typical day-to-day flow, from an empty project to keeping it in sync:

```bash
# 1. register the folder you want to search
doclex add contracts ~/Documents/legal/contracts

# 2. build the index — extracts, segments, and indexes every supported file
doclex index --project contracts
```
```
Processing: 42 new, 0 modified, 0 deleted
✓ Done.
```
```bash
# 3. search it
doclex search "termination clause" --project contracts
```
```
[1] MSA_2023_AcmeCorp.pdf — Section 9.2  (score: 6.104)
    "...either party may terminate this Agreement upon 30 days written notice..."

[2] vendor_agreement_v3.docx — Termination  (score: 5.887)
    "...termination for convenience requires 60 days advance notice to..."
```
```bash
# 4. check what's indexed
doclex status --project contracts
```
```
Folder       ~/Documents/legal/contracts
Indexed      42 files
Segments     318
BM25 index   318 docs
Disk state   up to date
```
```bash
# 5. a new contract shows up on disk — reindexing picks it up automatically
doclex index --project contracts
```
```
Processing: 1 new, 0 modified, 0 deleted
✓ Done.
```
```bash
# 6. see every registered project
doclex list
```
```
Name        Folder
contracts   /home/you/Documents/legal/contracts
```
```bash
# 7. done with it — deregister and purge its cache/index
doclex remove contracts
```

Each project is independent — register as many non-overlapping folders as you need, each with its own cache and index:

```bash
doclex add hr-policies ~/Documents/hr
doclex index --project hr-policies
doclex search "vacation days" --project hr-policies --top 5
```

## Projects

Every command operates on a **registered project** — a name bound to a folder — instead of a raw `--folder` flag. This keeps folder resolution unambiguous and lets Doclex reject overlapping folders (a subfolder registered as its own project would silently duplicate indexing and caching):

```bash
doclex add mydocs ./path/to/documents
doclex add mydocs ./other       # error: name already exists
doclex add sub ./path/to/documents/subdir   # error: overlaps with 'mydocs'
doclex remove mydocs            # deregisters and purges its cache/index
```

## Commands

| Command | Description |
|---|---|
| `doclex add <name> <folder>` | Register a folder under a project name |
| `doclex list` | List registered projects |
| `doclex remove <name>` | Remove a project and purge its cache/index |
| `doclex index --project <name>` | Scan and index (incremental by default) |
| `doclex search <query> --project <name>` | Search and print results with citations |
| `doclex status --project <name>` | Show corpus/index status |

Run `doclex <command> --help` for all flags and examples.

### Flags in practice

```bash
# force a full re-extraction
doclex index --project mydocs --force

# reindex specific files after editing them
doclex index --project mydocs --file report.pdf --file notes.docx

# more results, full segment text instead of a snippet
doclex search "risk assessment" --project mydocs --top 20 --full

# list every indexed file and its status
doclex status --project mydocs --all --filter error
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

Doclex is built to be local-first, incremental, explainable, deterministic, and cheap to run. It deliberately does **not**:

- use embeddings or a vector database
- upload files anywhere
- depend on external services to search
- run OCR by default
- generate answers — it retrieves evidence, it doesn't interpret it

## Stack

Python · [Typer](https://typer.tiangolo.com/) · [Kreuzberg](https://github.com/Goldziher/kreuzberg) · BM25X · Watchdog · SQLite

## Development

```bash
uv sync --extra dev
uv run pytest
```
