from __future__ import annotations

from pathlib import Path

import pytest

import doclex
from doclex import (
    Config,
    FileOutsideProjectError,
    Indexer,
    IndexMissingError,
    Searcher,
    clean_label,
    purge,
    results_to_dict,
)


def test_searcher_without_index_raises(docs_dir: Path) -> None:
    with pytest.raises(IndexMissingError):
        Searcher(Config(docs_dir))


def test_indexer_writes_nothing_until_start(docs_dir: Path) -> None:
    config = Config(docs_dir)
    Indexer(config)
    assert not config.cache_dir.exists()


async def test_use_before_start_raises(docs_dir: Path) -> None:
    indexer = Indexer(Config(docs_dir))
    with pytest.raises(RuntimeError, match="Indexer not started"):
        await indexer.scan()


async def test_searcher_offers_no_write_operations(docs_dir: Path) -> None:
    config = Config(docs_dir)
    async with Indexer(config) as indexer:
        await indexer.apply(await indexer.scan())
    searcher = Searcher(config)
    for name in ("scan", "apply", "reindex_files", "reindex_all"):
        assert not hasattr(searcher, name)


async def test_both_roles_can_inspect(docs_dir: Path) -> None:
    config = Config(docs_dir)
    async with Indexer(config) as indexer:
        await indexer.apply(await indexer.scan())
        assert len(await indexer.files()) == 3
    async with Searcher(config) as searcher:
        assert (await searcher.status())["files_indexed"] == 3


async def test_index_then_search(docs_dir: Path) -> None:
    config = Config(docs_dir)
    async with Indexer(config) as indexer:
        changes = await indexer.scan()
        assert len(changes.new) == 3
        await indexer.apply(changes)

    async with Searcher(config) as searcher:
        results = await searcher.search("Kreuzberg")
    assert results
    assert results[0].filename == "notas.txt"


async def test_scan_after_index_reports_no_changes(docs_dir: Path) -> None:
    config = Config(docs_dir)
    async with Indexer(config) as indexer:
        await indexer.apply(await indexer.scan())
        changes = await indexer.scan()
    assert not (changes.new or changes.modified or changes.deleted)


def test_resolve_files_rejects_missing_file(docs_dir: Path) -> None:
    indexer = Indexer(Config(docs_dir))
    with pytest.raises(FileNotFoundError):
        indexer.resolve_files([docs_dir / "nope.md"])


def test_resolve_files_rejects_file_outside_project(docs_dir: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside") / "x.md"
    outside.write_text("x", encoding="utf-8")
    indexer = Indexer(Config(docs_dir))
    with pytest.raises(FileOutsideProjectError):
        indexer.resolve_files([outside])


def test_resolve_files_returns_absolute_paths(
    docs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(docs_dir)
    indexer = Indexer(Config(docs_dir))
    [path] = indexer.resolve_files([Path("intro.md")])
    assert path.is_absolute()
    assert path == (docs_dir / "intro.md").resolve()


async def test_reindex_relative_path_updates_existing_record(
    docs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative --file must hit the record the scan created, not add a second one."""
    config = Config(docs_dir)
    async with Indexer(config) as indexer:
        await indexer.apply(await indexer.scan())
        monkeypatch.chdir(docs_dir)
        await indexer.reindex_files([Path("intro.md")])
        files = await indexer.files()
    assert len(files) == 3


async def test_purge_removes_cache(docs_dir: Path) -> None:
    config = Config(docs_dir)
    async with Indexer(config) as indexer:
        await indexer.apply(await indexer.scan())
    assert config.cache_dir.exists()

    removed = purge(config)
    assert config.cache_dir in removed
    assert not config.cache_dir.exists()


async def test_purge_removes_database_outside_cache(docs_dir: Path, tmp_path_factory) -> None:
    db_path = tmp_path_factory.mktemp("db") / "doclex.db"
    config = Config(docs_dir, db_path=db_path)
    async with Indexer(config) as indexer:
        await indexer.apply(await indexer.scan())
    assert db_path.exists()

    purge(config)
    assert not db_path.exists()
    assert not db_path.with_name("doclex.db-wal").exists()


def test_purge_without_data_removes_nothing(docs_dir: Path) -> None:
    assert purge(Config(docs_dir)) == []


def test_clean_label_drops_chunk_index_and_markdown() -> None:
    assert clean_label("## **Arquitectura** › 3") == "Arquitectura"


async def test_results_to_dict_shape(docs_dir: Path) -> None:
    config = Config(docs_dir)
    async with Indexer(config) as indexer:
        await indexer.apply(await indexer.scan())
    async with Searcher(config) as searcher:
        results = await searcher.search("Kreuzberg")

    data = results_to_dict("Kreuzberg", results)
    assert data["query"] == "Kreuzberg"
    assert data["total"] == len(results)
    passage = data["results"][0]["passages"][0]
    assert {"segment_id", "location_label", "snippet", "highlights"} <= passage.keys()
    assert "content" not in passage
    assert "content" in results_to_dict("Kreuzberg", results, include_content=True)["results"][0]["passages"][0]


def test_public_api_exports_resolve() -> None:
    for name in doclex.__all__:
        assert hasattr(doclex, name), name


def test_public_api_does_not_load_extraction() -> None:
    """Search startup depends on Kreuzberg loading lazily; the API must not pull it in."""
    import subprocess
    import sys

    code = "import sys, doclex; print('kreuzberg' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
