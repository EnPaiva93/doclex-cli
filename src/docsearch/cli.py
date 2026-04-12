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


def _get_pipeline(folder: Path, *, create: bool = False, ocr: bool = False) -> Pipeline:
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
    return Pipeline(config, ocr=ocr)


# ------------------------------------------------------------------
# index
# ------------------------------------------------------------------

@app.command()
def index(
    folder: Path = typer.Option(
        ..., "--folder", "-f", envvar="DOCSEARCH_FOLDER",
        help="Root folder that owns the index.",
    ),
    files: list[Path] | None = typer.Option(
        None, "--files",
        help="One or more specific files to (re)index. Must be inside --folder.",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Force re-extraction of every file, ignoring cached state.",
    ),
    ocr: bool = typer.Option(
        False, "--ocr",
        help="Enable OCR for scanned PDFs using RT-DETR v2 (slower, requires kreuzberg[ocr]).",
    ),
) -> None:
    """Index a folder or re-index specific files.

    \b
    Examples:
      docsearch index --folder ./docs                              # incremental scan
      docsearch index --folder ./docs --force                      # reindex everything
      docsearch index --folder ./docs --files report.pdf           # reindex one file
      docsearch index --folder ./docs --files a.pdf b.docx --ocr  # reindex with OCR
    """
    if files and force:
        console.print("[red]Error:[/red] --files and --force are mutually exclusive.")
        raise typer.Exit(1)

    if files:
        folder_resolved = folder.resolve()
        for f in files:
            if not f.exists():
                console.print(f"[red]Error:[/red] File not found: {f}")
                raise typer.Exit(1)
            if not f.resolve().is_relative_to(folder_resolved):
                console.print(f"[red]Error:[/red] {f} is not inside {folder}")
                raise typer.Exit(1)

    pipeline = _get_pipeline(folder, create=True, ocr=ocr)

    async def run() -> None:
        await pipeline.startup()

        # ── Specific files reindex ───────────────────────────────────
        if files:
            with Progress(
                SpinnerColumn(), BarColumn(), MofNCompleteColumn(),
                TimeElapsedColumn(), TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("", total=len(files))
                for f in files:
                    progress.update(task, advance=1, description=f"[cyan]reindexing[/cyan] {f.name}")
                    await pipeline.reindex_file(f)
            console.print(f"[green]✓[/green] Reindexed {len(files)} file(s).")
            await pipeline.shutdown()
            return

        # ── Force full reindex ───────────────────────────────────────
        if force:
            all_files = await pipeline.list_files()
            total = len(all_files)
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
    folder: Path = typer.Option(
        ..., "--folder", "-f", envvar="DOCSEARCH_FOLDER",
        help="Root folder of the index to search.",
    ),
    query: str = typer.Option(..., "--query", "-q", help="Search query (natural language or keywords)."),
    top_k: int = typer.Option(10, "--top", "-k", help="Maximum number of results to return."),
    full: bool = typer.Option(
        False, "--full", "-F",
        help="Show the full segment text instead of a short snippet.",
    ),
) -> None:
    """Search indexed documents and show results with citations.

    \b
    Examples:
      docsearch search --folder ./docs --query "GT/DPM"
      docsearch search --folder ./docs --query "presupuesto 2024" --top 5 --full
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
    folder: Path = typer.Option(
        ..., "--folder", "-f", envvar="DOCSEARCH_FOLDER",
        help="Root folder of the index.",
    ),
    files: list[Path] | None = typer.Option(
        None, "--files",
        help="Inspect one or more specific files.",
    ),
    list_all: bool = typer.Option(
        False, "--list",
        help="List all indexed files with their status.",
    ),
    filter_status: str | None = typer.Option(
        None, "--filter",
        help="Filter file list by status: indexed | error | pending.",
    ),
) -> None:
    """Show corpus status, optionally listing files or inspecting specific files.

    \b
    Examples:
      docsearch status --folder ./docs                              # corpus summary
      docsearch status --folder ./docs --list                       # list all files
      docsearch status --folder ./docs --list --filter error        # filtered list
      docsearch status --folder ./docs --files report.pdf r3.pdf   # inspect specific files
    """
    pipeline = _get_pipeline(folder)

    async def run() -> None:
        await pipeline.startup()

        # ── Specific-file inspect ────────────────────────────────────
        if files:
            for f in files:
                info = await pipeline.get_file_status(f)

                rec = info["record"]
                console.print()

                t = Table(show_header=False, box=None, padding=(0, 2))
                t.add_column(style="bold dim")
                t.add_column()
                t.add_row("File", str(f))
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

            await pipeline.shutdown()
            return

        # ── File list ────────────────────────────────────────────────
        if list_all:
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
            t.add_row("Disk state", "[yellow]not indexed — run docsearch index --folder <folder>[/yellow]")
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
