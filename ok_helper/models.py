"""Модель дерева файлов и режимы фильтрации/сортировки."""

from enum import Enum
from pathlib import Path
from typing import List, Tuple

from .analyzer import analyze_file


class FilterMode(Enum):
    ALL = 'все'
    ERRORS = 'ошибки'


class SortMode(Enum):
    NAME = 'имя'
    MODIFIED = 'дата'
    ERRORS = 'ошибки-сверху'


class FileTree:
    def __init__(self):
        self.root = Path.cwd()
        self.expanded: set = set()
        self.entries: List[Tuple[Path, int]] = []
        self.selected = 0
        self.filter_mode = FilterMode.ALL
        self.sort_mode = SortMode.NAME
        self._cache: dict = {}

    def info(self, path: Path) -> dict:
        try:
            mt = path.stat().st_mtime
        except OSError:
            return {'has_error': False, 'new_name': None,
                    'confidence': 'none', 'reason': ''}
        key = (str(path), mt)
        cached = self._cache.get(key)
        if cached is None:
            cached = analyze_file(path)
            self._cache[key] = cached
        return cached

    def is_error(self, path: Path) -> bool:
        return self.info(path)['has_error']

    def set_root(self, root: Path):
        self.root = root
        self.expanded = {root}
        self.selected = 0
        self.refresh()

    def refresh(self):
        sel_path = None
        if 0 <= self.selected < len(self.entries):
            sel_path = self.entries[self.selected][0]
        self.entries = []
        self._cache.clear()
        try:
            if self.filter_mode == FilterMode.ERRORS:
                self._walk_errors(self.root)
            else:
                self._walk(self.root, 0)
        except OSError:
            pass
        if sel_path is not None:
            for i, (p, _) in enumerate(self.entries):
                if p == sel_path:
                    self.selected = i
                    return
        if self.selected >= len(self.entries):
            self.selected = max(0, len(self.entries) - 1)

    def _walk(self, path: Path, depth: int):
        try:
            children = sorted(path.iterdir(), key=self._sort_key)
        except (PermissionError, OSError):
            return
        for c in children:
            self.entries.append((c, depth))
            if c.is_dir() and c in self.expanded:
                self._walk(c, depth + 1)

    def _walk_errors(self, path: Path):
        try:
            for c in sorted(path.iterdir(), key=self._sort_key):
                if c.is_dir():
                    self._walk_errors(c)
                elif c.is_file() and self.is_error(c):
                    self.entries.append((c, 0))
        except (PermissionError, OSError):
            pass

    def _sort_key(self, path: Path):
        is_dir = path.is_dir()
        if self.sort_mode == SortMode.NAME:
            return (not is_dir, path.name.lower())
        if self.sort_mode == SortMode.MODIFIED:
            try:
                mt = path.stat().st_mtime
            except OSError:
                mt = 0
            return (not is_dir, -mt)
        has_err = (not is_dir) and self.is_error(path)
        return (not is_dir, 0 if has_err else 1, path.name.lower())

    def move(self, delta: int):
        if self.entries:
            self.selected = max(0, min(len(self.entries) - 1,
                                       self.selected + delta))

    def toggle(self):
        if not self.entries:
            return
        path, _ = self.entries[self.selected]
        if path.is_dir():
            self.expanded.symmetric_difference_update({path})
            self.refresh()

    def select_by_path(self, path: Path):
        for i, (p, _) in enumerate(self.entries):
            if p == path:
                self.selected = i
                return
