from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


class RegistryError(Exception):
    pass


class ProjectNotFoundError(RegistryError):
    pass


class ProjectAlreadyExistsError(RegistryError):
    pass


class ProjectFolderNotFoundError(RegistryError):
    pass


class ProjectOverlapError(RegistryError):
    pass


@dataclass(frozen=True, slots=True)
class Project:
    name: str
    folder: Path


class ProjectRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or self._default_path()

    @staticmethod
    def _default_path() -> Path:
        env = os.environ.get("DOCSEARCH_REGISTRY_PATH")
        if env:
            return Path(env).expanduser().resolve()
        return Path.home() / ".docsearch" / "projects.json"

    def _load(self) -> dict[str, Project]:
        if not self._path.exists():
            return {}
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return {
            name: Project(name=name, folder=Path(v["folder"]))
            for name, v in data.get("projects", {}).items()
        }

    def _save(self, projects: dict[str, Project]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "projects": {p.name: {"folder": str(p.folder)} for p in projects.values()},
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, self._path)

    def add(self, name: str, folder: Path) -> Project:
        folder = folder.expanduser().resolve()
        if not folder.is_dir():
            raise ProjectFolderNotFoundError(f"Folder does not exist: {folder}")

        projects = self._load()
        if name in projects:
            raise ProjectAlreadyExistsError(
                f"Project '{name}' already exists (folder: {projects[name].folder})."
            )

        for existing in projects.values():
            if folder.is_relative_to(existing.folder) or existing.folder.is_relative_to(folder):
                raise ProjectOverlapError(
                    f"Folder {folder} overlaps with project '{existing.name}' "
                    f"({existing.folder}). Overlapping project folders are not allowed."
                )

        project = Project(name=name, folder=folder)
        projects[name] = project
        self._save(projects)
        return project

    def get(self, name: str) -> Project:
        projects = self._load()
        if name not in projects:
            raise ProjectNotFoundError(f"No project named '{name}'.")
        return projects[name]

    def list(self) -> list[Project]:
        return sorted(self._load().values(), key=lambda p: p.name)

    def remove(self, name: str) -> Project:
        projects = self._load()
        if name not in projects:
            raise ProjectNotFoundError(f"No project named '{name}'.")
        project = projects.pop(name)
        self._save(projects)
        return project
