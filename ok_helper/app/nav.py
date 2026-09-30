"""NavMixin: дерево, статус-бар, watcher основной директории."""

import time
from pathlib import Path
from typing import List, Optional, Tuple

from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Window
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType

from ..analyzer import analyze_file
from ..controls import TreeControl
from ..ftp import is_uploadable
from ..handlers import DirHandler
from watchdog.observers import Observer


_STATUS_HINTS: List[Tuple[str, str, str, int]] = [
    ('F1',  'Спр',   'Справка',     100),
    ('^Q',  'Вых',   'Выход',       100),
    ('^Z',  'Отм',   'Отмена',       70),
    ('^C',  'Вых',   'Выход',        50),
]


class NavMixin:
    # ---------- init ----------
    def _init_tree(self):
        self.tree_kb = self._build_tree_kb()
        self.tree_control = TreeControl(
            on_scroll=self._tree_scroll,
            text=self.render_tree,
            focusable=True,
            key_bindings=self.tree_kb,
            get_cursor_position=lambda: Point(0, self.tree.selected),
        )
        self.tree_window = Window(self.tree_control)

    def _build_tree_kb(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add('up')
        def _(event):
            self.tree.move(-1)
            self._sync_path_to_selection()
            event.app.invalidate()

        @kb.add('down')
        def _(event):
            self.tree.move(1)
            self._sync_path_to_selection()
            event.app.invalidate()

        @kb.add('left')
        def _(event):
            if self.tree.entries:
                p, _ = self.tree.entries[self.tree.selected]
                if p.is_dir() and p in self.tree.expanded:
                    self.tree.expanded.discard(p)
                    self.tree.refresh()
                    self._sync_path_to_selection()
                    event.app.invalidate()

        @kb.add('right')
        def _(event):
            if self.tree.entries:
                p, _ = self.tree.entries[self.tree.selected]
                if p.is_dir() and p not in self.tree.expanded:
                    self.tree.expanded.add(p)
                    self.tree.refresh()
                    self._sync_path_to_selection()
                    event.app.invalidate()

        @kb.add('enter')
        @kb.add(' ')
        def _(event):
            self.handle_tree_enter()
            self._sync_path_to_selection()
            event.app.invalidate()

        return kb

    # ---------- actions ----------
    def _sync_path_to_selection(self):
        """Обновляет поле «Путь:» на вкладке «Файлы» при навигации по
        дереву.

        Запрос на FTP НЕ выполняется: синхронизация вкладки FTP
        происходит только в момент переключения на неё (см.
        FtpTabMixin.switch_tab / _ftp_follow_from_files).
        """
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
        if self.modal is not None:
            return
        self.tree.move(delta)
        self._sync_path_to_selection()
        self.app.layout.focus(self.tree_window)
        self.invalidate()

    # ---------- click handlers ----------
    def _click_row(self, path: Path):
        def handler(event: MouseEvent):
            if event.event_type != MouseEventType.MOUSE_UP:
                return
            if self.modal is not None:
                return

            now = time.monotonic()
            is_double = (
                self._last_click_path == path
                and (now - self._last_click_time) <= self.DOUBLE_CLICK_INTERVAL
            )
            self._last_click_path = path
            self._last_click_time = now

            self.tree.select_by_path(path)

            if path.is_dir():
                self.tree.toggle()
                self._last_click_path = None
                self._last_click_time = 0.0
                self._sync_path_to_selection()
                self.app.layout.focus(self.tree_window)
                self.app.invalidate()
                return

            if is_double:
                self._last_click_path = None
                self._last_click_time = 0.0
                self.app.layout.focus(self.tree_window)
                self._sync_path_to_selection()
                self.open_edit_for_selection()
                return

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

    def _click_upload(self, path: Path):
        def handler(event: MouseEvent):
            if event.event_type != MouseEventType.MOUSE_UP:
                return
            if self.modal is not None:
                return
            self.tree.select_by_path(path)
            self.app.layout.focus(self.tree_window)
            self.open_upload_modal()
        return handler

    # ---------- rendering ----------
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
                style = 'class:tree.dir' + (
                    ' class:tree.sel' if selected else '')
                frags.append((style, f'{indent}{arrow} {path.name}/\n',
                              self._click_row(path)))
                continue

            info = self.tree.info(path)
            base = 'class:tree.err' if info['has_error'] else 'class:tree.file'
            style = base + (' class:tree.sel' if selected else '')
            frags.append((style, f'{indent}  {path.name}',
                          self._click_row(path)))

            if is_uploadable(path, info):
                frags.append(('', '  '))
                frags.append(('class:btn.ftp', '[⇪]',
                              self._click_upload(path)))

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

    # ---------- status bar ----------
    def _terminal_width(self) -> int:
        try:
            return self.app.output.get_size().columns
        except Exception:
            return 120

    @staticmethod
    def _build_hint(available: int) -> str:
        if available <= 0:
            return ''
        hints = sorted(_STATUS_HINTS, key=lambda h: -h[3])
        parts: List[str] = []
        used = 0
        sep = '  '
        for code, short, long, _ in hints:
            candidates: List[str] = []
            if long:
                candidates.append(f'{code} {long}')
            if short and short != long:
                candidates.append(f'{code} {short}')
            candidates.append(code)
            sep_len = len(sep) if parts else 0
            for cand in candidates:
                if used + sep_len + len(cand) <= available:
                    parts.append(cand)
                    used += sep_len + len(cand)
                    break
        return sep.join(parts)

    def _status_frags(self) -> FormattedText:
        entries = self.tree.entries
        total = sum(1 for p, _ in entries if p.is_file())
        errors = sum(1 for p, _ in entries
                     if p.is_file() and self.tree.is_error(p))

        frags: List[tuple] = [
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

        used_left = sum(len(t) for _, t in frags)
        width = self._terminal_width()
        available = max(0, width - used_left - 4)
        hint = self._build_hint(available)
        if hint:
            frags.append(('class:status.sep', '    '))
            frags.append(('class:status.hint', hint))

        return FormattedText(frags)

    # ---------- watcher (tree) ----------
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
