from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from docsearch.config import SUPPORTED_EXTENSIONS


class _Handler(FileSystemEventHandler):
    def __init__(
        self,
        debounce_secs: float,
        on_change: Callable[[Path, str], None],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()
        self._debounce = debounce_secs
        self._on_change = on_change
        self._loop = loop
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def _is_supported(self, path: str) -> bool:
        return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS

    def _schedule(self, path: str, event_type: str) -> None:
        if not self._is_supported(path):
            return
        if ".docsearch" in Path(path).parts:
            return
        with self._lock:
            if path in self._timers:
                self._timers[path].cancel()
            timer = threading.Timer(
                self._debounce,
                self._fire,
                args=(path, event_type),
            )
            self._timers[path] = timer
            timer.start()

    def _fire(self, path: str, event_type: str) -> None:
        with self._lock:
            self._timers.pop(path, None)
        self._loop.call_soon_threadsafe(self._on_change, Path(path), event_type)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule(event.src_path, "created")

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule(event.src_path, "modified")

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule(event.src_path, "deleted")

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule(event.src_path, "deleted")
            self._schedule(event.dest_path, "created")


class FileWatcher:
    """Watchdog-based folder monitor with debounce."""

    def __init__(
        self,
        folder: Path,
        debounce_secs: float,
        on_change: Callable[[Path, str], None],
    ) -> None:
        self._folder = folder
        self._debounce = debounce_secs
        self._on_change = on_change
        self._observer: Observer | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        handler = _Handler(self._debounce, self._on_change, loop)
        self._observer = Observer()
        self._observer.schedule(handler, str(self._folder), recursive=True)
        self._observer.start()

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
