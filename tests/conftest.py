from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from doclex.config import Config
from doclex.pipeline import Pipeline
from doclex.registry import ProjectRegistry


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCLEX_REGISTRY_PATH", str(tmp_path / "registry.json"))


@pytest.fixture()
def docs_dir(tmp_path: Path) -> Path:
    """A temporary folder with sample documents."""
    (tmp_path / "intro.md").write_text(
        textwrap.dedent("""\
            # Introducción

            Este documento explica el sistema de búsqueda local.

            ## Arquitectura

            Usa BM25 para indexación léxica sin embeddings ni servicios externos.

            ## Instalación

            Instalar con uv sync.
        """),
        encoding="utf-8",
    )
    (tmp_path / "notas.txt").write_text(
        textwrap.dedent("""\
            Reunión del equipo - 2024-01-15

            Se decidió usar Kreuzberg para extracción de texto de PDFs y DOCX.
            El índice BM25X se actualiza de forma incremental.

            Pendientes:
            - Configurar Watchdog
            - Probar con archivos XLSX reales
        """),
        encoding="utf-8",
    )
    (tmp_path / "datos.csv").write_text(
        "nombre,ciudad,score\nAlice,Madrid,0.92\nBob,Barcelona,0.87\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def config(docs_dir: Path, tmp_path: Path) -> Config:
    cfg = Config(docs_dir, cache_dir=tmp_path / ".cache")
    cfg.ensure_dirs()
    return cfg


@pytest.fixture()
async def pipeline(config: Config) -> Pipeline:
    p = Pipeline(config)
    await p.startup()
    yield p
    await p.shutdown()


@pytest.fixture()
def project_name(docs_dir: Path) -> str:
    ProjectRegistry().add("proj", docs_dir)
    return "proj"
