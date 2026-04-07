from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from docsearch.config import Config
from docsearch.pipeline import Pipeline

app = typer.Typer(name="docsearch", add_completion=False)


def _get_pipeline(folder: Path | None = None) -> Pipeline:
    import os
    if folder:
        os.environ["DOCSEARCH_FOLDER"] = str(folder)
    config = Config()
    config.ensure_dirs()
    return Pipeline(config)


@app.command()
def index(
    folder: Path = typer.Argument(..., help="Folder to scan and index"),
    watch: bool = typer.Option(False, "--watch", "-w", help="Keep watching for changes after indexing"),
) -> None:
    """Scan a folder and index all supported documents."""
    pipeline = _get_pipeline(folder)

    async def run() -> None:
        await pipeline.startup()
        changes = await pipeline.reconcile()
        total = len(changes.new) + len(changes.modified) + len(changes.deleted)

        if total == 0:
            typer.echo("Index is up to date. No changes detected.")
        else:
            typer.echo(
                f"Processing: {len(changes.new)} new, "
                f"{len(changes.modified)} modified, "
                f"{len(changes.deleted)} deleted"
            )
            await pipeline.apply_changes(changes)
            typer.echo("Done.")

        if watch:
            typer.echo(f"Watching {folder} for changes… (Ctrl+C to stop)")
            loop = asyncio.get_event_loop()
            pipeline.start_watcher(loop)
            try:
                await asyncio.Event().wait()
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                pipeline.stop_watcher()

        await pipeline.shutdown()

    asyncio.run(run())


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    folder: Path = typer.Option(..., "--folder", "-f", envvar="DOCSEARCH_FOLDER", help="Indexed folder"),
    top_k: int = typer.Option(10, "--top", "-k", help="Number of results to return"),
) -> None:
    """Search indexed documents and show results with citations."""
    pipeline = _get_pipeline(folder)

    async def run() -> None:
        await pipeline.startup()
        results = await pipeline.search(query, top_k)
        await pipeline.shutdown()

        if not results:
            typer.echo("No results found.")
            return

        for i, r in enumerate(results, 1):
            file_name = Path(r.file_path).name
            typer.echo(f"\n[{i}] {file_name} — {r.location_label}  (score: {r.score:.3f})")
            typer.echo(f'    "{r.snippet}"')

    asyncio.run(run())


@app.command("list")
def list_files(
    folder: Path = typer.Option(..., "--folder", "-f", envvar="DOCSEARCH_FOLDER", help="Indexed folder"),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status: indexed | error | pending"),
) -> None:
    """List all indexed files with their status."""
    pipeline = _get_pipeline(folder)

    async def run() -> None:
        await pipeline.startup()
        files = await pipeline.list_files(status)
        await pipeline.shutdown()

        if not files:
            typer.echo("No files found.")
            return

        for f in files:
            icon = {"indexed": "✓", "error": "✗", "pending": "…"}.get(f.status, "?")
            typer.echo(f"  {icon}  {f.path}  [{f.status}]")

    asyncio.run(run())


@app.command()
def status(
    folder: Path = typer.Option(..., "--folder", "-f", envvar="DOCSEARCH_FOLDER", help="Indexed folder"),
) -> None:
    """Show corpus summary: file count, segment count, index size."""
    pipeline = _get_pipeline(folder)

    async def run() -> None:
        await pipeline.startup()
        info = await pipeline.corpus_status()
        await pipeline.shutdown()

        typer.echo(f"Folder:    {info['folder']}")
        typer.echo(f"Files:     {info['files_total']} total  ({info['files_indexed']} indexed, {info['files_error']} errors)")
        typer.echo(f"Segments:  {info['segments_total']}")
        typer.echo(f"Index:     {info['index_size']} documents")

    asyncio.run(run())


@app.command()
def reindex(
    file: Path = typer.Argument(..., help="File to force-reindex"),
    folder: Path = typer.Option(..., "--folder", "-f", envvar="DOCSEARCH_FOLDER", help="Indexed folder"),
) -> None:
    """Force re-extraction and re-indexing of a specific file."""
    pipeline = _get_pipeline(folder)

    async def run() -> None:
        await pipeline.startup()
        typer.echo(f"Reindexing {file}…")
        await pipeline.reindex_file(file)
        typer.echo("Done.")
        await pipeline.shutdown()

    asyncio.run(run())


if __name__ == "__main__":
    app()
