from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from doclex.config import Config
from doclex.pipeline import Pipeline
from doclex.registry import (
    Project,
    ProjectAlreadyExistsError,
    ProjectFolderNotFoundError,
    ProjectNotFoundError,
    ProjectOverlapError,
    ProjectRegistry,
)

app = typer.Typer(
    name="doclex",
    add_completion=False,
    help="Local document search — BM25-based, no embeddings, no cloud.",
)
console = Console(width=220)


def _resolve_project(name: str) -> Project:
    try:
        return ProjectRegistry().get(name)
    except ProjectNotFoundError as exc:
        console.print(
            f"[red]Error:[/red] {exc}\n\n"
            "Run [bold]doclex list[/bold] to see registered projects."
        )
        raise typer.Exit(1)


def _build_pipeline(project: Project, *, create: bool = False) -> Pipeline:
    os.environ["DOCLEX_FOLDER"] = str(project.folder)
    config = Config()
    if create:
        config.ensure_dirs()
    elif not config.cache_dir.exists():
        console.print(
            f"[yellow]No index found for project[/yellow] [bold]{project.name}[/bold] "
            f"({project.folder}). Run [bold]doclex index --project {project.name}[/bold] first."
        )
        raise typer.Exit(0)
    return Pipeline(config)


# ------------------------------------------------------------------
# add / remove / projects
# ------------------------------------------------------------------

@app.command()
def add(
    name: str = typer.Argument(..., help="Unique name for the project."),
    folder: Path = typer.Argument(..., help="Folder to register."),
) -> None:
    """Register a folder under a project name.

    \b
    Examples:
      doclex add docs ./docs
    """
    try:
        project = ProjectRegistry().add(name, folder)
    except (ProjectAlreadyExistsError, ProjectFolderNotFoundError, ProjectOverlapError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Registered project '{project.name}' → {project.folder}")


@app.command("list")
def list_projects() -> None:
    """List registered projects."""
    all_projects = ProjectRegistry().list()
    if not all_projects:
        console.print(
            "[yellow]No projects registered.[/yellow] "
            "Use [bold]doclex add <name> <folder>[/bold]."
        )
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Name")
    table.add_column("Folder")
    for p in all_projects:
        table.add_row(p.name, str(p.folder))
    console.print(table)


@app.command()
def remove(
    name: str = typer.Argument(..., help="Project name to remove."),
) -> None:
    """Remove a project and purge its cache/index data."""
    try:
        project = ProjectRegistry().remove(name)
    except ProjectNotFoundError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    cache_dir = project.folder / ".doclex"
    shutil.rmtree(cache_dir, ignore_errors=True)
    console.print(f"[green]✓[/green] Removed project '{name}' and its cache ({cache_dir}).")


# ------------------------------------------------------------------
# index
# ------------------------------------------------------------------

@app.command()
def index(
    project: str = typer.Option(
        ..., "--project", "-p",
        help="Registered project name.",
    ),
    files: list[Path] | None = typer.Option(
        None, "--file",
        help="One or more specific files to (re)index. Must be inside the project's folder.",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Force re-extraction of every file, ignoring cached state.",
    ),
) -> None:
    """Index a project or re-index specific files.

    \b
    Examples:
      doclex index --project docs                        # incremental scan
      doclex index --project docs --force                # reindex everything
      doclex index --project docs --file report.pdf      # reindex one file
      doclex index --project docs --file a.pdf --file b.docx
    """
    if files and force:
        console.print("[red]Error:[/red] --file and --force are mutually exclusive.")
        raise typer.Exit(1)

    proj = _resolve_project(project)

    if files:
        for f in files:
            if not f.exists():
                console.print(f"[red]Error:[/red] File not found: {f}")
                raise typer.Exit(1)
            if not f.resolve().is_relative_to(proj.folder):
                console.print(
                    f"[red]Error:[/red] {f} is not inside project '{proj.name}' ({proj.folder})"
                )
                raise typer.Exit(1)

    pipeline = _build_pipeline(proj, create=True)

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

    # ONNX Runtime (layout detection) crashes during Python interpreter shutdown
    # when the GC tries to free native session objects. os._exit bypasses GC
    # teardown; all work is already saved to disk.
    os._exit(0)


# ------------------------------------------------------------------
# search
# ------------------------------------------------------------------

@app.command()
def search(
    query: str = typer.Argument(..., help="Search query (natural language or keywords)."),
    project: str = typer.Option(
        ..., "--project", "-p",
        help="Registered project name.",
    ),
    top_k: int = typer.Option(10, "--top", "-k", help="Maximum number of documents to return."),
    passages: int = typer.Option(
        2, "--passages", "-P",
        help="Maximum matching passages to show per document.",
    ),
    full: bool = typer.Option(
        False, "--full", "-F",
        help="Show the full segment text instead of a short snippet.",
    ),
    as_json: bool = typer.Option(
        False, "--json",
        help="Emit results as JSON instead of formatted text.",
    ),
) -> None:
    """Search indexed documents and show results with citations.

    Results are documents, not fragments: a file matching in many places is
    listed once, with its best passages beneath it.

    \b
    Examples:
      doclex search "GT/DPM" --project docs
      doclex search "presupuesto 2024" --project docs --top 5 --passages 3
      doclex search "viaticos" --project docs --json
    """
    proj = _resolve_project(project)
    pipeline = _build_pipeline(proj)

    async def run() -> None:
        if as_json:
            await pipeline.startup()
            results = await pipeline.search(query, top_k, passages_per_document=passages)
            await pipeline.shutdown()
            print(json.dumps(_results_to_json(query, results, full), ensure_ascii=False, indent=2))
            return

        with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True) as spin:
            spin.add_task("Searching\u2026")
            await pipeline.startup()
            results = await pipeline.search(query, top_k, passages_per_document=passages)
            await pipeline.shutdown()

        if not results:
            console.print("[yellow]No results found.[/yellow]")
            return

        console.print()
        for i, doc in enumerate(results, 1):
            _print_document(i, doc, full, proj.folder)

    asyncio.run(run())


def _print_document(rank: int, doc, full: bool, root: Path | None = None) -> None:
    """Render one document result: title, path, then its matching passages."""
    parent = _relative_parent(doc.file_path, root)
    console.print(
        f"[bold cyan][{rank}][/bold cyan] [bold]{doc.filename}[/bold]  "
        f"[yellow]{doc.score:.3f}[/yellow]"
    )
    if parent:
        console.print(f"    [dim]{parent}[/dim]")

    for p in doc.passages:
        location = _clean_label(p.location_label)
        text = p.content if full else _clean_text(_highlight(p.snippet))
        console.print(f"    [dim]{location}[/dim]")
        # Heading-only segments repeat their label as their whole body; printing
        # both just doubles the line.
        if _strip_markup(text).strip() != location:
            console.print(f"    {text}")
    console.print()


def _highlight(snippet) -> str:
    """Render snippet highlights as Rich bold markup, back to front.

    Walking in reverse keeps the remaining offsets valid as markup is spliced in.
    """
    text = snippet.text
    for h in sorted(snippet.highlights, key=lambda h: h.start, reverse=True):
        text = f"{text[:h.start]}[bold]{text[h.start:h.end]}[/bold]{text[h.end:]}"
    return text


def _relative_parent(file_path: str, root: Path | None) -> str:
    """Show the folder relative to the project root — absolute paths bury the result."""
    parent = Path(file_path).parent
    if root:
        try:
            rel = parent.relative_to(root)
        except ValueError:
            return str(parent)
        return str(rel) if str(rel) != "." else ""
    return str(parent)


def _strip_markup(text: str) -> str:
    """Drop Rich markup so rendered text can be compared against plain strings."""
    return re.sub(r"\[/?bold\]", "", text)


def _clean_label(label: str) -> str:
    """Turn an internal location label into a citation a reader can use.

    Drops markdown carried over from extraction, and the trailing "> N" that the
    size splitter appends: that number is the index of an internal chunk, not a
    page or a section, so it means nothing to whoever reads the result.
    """
    label = re.sub(r"\s*\u203a\s*\d+\s*$", "", label)
    label = label.replace("**", "").replace("#", "")
    return " ".join(label.split())


def _clean_text(text: str) -> str:
    """Flatten a snippet for one-line display, without disturbing offsets."""
    text = re.sub(r"(?:^|(?<=\s))#{1,6}\s*", "", text.replace("**", ""))
    return " ".join(text.split())


def _results_to_json(query: str, results: list, full: bool) -> dict:
    return {
        "query": query,
        "total": len(results),
        "results": [
            {
                "file_id": doc.file_id,
                "filename": doc.filename,
                "path": doc.file_path,
                "mime_type": doc.mime_type,
                "score": round(doc.score, 4),
                "passages": [
                    {
                        "segment_id": p.segment_id,
                        "score": round(p.score, 4),
                        "location_type": p.location_type,
                        "location_label": _clean_label(p.location_label),
                        "location_index": p.location_index,
                        "snippet": p.snippet.text,
                        "highlights": [
                            {"start": h.start, "end": h.end} for h in p.snippet.highlights
                        ],
                        **({"content": p.content} if full else {}),
                    }
                    for p in doc.passages
                ],
            }
            for doc in results
        ],
    }


# ------------------------------------------------------------------
# status
# ------------------------------------------------------------------

@app.command()
def status(
    project: str = typer.Option(
        ..., "--project", "-p",
        help="Registered project name.",
    ),
    files: list[Path] | None = typer.Option(
        None, "--file",
        help="Inspect one or more specific files.",
    ),
    all_files: bool = typer.Option(
        False, "--all",
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
      doclex status --project docs                                   # corpus summary
      doclex status --project docs --all                             # list all files
      doclex status --project docs --all --filter error              # filtered list
      doclex status --project docs --file report.pdf --file r3.pdf   # inspect specific files
    """
    proj = _resolve_project(project)
    pipeline = _build_pipeline(proj)

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
        if all_files:
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
        t.add_row("BM25 index", str(info["index_size"]) + " docs")

        if not info["has_index"]:
            t.add_row("Disk state", "[yellow]not indexed — run doclex index --project <name>[/yellow]")
        else:
            pending_total = info["pending_new"] + info["pending_modified"] + info["pending_deleted"]
            if pending_total:
                t.add_row(
                    "Needs reindex",
                    f"[yellow]{info['pending_new']} new  "
                    f"{info['pending_modified']} modified  "
                    f"{info['pending_deleted']} deleted[/yellow]"
                    "  → run [bold]doclex index[/bold]",
                )
            else:
                t.add_row("Disk state", "[green]up to date[/green]")

        console.print(t)

    asyncio.run(run())


if __name__ == "__main__":
    app()
