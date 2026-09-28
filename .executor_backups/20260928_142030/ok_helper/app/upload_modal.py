"""UploadMixin: модалка загрузки файла на FTP (F12 / кнопка [⇪])."""

import threading
from pathlib import Path
from typing import Optional, Tuple

from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea

from ..analyzer import human_size
from ..ftp import (
    find_target_folder, is_uploadable, upload_extensions_hint,
    upload_file, validate_folder_name,
)
from ..translit import transliterate


_FTP_LABEL_WIDTH = 26


def _ftp_label(name: str) -> str:
    return name.ljust(_FTP_LABEL_WIDTH) + '= '


class UploadMixin:
    # ---------- init ----------
    def _build_upload_modal(self):
        self._upload_target: Optional[Path] = None
        self._upload_status: Tuple[str, str] = ('', '')

        self.upload_name_input = TextArea(
            height=1,
            prompt=_ftp_label('Папка'),
            multiline=False,
            accept_handler=self._start_upload,
            style='class:modal.bg',
        )
        self._style_textarea_for_modal(self.upload_name_input)
        self._override_tab(self.upload_name_input)
        self._override_upload_keys()

        self.upload_header_window = Window(
            FormattedTextControl(text=self._upload_header_text),
            height=5, char=' ', style='class:modal.bg',
        )
        self.upload_status_window = Window(
            FormattedTextControl(text=self._upload_status_text),
            height=1, char=' ', style='class:modal.bg',
        )
        self.upload_hint_window = Window(
            FormattedTextControl(text=self._upload_hint_text),
            height=1, char=' ', style='class:modal.bg',
        )

        # content_height = 5 + 1 + 1 + 1 = 8; + 4 служебные = 12.
        body = HSplit([
            self.upload_header_window,
            self.upload_name_input,
            self.upload_status_window,
            self.upload_hint_window,
        ], style='class:modal.bg')

        self._upload_float = self._make_modal_float(
            body=body,
            title=' ▶ Загрузка на FTP — F12 ',
            cond=Condition(lambda: self.modal == 'upload'),
            width=86, height=12,
        )

    def _override_upload_keys(self):
        custom = KeyBindings()

        @custom.add('c-t')
        def _(event):
            text = self.upload_name_input.text
            new = transliterate(text)
            self.upload_name_input.text = new
            self.upload_name_input.cursor_position = len(new)
            self._upload_status = ('class:dim', '  Транслитерировано')
            event.app.invalidate()

        old = self.upload_name_input.control.key_bindings
        self.upload_name_input.control.key_bindings = (
            merge_key_bindings([custom, old]) if old else custom
        )

    # ---------- render ----------
    def _upload_header_text(self) -> FormattedText:
        if self._upload_target is None:
            return FormattedText([('', '')])
        p = self._upload_target
        try:
            size = human_size(p.stat().st_size)
        except OSError:
            size = '?'
        base = self.config.get('ftp_path', '/') or '/'
        host = self.config.get('ftp_host', '') or '—'
        readonly = bool(self.config.get('ftp_readonly', False))

        frags = [
            ('class:cfg.label', '  Файл:      '),
            ('class:cfg.path', f'{p.name}\n'),
            ('class:cfg.label', '  Размер:    '),
            ('class:cfg.path', f'{size}\n'),
            ('class:cfg.label', '  Сервер:    '),
            ('class:cfg.path', f'{host}  ({base})'),
        ]
        if readonly:
            frags.append(('class:status.sugg', '   [ЭМУЛЯЦИЯ]'))
        frags.extend([
            ('', '\n'),
            ('class:cfg.label', '  Источник:  '),
            ('class:dim', f'{p.parent}\n'),
        ])
        return FormattedText(frags)

    def _upload_status_text(self) -> FormattedText:
        style, text = self._upload_status
        if not text:
            return FormattedText([('', '')])
        return FormattedText([(style, text)])

    def _upload_hint_text(self) -> FormattedText:
        readonly = bool(self.config.get('ftp_readonly', False))
        verb = 'эмулировать загрузку' if readonly else 'загрузить'
        return FormattedText([
            ('class:cfg.hint',
             f'  Enter — {verb},  Esc — отмена,  Ctrl+T — транслит\n'),
        ])

    # ---------- open / close ----------
    def open_upload_modal(self):
        if not self.tree.entries:
            self.log('[FTP] Ничего не выделено')
            return
        path, _ = self.tree.entries[self.tree.selected]
        if not path.is_file():
            self.log(f'[FTP] Не файл: {path.name}')
            return

        # --- политика: только .plt / .wpt / .gpx ---
        if not is_uploadable(path):
            self.log(f'[FTP] Нельзя отправить {path.name} — '
                     f'разрешены только {upload_extensions_hint()}')
            return

        if not self.config.get('ftp_host') or not self.config.get('ftp_user'):
            self.log('[FTP] Задайте ftp_host и ftp_user в настройках (F10)')
            return

        self._upload_target = path
        self._upload_status = ('', '')

        folder, found = find_target_folder(path.parent)
        self.upload_name_input.text = folder
        self.upload_name_input.cursor_position = len(folder)

        readonly = bool(self.config.get('ftp_readonly', False))
        if found:
            note = '  Папка определена автоматически'
            if readonly:
                note += '; режим эмуляции'
            self._upload_status = ('class:dim', note)
        else:
            self._upload_status = (
                'class:status.err',
                '  Папка не найдена; введите ГГГГ-ММ-ДД_Место',
            )

        self.modal = 'upload'
        self.app.layout.focus(self.upload_name_input)
        self.invalidate()

    def _close_upload_modal(self):
        self._upload_target = None
        self._upload_status = ('', '')
        self.modal = None
        self.app.layout.focus(self.tree_window)
        self.invalidate()

    # ---------- upload ----------
    def _start_upload(self, buffer=None):
        if self._upload_target is None:
            self._close_upload_modal()
            return

        # Защита от обхода через Enter (если модалка как-то открылась
        # на нештатном файле — например, из-за будущих правок кода).
        if not is_uploadable(self._upload_target):
            self._upload_status = (
                'class:status.err',
                f'  Разрешены только {upload_extensions_hint()}',
            )
            self.invalidate()
            return

        name = self.upload_name_input.text.strip()
        ok, reason = validate_folder_name(name)
        if not ok:
            self._upload_status = ('class:status.err', f'  {reason}')
            self.invalidate()
            return

        src = self._upload_target
        host = self.config.get('ftp_host', '')
        port = int(self.config.get('ftp_port', 21))
        user = self.config.get('ftp_user', '')
        password = self.config.get('ftp_password', '')
        base = self.config.get('ftp_path', '/') or '/'
        readonly = bool(self.config.get('ftp_readonly', False))

        self._close_upload_modal()
        if readonly:
            self.log(f'[FTP] [эмуляция] {src.name} → {base}/{name}/')
        else:
            self.log(f'[FTP] Начинаю загрузку {src.name} → {base}/{name}/')

        t = threading.Thread(
            target=self._upload_worker,
            args=(host, port, user, password, base, name, src, readonly),
            daemon=True,
        )
        t.start()

    def _upload_worker(self, host, port, user, password,
                       base, folder, src, readonly):
        def _cb(msg: str):
            if self.loop is not None:
                self.loop.call_soon_threadsafe(self.log, msg)
        try:
            upload_file(host, port, user, password, base, folder, src, _cb,
                        readonly=readonly)
            if self.loop is not None:
                if readonly:
                    final = (f'[FTP] [эмуляция] {folder}/{src.name} — '
                             f'имитация завершена')
                else:
                    final = f'[FTP] Успешно: {folder}/{src.name}'
                self.loop.call_soon_threadsafe(self.log, final)
        except Exception as e:
            if self.loop is not None:
                self.loop.call_soon_threadsafe(
                    self.log, f'[FTP] Ошибка: {e}')
