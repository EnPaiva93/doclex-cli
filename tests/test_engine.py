from __future__ import annotations

from pathlib import Path

import pytest

from doclex.config import Config
from doclex.engine import Engine, FileOutsideProjectError, IndexMissingError
from doclex.results import clean_label, results_to_dict


def test_open_without_index_raises(docs_dir: Path) -> None:
    with pytest.raises(IndexMissingError):
        Engine.open(Config(docs_dir))


def test_open_with_create_writes_nothing_until_start(docs_dir: Path) -> None:
    config = Config(docs_dir)
    Engine.open(config, create=True)
    assert not config.cache_dir.exists()


async def test_use_before_start_raises(docs_dir: Path) -> None:
    engine = Engine.open(Config(docs_dir), create=True)
    with pytest.raises(RuntimeError):
        await engine.search("x")


async def test_index_then_search(docs_dir: Path) -> None:
    config = Config(docs_dir)
    async with Engine.open(config, create=True) as engine:
        changes = await engine.scan()
        assert len(changes.new) == 3
        await engine.apply(changes)

    async with Engine.open(config) as engine:
        results = await engine.search("Kreuzberg")
    assert results
    assert results[0].filename == "notas.txt"


async def test_scan_after_index_reports_no_changes(docs_dir: Path) -> None:
    config = Config(docs_dir)
    async with Engine.open(config, create=True) as engine:
        await engine.apply(await engine.scan())
        changes = await engine.scan()
    assert not (changes.new or changes.modified or changes.deleted)


def test_resolve_files_rejects_missing_file(docs_dir: Path) -> None:
    engine = Engine.open(Config(docs_dir), create=True)
    with pytest.raises(FileNotFoundError):
        engine.resolve_files([docs_dir / "nope.md"])


def test_resolve_files_rejects_file_outside_project(docs_dir: Path, tmp_path_factory) -> None:
    outside = tmp_path_factory.mktemp("outside") / "x.md"
    outside.write_text("x", encoding="utf-8")
    engine = Engine.open(Config(docs_dir), create=True)
    with pytest.raises(FileOutsideProjectError):
        engine.resolve_files([outside])


def test_resolve_files_returns_absolute_paths(
    docs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(docs_dir)
    engine = Engine.open(Config(docs_dir), create=True)
    [path] = engine.resolve_files([Path("intro.md")])
    assert path.is_absolute()
    assert path == (docs_dir / "intro.md").resolve()


async def test_reindex_relative_path_updates_existing_record(
    docs_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative --file must hit the record the scan created, not add a second one."""
    config = Config(docs_dir)
    async with Engine.open(config, create=True) as engine:
        await engine.apply(await engine.scan())
        monkeypatch.chdir(docs_dir)
        await engine.reindex_files([Path("intro.md")])
        files = await engine.files()
    assert len(files) == 3


async def test_purge_removes_cache(docs_dir: Path) -> None:
    config = Config(docs_dir)
    async with Engine.open(config, create=True) as engine:
        await engine.apply(await engine.scan())
    assert config.cache_dir.exists()

    removed = Engine.purge(config)
    assert config.cache_dir in removed
    assert not config.cache_dir.exists()


async def test_purge_removes_database_outside_cache(docs_dir: Path, tmp_path_factory) -> None:
    db_path = tmp_path_factory.mktemp("db") / "doclex.db"
    config = Config(docs_dir, db_path=db_path)
    async with Engine.open(config, create=True) as engine:
        await engine.apply(await engine.scan())
    assert db_path.exists()

    Engine.purge(config)
    assert not db_path.exists()
    assert not db_path.with_name("doclex.db-wal").exists()


def test_purge_without_data_removes_nothing(docs_dir: Path) -> None:
    assert Engine.purge(Config(docs_dir)) == []


def test_clean_label_drops_chunk_index_and_markdown() -> None:
    assert clean_label("## **Arquitectura** › 3") == "Arquitectura"


async def test_results_to_dict_shape(docs_dir: Path) -> None:
    config = Config(docs_dir)
    async with Engine.open(config, create=True) as engine:
        await engine.apply(await engine.scan())
        results = await engine.search("Kreuzberg")

    data = results_to_dict("Kreuzberg", results)
    assert data["query"] == "Kreuzberg"
    assert data["total"] == len(results)
    passage = data["results"][0]["passages"][0]
    assert {"segment_id", "location_label", "snippet", "highlights"} <= passage.keys()
    assert "content" not in passage
    assert "content" in results_to_dict("Kreuzberg", results, include_content=True)["results"][0]["passages"][0]
