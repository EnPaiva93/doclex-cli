from __future__ import annotations

from pathlib import Path

import pytest

from doclex.registry import (
    ProjectAlreadyExistsError,
    ProjectFolderNotFoundError,
    ProjectNotFoundError,
    ProjectOverlapError,
    ProjectRegistry,
)


def _registry(tmp_path: Path) -> ProjectRegistry:
    return ProjectRegistry(path=tmp_path / "registry.json")


def test_add_registers_and_get_returns_project(tmp_path: Path) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    reg = _registry(tmp_path)

    reg.add("p", folder)
    project = reg.get("p")

    assert project.name == "p"
    assert project.folder == folder.resolve()


def test_add_rejects_duplicate_name(tmp_path: Path) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    reg = _registry(tmp_path)
    reg.add("p", folder)

    with pytest.raises(ProjectAlreadyExistsError):
        reg.add("p", other)


def test_add_rejects_nonexistent_folder(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    with pytest.raises(ProjectFolderNotFoundError):
        reg.add("p", tmp_path / "missing")


def test_add_rejects_when_new_folder_is_descendant_of_existing(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    child = parent / "child"
    child.mkdir()
    reg = _registry(tmp_path)
    reg.add("parent", parent)

    with pytest.raises(ProjectOverlapError):
        reg.add("child", child)


def test_add_rejects_when_new_folder_is_ancestor_of_existing(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    child = parent / "child"
    child.mkdir()
    reg = _registry(tmp_path)
    reg.add("child", child)

    with pytest.raises(ProjectOverlapError):
        reg.add("parent", parent)


def test_add_rejects_exact_duplicate_folder_under_different_name(tmp_path: Path) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    reg = _registry(tmp_path)
    reg.add("p1", folder)

    with pytest.raises(ProjectOverlapError):
        reg.add("p2", folder)


def test_get_raises_for_unknown_project(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    with pytest.raises(ProjectNotFoundError):
        reg.get("nope")


def test_list_returns_sorted_by_name(tmp_path: Path) -> None:
    zeta = tmp_path / "zeta"
    zeta.mkdir()
    alpha = tmp_path / "alpha"
    alpha.mkdir()
    reg = _registry(tmp_path)
    reg.add("zeta", zeta)
    reg.add("alpha", alpha)

    names = [p.name for p in reg.list()]
    assert names == ["alpha", "zeta"]


def test_list_empty_registry_returns_empty_list(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    assert reg.list() == []


def test_remove_deletes_entry_and_returns_project(tmp_path: Path) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    reg = _registry(tmp_path)
    reg.add("p", folder)

    removed = reg.remove("p")

    assert removed.name == "p"
    with pytest.raises(ProjectNotFoundError):
        reg.get("p")


def test_remove_raises_for_unknown_project(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    with pytest.raises(ProjectNotFoundError):
        reg.remove("nope")


def test_persistence_across_separate_registry_instances(tmp_path: Path) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    path = tmp_path / "registry.json"

    ProjectRegistry(path=path).add("p", folder)
    reloaded = ProjectRegistry(path=path).get("p")

    assert reloaded.folder == folder.resolve()


def test_registry_creates_parent_directories_if_missing(tmp_path: Path) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    path = tmp_path / "nested" / "deep" / "registry.json"
    reg = ProjectRegistry(path=path)

    reg.add("p", folder)

    assert path.exists()


def test_registry_default_path_uses_env_var_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    target = tmp_path / "reg.json"
    monkeypatch.setenv("DOCLEX_REGISTRY_PATH", str(target))

    ProjectRegistry().add("p", folder)

    assert target.exists()
