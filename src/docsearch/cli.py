from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from docsearch.config import Config
from docsearch.pipeline import Pipeline

app = typer.Typer(name="docsearch", add_completion=False)
console = Console(width=220)


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

        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True) as spin:
            spin.add_task("Scanning folder…")
            changes = await pipeline.reconcile()

        total = len(changes.new) + len(changes.modified) + len(changes.deleted)

        if total == 0:
            console.print("[green]✓[/green] Index is up to date. No changes detected.")
        else:
            console.print(
                f"[bold]Processing:[/bold] {len(changes.new)} new, "
                f"{len(changes.modified)} modified, "
                f"{len(changes.deleted)} deleted"
            )
            with Progress(
                SpinnerColumn(),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("", total=total)

                def on_progress(path: Path, action: str) -> None:
                    progress.update(task, advance=1, description=f"[cyan]{action}[/cyan] {path.name}")

                await pipeline.apply_changes(changes, on_progress=on_progress)

            console.print("[green]✓[/green] Done.")

        if watch:
            console.print(f"\n[yellow]Watching[/yellow] {folder} for changes… (Ctrl+C to stop)")
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
    full: bool = typer.Option(False, "--full", "-F", help="Show full segment text instead of snippet"),
) -> None:
    """Search indexed documents and show results with citations."""
    pipeline = _get_pipeline(folder)

    async def run() -> None:
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True) as spin:
            spin.add_task("Searching…")
            await pipeline.startup()
            results = await pipeline.search(query, top_k)
            await pipeline.shutdown()

        if not results:
            console.print("[yellow]No results found.[/yellow]")
            return

        console.print()
        for i, r in enumerate(results, 1):
            file_name = Path(r.file_path).name
            console.print(
                f"[bold cyan][{i}][/bold cyan] [bold]{file_name}[/bold] — "
                f"[dim]{r.location_label}[/dim]  "
                f"[yellow](score: {r.score:.3f})[/yellow]"
            )
            text = r.content if full else r.snippet
            console.print(f'    [italic]"{text}"[/italic]')
            console.print()

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
            console.print("[yellow]No files found.[/yellow]")
            return

        table = Table(show_header=True, header_style="bold")
        table.add_column("Status", width=8)
        table.add_column("File")
        table.add_column("MIME type", style="dim")

        style_map = {"indexed": "green", "error": "red", "pending": "yellow"}
        icon_map = {"indexed": "✓", "error": "✗", "pending": "…"}

        for f in files:
            color = style_map.get(f.status, "white")
            icon = icon_map.get(f.status, "?")
            table.add_row(
                f"[{color}]{icon} {f.status}[/{color}]",
                f.path,
                f.mime_type,
            )

        console.print(table)

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

        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="bold dim")
        table.add_column()

        table.add_row("Folder", str(info["folder"]))
        table.add_row(
            "Files",
            f"{info['files_total']} total  "
            f"([green]{info['files_indexed']} indexed[/green], "
            f"[red]{info['files_error']} errors[/red])",
        )
        table.add_row("Segments", str(info["segments_total"]))
        table.add_row("Index size", f"{info['index_size']} documents")

        console.print(table)

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
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True) as spin:
            spin.add_task(f"Reindexing [bold]{file.name}[/bold]…")
            await pipeline.reindex_file(file)
        console.print(f"[green]✓[/green] Reindexed [bold]{file.name}[/bold]")
        await pipeline.shutdown()

    asyncio.run(run())


if __name__ == "__main__":
    app()