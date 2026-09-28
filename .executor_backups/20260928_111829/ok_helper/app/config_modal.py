"""ConfigModalMixin: модалка F10 — редактор конфига."""

from pathlib import Path

from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    ConditionalContainer, Float, HSplit, Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Frame, TextArea

from config import config_path, save_config


_CONFIG_LABEL_WIDTH = 26


def _cfg_label(name: str) -> str:
    return name.ljust(_CONFIG_LABEL_WIDTH) + '= '


class ConfigModalMixin:
    def _build_config_modal(self):
        # --- основные поля ---
        self.config_root_input = TextArea(
            height=1, prompt=_cfg_label('Корневая папка'),
            multiline=False, accept_handler=self._save_config_modal,
        )
        self.config_dl_input = TextArea(
            height=1, prompt=_cfg_label('Папка загрузок'),
            multiline=False, accept_handler=self._save_config_modal,
        )
        self._override_tab(self.config_root_input, with_arrows=True)
        self._override_tab(self.config_dl_input, with_arrows=True)

        # --- FTP-поля ---
        self.config_ftp_host_input = TextArea(
            height=1, prompt=_cfg_label('FTP хост'),
            multiline=False, accept_handler=self._save_config_modal,
        )
        self.config_ftp_port_input = TextArea(
            height=1, prompt=_cfg_label('FTP порт'),
            multiline=False, accept_handler=self._save_config_modal,
        )
        self.config_ftp_user_input = TextArea(
            height=1, prompt=_cfg_label('FTP логин'),
            multiline=False, accept_handler=self._save_config_modal,
        )
        self.config_ftp_pass_input = TextArea(
            height=1, prompt=_cfg_label('FTP пароль'),
            multiline=False, password=True,
            accept_handler=self._save_config_modal,
        )
        self.config_ftp_path_input = TextArea(
            height=1, prompt=_cfg_label('FTP путь'),
            multiline=False, accept_handler=self._save_config_modal,
        )
        for ta in (self.config_ftp_host_input, self.config_ftp_port_input,
                   self.config_ftp_user_input, self.config_ftp_pass_input,
                   self.config_ftp_path_input):
            self._override_tab(ta, with_arrows=True)

        # --- тумблеры ---
        self.config_watch_state = False
        self.config_theme_state = 'auto'

        self.config_watch_window = self._build_toggle_window(
            label=_cfg_label('Следить за загрузками'),
            get_state=lambda: '[x]' if self.config_watch_state else '[ ]',
            on_toggle=self._toggle_watch_state,
        )
        self.config_theme_window = self._build_toggle_window(
            label=_cfg_label('Тема интерфейса'),
            get_state=lambda: self.config_theme_state,
            on_toggle=self._cycle_theme,
        )

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
                 '  Enter — сохранить и применить,  Esc — отмена,  '
                 'Tab/↑/↓ — между полями,  Пробел — переключить\n'),
            ])),
            height=2,
        )

        body = HSplit([
            header,
            self.config_root_input,
            self.config_dl_input,
            self.config_watch_window,
            self.config_theme_window,
            Window(FormattedTextControl(text=lambda: FormattedText([
                ('class:dim', '\n')
            ])), height=1),
            self.config_ftp_host_input,
            self.config_ftp_port_input,
            self.config_ftp_user_input,
            self.config_ftp_pass_input,
            self.config_ftp_path_input,
            footer,
        ])

        self._config_float = Float(
            content=ConditionalContainer(
                content=Frame(body,
                              title=' ▶ Настройки ok-helper-tui — F10 '),
                filter=Condition(lambda: self.modal == 'edit_config'),
            ),
            top=3, left=6, width=88, height=18,
        )

    def _build_toggle_window(self, label: str, get_state, on_toggle):
        cursor_x = len(label)

        def render() -> FormattedText:
            return FormattedText([
                ('class:cfg.label', label),
                ('class:cfg.path', get_state()),
                ('class:cfg.hint', '   (Пробел — переключить)'),
            ])

        kb = KeyBindings()

        @kb.add('space')
        def _(event):
            on_toggle()
            event.app.invalidate()

        @kb.add('enter')
        def _(event):
            self._save_config_modal()
            event.app.invalidate()

        @kb.add('escape')
        def _(event):
            self._cancel_config_modal()
            event.app.invalidate()

        @kb.add('tab')
        @kb.add('c-i')
        def _(event):
            self._handle_tab(reverse=False)
            event.app.invalidate()

        @kb.add('s-tab')
        def _(event):
            self._handle_tab(reverse=True)
            event.app.invalidate()

        @kb.add('up')
        def _(event):
            if self.modal is None:
                return NotImplemented
            self._modal_focus_next(reverse=True)
            event.app.invalidate()

        @kb.add('down')
        def _(event):
            if self.modal is None:
                return NotImplemented
            self._modal_focus_next(reverse=False)
            event.app.invalidate()

        control = FormattedTextControl(
            text=render, focusable=True, key_bindings=kb,
            get_cursor_position=lambda: Point(x=cursor_x, y=0),
        )
        return Window(control, height=1)

    # ---------- toggles ----------
    def _toggle_watch_state(self):
        self.config_watch_state = not self.config_watch_state

    def _cycle_theme(self):
        order = ['auto', 'dark', 'light']
        idx = order.index(self.config_theme_state)
        self.config_theme_state = order[(idx + 1) % len(order)]
        self._apply_theme(self.config_theme_state)

    # ---------- open / save / cancel ----------
    def open_config_modal(self):
        self.config_root_input.text = self.config.get('root_dir', '~')
        self.config_root_input.cursor_position = len(self.config_root_input.text)
        self.config_dl_input.text = self.config.get('downloads_dir', '~/Downloads')
        self.config_dl_input.cursor_position = len(self.config_dl_input.text)

        self.config_ftp_host_input.text = str(self.config.get('ftp_host', ''))
        self.config_ftp_port_input.text = str(self.config.get('ftp_port', 21))
        self.config_ftp_user_input.text = str(self.config.get('ftp_user', ''))
        self.config_ftp_pass_input.text = str(self.config.get('ftp_password', ''))
        self.config_ftp_path_input.text = str(self.config.get('ftp_path', '/'))
        for ta in (self.config_ftp_host_input, self.config_ftp_port_input,
                   self.config_ftp_user_input, self.config_ftp_pass_input,
                   self.config_ftp_path_input):
            ta.cursor_position = len(ta.text)

        self.config_watch_state = bool(self.config.get('watch_downloads', False))
        self.config_theme_state = self.config.get('theme', 'auto')
        self._theme_setting_orig = self.config.get('theme', 'auto')
        self.modal = 'edit_config'
        self.app.layout.focus(self.config_root_input)
        self.invalidate()

    def _cancel_config_modal(self):
        if self._theme_setting_orig is not None:
            self._apply_theme(self._theme_setting_orig)
            self._theme_setting_orig = None
        self._close_modal()
        self.log('[НАСТР] Изменения отменены')

    def _save_config_modal(self, buffer=None):
        new_root = self.config_root_input.text.strip()
        new_dl = self.config_dl_input.text.strip()
        new_watch = bool(self.config_watch_state)
        new_theme = self.config_theme_state

        new_ftp_host = self.config_ftp_host_input.text.strip()
        new_ftp_port_s = self.config_ftp_port_input.text.strip()
        new_ftp_user = self.config_ftp_user_input.text.strip()
        new_ftp_pass = self.config_ftp_pass_input.text
        new_ftp_path = self.config_ftp_path_input.text.strip() or '/'

        root_path = Path(new_root).expanduser()
        if not new_root or not root_path.is_dir():
            self.log(f'[НАСТР] root_dir не существует: {root_path}')
            return
        dl_path = Path(new_dl).expanduser()
        if not new_dl or not dl_path.is_dir():
            self.log(f'[НАСТР] downloads_dir не существует: {dl_path}')
            return

        if new_ftp_host:
            try:
                new_ftp_port = int(new_ftp_port_s)
                if not (1 <= new_ftp_port <= 65535):
                    raise ValueError
            except ValueError:
                self.log(f'[НАСТР] Некорректный FTP порт: {new_ftp_port_s}')
                return
        else:
            try:
                new_ftp_port = int(new_ftp_port_s or 21)
            except ValueError:
                new_ftp_port = 21

        self.config['root_dir'] = new_root
        self.config['downloads_dir'] = new_dl
        self.config['watch_downloads'] = new_watch
        self.config['theme'] = new_theme
        self.config['ftp_host'] = new_ftp_host
        self.config['ftp_port'] = new_ftp_port
        self.config['ftp_user'] = new_ftp_user
        self.config['ftp_password'] = new_ftp_pass
        self.config['ftp_path'] = new_ftp_path
        self.config['root_dir_resolved'] = root_path.resolve()
        self.config['downloads_dir_resolved'] = dl_path.resolve()
        save_config(self.config)
        self.log(f'[НАСТР] Сохранено: {config_path()}')

        self._apply_theme(new_theme)
        self._theme_setting_orig = None

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
