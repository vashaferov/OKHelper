"""NavMixin: дерево, статус-бар, watcher основной директории."""

from pathlib import Path
from typing import Optional

from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Window
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType

from ..analyzer import analyze_file
from ..controls import TreeControl
from ..handlers import DirHandler
from watchdog.observers import Observer


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
                style = 'class:tree.dir' + (' class:tree.sel' if selected else '')
                frags.append((style, f'{indent}{arrow} {path.name}/\n',
                              self._click_row(path)))
                continue

            info = self.tree.info(path)
            base = 'class:tree.err' if info['has_error'] else 'class:tree.file'
            style = base + (' class:tree.sel' if selected else '')
            frags.append((style, f'{indent}  {path.name}',
                          self._click_row(path)))

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
             'F7 Имя  F8 Загр  F9 Мон  F10 Настр  F11 Журн  F12 FTP  '
             '^Z Отм  ^Q Вых'),
        ])
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
