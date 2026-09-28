#!/usr/bin/env python3
"""
Кроссплатформенный TUI-сервис ok-helper-tui (Linux / Windows):
  1. Транслит кириллицы.
  2. Сайдбар: поле пути + дерево файлов.
  3. Умный анализ имён (ГГГГММДД_Позывной и «скачанные» имена).
  4. Кнопки [Правка] / [Правка?], ручная правка F7, FixAll F5, Undo ^Z.
  5. Конфиг в ~/.config/ok-helper-tui/config.toml. Правка из TUI — F10.
  6. Мониторинг папки загрузок: F8 — очередь, F9 — вкл/выкл.
"""

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
import threading
from collections import deque
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from prompt_toolkit.application import Application
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import (
    ConditionalContainer, Float, FloatContainer,
    HSplit, VSplit, Window, Layout,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.styles import Style, DynamicStyle
from prompt_toolkit.widgets import Frame, TextArea
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from datetime import datetime

from config import load_config, save_config, config_path


# ====================== Цветовые темы ======================
# Основная идея: текст — `default` (терминальный цвет переднего плана),
# акценты — ANSI-цвета. Терминал сам раскрашивает их под свою схему,
# поэтому цвета читаемы и на тёмной, и на светлой теме, и на любых
# кастомных (Solarized, Nord, Gruvbox и т.п.).

_PALETTE_DARK = {
    # Рамки и заголовки
    'border':             'ansibrightblack',
    'title':              'default',
    'title.focus':        'bold reverse',
    'frame.border':       'ansibrightblack',
    'frame.title':        'default',

    # Дерево
    'tree.dir':           'bold ansibrightcyan',
    'tree.file':          'default',
    'tree.err':           'bold ansibrightred',
    'tree.sel':           'reverse',

    # Кнопки [Правка]
    'btn':                'bold default bg:ansigreen',
    'btn.med':            'bold default bg:ansicyan',
    'btn.warn':           'bold default bg:ansiyellow',
    'btn.dis':            'ansibrightblack',

    # Второстепенный текст
    'dim':                'ansibrightblack',

    # Статус-бар
    'status.sep':         'ansibrightblack',
    'status.key':         'ansibrightblue',
    'status.val':         'bold default',
    'status.err':         'bold ansibrightred',
    'status.ok':          'ansibrightgreen',
    'status.hint':        'ansibrightblue',
    'status.sugg':        'bold ansibrightyellow',
    'status.dl':          'bold ansibrightmagenta',

    # Модалки
    'modal':              'default',
    'cfg.label':          'ansibrightblue',
    'cfg.path':           'default',
    'cfg.hint':           'ansibrightblack',

    # Журнал
    'log.time':           'ansibrightblack',
    'log.msg':            'default',
    'log.tag.text':       'default',
    'log.tag.info':       'ansibrightblue',
    'log.tag.ok':         'bold ansibrightgreen',
    'log.tag.warn':       'bold ansibrightyellow',
    'log.tag.error':      'bold ansibrightred',
    'log.tag.dir':        'bold ansibrightcyan',
    'log.tag.dl':         'bold ansibrightmagenta',
    'log.tag.cfg':        'ansibrightblue',
    'log.tag.move':       'ansibrightcyan',
    'log.tag.open':       'ansicyan',
    'log.tag.undo':       'bold ansibrightyellow',
    'log.tag.translit':   'default',
}

_PALETTE_LIGHT = {
    'border':             'ansibrightblack',
    'title':              'default',
    'title.focus':        'bold reverse',
    'frame.border':       'ansibrightblack',
    'frame.title':        'default',

    'tree.dir':           'bold ansiblue',
    'tree.file':          'default',
    'tree.err':           'bold ansired',
    'tree.sel':           'reverse',

    'btn':                'bold default bg:ansigreen',
    'btn.med':            'bold default bg:ansicyan',
    'btn.warn':           'bold ansiblack bg:ansiyellow',
    'btn.dis':            'ansibrightblack',

    'dim':                'ansibrightblack',

    'status.sep':         'ansibrightblack',
    'status.key':         'ansiblue',
    'status.val':         'bold default',
    'status.err':         'bold ansired',
    'status.ok':          'ansigreen',
    'status.hint':        'ansiblue',
    'status.sugg':        'bold ansired',
    'status.dl':          'bold ansimagenta',

    'modal':              'default',
    'cfg.label':          'ansiblue',
    'cfg.path':           'default',
    'cfg.hint':           'ansibrightblack',

    'log.time':           'ansibrightblack',
    'log.msg':            'default',
    'log.tag.text':       'default',
    'log.tag.info':       'ansiblue',
    'log.tag.ok':         'bold ansigreen',
    'log.tag.warn':       'bold ansired',
    'log.tag.error':      'bold ansired',
    'log.tag.dir':        'bold ansiblue',
    'log.tag.dl':         'bold ansimagenta',
    'log.tag.cfg':        'ansiblue',
    'log.tag.move':       'ansicyan',
    'log.tag.open':       'ansicyan',
    'log.tag.undo':       'bold ansired',
    'log.tag.translit':   'default',
}


def _detect_terminal_theme() -> str:
    """Возвращает 'dark' или 'light'.

    Основной источник — переменная COLORFGBG (её выставляют xterm, rxvt,
    konsole, gnome-terminal, alacritty, kitty, foot). Формат: 'fg;bg',
    где fg и bg — ANSI-индексы (0..15). Также встречается 'fg;bg;attr'.
    Если переменная отсутствует или не разбирается — возвращаем 'dark'
    (большинство терминалов тёмные).
    """
    val = os.environ.get('COLORFGBG', '')
    if not val:
        return 'dark'
    parts = [p for p in re.split(r'[;:]', val) if p.strip().isdigit()]
    if not parts:
        return 'dark'
    try:
        bg = int(parts[-1])
    except ValueError:
        return 'dark'
    # ANSI: 0..6 — насыщенные тёмные, 7 — светло-серый,
    # 8 — ярко-чёрный (тёмный), 9..15 — яркие светлые.
    if bg in (7, 9, 10, 11, 12, 13, 14, 15):
        return 'light'
    return 'dark'


def build_style(theme: str) -> Style:
    """Собирает Style по имени темы: 'auto' | 'dark' | 'light'."""
    if theme not in ('auto', 'dark', 'light'):
        theme = 'auto'
    if theme == 'auto':
        theme = _detect_terminal_theme()
    palette = _PALETTE_LIGHT if theme == 'light' else _PALETTE_DARK
    return Style.from_dict(palette)

# ====================== Транслитерация ======================
_TRANSLIT_MAP = {
    'а': 'a',  'б': 'b',  'в': 'v',  'г': 'g',  'д': 'd',  'е': 'e',
    'ё': 'yo', 'ж': 'zh', 'з': 'z',  'и': 'i',  'й': 'y',  'к': 'k',
    'л': 'l',  'м': 'm',  'н': 'n',  'о': 'o',  'п': 'p',  'р': 'r',
    'с': 's',  'т': 't',  'у': 'u',  'ф': 'f',  'х': 'kh', 'ц': 'ts',
    'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y',  'ь': '',
    'э': 'e',  'ю': 'yu', 'я': 'ya',
    'А': 'A',  'Б': 'B',  'В': 'V',  'Г': 'G',  'Д': 'D',  'Е': 'E',
    'Ё': 'Yo', 'Ж': 'Zh', 'З': 'Z',  'И': 'I',  'Й': 'Y',  'К': 'K',
    'Л': 'L',  'М': 'M',  'Н': 'N',  'О': 'O',  'П': 'P',  'Р': 'R',
    'С': 'S',  'Т': 'T',  'У': 'U',  'Ф': 'F',  'Х': 'Kh', 'Ц': 'Ts',
    'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch', 'Ъ': '', 'Ы': 'Y',  'Ь': '',
    'Э': 'E',  'Ю': 'Yu', 'Я': 'Ya',
}


def transliterate(text: str) -> str:
    return ''.join(_TRANSLIT_MAP.get(ch, ch) for ch in text)


def human_size(n: int) -> str:
    x = float(n)
    for unit in ('Б', 'КБ', 'МБ', 'ГБ', 'ТБ'):
        if x < 1024 or unit == 'ТБ':
            if unit == 'Б':
                return f'{int(x)} {unit}'
            return f'{x:.1f} {unit}'
        x /= 1024
    return f'{x:.1f} ТБ'

_CONFIG_LABEL_WIDTH = 22


def _cfg_label(name: str) -> str:
    return name.ljust(_CONFIG_LABEL_WIDTH) + '= '

# ====================== Анализ имён ======================
_LATIN_CALLSIGN_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_FILENAME_RE = re.compile(r'^(\d{8})_(.+)$')

_DATE_PATTERNS = [
    (re.compile(r'^(\d{4})[-_.](\d{2})[-_.](\d{2})'), 'ymd'),
    (re.compile(r'^(\d{4})(\d{2})(\d{2})'),          'ymd'),
    (re.compile(r'^(\d{2})[-_.](\d{2})[-_.](\d{4})'), 'dmy'),
    (re.compile(r'^(\d{2})(\d{2})(\d{4})'),          'dmy'),
]

_STOPWORDS_LATIN = {
    'bezymyannyy', 'bezymyannaya', 'bez', 'imeni', 'untitled',
    'unnamed', 'track', 'trek', 'treka', 'gpx', 'record',
    'zapis', 'download', 'zagruzka', 'new', 'novyy', 'novaya',
}


def sanitize_callsign(cs: str) -> str:
    if _LATIN_CALLSIGN_RE.match(cs):
        return cs
    return re.sub(r'[^A-Za-z0-9_-]', '', transliterate(cs))


def _extract_date_and_rest(stem: str) -> Tuple[Optional[str], str]:
    for pat, kind in _DATE_PATTERNS:
        m = pat.match(stem)
        if not m:
            continue
        a, b, c = m.groups()
        try:
            if kind == 'ymd':
                y, mo, d = a, b, c
            else:
                d, mo, y = a, b, c
            if not (1 <= int(mo) <= 12 and 1 <= int(d) <= 31):
                continue
            return f'{y}{mo}{d}', stem[m.end():]
        except (ValueError, IndexError):
            continue
    return None, stem


_TIME_PREFIX_RE = re.compile(
    r'^\s*\d{1,2}[-_:.]?\d{2}(?:[-_:.]?\d{2})?\s*'
)


def _clean_rest(rest: str) -> Tuple[str, bool]:
    rest = rest.strip()
    rest = _TIME_PREFIX_RE.sub('', rest)
    rest = re.sub(r'[\s\-–—_.]+', '_', rest)
    rest = transliterate(rest)
    rest = re.sub(r'[^A-Za-z0-9_-]', '', rest)
    rest = re.sub(r'_+', '_', rest).strip('_-')
    if not rest:
        return '', True
    words = [w for w in re.split(r'[_-]+', rest.lower()) if w]
    is_placeholder = bool(words) and all(w in _STOPWORDS_LATIN for w in words)
    return rest, is_placeholder


def analyze_file(path: Path) -> dict:
    if not path.is_file():
        return {'has_error': False, 'new_name': None,
                'confidence': 'none', 'reason': ''}
    stem = path.stem
    suffix = path.suffix

    m = _FILENAME_RE.match(stem)
    if m:
        date, cs = m.groups()
        if _LATIN_CALLSIGN_RE.match(cs):
            return {'has_error': False, 'new_name': None,
                    'confidence': 'none', 'reason': ''}
        new_cs = sanitize_callsign(cs)
        if new_cs and new_cs != cs:
            return {'has_error': True,
                    'new_name': f'{date}_{new_cs}{suffix}',
                    'confidence': 'high',
                    'reason': 'транслит позывного'}
        return {'has_error': True, 'new_name': None,
                'confidence': 'none', 'reason': 'позывной не исправить'}

    date_str, rest = _extract_date_and_rest(stem)
    if date_str is None:
        return {'has_error': True, 'new_name': None,
                'confidence': 'none', 'reason': 'дата в имени не найдена'}

    cleaned, is_placeholder = _clean_rest(rest)
    if not cleaned:
        return {'has_error': True, 'new_name': None,
                'confidence': 'low',
                'reason': f'дата найдена ({date_str}), позывной пуст'}
    if is_placeholder:
        return {'has_error': True,
                'new_name': f'{date_str}_{cleaned}{suffix}',
                'confidence': 'low',
                'reason': f'похоже на заглушку «{cleaned}»'}
    return {'has_error': True,
            'new_name': f'{date_str}_{cleaned}{suffix}',
            'confidence': 'medium',
            'reason': 'дата + позывной из имени'}

# ---- Разбор тегов и определение уровня сообщения ----
_LOG_TAG_RE = re.compile(r'^(\[[^\]]+\])\s*')

_LOG_LEVEL_BY_TAG = {
    'i':            'info',
    '+':            'ok',
    '!':            'warn',
    'OK':           'ok',
    'ОШБ':          'error', 'ERR':   'error',
    'КАТАЛОГ':      'dir',   'DIR':   'dir',
    'ЗАГР':         'dl',    'DL':    'dl',
    'НАСТР':        'cfg',   'CFG':   'cfg',
    'КОНФИГ':       'cfg',   'CONFIG':'cfg',
    'ПЕРЕНОС':      'move',  'MOVE':  'move',
    'ОТКР':         'open',  'OPEN':  'open',
    'ОТМЕНА':       'undo',  'UNDO':  'undo',
    'ТРАНСЛИТ':     'translit',
}

# ====================== Режимы ======================
class FilterMode(Enum):
    ALL = 'все'
    ERRORS = 'ошибки'


class SortMode(Enum):
    NAME = 'имя'
    MODIFIED = 'дата'
    ERRORS = 'ошибки-сверху'


# ====================== Дерево ======================
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


class TreeControl(FormattedTextControl):
    """FormattedTextControl, который перехватывает прокрутку мыши.

    Базовый FormattedTextControl.mouse_handler делегирует событие
    фрагменту под курсором, поэтому без этого подкласса скролл
    срабатывал бы только когда курсор стоит ровно на строке файла,
    а на пустом месте панели — нет.
    """

    def __init__(self, on_scroll: Callable[[int], None], **kwargs):
        super().__init__(**kwargs)
        self._on_scroll = on_scroll

    def mouse_handler(self, mouse_event: MouseEvent):
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self._on_scroll(-3)
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self._on_scroll(3)
            return None
        return super().mouse_handler(mouse_event)

class LogControl(FormattedTextControl):
    """FormattedTextControl с перехватом колесика мыши для прокрутки."""

    def __init__(self, on_scroll: Callable[[int], None], **kwargs):
        super().__init__(**kwargs)
        self._on_scroll = on_scroll

    def mouse_handler(self, mouse_event: MouseEvent):
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self._on_scroll(-3)
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self._on_scroll(3)
            return None
        return super().mouse_handler(mouse_event)

# ====================== watchdog ======================
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


# ====================== Приложение ======================
class App:
    MAX_LOG = 500
    MAX_UNDO = 20

    HELP_TEXT = (
        '  F1   Справка\n'
        '  F2   Фильтр: Все ↔ Только ошибки\n'
        '  F3   Открыть выделенный файл\n'
        '  F4   Сортировка: Имя → Дата → Ошибки сверху\n'
        '  F5   Исправить все (уверенные случаи)\n'
        '  F6   Пересканировать директорию\n'
        '  F7   Переименовать вручную\n'
        '  F8   Показать очередь файлов из Загрузок\n'
        '  F9   Вкл/выкл мониторинг папки Загрузок (сохраняется)\n'
        '  F10  Открыть редактор конфига\n'
        ' ^Z    Отменить последнее переименование\n'
        ' ^C    Выход (или ^Q)\n'
        '\n'
        ' Конфиг (F10):\n'
        '   root_dir        — открывается при запуске\n'
        '   downloads_dir   — папка, которую мониторим\n'
        '   watch_downloads — true/false\n'
        '   Файл: ' + str(config_path()) + '\n'
        '\n'
        ' Мониторинг загрузок:\n'
        '   При появлении нового файла — модалка:\n'
        '     Y / Enter — перенести в текущую директорию дерева\n'
        '     N         — пропустить\n'
        '     Esc       — отложить (F8 вернёт модалку)\n'
        '\n'
        ' Умный анализ имён:\n'
        '   ГГГГММДД_Позывной              — валидный формат\n'
        '   2026-09-17_11-55_бабушка.gpx   — [Правка]  (уверенно)\n'
        '   2026-09-23-1803 Иванов.gpx     — [Правка]  (средне)\n'
        '   2026-09-23 Безымянный трек.gpx — [Правка?] (откроет редактор)\n'
        ' Журнал:\n'
        '   Прокрутка — колесо мыши, PageUp / PageDown, Home / End\n'
        '   F11 — очистить журнал\n'
        '\n'
    )

    def __init__(self, initial_dir: Path, config: dict):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.lines: List[Tuple[str, str, str]] = []   # (время, уровень, текст)
        self.lock = threading.Lock()
        self.observer: Optional[Observer] = None
        self.downloads_observer: Optional[Observer] = None
        self.watch_dir = initial_dir
        self.undo_stack: deque = deque(maxlen=self.MAX_UNDO)
        self.modal: Optional[str] = None
        self._pending_fix_list: List[Tuple[str, str, Path, str]] = []
        self._edit_target: Optional[Path] = None
        self.config = config
        self.pending_downloads: List[Path] = []
        self.watch_downloads = False

        self.tree = FileTree()
        self.tree.set_root(initial_dir)

        # ---------- Поля ввода ----------
        self.translit_input = TextArea(
            height=1, prompt='> ', multiline=False,
            accept_handler=self.on_translit,
            history=InMemoryHistory(),
        )
        self.path_input = TextArea(
            height=1, prompt='Путь: ', multiline=False,
            text=str(initial_dir),
            accept_handler=self.on_path_change,
            history=InMemoryHistory(),
        )
        self._override_tab(self.translit_input)
        self._override_tab(self.path_input)

        # ---------- Дерево ----------
        tree_kb = KeyBindings()

        @tree_kb.add('up')
        def _(event):
            self.tree.move(-1)
            self._sync_path_to_selection()
            event.app.invalidate()

        @tree_kb.add('down')
        def _(event):
            self.tree.move(1)
            self._sync_path_to_selection()
            event.app.invalidate()

        @tree_kb.add('left')
        def _(event):
            if self.tree.entries:
                p, _ = self.tree.entries[self.tree.selected]
                if p.is_dir() and p in self.tree.expanded:
                    self.tree.expanded.discard(p)
                    self.tree.refresh()
                    self._sync_path_to_selection()
                    event.app.invalidate()

        @tree_kb.add('right')
        def _(event):
            if self.tree.entries:
                p, _ = self.tree.entries[self.tree.selected]
                if p.is_dir() and p not in self.tree.expanded:
                    self.tree.expanded.add(p)
                    self.tree.refresh()
                    self._sync_path_to_selection()
                    event.app.invalidate()

        @tree_kb.add('enter')
        @tree_kb.add(' ')
        def _(event):
            self.handle_tree_enter()
            self._sync_path_to_selection()
            event.app.invalidate()

        self.tree_kb = tree_kb
        self.tree_control = TreeControl(
            on_scroll=self._tree_scroll,
            text=self.render_tree,
            focusable=True,
            key_bindings=tree_kb,
            get_cursor_position=lambda: Point(0, self.tree.selected),
        )
        self.tree_window = Window(self.tree_control)

        # ---------- Лог ----------
        self.log_control = LogControl(
            on_scroll=self._log_scroll,
            text=self._log_text,
            focusable=True,
            key_bindings=self._log_kb(),
        )
        self.log_window = Window(self.log_control, wrap_lines=True)
        # ---------- Панели ----------
        left = HSplit([
            self._titled('Журнал', self.log_window, 'log'),
            self._titled('Транслит — Enter', self.translit_input, 'translit'),
        ])
        right = HSplit([
            self._titled('Директория — Enter', self.path_input, 'path'),
            self._titled('Файлы — F1 справка, [Правка] клик/Enter',
                         self.tree_window, 'tree'),
        ], width=D(min=40, preferred=64, max=110))

        # ---------- Статус-бар ----------
        self.status_window = Window(
            FormattedTextControl(text=self._status_frags),
            height=1,
        )

        # ---------- Модалка: help / confirm_fix_all / move_download ----------
        self.modal_control = FormattedTextControl(
            text=self._modal_text,
            focusable=True,
            key_bindings=self._modal_kb(),
        )
        self.modal_window = Window(self.modal_control)

        self._modal_float = Float(
            content=ConditionalContainer(
                content=Frame(self.modal_window, title=self._modal_title),
                filter=Condition(
                    lambda: self.modal in
                    ('help', 'confirm_fix_all', 'move_download')),
            ),
            top=3, left=6, width=86, height=24,
        )

        # ---------- Модалка: edit_name ----------
        self.edit_input = TextArea(
            height=1, prompt='Новое: ', multiline=False,
            accept_handler=self._apply_edit_modal,
        )
        self._override_tab(self.edit_input)

        self.edit_preview_control = FormattedTextControl(
            text=self._edit_preview_text,
        )
        self.edit_preview_window = Window(self.edit_preview_control, height=2)

        self._edit_float = Float(
            content=ConditionalContainer(
                content=Frame(
                    HSplit([
                        self.edit_preview_window,
                        self.edit_input,
                        Window(FormattedTextControl(text=lambda: FormattedText([
                            ('class:dim',
                             '  Enter — применить,  Esc — отмена')
                        ])), height=1),
                    ]),
                    title=' ▶ Переименование — F7 ',
                ),
                filter=Condition(lambda: self.modal == 'edit_name'),
            ),
            top=8, left=6, width=86, height=7,
        )

        # ---------- Модалка: edit_config (F10) ----------
        self._build_config_modal()

        body = HSplit([VSplit([left, right], padding=1), self.status_window])
        root = FloatContainer(
            content=body,
            floats=[self._modal_float, self._edit_float, self._config_float],
        )

        # ---------- Глобальные биндинги ----------
        kb = KeyBindings()

        @kb.add('c-c')
        @kb.add('c-q')
        def _(event):
            event.app.exit()

        @kb.add('tab')
        @kb.add('c-i')
        def _(event):
            self._handle_tab(reverse=False)
            event.app.invalidate()

        @kb.add('s-tab')
        def _(event):
            self._handle_tab(reverse=True)
            event.app.invalidate()

        @kb.add('f1')
        def _(event):
            self._toggle_modal('help')
            event.app.invalidate()

        @kb.add('f2')
        def _(event):
            self.tree.filter_mode = (
                FilterMode.ERRORS
                if self.tree.filter_mode == FilterMode.ALL
                else FilterMode.ALL
            )
            self.tree.refresh()
            self.log(f'[i] Фильтр: {self.tree.filter_mode.value}')
            event.app.invalidate()

        @kb.add('f3')
        def _(event):
            self.open_selected()
            event.app.invalidate()

        @kb.add('f4')
        def _(event):
            modes = list(SortMode)
            idx = modes.index(self.tree.sort_mode)
            self.tree.sort_mode = modes[(idx + 1) % len(modes)]
            self.tree.refresh()
            self.log(f'[i] Сортировка: {self.tree.sort_mode.value}')
            event.app.invalidate()

        @kb.add('f5')
        def _(event):
            if self.modal == 'confirm_fix_all':
                self._confirm_fix_all()
            else:
                self.on_fix_all()
            event.app.invalidate()

        @kb.add('f6')
        def _(event):
            self.scan_dir(self.watch_dir)
            self.tree.refresh()
            self.log('[i] Пересканировано')
            event.app.invalidate()

        @kb.add('f7')
        def _(event):
            self.open_edit_for_selection()
            event.app.invalidate()

        @kb.add('f8')
        def _(event):
            self.show_pending_downloads()
            event.app.invalidate()

        @kb.add('f9')
        def _(event):
            self.toggle_downloads_watch()
            event.app.invalidate()

        @kb.add('f10')
        def _(event):
            if self.modal == 'edit_config':
                self._cancel_config_modal()
            elif self.modal is None:
                self.open_config_modal()
            event.app.invalidate()

        @kb.add('f11')
        def _(event):
            with self.lock:
                self.lines.clear()
            self.log('[i] Журнал очищен')
            event.app.invalidate()

        @kb.add('c-z')
        def _(event):
            self.undo()
            event.app.invalidate()

        self.kb = kb

        # Тема из конфига; 'auto' развернётся в 'dark'/'light' внутри build_style
        self._theme_setting = self.config.get('theme', 'auto')
        self._current_style = build_style(self._theme_setting)

        self.app = Application(
            layout=Layout(root, focused_element=self.translit_input),
            full_screen=True,
            mouse_support=True,
            key_bindings=kb,
            # DynamicStyle вызывает lambda при каждой отрисовке, поэтому
            # смена self._current_style перерисует интерфейс без перезапуска.
            style=DynamicStyle(lambda: self._current_style),
        )

    # ---------- helpers: tab / focus ----------
    def _modal_focus_chain(self) -> list:
        """Возвращает список Window, между которыми циклится Tab в текущей модалке."""
        if self.modal == 'edit_config':
            return [
                self.config_root_input.window,
                self.config_dl_input.window,
                self.config_watch_window,
            ]
        if self.modal == 'edit_name':
            return [self.edit_input.window]
        if self.modal in ('help', 'confirm_fix_all', 'move_download'):
            return [self.modal_window]
        return []

    def _modal_focus_next(self, reverse: bool = False):
        chain = self._modal_focus_chain()
        if not chain:
            return
        current = self.app.layout.current_window
        try:
            idx = chain.index(current)
        except ValueError:
            idx = 0
        step = -1 if reverse else 1
        self.app.layout.focus(chain[(idx + step) % len(chain)])

    def _handle_tab(self, reverse: bool = False):
        """Tab / S-Tab: если открыта модалка — циклит только внутри неё,
        иначе — обычный переход между панелями основного окна."""
        if self.modal is not None:
            self._modal_focus_next(reverse=reverse)
        else:
            if reverse:
                self.app.layout.focus_previous()
            else:
                self.app.layout.focus_next()

    def _override_tab(self, ta: TextArea, with_arrows: bool = False):
        """Ставит свои Tab/S-Tab (и, опционально, ↑/↓, Esc) поверх TextArea.

        with_arrows=True используется для полей в модалке настроек:
        ↑/↓ переключают фокус между полями.
        Esc работает везде, где открыта модалка — но не в главном окне,
        поэтому фильтр: self.modal is not None.
        """
        custom = KeyBindings()

        @custom.add('tab')
        @custom.add('c-i')
        def _(event):
            self._handle_tab(reverse=False)
            event.app.invalidate()

        @custom.add('s-tab')
        def _(event):
            self._handle_tab(reverse=True)
            event.app.invalidate()

        # Esc закрывает модалку — но только если она открыта,
        # иначе не мешает обычному вводу в поле.
        @custom.add('escape', filter=Condition(lambda: self.modal is not None))
        def _(event):
            if self.modal == 'edit_config':
                self._cancel_config_modal()
            else:
                self._close_modal()
            event.app.invalidate()

        if with_arrows:
            @custom.add('up', filter=Condition(lambda: self.modal is not None))
            def _(event):
                self._modal_focus_next(reverse=True)
                event.app.invalidate()

            @custom.add('down', filter=Condition(lambda: self.modal is not None))
            def _(event):
                self._modal_focus_next(reverse=False)
                event.app.invalidate()

        old = ta.control.key_bindings
        ta.control.key_bindings = (
            merge_key_bindings([custom, old]) if old else custom
        )

    def _focused(self, name: str) -> bool:
        w = self.app.layout.current_window
        if name == 'translit':
            return w is self.translit_input.window
        if name == 'path':
            return w is self.path_input.window
        if name == 'tree':
            return w is self.tree_window
        if name == 'log':
            return w is self.log_window
        return False

    def _titled(self, label: str, body, name: str):
        def title() -> FormattedText:
            focused = self._focused(name)
            prefix = ' ▶ ' if focused else '   '
            style = 'class:title.focus' if focused else 'class:title'
            return FormattedText([(style, prefix + label + ' ')])
        return Frame(body, title=title)

    def _apply_theme(self, theme: str):
        """Меняет цветовую тему и перерисовывает интерфейс."""
        self._theme_setting = theme if theme in ('auto', 'dark', 'light') else 'auto'
        self._current_style = build_style(self._theme_setting)
        self.invalidate()

    # ---------- модалки (общие) ----------
    def _toggle_modal(self, name: str):
        if self.modal == name:
            self._close_modal()
        else:
            self._open_modal(name)

    def _open_modal(self, name: str):
        self.modal = name
        self.app.layout.focus(self.modal_window)

    def _close_modal(self):
        self.modal = None
        self._pending_fix_list = []
        self._edit_target = None
        self.app.layout.focus(self.tree_window)

    def _modal_title(self) -> FormattedText:
        if self.modal == 'help':
            return FormattedText([('class:title.focus',
                                   ' ▶ Справка — F1 или Esc ')])
        if self.modal == 'confirm_fix_all':
            return FormattedText([('class:title.focus',
                                   ' ▶ Подтверждение — Enter/Y, Esc/N ')])
        if self.modal == 'move_download':
            n = len(self.pending_downloads)
            more = f' (+{n - 1})' if n > 1 else ''
            return FormattedText([('class:title.focus',
                                   f' ▶ Файл из Загрузок{more} — Y/N/Esc ')])
        return FormattedText([('', ' ')])

    def _modal_text(self) -> FormattedText:
        if self.modal == 'help':
            return FormattedText([('class:modal', self.HELP_TEXT)])
        if self.modal == 'confirm_fix_all':
            n = len(self._pending_fix_list)
            lines = [f'  Файлов к переименованию (уверенные): {n}', '']
            for old, new, _, _ in self._pending_fix_list[:12]:
                lines.append(f'    {old}  →  {new}')
            if n > 12:
                lines.append(f'    ... и ещё {n - 12}')
            lines.append('')
            lines.append('  Enter / Y — применить    Esc / N — отмена')
            return FormattedText([('class:modal', '\n'.join(lines))])
        if self.modal == 'move_download':
            return self._move_modal_text()
        return FormattedText([('', '')])

    def _move_modal_text(self) -> FormattedText:
        if not self.pending_downloads:
            return FormattedText([('', '')])
        src = self.pending_downloads[0]
        dst_dir = self.tree.root
        try:
            size = human_size(src.stat().st_size)
        except OSError:
            size = '?'
        frags = [
            ('', '  Файл:        '),
            ('class:status.val', f'{src.name}\n'),
            ('', '  Размер:      '),
            ('class:dim', f'{size}\n'),
            ('', '  Источник:    '),
            ('class:dim', f'{src.parent}\n'),
            ('', '  Перенести в: '),
            ('class:status.sugg', f'{dst_dir}\n'),
            ('', '\n'),
            ('class:dim',
             '  Enter / Y — перенести    N — пропустить    Esc — позже\n'),
        ]
        if len(self.pending_downloads) > 1:
            frags.append(
                ('class:dim',
                 f'  В очереди ещё: {len(self.pending_downloads) - 1}\n')
            )
        return FormattedText(frags)

    def _modal_kb(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add('escape')
        def _(event):
            self._close_modal()
            event.app.invalidate()

        @kb.add('n')
        @kb.add('N')
        def _(event):
            if self.modal == 'move_download':
                self.reject_move()
            else:
                self._close_modal()
            event.app.invalidate()

        @kb.add('enter')
        @kb.add('y')
        @kb.add('Y')
        def _(event):
            if self.modal == 'confirm_fix_all':
                self._confirm_fix_all()
            elif self.modal == 'move_download':
                self.accept_move()
            else:
                self._close_modal()
            event.app.invalidate()

        return kb

    # ---------- модалка edit_name ----------
    def _edit_preview_text(self) -> FormattedText:
        if self._edit_target is None:
            return FormattedText([('', '')])
        info = analyze_file(self._edit_target)
        lines = [
            ('class:dim', '  Было: '),
            ('', self._edit_target.name + '\n'),
        ]
        if info['new_name']:
            lines.append(('class:dim', '  Предложение: '))
            lines.append(('class:status.sugg', info['new_name']))
            lines.append(('', f"  ({info['confidence']})"))
        else:
            lines.append(('class:dim', '  (автопредложение недоступно)'))
        return FormattedText(lines)

    def open_edit_for_selection(self):
        if not self.tree.entries:
            return
        path, _ = self.tree.entries[self.tree.selected]
        if not path.is_file():
            self.log(f'[i] Не файл: {path.name}')
            return
        info = analyze_file(path)
        suggestion = info['new_name'] or path.name
        self._edit_target = path
        self.edit_input.text = suggestion
        self.edit_input.cursor_position = len(suggestion)
        self.modal = 'edit_name'
        self.app.layout.focus(self.edit_input)
        self.invalidate()

    def _apply_edit_modal(self, buffer):
        text = buffer.text.strip()
        if self._edit_target is None or not text:
            self._close_modal()
            return
        path = self._edit_target
        if text == path.name:
            self.log(f'[i] Без изменений: {path.name}')
            self._close_modal()
            return
        new_path = path.with_name(text)
        if new_path.exists():
            self.log(f'[ОШБ] Уже существует: {text}')
            return
        try:
            path.rename(new_path)
            self.undo_stack.append((new_path, path))
            self.log(f'[OK] {path.name} -> {text}')
        except OSError as e:
            self.log(f'[ОШБ] {e}')
        self._close_modal()
        self.tree.refresh()
        self.invalidate()

    # ---------- модалка edit_config (F10) ----------
    def _build_config_modal(self):
        # --- Поля путей: русские подписи, выравнивание через _cfg_label ---
        self.config_root_input = TextArea(
            height=1,
            prompt=_cfg_label('Корневая папка'),       # 'Корневая папка        = '
            multiline=False,
            accept_handler=self._save_config_modal,
        )
        self.config_dl_input = TextArea(
            height=1,
            prompt=_cfg_label('Папка загрузок'),       # 'Папка загрузок        = '
            multiline=False,
            accept_handler=self._save_config_modal,
        )
        # with_arrows=True — ↑/↓ переключают поля именно в этой модалке
        self._override_tab(self.config_root_input, with_arrows=True)
        self._override_tab(self.config_dl_input, with_arrows=True)

        # --- Тумблер: русская подпись + каретка после '= ' ---
        self.config_watch_state = False

        toggle_label = _cfg_label('Следить за загрузками')  # 'Следить за загрузками = '
        toggle_cursor_x = len(toggle_label)                 # ровно после '= '

        def _toggle_render() -> FormattedText:
            mark = 'x' if self.config_watch_state else ' '
            return FormattedText([
                ('class:cfg.label', toggle_label),
                ('class:cfg.path', f'[{mark}]'),
                ('class:cfg.hint', '   (Пробел — переключить)'),
            ])

        toggle_kb = KeyBindings()

        @toggle_kb.add('space')
        def _(event):
            self.config_watch_state = not self.config_watch_state
            event.app.invalidate()

        @toggle_kb.add('enter')
        def _(event):
            self._save_config_modal()
            event.app.invalidate()

        @toggle_kb.add('escape')
        def _(event):
            self._cancel_config_modal()
            event.app.invalidate()

        @toggle_kb.add('tab')
        @toggle_kb.add('c-i')
        def _(event):
            self._handle_tab(reverse=False)
            event.app.invalidate()

        @toggle_kb.add('s-tab')
        def _(event):
            self._handle_tab(reverse=True)
            event.app.invalidate()

        @toggle_kb.add('up')
        def _(event):
            if self.modal is None:
                return NotImplemented
            self._modal_focus_next(reverse=True)
            event.app.invalidate()

        @toggle_kb.add('down')
        def _(event):
            if self.modal is None:
                return NotImplemented
            self._modal_focus_next(reverse=False)
            event.app.invalidate()

        self.config_watch_control = FormattedTextControl(
            text=_toggle_render,
            focusable=True,
            key_bindings=toggle_kb,
            # Каретка — ровно там же, где у обычных TextArea:
            # сразу после '= '.
            get_cursor_position=lambda: Point(x=toggle_cursor_x, y=0),
        )
        self.config_watch_window = Window(self.config_watch_control, height=1)

        header = Window(
            FormattedTextControl(text=lambda: FormattedText([
                ('class:cfg.label', '  Файл: '),
                ('class:cfg.path', str(config_path())),
                ('', '\n'),
            ])),
            height=2,
        )

        footer = Window(
            FormattedTextControl(text=lambda: FormattedText([
                ('', '\n'),
                ('class:cfg.hint',
                '  Enter — сохранить и применить,  '
                'Esc — отмена,  Tab/↑/↓ — между полями\n'),
            ])),
            height=2,
        )

        body = HSplit([
            header,
            self.config_root_input,
            self.config_dl_input,
            self.config_watch_window,
            footer,
        ])

        self._config_float = Float(
            content=ConditionalContainer(
                content=Frame(body, title=' ▶ Настройки ok-helper-tui — F10 '),
                filter=Condition(lambda: self.modal == 'edit_config'),
            ),
            top=5, left=6, width=88, height=11,
        )

    def open_config_modal(self):
        self.config_root_input.text = self.config.get('root_dir', '~')
        self.config_root_input.cursor_position = len(self.config_root_input.text)
        self.config_dl_input.text = self.config.get('downloads_dir', '~/Downloads')
        self.config_dl_input.cursor_position = len(self.config_dl_input.text)
        self.config_watch_state = bool(self.config.get('watch_downloads', False))
        self.modal = 'edit_config'
        self.app.layout.focus(self.config_root_input)
        self.invalidate()

    def _cancel_config_modal(self):
        self._close_modal()
        self.log('[НАСТР] Изменения отменены')

    def _save_config_modal(self, buffer=None):
        new_root = self.config_root_input.text.strip()
        new_dl = self.config_dl_input.text.strip()
        new_watch = bool(self.config_watch_state)

        root_path = Path(new_root).expanduser()
        if not new_root or not root_path.is_dir():
            self.log(f'[НАСТР] root_dir не существует: {root_path}')
            return

        dl_path = Path(new_dl).expanduser()
        if not new_dl or not dl_path.is_dir():
            self.log(f'[НАСТР] downloads_dir не существует: {dl_path}')
            return

        self.config['root_dir'] = new_root
        self.config['downloads_dir'] = new_dl
        self.config['watch_downloads'] = new_watch
        self.config['root_dir_resolved'] = root_path.resolve()
        self.config['downloads_dir_resolved'] = dl_path.resolve()
        save_config(self.config)
        self.log(f'[НАСТР] Сохранено: {config_path()}')

        new_root_resolved = root_path.resolve()
        if new_root_resolved != self.tree.root:
            self.watch_dir = new_root_resolved
            self.tree.set_root(new_root_resolved)
            self.path_input.text = str(new_root_resolved)
            self.path_input.cursor_position = len(str(new_root_resolved))
            self.restart_watch()
            self.log(f'[НАСТР] root_dir → {new_root_resolved}')

        self.stop_downloads_watch()
        if new_watch:
            self.start_downloads_watch()
        else:
            self.log('[НАСТР] Мониторинг загрузок выключен')

        self._close_modal()
        self.invalidate()

    # ---------- отрисовка дерева ----------
    def _click_row(self, path: Path):
        def handler(event: MouseEvent):
            if event.event_type != MouseEventType.MOUSE_UP:
                return
            if self.modal is not None:
                return
            self.tree.select_by_path(path)
            self._sync_path_to_selection()
            self.app.layout.focus(self.tree_window)
            self.app.invalidate()
        return handler

    def _click_fix(self, path: Path, new_name: str):
        def handler(event: MouseEvent):
            if event.event_type != MouseEventType.MOUSE_UP:
                return
            if self.modal is not None:
                return
            self.app.layout.focus(self.tree_window)
            self.do_fix(path, new_name)
        return handler

    def _click_edit(self, path: Path):
        def handler(event: MouseEvent):
            if event.event_type != MouseEventType.MOUSE_UP:
                return
            if self.modal is not None:
                return
            self.tree.select_by_path(path)
            self.app.layout.focus(self.tree_window)
            self.open_edit_for_selection()
        return handler

    def render_tree(self) -> FormattedText:
        frags = []
        if not self.tree.entries:
            frags.append(('class:dim', '  (пусто)'))
            return FormattedText(frags)

        for i, (path, depth) in enumerate(self.tree.entries):
            indent = '  ' * depth
            selected = (i == self.tree.selected)

            if path.is_dir():
                arrow = '▼' if path in self.tree.expanded else '▶'
                style = 'class:tree.dir' + (' class:tree.sel' if selected else '')
                frags.append((style, f'{indent}{arrow} {path.name}/\n',
                              self._click_row(path)))
                continue

            info = self.tree.info(path)
            base = 'class:tree.err' if info['has_error'] else 'class:tree.file'
            style = base + (' class:tree.sel' if selected else '')
            frags.append((style, f'{indent}  {path.name}',
                          self._click_row(path)))

            if info['has_error']:
                frags.append(('', '  '))
                if not info['new_name']:
                    frags.append(('class:btn.dis', '[Правка]',
                                  self._click_row(path)))
                else:
                    conf = info['confidence']
                    if conf == 'high':
                        frags.append(('class:btn', '[Правка]',
                                      self._click_fix(path, info['new_name'])))
                    elif conf == 'medium':
                        frags.append(('class:btn.med', '[Правка]',
                                      self._click_fix(path, info['new_name'])))
                    else:
                        frags.append(('class:btn.warn', '[Правка?]',
                                      self._click_edit(path)))
            frags.append(('', '\n'))

        return FormattedText(frags)

    # ---------- статус-бар ----------
    def _status_frags(self) -> FormattedText:
        entries = self.tree.entries
        total = sum(1 for p, _ in entries if p.is_file())
        errors = sum(1 for p, _ in entries
                     if p.is_file() and self.tree.is_error(p))

        frags = [
            ('class:status.sep', '  '),
            ('class:status.key', 'фильтр: '),
            ('class:status.val', self.tree.filter_mode.value),
            ('class:status.sep', '   '),
            ('class:status.key', 'сорт: '),
            ('class:status.val', self.tree.sort_mode.value),
            ('class:status.sep', '   '),
            ('class:status.key', 'файлов: '),
            ('class:status.val', str(total)),
            ('class:status.sep', '   '),
        ]
        if errors:
            frags.append(('class:status.err', f'ошибок: {errors}'))
        else:
            frags.append(('class:status.ok', 'ошибок: 0'))
        frags.extend([
            ('class:status.sep', '   '),
            ('class:status.key', 'отм: '),
            ('class:status.val', str(len(self.undo_stack))),
        ])

        if self.watch_downloads:
            frags.append(('class:status.sep', '   '))
            frags.append(('class:status.key', 'загр: '))
            if self.pending_downloads:
                frags.append(('class:status.dl',
                              f'{len(self.pending_downloads)}'))
            else:
                frags.append(('class:status.val', '0'))

        if self.tree.entries:
            p, _ = self.tree.entries[self.tree.selected]
            if p.is_file():
                info = self.tree.info(p)
                if info['has_error'] and info['new_name']:
                    frags.append(('class:status.sep', '   → '))
                    frags.append(('class:status.sugg', info['new_name']))

        frags.extend([
            ('class:status.sep', '    '),
            ('class:status.hint',
                'F1 Спр  F2 Фил  F3 Откр  F4 Сорт  F5 Прав  F6 Скан  '
                'F7 Имя  F8 Загр  F9 Мон  F10 Настр  F11 Журн  ^Z Отм  ^Q Вых'),
        ])
        return FormattedText(frags)

    # ---------- действия ----------
    def _sync_path_to_selection(self):
        if not self.tree.entries:
            return
        path, _ = self.tree.entries[self.tree.selected]
        target = path if path.is_dir() else path.parent
        text = str(target)
        if self.path_input.text == text:
            return
        self.path_input.text = text
        self.path_input.cursor_position = len(text)

    def _tree_scroll(self, delta: int):
        """Обработчик колесика мыши над деревом."""
        if self.modal is not None:
            return  # пока открыта модалка — скролл не должен менять выделение
        self.tree.move(delta)
        self._sync_path_to_selection()
        self.app.layout.focus(self.tree_window)
        self.invalidate()

    def handle_tree_enter(self):
        if not self.tree.entries:
            return
        path, _ = self.tree.entries[self.tree.selected]
        if path.is_dir():
            self.tree.toggle()
            return
        info = analyze_file(path)
        if not info['has_error']:
            self.log(f'[i] {path.name} — ок')
            return
        if not info['new_name']:
            self.log(f'[!] {path.name} — {info["reason"]}')
            return
        if info['confidence'] in ('high', 'medium'):
            self.do_fix(path, info['new_name'])
        else:
            self.open_edit_for_selection()

    def do_fix(self, path: Path, new_name: str):
        new_path = path.with_name(new_name)
        if new_path.exists():
            self.log(f'[ОШБ] Уже существует: {new_name}')
            return
        try:
            path.rename(new_path)
            self.undo_stack.append((new_path, path))
            self.log(f'[OK] {path.name} -> {new_name}')
        except OSError as e:
            self.log(f'[ОШБ] {e}')
        self.tree.refresh()
        self.invalidate()

    def on_fix_all(self):
        files: List[Tuple[str, str, Path, str]] = []
        for p, _ in self.tree.entries:
            if p.is_file():
                info = analyze_file(p)
                if (info['has_error'] and info['new_name']
                        and info['confidence'] in ('high', 'medium')):
                    files.append((p.name, info['new_name'], p,
                                  info['new_name']))
        if not files:
            self.log('[i] Нет файлов для автоисправления (уверенные случаи)')
            return
        self._pending_fix_list = files
        self._open_modal('confirm_fix_all')

    def _confirm_fix_all(self):
        count = 0
        for old_name, new_name, path, _ in self._pending_fix_list:
            new_path = path.with_name(new_name)
            if new_path.exists():
                self.log(f'[ОШБ] Уже существует: {new_name}')
                continue
            try:
                path.rename(new_path)
                self.undo_stack.append((new_path, path))
                count += 1
            except OSError as e:
                self.log(f'[ОШБ] {old_name}: {e}')
        self.log(f'[OK] Исправлено: {count}')
        self._close_modal()
        self.tree.refresh()
        self.invalidate()

    def undo(self):
        if not self.undo_stack:
            self.log('[i] Нечего отменять')
            return
        new_path, old_path = self.undo_stack.pop()
        try:
            new_path.rename(old_path)
            self.log(f'[ОТМЕНА] {new_path.name} -> {old_path.name}')
        except OSError as e:
            self.log(f'[ОШБ] Отмена: {e}')
        self.tree.refresh()
        self.invalidate()

    def open_selected(self):
        if not self.tree.entries:
            return
        path, _ = self.tree.entries[self.tree.selected]
        if not path.is_file():
            self.log(f'[i] Не файл: {path.name}')
            return
        try:
            if sys.platform.startswith('linux'):
                subprocess.Popen(['xdg-open', str(path)],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(path)],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            elif sys.platform == 'win32':
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                self.log(f'[ОШБ] Открытие не поддержано: {sys.platform}')
                return
            self.log(f'[ОТКР] {path.name}')
        except Exception as e:
            self.log(f'[ОШБ] Открыть не удалось: {e}')

    # ---------- загрузки ----------
    def start_downloads_watch(self):
        d = self.config['downloads_dir_resolved']
        if not d.is_dir():
            self.log(f'[ЗАГР] Папка загрузок не найдена: {d}')
            self.watch_downloads = False
            return
        if d == self.tree.root:
            self.log('[ЗАГР] Папка загрузок совпадает с текущей '
                     'директорией; мониторинг выключен')
            self.watch_downloads = False
            return
        handler = DirHandler(self.on_download_event)
        obs = Observer()
        obs.schedule(handler, str(d), recursive=False)
        obs.start()
        self.downloads_observer = obs
        self.watch_downloads = True
        self.log(f'[ЗАГР] Мониторинг загрузок: {d}')

    def stop_downloads_watch(self):
        if self.downloads_observer:
            self.downloads_observer.stop()
            self.downloads_observer.join()
            self.downloads_observer = None
        self.watch_downloads = False

    def toggle_downloads_watch(self):
        if self.watch_downloads:
            self.stop_downloads_watch()
            self.config['watch_downloads'] = False
            save_config(self.config)
            self.log('[i] Мониторинг загрузок: выкл (сохранено в конфиг)')
        else:
            self.config['watch_downloads'] = True
            save_config(self.config)
            self.start_downloads_watch()
            self.log('[i] Мониторинг загрузок: вкл (сохранено в конфиг)')
        self.invalidate()

    def on_download_event(self, path: Optional[Path]):
        if path is None or self.loop is None:
            return
        self.loop.call_soon_threadsafe(self._on_download_event_main, path)

    def _on_download_event_main(self, path: Path):
        if path.name.startswith('.'):
            return
        if any(p == path for p in self.pending_downloads):
            return
        self.pending_downloads.append(path)
        try:
            size = human_size(path.stat().st_size)
        except OSError:
            size = '?'
        self.log(f'[ЗАГР] Новый файл в Загрузках: {path.name} ({size})')
        if self.modal is None:
            self.show_move_modal()
        self.invalidate()

    def show_move_modal(self):
        if not self.pending_downloads:
            return
        self.modal = 'move_download'
        self.app.layout.focus(self.modal_window)
        self.invalidate()

    def show_pending_downloads(self):
        if not self.pending_downloads:
            self.log('[i] Очередь загрузок пуста')
            return
        self.show_move_modal()

    def accept_move(self):
        if not self.pending_downloads:
            self._close_modal()
            return
        src = self.pending_downloads[0]
        dst_dir = self.tree.root
        if not src.exists():
            self.log(f'[ОШБ] Файл исчез: {src.name}')
            self.pending_downloads.pop(0)
            self._after_move_action()
            return
        dst = dst_dir / src.name
        if dst.exists():
            self.log(f'[ОШБ] Уже существует: {dst}')
            self.pending_downloads.pop(0)
        else:
            try:
                shutil.move(str(src), str(dst))
                self.pending_downloads.pop(0)
                self.log(f'[ПЕРЕНОС] {src.name} -> {dst_dir}')
            except OSError as e:
                self.log(f'[ОШБ] Перенос: {e}')
                self.pending_downloads.pop(0)
        self._after_move_action()

    def reject_move(self):
        if not self.pending_downloads:
            self._close_modal()
            return
        src = self.pending_downloads.pop(0)
        self.log(f'[ЗАГР] Пропущен: {src.name}')
        self._after_move_action()

    def _after_move_action(self):
        if self.pending_downloads:
            self.invalidate()
        else:
            self._close_modal()

    # ---------- поля ввода ----------
    def on_translit(self, buffer):
        text = buffer.text
        buffer.reset()
        if text.strip():
            self.log(f'[ТРАНСЛИТ] «{text}» -> «{transliterate(text)}»')

    def on_path_change(self, buffer):
        text = buffer.text.strip()
        p = Path(text).expanduser()
        if not p.is_dir():
            self.log(f'[ОШБ] Не директория: {p}')
            return
        p = p.resolve()
        self.watch_dir = p
        buffer.text = str(p)
        buffer.cursor_position = len(str(p))
        self.tree.set_root(p)

        self.config['root_dir'] = str(p)
        save_config(self.config)

        self.restart_watch()
        self.log(f'[КАТАЛОГ] {p}')
        self.scan_dir(p)
        self.invalidate()

    # ---------- watchdog (tree) ----------
    def restart_watch(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        handler = DirHandler(self.on_fs_event)
        obs = Observer()
        obs.schedule(handler, str(self.watch_dir), recursive=True)
        obs.start()
        self.observer = obs

    def on_fs_event(self, path: Optional[Path]):
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(self._on_fs_event_main, path)

    def _on_fs_event_main(self, path: Optional[Path]):
        self.tree.refresh()
        if path is not None:
            info = analyze_file(path)
            if info['has_error']:
                tag = {'high': 'Правка', 'medium': 'Правка',
                       'low': 'Правка?', 'none': '—'}[info['confidence']]
                self.log(f'[!] {path.name} — {info["reason"]} [{tag}]')
            else:
                self.log(f'[+] {path.name}')
        self.invalidate()

    def scan_dir(self, path: Path):
        problems = 0
        if path.is_dir():
            for p in sorted(path.iterdir()):
                if p.is_file():
                    info = analyze_file(p)
                    if info['has_error']:
                        problems += 1
                        tag = {'high': 'Правка', 'medium': 'Правка',
                               'low': 'Правка?', 'none': '—'}[info['confidence']]
                        self.log(f'[!] {p.name} — {info["reason"]} [{tag}]')
        if problems:
            self.log(f'[КАТАЛОГ] Проблем: {problems} — F5 (уверенные), '
                     f'F7 для ручной правки')
        else:
            self.log('[КАТАЛОГ] Все имена корректны')

    # ---------- логи / invalidate ----------
    def log(self, msg: str, level: Optional[str] = None):
        """Добавляет запись в журнал.

        level можно задать явно ('info','ok','warn','error','dir','dl',
        'cfg','move','open','undo','translit','text'); если не задан —
        определяется по тегу в начале msg ([i], [OK], [ОШБ] и т.п.).
        """
        ts = datetime.now().strftime('%H:%M:%S')
        if level is None:
            level = self._level_from_msg(msg)
        with self.lock:
            self.lines.append((ts, level, msg))
            if len(self.lines) > self.MAX_LOG:
                self.lines = self.lines[-self.MAX_LOG:]
        if self.loop is not None:
            try:
                self.loop.call_soon_threadsafe(self._after_log_update)
            except Exception:
                pass

    def _log_text(self) -> FormattedText:
        frags: List[tuple] = []
        with self.lock:
            snapshot = list(self.lines)

        for ts, level, msg in snapshot:
            # 1) время
            frags.append(('class:log.time', ts + '  '))

            # 2) тег (если есть) — своим цветом, выровненный по колонке
            m = _LOG_TAG_RE.match(msg)
            if m:
                tag = m.group(1)
                rest = msg[m.end():]
                frags.append((f'class:log.tag.{level}', tag.ljust(10)))
                frags.append(('class:log.msg', rest))
            else:
                frags.append(('class:log.msg', msg))

            frags.append(('', '\n'))

        # убрать завершающий перевод — иначе лишняя пустая строка
        if frags and frags[-1][1] == '\n':
            frags.pop()

        return FormattedText(frags)

    def _level_from_msg(self, msg: str) -> str:
        m = _LOG_TAG_RE.match(msg)
        if not m:
            return 'text'
        tag = m.group(1)[1:-1].strip()
        return _LOG_LEVEL_BY_TAG.get(tag, 'info')

    def _after_log_update(self):
        """Вызывается в главном потоке после добавления записи."""
        self._scroll_log_to_bottom()
        self.app.invalidate()

    def _scroll_log_to_bottom(self):
        """Подматывает журнал вниз, если окно уже отрисовано."""
        try:
            w = self.log_window
            info = getattr(w, 'render_info', None)
            h = info.window_height if info else 0
            with self.lock:
                total = len(self.lines)
            if h > 0:
                w.vertical_scroll = max(0, total - h)
        except Exception:
            pass

    def _log_scroll(self, delta: int):
        """Ручной скролл журнала (колесо мыши, PageUp/PageDown)."""
        if self.modal is not None:
            return
        try:
            w = self.log_window
            cur = w.vertical_scroll
            info = getattr(w, 'render_info', None)
            h = info.window_height if info else 0
            with self.lock:
                total = len(self.lines)
            if h > 0:
                cur = min(cur, max(0, total - h))
            w.vertical_scroll = max(0, cur + delta)
            self.app.invalidate()
        except Exception:
            pass

    def _log_kb(self) -> KeyBindings:
        """Клавиши прокрутки журнала."""
        kb = KeyBindings()

        @kb.add('pageup')
        def _(event):
            self._log_scroll(-10)
            event.app.invalidate()

        @kb.add('pagedown')
        def _(event):
            self._log_scroll(10)
            event.app.invalidate()

        @kb.add('home')
        def _(event):
            if self.modal is not None:
                return
            try:
                self.log_window.vertical_scroll = 0
            except Exception:
                pass
            event.app.invalidate()

        @kb.add('end')
        def _(event):
            if self.modal is not None:
                return
            self._scroll_log_to_bottom()
            event.app.invalidate()

        return kb
    
    def invalidate(self):
        if self.loop is None:
            return
        try:
            self.loop.call_soon_threadsafe(self.app.invalidate)
        except Exception:
            pass


# ====================== Точка входа ======================
async def run(initial_dir: Path, config: dict):
    app = App(initial_dir, config)
    app.loop = asyncio.get_running_loop()

    app.log(f'[КОНФИГ] {config_path()}')
    app.log(f'[КАТАЛОГ] {initial_dir}')
    app.log('[i] F1 — справка, F7 — переименование, '
            'F8/F9 — загрузки, F10 — настройки')

    app.scan_dir(initial_dir)

    if config['watch_downloads']:
        app.start_downloads_watch()

    app.restart_watch()
    try:
        await app.app.run_async()
    finally:
        if app.observer:
            app.observer.stop()
            app.observer.join()
        if app.downloads_observer:
            app.downloads_observer.stop()
            app.downloads_observer.join()


def main():
    parser = argparse.ArgumentParser(
        description='ok-helper-tui: транслит + умная проверка имён файлов.')
    parser.add_argument(
        'directory', nargs='?', default=None,
        help='Начальная директория. Если не задана — берётся из конфига.',
    )
    args = parser.parse_args()

    config = load_config()

    if args.directory is None:
        d = config['root_dir_resolved']
    else:
        d = Path(args.directory).expanduser().resolve()

    if not d.is_dir():
        print(f'Не директория: {d}', file=sys.stderr)
        print(f'Проверьте root_dir в {config_path()}', file=sys.stderr)
        sys.exit(1)

    try:
        asyncio.run(run(d, config))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()