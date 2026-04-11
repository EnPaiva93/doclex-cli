from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from docsearch.config import Config
from docsearch.pipeline import Pipeline

app = typer.Typer(
    name="docsearch",
    add_completion=False,
    help="Local document search — BM25-based, no embeddings, no cloud.",
)
console = Console(width=220)


def _get_pipeline(folder: Path, *, create: bool = False) -> Pipeline:
    import os
    os.environ["DOCSEARCH_FOLDER"] = str(folder)
    config = Config()
    if create:
        config.ensure_dirs()
    elif not config.cache_dir.exists():
        console.print(
            f"[yellow]No index found for[/yellow] [bold]{folder}[/bold]. "
            "Run [bold]docsearch index <folder>[/bold] first."
        )
        raise typer.Exit(0)
    return Pipeline(config)


# ------------------------------------------------------------------
# index
# ------------------------------------------------------------------

@app.command()
def index(
    target: Path = typer.Argument(
        ...,
        help="Folder to scan, or a single file to (re)index.",
    ),
    folder: Path | None = typer.Option(
        None, "--folder", "-f", envvar="DOCSEARCH_FOLDER",
        help="Root folder that owns the index (required when TARGET is a file).",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Force re-extraction of every file, ignoring cached state.",
    ),
) -> None:
    """Index a folder or re-index a specific file.

    \b
    Examples:
      docsearch index ./docs                      # incremental scan
      docsearch index ./docs --force              # reindex everything
      docsearch index report.pdf --folder ./docs  # reindex one file
    """
    is_file = target.is_file()

    if is_file and folder is None:
        console.print("[red]Error:[/red] --folder is required when TARGET is a file.")
        raise typer.Exit(1)

    root = folder if is_file else target
    pipeline = _get_pipeline(root, create=True)

    async def run() -> None:
        await pipeline.startup()

        # ── Single-file reindex ──────────────────────────────────────
        if is_file:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True) as spin:
                spin.add_task(f"Reindexing [bold]{target.name}[/bold]…")
                await pipeline.reindex_file(target)
            console.print(f"[green]✓[/green] Reindexed [bold]{target.name}[/bold]")
            await pipeline.shutdown()
            return

        # ── Force full reindex ───────────────────────────────────────
        if force:
            files = await pipeline.list_files()
            total = len(files)
            if total == 0:
                console.print("[yellow]No files in index to reindex.[/yellow]")
                await pipeline.shutdown()
                return

            console.print(f"[bold]Force reindexing[/bold] {total} files…")
            with Progress(
                SpinnerColumn(), BarColumn(), MofNCompleteColumn(),
                TimeElapsedColumn(), TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("", total=total)

                def on_progress_force(path: Path, action: str) -> None:
                    progress.update(task, advance=1, description=f"[cyan]{action}[/cyan] {path.name}")

                await pipeline.reindex_all(on_progress=on_progress_force)
            console.print("[green]✓[/green] Done.")
            await pipeline.shutdown()
            return

        # ── Incremental reconciliation ───────────────────────────────
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
                SpinnerColumn(), BarColumn(), MofNCompleteColumn(),
                TimeElapsedColumn(), TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("", total=total)

                def on_progress(path: Path, action: str) -> None:
                    progress.update(task, advance=1, description=f"[cyan]{action}[/cyan] {path.name}")

                await pipeline.apply_changes(changes, on_progress=on_progress)

            console.print("[green]✓[/green] Done.")

        await pipeline.shutdown()

    asyncio.run(run())


# ------------------------------------------------------------------
# search
# ------------------------------------------------------------------

@app.command()
def search(
    query: str = typer.Argument(..., help="Search query (natural language or keywords)."),
    folder: Path = typer.Option(
        ..., "--folder", "-f", envvar="DOCSEARCH_FOLDER",
        help="Root folder of the index to search.",
    ),
    top_k: int = typer.Option(10, "--top", "-k", help="Maximum number of results to return."),
    full: bool = typer.Option(
        False, "--full", "-F",
        help="Show the full segment text instead of a short snippet.",
    ),
) -> None:
    """Search indexed documents and show results with citations.

    \b
    Examples:
      docsearch search "GT/DPM" --folder ./docs
      docsearch search "presupuesto 2024" --folder ./docs --top 5 --full
    """
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


# ------------------------------------------------------------------
# status
# ------------------------------------------------------------------

@app.command()
def status(
    target: Path | None = typer.Argument(
        None,
        help="Optional: path to a specific file to inspect.",
    ),
    folder: Path = typer.Option(
        ..., "--folder", "-f", envvar="DOCSEARCH_FOLDER",
        help="Root folder of the index.",
    ),
    files: bool = typer.Option(
        False, "--files",
        help="List all indexed files with their status.",
    ),
    filter_status: str | None = typer.Option(
        None, "--filter",
        help="Filter file list by status: indexed | error | pending.",
    ),
) -> None:
    """Show corpus status, optionally listing files or inspecting a specific file.

    \b
    Examples:
      docsearch status --folder ./docs               # corpus summary
      docsearch status --folder ./docs --files       # list all files
      docsearch status --folder ./docs --files --filter error
      docsearch status report.pdf --folder ./docs    # inspect one file
    """
    pipeline = _get_pipeline(folder)

    async def run() -> None:
        await pipeline.startup()

        # ── Single-file inspect ──────────────────────────────────────
        if target is not None:
            info = await pipeline.get_file_status(target)
            await pipeline.shutdown()

            rec = info["record"]
            console.print()
            _row = lambda k, v: (k, str(v))

            t = Table(show_header=False, box=None, padding=(0, 2))
            t.add_column(style="bold dim")
            t.add_column()
            t.add_row("File", str(target))
            t.add_row("On disk", "[green]yes[/green]" if info["on_disk"] else "[red]no[/red]")
            t.add_row("In index", "[green]yes[/green]" if info["in_index"] else "[yellow]no[/yellow]")

            if rec:
                modified_label = "[yellow]yes — run index to update[/yellow]" if info["is_modified"] else "[green]no[/green]"
                t.add_row("Modified on disk", modified_label)
                t.add_row("Status", rec.status)
                t.add_row("MIME type", rec.mime_type)
                t.add_row("Segments", str(len(info["segments"])))
                if rec.error_msg:
                    t.add_row("Error", f"[red]{rec.error_msg}[/red]")

            console.print(t)
            return

        # ── File list ────────────────────────────────────────────────
        if files:
            file_list = await pipeline.list_files(filter_status)
            await pipeline.shutdown()

            if not file_list:
                console.print("[yellow]No files found.[/yellow]")
                return

            table = Table(show_header=True, header_style="bold")
            table.add_column("Status", width=10)
            table.add_column("File")
            table.add_column("MIME type", style="dim")

            style_map = {"indexed": "green", "error": "red", "pending": "yellow"}
            icon_map = {"indexed": "✓", "error": "✗", "pending": "…"}

            for f in file_list:
                color = style_map.get(f.status, "white")
                icon = icon_map.get(f.status, "?")
                table.add_row(
                    f"[{color}]{icon} {f.status}[/{color}]",
                    f.path,
                    f.mime_type,
                )
            console.print(table)
            return

        # ── Corpus summary ───────────────────────────────────────────
        info = await pipeline.corpus_status()
        await pipeline.shutdown()

        t = Table(show_header=False, box=None, padding=(0, 2))
        t.add_column(style="bold dim")
        t.add_column()

        t.add_row("Folder", str(info["folder"]))
        t.add_row(
            "Indexed",
            f"[green]{info['files_indexed']} files[/green]"
            + (f"  [red]{info['files_error']} errors[/red]" if info["files_error"] else "")
            + (f"  [yellow]{info['files_pending']} pending[/yellow]" if info["files_pending"] else ""),
        )
        t.add_row("Segments", str(info["segments_total"]))

        if not info["has_index"]:
            t.add_row("Disk state", "[yellow]not indexed — run docsearch index <folder>[/yellow]")
        else:
            pending_total = info["pending_new"] + info["pending_modified"] + info["pending_deleted"]
            if pending_total:
                t.add_row(
                    "Needs reindex",
                    f"[yellow]{info['pending_new']} new  "
                    f"{info['pending_modified']} modified  "
                    f"{info['pending_deleted']} deleted[/yellow]"
                    "  → run [bold]docsearch index[/bold]",
                )
            else:
                t.add_row("Disk state", "[green]up to date[/green]")

        console.print(t)

    asyncio.run(run())


if __name__ == "__main__":
    app()
