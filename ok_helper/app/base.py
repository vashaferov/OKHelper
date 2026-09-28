"""AppBase: состояние, журнал, фокус, Tab, общие модалки, тема."""

import re
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import (
    ConditionalContainer, Float, HSplit, VSplit, Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.widgets import Frame, TextArea

from config import config_path
from ..models import FileTree


_LOG_TAG_RE = re.compile(r'^(\[[^\]]+\])\s*')

_LOG_LEVEL_BY_TAG = {
    'i': 'info', '+': 'ok', '!': 'warn',
    'OK': 'ok',
    'ОШБ': 'error', 'ERR': 'error',
    'КАТАЛОГ': 'dir', 'DIR': 'dir',
    'ЗАГР': 'dl', 'DL': 'dl',
    'НАСТР': 'cfg', 'CFG': 'cfg', 'КОНФИГ': 'cfg', 'CONFIG': 'cfg',
    'FTP': 'cfg',
    'ПЕРЕНОС': 'move', 'MOVE': 'move',
    'ОТКР': 'open', 'OPEN': 'open',
    'ОТМЕНА': 'undo', 'UNDO': 'undo',
    'ТРАНСЛИТ': 'translit',
}


class AppBase:
    MAX_LOG = 1000
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
        '  F11  Очистить журнал\n'
        '  F12  Загрузить выделенный файл на FTP\n'
        ' ^Z    Отменить последнее переименование\n'
        ' ^C    Выход (или ^Q)\n'
        '\n'
        ' Журнал:\n'
        '   Прокрутка — колесо мыши, PageUp / PageDown, Home / End\n'
        '\n'
        ' Конфиг (F10):\n'
        '   root_dir / downloads_dir / watch_downloads / theme\n'
        '   ftp_host / ftp_port / ftp_user / ftp_password / ftp_path\n'
        '   ftp_readonly — режим эмуляции: подключение и чтение реальны,\n'
        '                  изменения (mkdir, upload) не выполняются\n'
        '   Файл: ' + str(config_path()) + '\n'
        '\n'
        ' Проверка имён файлов (общая):\n'
        '   • .gpx и .plt — формат ГГГГММДД_Позывной\n'
        '     (для скачанных — дата в начале, остаток в позывной);\n'
        '   • <1-4 цифры>m.gpx — исключение, валидация не проводится;\n'
        '   • .wpt — только Waypoints_ГГГГММДД;\n'
        '   • остальные расширения не проверяются.\n'
        '\n'
        ' FTP (F12) — что можно отправить:\n'
        '   • .gpx — ТОЛЬКО в виде <1-4 цифры>m.gpx\n'
        '     (например, 100m.gpx или 20260917_999m.gpx).\n'
        '     Обычный ГГГГММДД_Позывной.gpx не отправляется;\n'
        '   • .plt — с корректным именем (см. «Проверка имён»);\n'
        '   • .wpt — только Waypoints_ГГГГММДД.\n'
        '   Папка назначения — строго ГГГГ-ММ-ДД_Место\n'
        '   (латиница, цифры, «_», «-»). Ищется вверх по дереву от\n'
        '   папки файла. Если не найдена — введите вручную.\n'
        '   Ctrl+T в поле — транслит введённого значения.\n'
        '   Папка создаётся на сервере автоматически.\n'
        '   Для недопустимых файлов кнопка [⇪] в дереве не\n'
        '   показывается, а F12 пишет причину в журнал.\n'
        '\n'
        ' Мониторинг загрузок (F8/F9):\n'
        '   Файл из Загрузок переносится в ТЕКУЩУЮ открытую\n'
        '   директорию (то, что показано в поле «Путь»).\n'
        '   Y / Enter — перенести,  N — пропустить,  Esc — позже\n'
    )

    # ---------- state ----------
    def _init_state(self, initial_dir, config: dict):
        self.loop = None
        self.lines: List[Tuple[str, str, str]] = []
        self.lock = threading.Lock()
        self.observer = None
        self.downloads_observer = None
        self.watch_dir = initial_dir
        self.undo_stack = deque(maxlen=self.MAX_UNDO)
        self.modal: Optional[str] = None
        self._pending_fix_list = []
        self._edit_target = None
        self.config = config
        self.pending_downloads: list = []
        self.watch_downloads = False
        self._theme_setting_orig = None
        self.tree = FileTree()
        self.tree.set_root(initial_dir)

    # ---------- inputs ----------
    def _init_inputs(self):
        self.translit_input = TextArea(
            height=1, prompt='> ', multiline=False,
            accept_handler=self.on_translit,
            history=InMemoryHistory(),
        )
        self.path_input = TextArea(
            height=1, prompt='Путь: ', multiline=False,
            text=str(self.tree.root),
            accept_handler=self.on_path_change,
            history=InMemoryHistory(),
        )
        self._override_tab(self.translit_input)
        self._override_tab(self.path_input)

    # ---------- log ----------
    def _init_log(self):
        from ..controls import LogControl
        self.log_control = LogControl(
            on_scroll=self._log_scroll,
            text=self._log_text,
            focusable=True,
            key_bindings=self._log_kb(),
        )
        self.log_window = Window(self.log_control, wrap_lines=True)

    def _level_from_msg(self, msg: str) -> str:
        m = _LOG_TAG_RE.match(msg)
        if not m:
            return 'text'
        tag = m.group(1)[1:-1].strip()
        return _LOG_LEVEL_BY_TAG.get(tag, 'info')

    def log(self, msg: str, level: Optional[str] = None):
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
            frags.append(('class:log.time', ts + '  '))
            m = _LOG_TAG_RE.match(msg)
            if m:
                tag = m.group(1)
                rest = msg[m.end():]
                frags.append((f'class:log.tag.{level}', tag.ljust(10)))
                frags.append(('class:log.msg', rest))
            else:
                frags.append(('class:log.msg', msg))
            frags.append(('', '\n'))
        if frags and frags[-1][1] == '\n':
            frags.pop()
        return FormattedText(frags)

    def _after_log_update(self):
        self._scroll_log_to_bottom()
        self.app.invalidate()

    def _scroll_log_to_bottom(self):
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
            if self.modal is None:
                try:
                    self.log_window.vertical_scroll = 0
                except Exception:
                    pass
            event.app.invalidate()

        @kb.add('end')
        def _(event):
            if self.modal is None:
                self._scroll_log_to_bottom()
            event.app.invalidate()

        return kb

    # ---------- current directory ----------
    def _current_target_dir(self) -> Path:
        """Директория, в которую будут переноситься файлы из Загрузок."""
        try:
            txt = (self.path_input.text or '').strip()
            if txt:
                p = Path(txt).expanduser()
                if p.is_dir():
                    return p.resolve()
        except (OSError, RuntimeError):
            pass
        return self.tree.root

    # ---------- focus / tab ----------
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

    # ---------- modal helpers ----------
    def _style_textarea_for_modal(self, ta: TextArea):
        """TextArea внутри модалки: закрасить фон до правого края."""
        ta.window.char = ' '
        ta.window.style = 'class:modal.bg'

    def _modal_frame(self, body, title, width: int, height: int):
        """Рамка модального окна с полностью непрозрачным фоном."""
        def _title_str() -> str:
            if callable(title):
                return title() or ''
            return title or ''

        def top_text() -> FormattedText:
            t = _title_str()
            max_t = max(0, width - 4)
            if len(t) > max_t:
                t = t[:max_t]
            dashes = max(0, width - 3 - len(t))
            return FormattedText([
                ('class:modal.border', '┌─'),
                ('class:modal.title', t),
                ('class:modal.border', '─' * dashes + '┐'),
            ])

        def bottom_text() -> FormattedText:
            return FormattedText([
                ('class:modal.border', '└' + '─' * (width - 2) + '┘'),
            ])

        top = Window(
            FormattedTextControl(text=top_text),
            height=1, style='class:modal.bg', char=' ',
        )
        bottom = Window(
            FormattedTextControl(text=bottom_text),
            height=1, style='class:modal.bg', char=' ',
        )
        left = Window(width=1, char='│', style='class:modal.border')
        right = Window(width=1, char='│', style='class:modal.border')

        body_padded = HSplit([
            Window(height=1, char=' ', style='class:modal.bg'),
            body,
            Window(height=1, char=' ', style='class:modal.bg'),
        ], style='class:modal.bg')
        body_padded = VSplit([
            Window(width=1, char=' ', style='class:modal.bg'),
            body_padded,
            Window(width=1, char=' ', style='class:modal.bg'),
        ], style='class:modal.bg')

        middle = VSplit([left, body_padded, right], style='class:modal.bg')

        inner = HSplit([top, middle, bottom], height=height,
                       style='class:modal.bg')

        return VSplit([inner], width=D.exact(width))

    def _make_modal_float(
        self,
        body,
        title,
        cond,
        width: int,
        height: int,
        z_index: int = 10,
    ) -> Float:
        """Float с модальным окном по центру экрана."""
        box = self._modal_frame(body, title, width, height)
        centered = HSplit([
            Window(height=D(weight=1)),
            VSplit([
                Window(width=D(weight=1)),
                box,
                Window(width=D(weight=1)),
            ]),
            Window(height=D(weight=1)),
        ])
        return Float(
            content=ConditionalContainer(content=centered, filter=cond),
            top=0, bottom=0, left=0, right=0,
            z_index=z_index,
            transparent=True,
        )

    def _override_tab(self, ta: TextArea, with_arrows: bool = False):
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

        @custom.add('escape', filter=Condition(lambda: self.modal is not None))
        def _(event):
            if self.modal == 'edit_config':
                self._cancel_config_modal()
            elif self.modal == 'upload':
                self._close_upload_modal()
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

    def _modal_focus_chain(self) -> list:
        if self.modal == 'edit_config':
            return [
                self.config_root_input.window,
                self.config_dl_input.window,
                self.config_watch_window,
                self.config_theme_window,
                self.config_ftp_host_input.window,
                self.config_ftp_port_input.window,
                self.config_ftp_user_input.window,
                self.config_ftp_pass_input.window,
                self.config_ftp_path_input.window,
                self.config_ftp_readonly_window,
            ]
        if self.modal == 'edit_name':
            return [self.edit_input.window]
        if self.modal == 'upload':
            return [self.upload_name_input.window]
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
        if self.modal is not None:
            self._modal_focus_next(reverse=reverse)
        else:
            if reverse:
                self.app.layout.focus_previous()
            else:
                self.app.layout.focus_next()

    # ---------- common modals ----------
    def _toggle_modal(self, name: str):
        if self.modal == name:
            self._close_modal()
        else:
            self._open_modal(name)

    def _open_modal(self, name: str):
        self.modal = name
        self.app.layout.focus(self.modal_window)
        self.invalidate()

    def _close_modal(self):
        self.modal = None
        self._pending_fix_list = []
        self._edit_target = None
        self.app.layout.focus(self.tree_window)
        self.invalidate()

    def _modal_title(self) -> str:
        if self.modal == 'help':
            return ' ▶ Справка — F1 или Esc '
        if self.modal == 'confirm_fix_all':
            return ' ▶ Подтверждение — Enter/Y, Esc/N '
        if self.modal == 'move_download':
            n = len(self.pending_downloads)
            more = f' (+{n - 1})' if n > 1 else ''
            return f' ▶ Файл из Загрузок{more} — Y/N/Esc '
        return ''

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
        """Содержимое модалки переноса файла из Загрузок."""
        from ..analyzer import human_size
        if not self.pending_downloads:
            return FormattedText([('', '')])
        src = self.pending_downloads[0]
        dst_dir = self._current_target_dir()
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
            ('', '  '),
            ('class:dim', '(текущая открытая директория)\n'),
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
        """Клавиши модалок подтверждения и переноса.

        Хоткеи n/y продублированы кириллическими эквивалентами
        физических клавиш в русской раскладке.
        """
        kb = KeyBindings()

        @kb.add('escape')
        def _(event):
            self._close_modal()
            event.app.invalidate()

        @kb.add('n')
        @kb.add('N')
        @kb.add('т')
        @kb.add('Т')
        def _(event):
            if self.modal == 'move_download':
                self.reject_move()
            else:
                self._close_modal()
            event.app.invalidate()

        @kb.add('enter')
        @kb.add('y')
        @kb.add('Y')
        @kb.add('н')
        @kb.add('Н')
        def _(event):
            if self.modal == 'confirm_fix_all':
                self._confirm_fix_all()
            elif self.modal == 'move_download':
                self.accept_move()
            else:
                self._close_modal()
            event.app.invalidate()

        return kb

    # ---------- theme ----------
    def _apply_theme(self, theme: str):
        from ..theme import build_style
        self._theme_setting = theme if theme in ('auto', 'dark', 'light') else 'auto'
        self._current_style = build_style(self._theme_setting)
        self.invalidate()

    # ---------- invalidate ----------
    def invalidate(self):
        if self.loop is None:
            return
        try:
            self.loop.call_soon_threadsafe(self.app.invalidate)
        except Exception:
            pass
