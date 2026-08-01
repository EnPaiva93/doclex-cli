from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from docsearch.cli import app

runner = CliRunner()


def _env(tmp_path: Path) -> dict:
    cache = tmp_path / ".cache"
    return {
        "DOCSEARCH_CACHE_DIR": str(cache),
        "DOCSEARCH_DB_PATH": str(cache / "docsearch.db"),
    }


def _register(docs_dir: Path, name: str = "proj") -> None:
    result = runner.invoke(app, ["project", "add", name, str(docs_dir)])
    assert result.exit_code == 0, result.output


def _index(docs_dir: Path, env: dict, project: str = "proj") -> None:
    """Helper: register the project and run index, mocking os._exit so it doesn't kill pytest."""
    _register(docs_dir, project)
    with patch("os._exit"):
        runner.invoke(app, ["index", "--project", project], env=env)


# ------------------------------------------------------------------
# project add / list / remove
# ------------------------------------------------------------------

def test_project_add_registers_project(docs_dir: Path) -> None:
    result = runner.invoke(app, ["project", "add", "proj", str(docs_dir)])
    assert result.exit_code == 0
    assert "proj" in result.output

    result = runner.invoke(app, ["project", "list"])
    assert "proj" in result.output
    assert str(docs_dir.resolve()) in result.output


def test_project_add_duplicate_name_rejected(docs_dir: Path) -> None:
    _register(docs_dir, "proj")
    result = runner.invoke(app, ["project", "add", "proj", str(docs_dir)])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_project_add_nonexistent_folder_rejected(tmp_path: Path) -> None:
    result = runner.invoke(app, ["project", "add", "proj", str(tmp_path / "missing")])
    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_project_add_overlapping_descendant_rejected(docs_dir: Path) -> None:
    _register(docs_dir, "a")
    subdir = docs_dir / "subdir"
    subdir.mkdir()
    result = runner.invoke(app, ["project", "add", "b", str(subdir)])
    assert result.exit_code != 0
    assert "overlaps" in result.output
    assert "a" in result.output


def test_project_add_overlapping_ancestor_rejected(docs_dir: Path) -> None:
    subdir = docs_dir / "subdir"
    subdir.mkdir()
    _register(subdir, "a")
    result = runner.invoke(app, ["project", "add", "b", str(docs_dir)])
    assert result.exit_code != 0
    assert "overlaps" in result.output


def test_project_list_empty() -> None:
    result = runner.invoke(app, ["project", "list"])
    assert result.exit_code == 0
    assert "No projects registered" in result.output


def test_project_list_shows_multiple(docs_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    other = tmp_path_factory.mktemp("other")
    _register(docs_dir, "a")
    _register(other, "b")
    result = runner.invoke(app, ["project", "list"])
    assert "a" in result.output
    assert "b" in result.output


def test_project_remove_deletes_registry_entry_and_cache(docs_dir: Path) -> None:
    """Uses the default cache location (<folder>/.docsearch), not the DOCSEARCH_CACHE_DIR
    override used elsewhere, so the purge path actually matches what index created."""
    _register(docs_dir)
    with patch("os._exit"):
        runner.invoke(app, ["index", "--project", "proj"])
    assert (docs_dir / ".docsearch").exists()

    result = runner.invoke(app, ["project", "remove", "proj"])
    assert result.exit_code == 0

    list_result = runner.invoke(app, ["project", "list"])
    assert "No projects registered" in list_result.output
    assert not (docs_dir / ".docsearch").exists()


def test_project_remove_unknown_name() -> None:
    result = runner.invoke(app, ["project", "remove", "nope"])
    assert result.exit_code != 0
    assert "No project named" in result.output


# ------------------------------------------------------------------
# unknown project errors
# ------------------------------------------------------------------

def test_index_unknown_project() -> None:
    result = runner.invoke(app, ["index", "--project", "nope"])
    assert result.exit_code != 0
    assert "No project named" in result.output


def test_search_unknown_project() -> None:
    result = runner.invoke(app, ["search", "query", "--project", "nope"])
    assert result.exit_code != 0
    assert "No project named" in result.output


def test_status_unknown_project() -> None:
    result = runner.invoke(app, ["status", "--project", "nope"])
    assert result.exit_code != 0
    assert "No project named" in result.output


# ------------------------------------------------------------------
# index
# ------------------------------------------------------------------

def test_index_command_detects_new_files(docs_dir: Path, tmp_path: Path) -> None:
    _register(docs_dir)
    with patch("os._exit"):
        result = runner.invoke(app, ["index", "--project", "proj"], env=_env(tmp_path))
    assert result.exit_code == 0
    assert "new" in result.output
    assert "Done" in result.output


def test_index_command_idempotent(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _register(docs_dir)
    with patch("os._exit"):
        runner.invoke(app, ["index", "--project", "proj"], env=env)
        result = runner.invoke(app, ["index", "--project", "proj"], env=env)
    assert result.exit_code == 0
    assert "up to date" in result.output


def test_index_single_file(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)

    notas = docs_dir / "notas.txt"
    notas.write_text(notas.read_text() + "\nZorglub reindexado correctamente.\n", encoding="utf-8")

    with patch("os._exit"):
        result = runner.invoke(
            app,
            ["index", "--project", "proj", "--file", str(notas)],
            env=env,
        )
    assert result.exit_code == 0
    assert "Reindexed" in result.output

    result = runner.invoke(app, ["search", "Zorglub", "--project", "proj"], env=env)
    assert "notas.txt" in result.output


def test_index_multiple_files_via_repeated_flag(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)

    notas = docs_dir / "notas.txt"
    intro = docs_dir / "intro.md"

    with patch("os._exit"):
        result = runner.invoke(
            app,
            ["index", "--project", "proj", "--file", str(notas), "--file", str(intro)],
            env=env,
        )
    assert result.exit_code == 0
    assert "Reindexed 2 file(s)" in result.output


def test_index_requires_project(docs_dir: Path, tmp_path: Path) -> None:
    notas = docs_dir / "notas.txt"
    result = runner.invoke(app, ["index", "--file", str(notas)], env=_env(tmp_path))
    assert result.exit_code != 0


def test_index_force(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    with patch("os._exit"):
        _index(docs_dir, env)
        result = runner.invoke(app, ["index", "--project", "proj", "--force"], env=env)
    assert result.exit_code == 0
    assert "Done" in result.output


# ------------------------------------------------------------------
# search
# ------------------------------------------------------------------

def test_search_returns_results(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)
    result = runner.invoke(app, ["search", "BM25 indexación", "--project", "proj"], env=env)
    assert result.exit_code == 0
    assert "intro.md" in result.output
    assert "score" in result.output


def test_search_no_results(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)
    result = runner.invoke(app, ["search", "xyzzy_nonexistent_term_42", "--project", "proj"], env=env)
    assert result.exit_code == 0
    assert "No results" in result.output


def test_search_full_flag(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)
    result_snippet = runner.invoke(app, ["search", "BM25", "--project", "proj"], env=env)
    result_full = runner.invoke(app, ["search", "BM25", "--project", "proj", "--full"], env=env)
    assert result_full.exit_code == 0
    assert len(result_full.output) >= len(result_snippet.output)


# ------------------------------------------------------------------
# status
# ------------------------------------------------------------------

def test_status_corpus_summary(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)
    result = runner.invoke(app, ["status", "--project", "proj"], env=env)
    assert result.exit_code == 0
    assert "Indexed" in result.output
    assert "Segments" in result.output


def test_status_shows_pending_when_file_added(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)

    (docs_dir / "nuevo.txt").write_text("Archivo nuevo sin indexar todavía.\n" * 5, encoding="utf-8")

    result = runner.invoke(app, ["status", "--project", "proj"], env=env)
    assert result.exit_code == 0
    assert "new" in result.output or "Needs reindex" in result.output


def test_status_up_to_date(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)
    result = runner.invoke(app, ["status", "--project", "proj"], env=env)
    assert "up to date" in result.output


def test_status_files_list(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)
    result = runner.invoke(app, ["status", "--project", "proj", "--list"], env=env)
    assert result.exit_code == 0
    assert "indexed" in result.output
    assert "intro" in result.output


def test_status_files_filter(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)
    result = runner.invoke(app, ["status", "--project", "proj", "--list", "--filter", "indexed"], env=env)
    assert result.exit_code == 0
    assert "indexed" in result.output


def test_status_single_file(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)
    notas = docs_dir / "notas.txt"
    result = runner.invoke(app, ["status", "--project", "proj", "--file", str(notas)], env=env)
    assert result.exit_code == 0
    assert "On disk" in result.output
    assert "Segments" in result.output


def test_status_single_file_detects_modification(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)

    notas = docs_dir / "notas.txt"
    notas.write_text(notas.read_text() + "\nCambio sin reindexar.\n", encoding="utf-8")

    result = runner.invoke(app, ["status", "--project", "proj", "--file", str(notas)], env=env)
    assert result.exit_code == 0
    assert "yes" in result.output  # Modified on disk: yes


def test_status_multiple_files_each_printed(docs_dir: Path, tmp_path: Path) -> None:
    """Regression test: each --file must print its own detail table, not just the last one."""
    env = _env(tmp_path)
    _index(docs_dir, env)

    intro = docs_dir / "intro.md"
    notas = docs_dir / "notas.txt"
    result = runner.invoke(
        app,
        ["status", "--project", "proj", "--file", str(intro), "--file", str(notas)],
        env=env,
    )
    assert result.exit_code == 0
    assert "intro.md" in result.output
    assert "notas.txt" in result.output
    assert result.output.count("On disk") == 2
