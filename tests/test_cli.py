from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from doclex.cli import app

runner = CliRunner()


def _env(tmp_path: Path) -> dict:
    cache = tmp_path / ".cache"
    return {
        "DOCLEX_CACHE_DIR": str(cache),
        "DOCLEX_DB_PATH": str(cache / "doclex.db"),
    }


def _register(docs_dir: Path, name: str = "proj") -> None:
    result = runner.invoke(app, ["add", name, str(docs_dir)])
    assert result.exit_code == 0, result.output


def _index(docs_dir: Path, env: dict, project: str = "proj") -> None:
    """Helper: register the project and run index, mocking os._exit so it doesn't kill pytest."""
    _register(docs_dir, project)
    with patch("os._exit"):
        runner.invoke(app, ["index", "--project", project], env=env)


# ------------------------------------------------------------------
# add / projects / remove
# ------------------------------------------------------------------

def test_project_add_registers_project(docs_dir: Path) -> None:
    result = runner.invoke(app, ["add", "proj", str(docs_dir)])
    assert result.exit_code == 0
    assert "proj" in result.output

    result = runner.invoke(app, ["list"])
    assert "proj" in result.output
    assert str(docs_dir.resolve()) in result.output


def test_project_add_duplicate_name_rejected(docs_dir: Path) -> None:
    _register(docs_dir, "proj")
    result = runner.invoke(app, ["add", "proj", str(docs_dir)])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_project_add_nonexistent_folder_rejected(tmp_path: Path) -> None:
    result = runner.invoke(app, ["add", "proj", str(tmp_path / "missing")])
    assert result.exit_code != 0
    assert "does not exist" in result.output


def test_project_add_overlapping_descendant_rejected(docs_dir: Path) -> None:
    _register(docs_dir, "a")
    subdir = docs_dir / "subdir"
    subdir.mkdir()
    result = runner.invoke(app, ["add", "b", str(subdir)])
    assert result.exit_code != 0
    assert "overlaps" in result.output
    assert "a" in result.output


def test_project_add_overlapping_ancestor_rejected(docs_dir: Path) -> None:
    subdir = docs_dir / "subdir"
    subdir.mkdir()
    _register(subdir, "a")
    result = runner.invoke(app, ["add", "b", str(docs_dir)])
    assert result.exit_code != 0
    assert "overlaps" in result.output


def test_projects_empty() -> None:
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "No projects registered" in result.output


def test_projects_shows_multiple(docs_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    other = tmp_path_factory.mktemp("other")
    _register(docs_dir, "a")
    _register(other, "b")
    result = runner.invoke(app, ["list"])
    assert "a" in result.output
    assert "b" in result.output


def test_project_remove_deletes_registry_entry_and_cache(docs_dir: Path) -> None:
    """Uses the default cache location (<folder>/.doclex), not the DOCLEX_CACHE_DIR
    override used elsewhere, so the purge path actually matches what index created."""
    _register(docs_dir)
    with patch("os._exit"):
        runner.invoke(app, ["index", "--project", "proj"])
    assert (docs_dir / ".doclex").exists()

    result = runner.invoke(app, ["remove", "proj"])
    assert result.exit_code == 0

    list_result = runner.invoke(app, ["list"])
    assert "No projects registered" in list_result.output
    assert not (docs_dir / ".doclex").exists()


def test_project_remove_unknown_name() -> None:
    result = runner.invoke(app, ["remove", "nope"])
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
    assert re.search(r"\d+\.\d{3}", result.output)  # document score


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
    result = runner.invoke(app, ["status", "--project", "proj", "--all"], env=env)
    assert result.exit_code == 0
    assert "indexed" in result.output
    assert "intro" in result.output


def test_status_files_filter(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)
    result = runner.invoke(app, ["status", "--project", "proj", "--all", "--filter", "indexed"], env=env)
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


# ------------------------------------------------------------------
# search — document grouping and JSON output
# ------------------------------------------------------------------

def test_search_lists_each_document_once(docs_dir: Path, tmp_path: Path) -> None:
    """A file matching in several segments is one result, not several rows."""
    env = _env(tmp_path)
    _index(docs_dir, env)

    result = runner.invoke(app, ["search", "BM25", "--project", "proj"], env=env)
    assert result.exit_code == 0
    assert result.output.count("intro.md") == 1


def test_search_json_is_grouped_by_document(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)

    result = runner.invoke(
        app, ["search", "BM25", "--project", "proj", "--json"], env=env
    )
    assert result.exit_code == 0

    payload = json.loads(result.output)
    assert payload["query"] == "BM25"
    assert payload["total"] == len(payload["results"])

    filenames = [doc["filename"] for doc in payload["results"]]
    assert len(filenames) == len(set(filenames))

    for doc in payload["results"]:
        assert doc["passages"], "every document result carries its matching passages"
        for passage in doc["passages"]:
            snippet = passage["snippet"]
            for h in passage["highlights"]:
                assert snippet[h["start"]:h["end"]]


def test_search_passages_flag_limits_passages_per_document(
    docs_dir: Path, tmp_path: Path
) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)

    result = runner.invoke(
        app,
        ["search", "BM25", "--project", "proj", "--passages", "1", "--json"],
        env=env,
    )
    assert result.exit_code == 0

    payload = json.loads(result.output)
    assert all(len(doc["passages"]) <= 1 for doc in payload["results"])


def test_search_top_counts_documents_not_passages(docs_dir: Path, tmp_path: Path) -> None:
    env = _env(tmp_path)
    _index(docs_dir, env)

    result = runner.invoke(
        app, ["search", "BM25", "--project", "proj", "--top", "1", "--json"], env=env
    )
    assert result.exit_code == 0
    assert len(json.loads(result.output)["results"]) == 1


def test_search_survives_terms_nested_in_each_other(docs_dir: Path, tmp_path: Path) -> None:
    """Overlapping matches used to splice broken markup and crash the renderer."""
    env = _env(tmp_path)
    _index(docs_dir, env)

    result = runner.invoke(
        app,
        ["search", "indexación de la documentación con index", "--project", "proj"],
        env=env,
    )
    assert result.exit_code == 0, result.output


def test_search_renders_text_containing_brackets(tmp_path: Path) -> None:
    """Square brackets in a document must not be parsed as console markup."""
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "nota.md").write_text(
        "# Nota\n\nEl artículo [30] fija el plazo de vacaciones anuales del personal.\n" * 3,
        encoding="utf-8",
    )
    env = _env(tmp_path)
    _index(folder, env)

    result = runner.invoke(app, ["search", "vacaciones", "--project", "proj"], env=env)
    assert result.exit_code == 0, result.output
    assert "[30]" in result.output


def test_status_reports_files_without_extractable_text(tmp_path: Path) -> None:
    """A scanned PDF indexes cleanly and can never be found; status must say so."""
    folder = tmp_path / "docs"
    folder.mkdir()
    # A large file whose extracted text is a few characters, like a scan.
    (folder / "escaneado.txt").write_text("Anexo 1.\n" + "\x00" * 200_000, encoding="utf-8")
    (folder / "normal.md").write_text("# Nota\n\n" + ("Texto real del documento. " * 200), encoding="utf-8")

    env = _env(tmp_path)
    _index(folder, env)

    summary = runner.invoke(app, ["status", "--project", "proj"], env=env)
    assert summary.exit_code == 0
    assert "No text" in summary.output

    listed = runner.invoke(
        app, ["status", "--project", "proj", "--all", "--filter", "no-text"], env=env
    )
    assert listed.exit_code == 0
    assert "escaneado.txt" in listed.output
    assert "normal.md" not in listed.output


def test_search_warns_when_the_index_predates_the_segmentation(
    docs_dir: Path, tmp_path: Path
) -> None:
    """An index built by an older Doclex yields wrong citations; say so."""
    env = _env(tmp_path)
    _index(docs_dir, env)

    import sqlite3

    conn = sqlite3.connect(tmp_path / ".cache" / "doclex.db")
    conn.execute("UPDATE meta SET value = '1' WHERE key = 'index_version'")
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["search", "BM25", "--project", "proj"], env=env)
    assert result.exit_code == 0
    assert "outdated segments" in result.output

    status = runner.invoke(app, ["status", "--project", "proj"], env=env)
    assert "outdated" in status.output
