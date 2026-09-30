"""FtpTabMixin: вкладка FTP в правой панели.

Возможности:
  • своя «Директория» и список содержимого папки на сервере;
  • чек-бокс «Отслеживать папку из вкладки «Файлы»»;
  • удаление файлов (клавиша Del или кнопка [✕]) с подтверждением —
    только если ftp_readonly = false.
"""

import threading
from pathlib import Path
from typing import List, Optional, Tuple

from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.widgets import TextArea

from ..analyzer import human_size
from ..ftp import (
    delete_file, find_target_folder, list_folder, validate_folder_name,
)


class FtpTabMixin:
    # ---------- init ----------
    def _init_ftp_tab(self):
        # Состояние вкладки FTP.
        self.ftp_connected = False
        self.ftp_loading = False
        self.ftp_error = ''
        self.ftp_folder = ''
        self.ftp_entries: List[Tuple[str, bool, int]] = []
        self.ftp_selected = 0
        self.ftp_follow_files = True

        # Цель для модалки удаления: (имя файла, размер).
        self._ftp_delete_target: Optional[Tuple[str, int]] = None

        # Поле «Путь:» на вкладке FTP.
        self.ftp_path_input = TextArea(
            height=1, prompt='Путь: ', multiline=False,
            accept_handler=self._ftp_path_submit,
        )
        self._override_tab(self.ftp_path_input)

        # Чек-бокс «Отслеживать папку из вкладки «Файлы»».
        self.ftp_checkbox_control = FormattedTextControl(
            text=self._render_ftp_checkbox,
            focusable=True,
            key_bindings=self._ftp_checkbox_kb(),
        )
        self.ftp_checkbox_window = Window(
            self.ftp_checkbox_control, height=1, char=' ',
        )

        # Список содержимого папки.
        self.ftp_list_control = FormattedTextControl(
            text=self._render_ftp,
            focusable=True,
            key_bindings=self._ftp_kb(),
            get_cursor_position=lambda: Point(0, self.ftp_selected),
        )
        self.ftp_list_window = Window(self.ftp_list_control, char=' ')

        self.ftp_top_window = HSplit([
            self.ftp_path_input,
            self.ftp_checkbox_window,
        ])

    def _ftp_kb(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add('up')
        def _(event):
            self.ftp_move(-1)
            event.app.invalidate()

        @kb.add('down')
        def _(event):
            self.ftp_move(1)
            event.app.invalidate()

        @kb.add('enter')
        def _(event):
            self.handle_ftp_enter()
            event.app.invalidate()

        @kb.add('delete')
        def _(event):
            self.open_ftp_delete_modal()
            event.app.invalidate()

        return kb

    def _ftp_checkbox_kb(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add('space')
        def _(event):
            self.toggle_ftp_follow()
            event.app.invalidate()

        @kb.add('enter')
        def _(event):
            self.toggle_ftp_follow()
            event.app.invalidate()

        return kb

    # ---------- checkbox ----------
    def _render_ftp_checkbox(self) -> FormattedText:
        mark = 'x' if self.ftp_follow_files else ' '
        focused = False
        try:
            focused = (
                self.app.layout.current_window is self.ftp_checkbox_window
            )
        except Exception:
            pass
        prefix = ' ▶ ' if focused else '   '
        box_style = ('class:tab.active' if self.ftp_follow_files
                     else 'class:tab.inactive')
        label_style = ('class:cfg.path' if self.ftp_follow_files
                       else 'class:dim')
        return FormattedText([
            ('class:dim', prefix),
            (box_style, f'[{mark}]', self._click_checkbox()),
            (label_style, ' Отслеживать папку из вкладки «Файлы»',
             self._click_checkbox()),
        ])

    def _click_checkbox(self):
        def handler(event: MouseEvent):
            if event.event_type != MouseEventType.MOUSE_UP:
                return
            if self.modal is not None:
                return
            self.toggle_ftp_follow()
            try:
                self.app.layout.focus(self.ftp_checkbox_window)
            except Exception:
                pass
            self.app.invalidate()
        return handler

    def toggle_ftp_follow(self):
        self.ftp_follow_files = not self.ftp_follow_files
        if self.ftp_follow_files:
            local = (self.path_input.text or '').strip()
            if local:
                self._ftp_follow_from_files(local)
            self.log('[FTP] Отслеживание папки из «Файлы»: вкл')
        else:
            self.log('[FTP] Отслеживание папки из «Файлы»: выкл')
        self.invalidate()

    # ---------- navigation ----------
    def ftp_move(self, delta: int):
        if self.ftp_entries:
            self.ftp_selected = max(
                0, min(len(self.ftp_entries) - 1,
                       self.ftp_selected + delta))

    def handle_ftp_enter(self):
        if not self.ftp_entries:
            return
        name, is_dir, _ = self.ftp_entries[self.ftp_selected]
        if not is_dir:
            return
        current = self.ftp_path_input.text.strip()
        new_folder = f'{current}/{name}' if current else name
        self.ftp_path_input.text = new_folder
        self.ftp_path_input.cursor_position = len(new_folder)
        self._ftp_load(new_folder)

    def _ftp_path_submit(self, buffer=None):
        path = (self.ftp_path_input.text or '').strip()
        if not path:
            return
        first = path.split('/')[0]
        ok, reason = validate_folder_name(first)
        if not ok:
            self.ftp_error = f'первый компонент пути: {reason}'
            self.ftp_connected = False
            self.invalidate()
            return
        self._ftp_load(path)

    # ---------- following files tab ----------
    def _ftp_follow_from_files(self, local_path: str):
        if not self.ftp_follow_files:
            return
        try:
            p = Path(local_path)
        except Exception:
            return

        folder, found = find_target_folder(p)
        if not found:
            if self.ftp_path_input.text:
                self.ftp_path_input.text = ''
            self.ftp_error = (
                f'имя «{p.name}» не соответствует шаблону '
                'ГГГГ-ММ-ДД_Место — введите папку на сервере вручную'
            )
            self.ftp_connected = False
            self.ftp_entries = []
            self.invalidate()
            return

        if folder == self.ftp_folder and (
                self.ftp_connected or self.ftp_loading):
            return
        if (folder == self.ftp_path_input.text.strip()
                and self.ftp_loading):
            return

        self.ftp_path_input.text = folder
        self.ftp_path_input.cursor_position = len(folder)
        self._ftp_load(folder)

    # ---------- loading ----------
    def _ftp_load(self, folder: str):
        host = self.config.get('ftp_host', '')
        user = self.config.get('ftp_user', '')
        if not host or not user:
            self.ftp_error = 'задайте ftp_host и ftp_user в настройках (F10)'
            self.ftp_connected = False
            self.ftp_loading = False
            self.invalidate()
            return

        port = int(self.config.get('ftp_port', 21))
        password = self.config.get('ftp_password', '')
        base = self.config.get('ftp_path', '/') or '/'

        self.ftp_loading = True
        self.ftp_connected = False
        self.ftp_error = ''
        self.ftp_entries = []
        self.ftp_selected = 0
        self.ftp_folder = folder
        self.invalidate()

        t = threading.Thread(
            target=self._ftp_load_worker,
            args=(host, port, user, password, base, folder),
            daemon=True,
        )
        t.start()

    def _ftp_load_worker(self, host, port, user, password, base, folder):
        try:
            entries = list_folder(host, port, user, password, base, folder)
            err = ''
        except Exception as e:
            entries = []
            err = str(e)
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(
            self._ftp_apply_result, entries, err, folder)

    def _ftp_apply_result(self, entries, err, folder):
        if folder != self.ftp_folder:
            return
        self.ftp_loading = False
        if err:
            self.ftp_error = err
            self.ftp_connected = False
            self.ftp_entries = []
            self.log(f'[FTP] Ошибка: {err}')
        else:
            self.ftp_connected = True
            self.ftp_error = ''
            self.ftp_entries = entries
            self.ftp_selected = 0
            self.log(f'[FTP] Открыта папка {folder} '
                     f'({len(entries)} элементов)')
        self.invalidate()

    # ---------- delete ----------
    def _ftp_delete_allowed(self) -> bool:
        """Удаление разрешено только когда ftp_readonly = false."""
        return not bool(self.config.get('ftp_readonly', False))

    def open_ftp_delete_modal(self):
        if self.modal is not None:
            return
        if not self.ftp_connected:
            return
        if not self.ftp_entries:
            return

        name, is_dir, size = self.ftp_entries[self.ftp_selected]
        if is_dir:
            self.log('[FTP] Удаление папок не поддерживается '
                     '(только отдельные файлы)')
            return

        if not self._ftp_delete_allowed():
            self.log(f'[FTP] Удаление «{name}» запрещено: '
                     'включён режим эмуляции (ftp_readonly = true)')
            return

        self._ftp_delete_target = (name, size)
        self.modal = 'confirm_ftp_delete'
        self.app.layout.focus(self.modal_window)
        self.invalidate()

    def _ftp_delete_modal_text(self) -> FormattedText:
        """Содержимое модалки подтверждения удаления."""
        if not self._ftp_delete_target:
            return FormattedText([('', '')])
        name, size = self._ftp_delete_target
        sz = human_size(size) if size else '?'
        folder = self.ftp_folder or '—'
        base = self.config.get('ftp_path', '/') or '/'
        host = self.config.get('ftp_host', '') or '—'
        frags = [
            ('', '  Удалить файл на сервере?\n'),
            ('', '\n'),
            ('class:cfg.label', '  Файл:      '),
            ('class:status.val', f'{name}\n'),
            ('class:cfg.label', '  Размер:    '),
            ('class:dim', f'{sz}\n'),
            ('class:cfg.label', '  Папка:     '),
            ('class:status.val', f'{base.rstrip("/")}/{folder}\n'),
            ('class:cfg.label', '  Сервер:    '),
            ('class:dim', f'{host}\n'),
            ('', '\n'),
            ('class:status.err',
             '  Действие необратимо.\n'),
            ('class:dim',
             '  Enter / Y — удалить    Esc / N — отмена\n'),
        ]
        return FormattedText(frags)

    def _confirm_ftp_delete(self):
        if not self._ftp_delete_target:
            self._close_modal()
            return
        name, _ = self._ftp_delete_target
        folder = self.ftp_folder

        # Ещё раз проверяем режим — конфиг могли изменить в F10.
        if not self._ftp_delete_allowed():
            self.log(f'[FTP] Удаление «{name}» запрещено: '
                     'включён режим эмуляции')
            self._ftp_delete_target = None
            self._close_modal()
            return

        host = self.config.get('ftp_host', '')
        port = int(self.config.get('ftp_port', 21))
        user = self.config.get('ftp_user', '')
        password = self.config.get('ftp_password', '')
        base = self.config.get('ftp_path', '/') or '/'

        self._ftp_delete_target = None
        self._close_modal()
        self.log(f'[FTP] Удаляю {folder}/{name}...')

        t = threading.Thread(
            target=self._ftp_delete_worker,
            args=(host, port, user, password, base, folder, name),
            daemon=True,
        )
        t.start()

    def _ftp_delete_worker(self, host, port, user, password,
                           base, folder, filename):
        try:
            delete_file(host, port, user, password, base, folder, filename)
            err = ''
        except Exception as e:
            err = str(e)
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(
            self._ftp_delete_done, folder, filename, err)

    def _ftp_delete_done(self, folder, filename, err):
        if err:
            self.log(f'[FTP] Ошибка удаления {filename}: {err}')
        else:
            self.log(f'[FTP] Удалён: {folder}/{filename}')
        # Обновляем содержимое текущей папки.
        if folder == self.ftp_folder:
            self._ftp_load(folder)
        self.invalidate()

    # ---------- tabs ----------
    def switch_tab(self, name: str):
        if name not in ('files', 'ftp'):
            return
        if self.active_tab == name:
            return
        self.active_tab = name

        if name == 'ftp':
            if self.ftp_follow_files:
                local = (self.path_input.text or '').strip()
                if local:
                    self._ftp_follow_from_files(local)
            try:
                self.app.layout.focus(self.ftp_path_input.window)
            except Exception:
                pass
        else:
            try:
                self.app.layout.focus(self.tree_window)
            except Exception:
                pass
        self.invalidate()

    # ---------- rendering ----------
    def _render_ftp(self) -> FormattedText:
        frags: list = []
        if self.ftp_loading:
            frags.append(('class:dim', '  Подключение к серверу...\n'))
            return FormattedText(frags)

        if self.ftp_error:
            frags.append(('class:status.err',
                          '  ' + self.ftp_error + '\n'))
            frags.append(('class:dim',
                          '  Введите путь и нажмите Enter\n'))
            return FormattedText(frags)

        if not self.ftp_connected:
            frags.append(('class:dim',
                          '  Укажите директорию на сервере '
                          '(ГГГГ-ММ-ДД_Место) и нажмите Enter.\n'))
            return FormattedText(frags)

        if not self.ftp_entries:
            frags.append(('class:dim', '  (папка пуста)\n'))
            return FormattedText(frags)

        allow_delete = self._ftp_delete_allowed()

        for i, (name, is_dir, size) in enumerate(self.ftp_entries):
            selected = (i == self.ftp_selected)
            if is_dir:
                style = 'class:tree.dir' + (
                    ' class:tree.sel' if selected else '')
                frags.append((style, f'  {name}/',
                              self._click_ftp_row(i)))
                frags.append(('', '\n'))
            else:
                style = 'class:tree.file' + (
                    ' class:tree.sel' if selected else '')
                sz = human_size(size) if size else ''
                frags.append((style, f'  {name}',
                              self._click_ftp_row(i)))
                if sz:
                    frags.append(('class:dim', f'  {sz}'))
                if allow_delete:
                    frags.append(('', '  '))
                    frags.append((
                        'class:btn.del', '[✕]',
                        self._click_ftp_delete(name, size),
                    ))
                frags.append(('', '\n'))
        return FormattedText(frags)

    def _click_ftp_row(self, i: int):
        def handler(event: MouseEvent):
            if event.event_type != MouseEventType.MOUSE_UP:
                return
            if self.modal is not None:
                return
            self.ftp_selected = i
            self.app.layout.focus(self.ftp_list_window)
            self.app.invalidate()
        return handler

    def _click_ftp_delete(self, name: str, size: int):
        def handler(event: MouseEvent):
            if event.event_type != MouseEventType.MOUSE_UP:
                return
            if self.modal is not None:
                return
            # Выделяем строку этого файла и открываем модалку.
            for i, (n, is_d, _) in enumerate(self.ftp_entries):
                if n == name and not is_d:
                    self.ftp_selected = i
                    break
            self.open_ftp_delete_modal()
        return handler

    def _click_tab(self, name: str):
        def handler(event: MouseEvent):
            if event.event_type != MouseEventType.MOUSE_UP:
                return
            if self.modal is not None:
                return
            self.switch_tab(name)
        return handler
