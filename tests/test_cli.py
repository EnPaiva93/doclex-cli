from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from docsearch.cli import app
from docsearch.pipeline import Pipeline

runner = CliRunner()


def _env(docs_dir: Path, tmp_path: Path) -> dict:
    cache = tmp_path / ".cache"
    return {
        "DOCSEARCH_FOLDER": str(docs_dir),
        "DOCSEARCH_CACHE_DIR": str(cache),
        "DOCSEARCH_DB_PATH": str(cache / "docsearch.db"),
    }


def test_index_command_detects_new_files(docs_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["index", str(docs_dir)], env=_env(docs_dir, tmp_path))
    assert result.exit_code == 0
    assert "new" in result.output
    assert "Done" in result.output


def test_index_command_idempotent(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)
    result = runner.invoke(app, ["index", str(docs_dir)], env=env)
    assert result.exit_code == 0
    assert "up to date" in result.output


def test_status_command(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)
    result = runner.invoke(app, ["status", "--folder", str(docs_dir)], env=env)
    assert result.exit_code == 0
    assert "Files:" in result.output
    assert "Segments:" in result.output


def test_list_command(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)
    result = runner.invoke(app, ["list", "--folder", str(docs_dir)], env=env)
    assert result.exit_code == 0
    assert "indexed" in result.output
    assert "intro.md" in result.output


def test_list_filter_by_status(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)
    result = runner.invoke(app, ["list", "--folder", str(docs_dir), "--status", "indexed"], env=env)
    assert result.exit_code == 0
    assert "intro.md" in result.output


def test_search_returns_results(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)
    result = runner.invoke(app, ["search", "BM25 indexación", "--folder", str(docs_dir)], env=env)
    assert result.exit_code == 0
    assert "intro.md" in result.output
    assert "score" in result.output


def test_search_no_results(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)
    result = runner.invoke(app, ["search", "xyzzy_nonexistent_term_42", "--folder", str(docs_dir)], env=env)
    assert result.exit_code == 0
    assert "No results" in result.output


def test_reindex_command(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)

    # Modify the file with a highly distinctive term
    notas = docs_dir / "notas.txt"
    notas.write_text(notas.read_text() + "\nZorglub reindexado correctamente.\n", encoding="utf-8")

    result = runner.invoke(app, ["reindex", str(notas), "--folder", str(docs_dir)], env=env)
    assert result.exit_code == 0
    assert "Done" in result.output

    # New content is searchable
    result = runner.invoke(app, ["search", "Zorglub", "--folder", str(docs_dir)], env=env)
    assert "notas.txt" in result.output
