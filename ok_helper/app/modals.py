"""ModalsMixin: help / confirm_fix_all / move_download / edit_name / new_folder.

Модалка confirm_ftp_delete живёт в FtpTabMixin — там же, где вся
логика вкладки FTP. Модалки help/confirm/move/edit_name/new_folder —
здесь.
"""

from pathlib import Path

from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea

from ..analyzer import analyze_file, validate_new_folder_name
from ..translit import transliterate


class ModalsMixin:
    def _init_modals(self):
        self._build_common_modals()
        self._build_edit_name_modal()
        self._build_new_folder_modal()
        self._build_config_modal()

    # ---------- help / confirm / move ----------
    def _build_common_modals(self):
        self.modal_control = FormattedTextControl(
            text=self._modal_text,
            focusable=True,
            key_bindings=self._modal_kb(),
        )
        self.modal_window = Window(
            self.modal_control, char=' ', style='class:modal.bg',
        )

        self._modal_float = self._make_modal_float(
            body=self.modal_window,
            title=self._modal_title,
            cond=Condition(
                lambda: self.modal in
                ('help', 'confirm_fix_all', 'move_download',
                 'confirm_ftp_delete')),
            width=86, height=24,
        )

    # ---------- edit_name ----------
    def _build_edit_name_modal(self):
        self.edit_input = TextArea(
            height=1, prompt='Новое: ', multiline=False,
            accept_handler=self._apply_edit_modal,
            style='class:modal.bg',
        )
        self._style_textarea_for_modal(self.edit_input)
        self._override_tab(self.edit_input)
        self._override_translit_keys(self.edit_input)

        self.edit_preview_window = Window(
            FormattedTextControl(text=self._edit_preview_text),
            height=2, char=' ', style='class:modal.bg',
        )

        body = HSplit([
            self.edit_preview_window,
            self.edit_input,
            Window(
                FormattedTextControl(text=lambda: FormattedText([
                    ('class:dim',
                     '  Enter — применить,  Esc — отмена,  '
                     'Ctrl+T — транслит')
                ])),
                height=1, char=' ', style='class:modal.bg',
            ),
        ], style='class:modal.bg')

        self._edit_float = self._make_modal_float(
            body=body,
            title=' ▶ Переименование — F7 ',
            cond=Condition(lambda: self.modal == 'edit_name'),
            width=86, height=8,
        )

    def _override_translit_keys(self, ta: TextArea):
        """Ctrl+T на TextArea — транслит содержимого в латиницу."""
        custom = KeyBindings()

        @custom.add('c-t')
        def _(event):
            text = ta.text
            new = transliterate(text)
            ta.text = new
            ta.cursor_position = len(new)
            event.app.invalidate()

        old = ta.control.key_bindings
        ta.control.key_bindings = (
            merge_key_bindings([custom, old]) if old else custom
        )

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

    # ---------- new_folder ----------
    def _build_new_folder_modal(self):
        self.new_folder_input = TextArea(
            height=1, prompt='Имя: ', multiline=False,
            accept_handler=self._apply_new_folder_modal,
            style='class:modal.bg',
        )
        self._style_textarea_for_modal(self.new_folder_input)
        self._override_tab(self.new_folder_input)
        self._override_translit_keys(self.new_folder_input)

        self.new_folder_preview_window = Window(
            FormattedTextControl(text=self._new_folder_preview_text),
            height=3, char=' ', style='class:modal.bg',
        )

        body = HSplit([
            self.new_folder_preview_window,
            self.new_folder_input,
            Window(
                FormattedTextControl(text=lambda: FormattedText([
                    ('class:dim',
                     '  Enter — создать,  Esc — отмена,  '
                     'Ctrl+T — транслит')
                ])),
                height=1, char=' ', style='class:modal.bg',
            ),
        ], style='class:modal.bg')

        # content = 3 + 1 + 1 = 5; + 4 служебные = 9
        self._new_folder_float = self._make_modal_float(
            body=body,
            title=' ▶ Новая папка — Ctrl+N ',
            cond=Condition(lambda: self.modal == 'new_folder'),
            width=86, height=9,
        )

    def _new_folder_preview_text(self) -> FormattedText:
        base = getattr(self, '_new_folder_base', None)
        if base is None:
            return FormattedText([('', '')])
        return FormattedText([
            ('class:dim', '  Где:  '),
            ('class:cfg.path', f'{base}\n'),
            ('class:dim', '  Папка создаётся только локально.\n'),
            ('class:dim',
             '  На FTP она появится автоматически при загрузке в неё файла.\n'),
        ])

    def open_new_folder_modal(self):
        """Открывает модалку создания новой папки.

        Папка создаётся в текущей директории вкладки «Файлы»
        (то, что показано в поле «Путь:»). На FTP ничего не
        создаётся — там папка появится автоматически при загрузке
        в неё файла через F12.
        """
        if self.modal is not None:
            return
        if getattr(self, 'active_tab', 'files') != 'files':
            return

        base_dir = (self.path_input.text or '').strip()
        if not base_dir:
            self.log('[i] Не задана текущая директория')
            return
        base = Path(base_dir).expanduser()
        if not base.is_dir():
            self.log(f'[ОШБ] Не директория: {base}')
            return

        self._new_folder_base = base
        self.new_folder_input.text = ''
        self.new_folder_input.cursor_position = 0
        self.modal = 'new_folder'
        self.app.layout.focus(self.new_folder_input)
        self.invalidate()

    def _apply_new_folder_modal(self, buffer):
        name = buffer.text.strip()
        base = getattr(self, '_new_folder_base', None)
        if base is None:
            self._close_modal()
            return
        if not name:
            self._close_modal()
            return

        ok, reason = validate_new_folder_name(name)
        if not ok:
            self.log(f'[ОШБ] {reason}')
            return

        target = base / name
        if target.exists():
            self.log(f'[ОШБ] Уже существует: {target.name}')
            return

        try:
            target.mkdir(parents=False, exist_ok=False)
            self.log(f'[OK] Создана папка: {target}')
        except OSError as e:
            self.log(f'[ОШБ] Не создать папку: {e}')
            return

        self._close_modal()
        self.tree.refresh()
        self.tree.select_by_path(target)
        self._sync_path_to_selection()
        self.invalidate()

    # ---------- move_download ----------
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
