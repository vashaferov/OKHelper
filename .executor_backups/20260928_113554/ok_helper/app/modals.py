"""ModalsMixin: help / confirm_fix_all / move_download / edit_name."""

from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea

from ..analyzer import analyze_file


class ModalsMixin:
    def _init_modals(self):
        self._build_common_modals()
        self._build_edit_name_modal()
        self._build_config_modal()

    # ---------- help / confirm / move ----------
    def _build_common_modals(self):
        self.modal_control = FormattedTextControl(
            text=self._modal_text,
            focusable=True,
            key_bindings=self._modal_kb(),
        )
        self.modal_window = Window(self.modal_control)

        # Центрированный float поверх всего интерфейса
        self._modal_float = self._make_modal_float(
            body=self.modal_window,
            title=self._modal_title,
            cond=Condition(
                lambda: self.modal in
                ('help', 'confirm_fix_all', 'move_download')),
            width=86, height=24,
        )

    # ---------- edit_name ----------
    def _build_edit_name_modal(self):
        self.edit_input = TextArea(
            height=1, prompt='Новое: ', multiline=False,
            accept_handler=self._apply_edit_modal,
        )
        self._override_tab(self.edit_input)

        self.edit_preview_window = Window(
            FormattedTextControl(text=self._edit_preview_text), height=2,
        )

        body = HSplit([
            self.edit_preview_window,
            self.edit_input,
            Window(FormattedTextControl(text=lambda: FormattedText([
                ('class:dim',
                 '  Enter — применить,  Esc — отмена')
            ])), height=1),
        ])

        self._edit_float = self._make_modal_float(
            body=body,
            title=' ▶ Переименование — F7 ',
            cond=Condition(lambda: self.modal == 'edit_name'),
            width=86, height=7,
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
