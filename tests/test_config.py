from __future__ import annotations

from pathlib import Path

import pytest

from doclex.config import Config


def test_defaults_derive_from_folder(tmp_path: Path) -> None:
    cfg = Config(tmp_path)
    assert cfg.folder == tmp_path.resolve()
    assert cfg.cache_dir == tmp_path.resolve() / ".doclex"
    assert cfg.db_path == cfg.cache_dir / "doclex.db"
    assert cfg.bm25_index_dir == cfg.cache_dir / "bm25_index"
    assert cfg.top_k == 10
    assert cfg.debounce_secs == 1.0


def test_explicit_arguments_win(tmp_path: Path) -> None:
    cache = tmp_path / "elsewhere"
    cfg = Config(tmp_path, cache_dir=cache, top_k=3)
    assert cfg.cache_dir == cache.resolve()
    assert cfg.db_path == cache.resolve() / "doclex.db"
    assert cfg.top_k == 3


def test_rejects_missing_folder(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Config(tmp_path / "nope")


def test_does_not_read_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCLEX_CACHE_DIR", str(tmp_path / "from-env"))
    monkeypatch.setenv("DOCLEX_TOP_K", "99")
    cfg = Config(tmp_path)
    assert cfg.cache_dir == tmp_path.resolve() / ".doclex"
    assert cfg.top_k == 10


def test_from_env_reads_overrides(tmp_path: Path) -> None:
    env = {
        "DOCLEX_FOLDER": str(tmp_path),
        "DOCLEX_CACHE_DIR": str(tmp_path / "c"),
        "DOCLEX_TOP_K": "5",
        "DOCLEX_DEBOUNCE": "0.5",
    }
    cfg = Config.from_env(environ=env)
    assert cfg.folder == tmp_path.resolve()
    assert cfg.cache_dir == (tmp_path / "c").resolve()
    assert cfg.top_k == 5
    assert cfg.debounce_secs == 0.5


def test_from_env_folder_argument_beats_variable(tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    cfg = Config.from_env(other, environ={"DOCLEX_FOLDER": str(tmp_path)})
    assert cfg.folder == other.resolve()


def test_from_env_requires_a_folder() -> None:
    with pytest.raises(ValueError):
        Config.from_env(environ={})
