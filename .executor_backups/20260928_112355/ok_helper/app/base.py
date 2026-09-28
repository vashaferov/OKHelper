"""AppBase: состояние, журнал, фокус, Tab, общие модалки, тема."""

import re
import threading
from collections import deque
from datetime import datetime
from typing import List, Optional, Tuple

from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import (
    ConditionalContainer, Float, HSplit, VSplit, Window,
)
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
        '   Файл: ' + str(config_path()) + '\n'
        '\n'
        ' FTP (F12):\n'
        '   Папка назначения — строго ГГГГ-ММ-ДД_Место\n'
        '   (латиница, цифры, «_», «-»). Ищется вверх по дереву от\n'
        '   папки файла. Если не найдена — введите вручную.\n'
        '   Ctrl+T в поле — транслит введённого значения.\n'
        '   Папка создаётся на сервере автоматически.\n'
        '\n'
        ' Мониторинг загрузок (F8/F9):\n'
        '   Y / Enter — перенести,  N — пропустить,  Esc — позже\n'
        '\n'
        ' Умный анализ имён:\n'
        '   ГГГГММДД_Позывной              — валидный формат\n'
        '   2026-09-17_11-55_бабушка.gpx   — [Правка]  (уверенно)\n'
        '   2026-09-23-1803 Иванов.gpx     — [Правка]  (средне)\n'
        '   2026-09-23 Безымянный трек.gpx — [Правка?] (откроет редактор)\n'
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

    # ---------- centered modal helper ----------
    def _make_modal_float(
        self,
        body,
        title,
        cond,
        width: int,
        height: int,
        z_index: int = 10,
    ) -> Float:
        """Float, центрирующий модальное окно по экрану.

        Конструкция: HSplit из трёх частей — верхний spacer, VSplit
        с зафиксированной высотой, нижний spacer. Внутри VSplit —
        левый spacer, Frame, правый spacer. Все spacer'ы тянутся
        через D(weight=1), поэтому центр всегда оказывается в
        геометрическом центре Float'а, независимо от размера
        терминала.

        Float растянут на весь экран (top/bottom/left/right=0) и
        помечен transparent=True — это ключевой момент: иначе
        непрозрачный Float затрёт собой ВСЁ, что под ним (дерево,
        журнал, статус-бар), и при открытии модалки основной
        интерфейс исчезнет.
        """
        frame = Frame(body, title=title, width=width)
        centered = HSplit([
            Window(height=D(weight=1)),               # top spacer
            VSplit([
                Window(width=D(weight=1)),            # left spacer
                frame,
                Window(width=D(weight=1)),            # right spacer
            ], height=height),
            Window(height=D(weight=1)),               # bottom spacer
        ])
        return Float(
            content=ConditionalContainer(content=centered, filter=cond),
            top=0, bottom=0, left=0, right=0,
            z_index=z_index,
            transparent=True,                         # ← не затираем фон
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

    def _close_modal(self):
        self.modal = None
        self._pending_fix_list = []
        self._edit_target = None
        self.app.layout.focus(self.tree_window)

    def _modal_title(self) -> FormattedText:
        if self.modal == 'help':
            return FormattedText([('class:title.focus',
                                   ' ▶ Справка — F1 или Esc ')])
        if self.modal == 'confirm_fix_all':
            return FormattedText([('class:title.focus',
                                   ' ▶ Подтверждение — Enter/Y, Esc/N ')])
        if self.modal == 'move_download':
            n = len(self.pending_downloads)
            more = f' (+{n - 1})' if n > 1 else ''
            return FormattedText([('class:title.focus',
                                   f' ▶ Файл из Загрузок{more} — Y/N/Esc ')])
        return FormattedText([('', ' ')])

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
        from ..analyzer import human_size
        if not self.pending_downloads:
            return FormattedText([('', '')])
        src = self.pending_downloads[0]
        dst_dir = self.tree.root
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
        kb = KeyBindings()

        @kb.add('escape')
        def _(event):
            self._close_modal()
            event.app.invalidate()

        @kb.add('n')
        @kb.add('N')
        def _(event):
            if self.modal == 'move_download':
                self.reject_move()
            else:
                self._close_modal()
            event.app.invalidate()

        @kb.add('enter')
        @kb.add('y')
        @kb.add('Y')
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
