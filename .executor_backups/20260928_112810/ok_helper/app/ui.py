"""UIMixin: сборка layout, Application, глобальные клавиши."""

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    FloatContainer, HSplit, VSplit, Window, Layout,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.styles import DynamicStyle

from ..theme import build_style


class UIMixin:
    def _init_layout(self):
        left = HSplit([
            self._titled('Журнал', self.log_window, 'log'),
            self._titled('Транслит — Enter', self.translit_input, 'translit'),
        ])
        right = HSplit([
            self._titled('Директория — Enter', self.path_input, 'path'),
            self._titled('Файлы — F1 справка, [Правка]/[⇪] клик',
                         self.tree_window, 'tree'),
        ], width=D(min=40, preferred=64, max=110))

        self.status_window = Window(
            FormattedTextControl(text=self._status_frags),
            height=1,
        )

        body = HSplit([VSplit([left, right], padding=1), self.status_window])
        self._root_container = FloatContainer(
            content=body,
            floats=[
                self._modal_float,
                self._edit_float,
                self._config_float,
                self._upload_float,
            ],
        )

    def _init_application(self):
        self._theme_setting = self.config.get('theme', 'auto')
        self._current_style = build_style(self._theme_setting)
        self._current_style_dimmed = build_style(self._theme_setting, dimmed=True)

        self.app = Application(
            layout=Layout(self._root_container,
                          focused_element=self.translit_input),
            full_screen=True,
            mouse_support=True,
            key_bindings=self._build_global_kb(),
            # DynamicStyle вызывает _dynamic_style при каждой отрисовке —
            # при открытии/закрытии модалки палитра переключается на
            # dim-версию или обратно.
            style=DynamicStyle(self._dynamic_style),
        )

    def _build_global_kb(self) -> KeyBindings:
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
            from ..models import FilterMode
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
            from ..models import SortMode
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

        @kb.add('f12')
        def _(event):
            if self.modal is None:
                self.open_upload_modal()
            event.app.invalidate()

        @kb.add('c-z')
        def _(event):
            self.undo()
            event.app.invalidate()

        return kb
