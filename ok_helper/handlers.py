"""Watchdog-обработчик для одной директории."""

from pathlib import Path
from typing import Callable, Optional

from watchdog.events import FileSystemEventHandler


class DirHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[Optional[Path]], None]):
        self.callback = callback

    def on_created(self, e):
        if not e.is_directory:
            self.callback(Path(e.src_path))

    def on_moved(self, e):
        if not e.is_directory:
            self.callback(Path(e.dest_path))

    def on_deleted(self, e):
        if not e.is_directory:
            self.callback(None)
