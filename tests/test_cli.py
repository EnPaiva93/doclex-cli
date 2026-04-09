from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from docsearch.cli import app

runner = CliRunner()


def _env(docs_dir: Path, tmp_path: Path) -> dict:
    cache = tmp_path / ".cache"
    return {
        "DOCSEARCH_FOLDER": str(docs_dir),
        "DOCSEARCH_CACHE_DIR": str(cache),
        "DOCSEARCH_DB_PATH": str(cache / "docsearch.db"),
    }


# ------------------------------------------------------------------
# index
# ------------------------------------------------------------------

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


def test_index_single_file(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)

    notas = docs_dir / "notas.txt"
    notas.write_text(notas.read_text() + "\nZorglub reindexado correctamente.\n", encoding="utf-8")

    result = runner.invoke(app, ["index", str(notas), "--folder", str(docs_dir)], env=env)
    assert result.exit_code == 0
    assert "Reindexed" in result.output

    result = runner.invoke(app, ["search", "Zorglub", "--folder", str(docs_dir)], env=env)
    assert "notas.txt" in result.output


def test_index_single_file_requires_folder(docs_dir: Path, tmp_path: Path) -> None:
    notas = docs_dir / "notas.txt"
    env = {**_env(docs_dir, tmp_path), "DOCSEARCH_FOLDER": ""}
    result = runner.invoke(app, ["index", str(notas)], env=env)
    assert result.exit_code != 0 or "Error" in result.output


def test_index_force(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)
    result = runner.invoke(app, ["index", str(docs_dir), "--force"], env=env)
    assert result.exit_code == 0
    assert "Done" in result.output


# ------------------------------------------------------------------
# search
# ------------------------------------------------------------------

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


def test_search_full_flag(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)
    result_snippet = runner.invoke(app, ["search", "BM25", "--folder", str(docs_dir)], env=env)
    result_full = runner.invoke(app, ["search", "BM25", "--folder", str(docs_dir), "--full"], env=env)
    assert result_full.exit_code == 0
    # Full output is >= snippet output in length
    assert len(result_full.output) >= len(result_snippet.output)


# ------------------------------------------------------------------
# status
# ------------------------------------------------------------------

def test_status_corpus_summary(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)
    result = runner.invoke(app, ["status", "--folder", str(docs_dir)], env=env)
    assert result.exit_code == 0
    assert "Indexed" in result.output
    assert "Segments" in result.output


def test_status_shows_pending_when_file_added(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)

    # Add a new file without reindexing
    (docs_dir / "nuevo.txt").write_text("Archivo nuevo sin indexar todavía.\n" * 5, encoding="utf-8")

    result = runner.invoke(app, ["status", "--folder", str(docs_dir)], env=env)
    assert result.exit_code == 0
    assert "new" in result.output or "Needs reindex" in result.output


def test_status_up_to_date(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)
    result = runner.invoke(app, ["status", "--folder", str(docs_dir)], env=env)
    assert "up to date" in result.output


def test_status_files_list(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)
    result = runner.invoke(app, ["status", "--folder", str(docs_dir), "--files"], env=env)
    assert result.exit_code == 0
    assert "indexed" in result.output
    assert "intro" in result.output


def test_status_files_filter(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)
    result = runner.invoke(app, ["status", "--folder", str(docs_dir), "--files", "--filter", "indexed"], env=env)
    assert result.exit_code == 0
    assert "indexed" in result.output


def test_status_single_file(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)
    notas = docs_dir / "notas.txt"
    result = runner.invoke(app, ["status", str(notas), "--folder", str(docs_dir)], env=env)
    assert result.exit_code == 0
    assert "On disk" in result.output
    assert "Segments" in result.output


def test_status_single_file_detects_modification(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(docs_dir, tmp_path)
    runner.invoke(app, ["index", str(docs_dir)], env=env)

    notas = docs_dir / "notas.txt"
    notas.write_text(notas.read_text() + "\nCambio sin reindexar.\n", encoding="utf-8")

    result = runner.invoke(app, ["status", str(notas), "--folder", str(docs_dir)], env=env)
    assert result.exit_code == 0
    assert "yes" in result.output  # Modified on disk: yes
