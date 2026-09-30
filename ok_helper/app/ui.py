"""UIMixin: сборка layout, Application, глобальные клавиши."""

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    DynamicContainer, FloatContainer, HSplit, VSplit, Window, Layout,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.styles import DynamicStyle
from prompt_toolkit.widgets import Frame

from ..theme import build_style


class UIMixin:
    # ---------- layout ----------
    def _init_layout(self):
        # Левая колонка — журнал.
        left = HSplit([
            self._titled('Журнал', self.log_window, 'log'),
        ])

        # --- вкладка «Файлы» ---
        files_content = HSplit([
            self._titled('Директория — Enter', self.path_input, 'path'),
            Frame(self.tree_window, title=self._files_title),
        ])

        # --- вкладка «FTP» ---
        ftp_content = HSplit([
            Frame(self.ftp_top_window, title=self._ftp_top_title),
            Frame(self.ftp_list_window, title=self._ftp_list_title),
        ])

        self._tab_contents = {
            'files': files_content,
            'ftp': ftp_content,
        }
        self._tab_body = DynamicContainer(
            lambda: self._tab_contents[self.active_tab])

        right = HSplit([
            self._tabs_bar(),
            self._tab_body,
        ], width=D(min=40, preferred=64, max=110))

        self.status_window = Window(
            FormattedTextControl(text=self._status_frags), height=1,
        )

        body = HSplit([
            VSplit([left, right], padding=1),
            self.status_window,
        ])
        self._root_container = FloatContainer(
            content=body,
            floats=[
                self._modal_float,
                self._edit_float,
                self._config_float,
                self._upload_float,
            ],
        )

    # ---------- titles ----------
    def _files_title(self):
        return [('class:title',
                 ' Файлы — F1 справка, [Правка]/[⇪] клик ')]

    def _ftp_top_title(self):
        return [('class:title',
                 ' Директория (FTP) — Enter / Пробел ')]

    def _ftp_list_title(self):
        folder = (self.ftp_path_input.text or '').strip() or '—'
        if self.ftp_loading:
            text = f' FTP — {folder} (загрузка…) '
        elif self.ftp_connected:
            text = f' FTP — {folder} '
        else:
            text = ' FTP — не подключено '
        return [('class:title', text)]

    # ---------- tab bar ----------
    def _tabs_bar(self) -> Window:
        def render():
            active = getattr(self, 'active_tab', 'files')
            files_style = ('class:tab.active' if active == 'files'
                           else 'class:tab.inactive')
            ftp_style = ('class:tab.active' if active == 'ftp'
                         else 'class:tab.inactive')
            return [
                ('', ' '),
                (files_style, ' Файлы ', self._click_tab('files')),
                ('', '  '),
                (ftp_style, ' FTP ', self._click_tab('ftp')),
                ('', ''),
            ]
        return Window(FormattedTextControl(render), height=1)

    # ---------- application ----------
    def _init_application(self):
        self._theme_setting = self.config.get('theme', 'auto')
        self._current_style = build_style(self._theme_setting)

        self.app = Application(
            layout=Layout(self._root_container,
                          focused_element=self.path_input),
            full_screen=True,
            mouse_support=True,
            key_bindings=self._build_global_kb(),
            style=DynamicStyle(lambda: self._current_style),
        )

    # ---------- global keys ----------
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

        @kb.add('c-right')
        @kb.add('c-left')
        def _(event):
            other = 'ftp' if self.active_tab == 'files' else 'files'
            self.switch_tab(other)
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
            if self.active_tab == 'ftp':
                folder = (self.ftp_path_input.text or '').strip()
                if folder:
                    self._ftp_load(folder)
                    self.log(f'[FTP] Обновление папки {folder}')
            else:
                self.scan_dir(self.watch_dir)
                self.tree.refresh()
                self.log('[i] Пересканировано')
            event.app.invalidate()

        @kb.add('f7')
        def _(event):
            if self.active_tab == 'files':
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
            if self.modal is None and self.active_tab == 'files':
                self.open_upload_modal()
            event.app.invalidate()

        @kb.add('c-z')
        def _(event):
            self.undo()
            event.app.invalidate()

        return kb