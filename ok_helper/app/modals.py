"""ModalsMixin: help / confirm_fix_all / move_download / edit_name /
new_folder / move_file.

Модалка confirm_ftp_delete живёт в FtpTabMixin. Остальные — здесь.

Особенность edit_name: помимо ввода нового имени, окно содержит
кликабельную кнопку «[⇢ Перенести в другую папку]», которая
закрывает F7 и открывает модалку переноса для того же файла.

Также здесь живёт schedule_startup_modals() — логика стартовых окон:
на первом запуске — настройки, затем подсказки; на остальных —
подсказки, если включён чек-бокс help_visible_at_start.
"""

import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import save_config
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType
from prompt_toolkit.widgets import TextArea

from ..analyzer import analyze_file, validate_new_folder_name
from ..translit import transliterate


class ModalsMixin:
    def _init_modals(self):
        self._build_common_modals()
        self._build_edit_name_modal()
        self._build_new_folder_modal()
        self._build_move_modal()
        self._build_config_modal()

    # ---------- startup modals ----------
    def schedule_startup_modals(self):
        """Определяет, какие окна показать при запуске.

        Правила:
          • Если first_run == True (первый запуск):
              1. Ставим first_run = False и сразу сохраняем конфиг
                 (чтобы при аварийном завершении больше не показывать
                 окно настроек).
              2. Открываем окно настроек (F10).
              3. После его закрытия автоматически откроется окно
                 подсказок (F1) — см. AppBase._close_modal.
          • Иначе:
              – если help_visible_at_start == True — открываем
                подсказки (F1);
              – иначе — ничего не показываем.
        """
        first_run = bool(self.config.get('first_run', True))
        if first_run:
            self.config['first_run'] = False
            try:
                save_config(self.config)
            except Exception:
                pass
            self._pending_help_after_config = True
            self.open_config_modal()
            return

        if self.config.get('help_visible_at_start', True):
            self._open_modal('help')

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

    # ---------- edit_name (F7) ----------
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

        # Строка с кнопкой «[⇢ Перенести в другую папку]».
        self.edit_move_row_window = Window(
            FormattedTextControl(text=self._edit_move_row_text),
            height=1, char=' ', style='class:modal.bg',
        )

        body = HSplit([
            self.edit_preview_window,
            self.edit_input,
            self.edit_move_row_window,
            Window(
                FormattedTextControl(text=lambda: FormattedText([
                    ('class:dim',
                     '  Enter — применить,  Esc — отмена,  '
                     'Ctrl+T — транслит')
                ])),
                height=1, char=' ', style='class:modal.bg',
            ),
        ], style='class:modal.bg')

        # content = 2 + 1 + 1 + 1 = 5; + 4 служебные = 9
        self._edit_float = self._make_modal_float(
            body=body,
            title=' ▶ Переименование — F7 ',
            cond=Condition(lambda: self.modal == 'edit_name'),
            width=86, height=9,
        )

    def _edit_move_row_text(self) -> FormattedText:
        """Строка с кликабельной кнопкой переноса.

        Кнопка открывает модалку переноса для того же файла, что
        редактируется в F7. Работает только для файлов (папки
        переименовывать нельзя, и переносить тоже).
        """
        src = getattr(self, '_edit_target', None)
        if src is None or not src.is_file():
            return FormattedText([('', '')])
        return FormattedText([
            ('class:dim', '  '),
            ('class:btn.move', ' [⇢ Перенести в другую папку] ',
             self._click_move_from_edit()),
            ('class:dim', '   Ctrl+X из главного окна'),
        ])

    def _click_move_from_edit(self):
        """Клик по кнопке переноса внутри модалки F7.

        Запоминаем целевой файл, закрываем edit_name, открываем
        move_file с этим же файлом.
        """
        def handler(event: MouseEvent):
            if event.event_type != MouseEventType.MOUSE_UP:
                return
            target = getattr(self, '_edit_target', None)
            if target is None or not target.is_file():
                return

            # Закрываем edit_name. Внутри _close_modal сбрасывается
            # self._edit_target и self._move_target, поэтому целевой
            # путь сохраняем в локальной переменной заранее.
            self._close_modal()

            # Открываем move_file.
            self._move_target = target
            self.move_input.text = ''
            self.move_input.cursor_position = 0
            self.modal = 'move_file'
            self.app.layout.focus(self.move_input)
            self.invalidate()
        return handler

    def _override_translit_keys(self, ta: TextArea):
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

        self._new_folder_float = self._make_modal_float(
            body=body,
            title=' ▶ Новая папка ',
            cond=Condition(lambda: self.modal == 'new_folder'),
            width=86, height=9,
        )

    def _click_toggle_new_folder_tracks(self):
        def handler(event: MouseEvent):
            if event.event_type != MouseEventType.MOUSE_UP:
                return
            if not getattr(self, '_new_folder_is_root', False):
                return
            self._new_folder_with_tracks = not getattr(
                self, '_new_folder_with_tracks', False)
            self.invalidate()
        return handler

    def _new_folder_preview_text(self) -> FormattedText:
        base = getattr(self, '_new_folder_base', None)
        if base is None:
            return FormattedText([('', '')])

        is_root = getattr(self, '_new_folder_is_root', False)
        with_tracks = getattr(self, '_new_folder_with_tracks', False)

        frags: list = [
            ('class:dim', '  Где:  '),
            ('class:cfg.path', f'{base}\n'),
            ('class:dim',
             '  Папка создаётся локально; на FTP появится при '
             'загрузке в неё файла.\n'),
        ]

        if is_root:
            mark = 'x' if with_tracks else ' '
            h = self._click_toggle_new_folder_tracks()
            frags.append(('class:dim', '  '))
            frags.append(('class:btn', f'[{mark}]', h))
            frags.append(('class:cfg.path', ' Создать внутри 10-Tracks', h))
            frags.append(('class:dim', '   (клик мышью)\n'))
        else:
            frags.append(('', '\n'))

        return FormattedText(frags)

    def open_new_folder_modal(self, base_dir: Optional[Path] = None):
        if self.modal is not None:
            return
        if getattr(self, 'active_tab', 'files') != 'files':
            return

        if base_dir is None:
            base_str = (self.path_input.text or '').strip()
            if not base_str:
                self.log('[i] Не задана текущая директория')
                return
            base = Path(base_str).expanduser()
        else:
            base = Path(base_dir)

        if not base.is_dir():
            self.log(f'[ОШБ] Не директория: {base}')
            return

        self._new_folder_base = base

        root = self.config.get('root_dir_resolved')
        is_root = False
        if root:
            try:
                is_root = (Path(root).resolve() == base.resolve())
            except Exception:
                is_root = False
        self._new_folder_is_root = is_root
        self._new_folder_with_tracks = False

        if is_root:
            self.new_folder_input.text = datetime.now().strftime('%Y-%m-%d_')
        else:
            self.new_folder_input.text = ''
        self.new_folder_input.cursor_position = len(self.new_folder_input.text)

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

        with_tracks = bool(getattr(self, '_new_folder_with_tracks', False))
        if with_tracks and getattr(self, '_new_folder_is_root', False):
            sub = target / '10-Tracks'
            try:
                sub.mkdir(parents=False, exist_ok=False)
                self.log(f'[OK] Создана папка: {sub}')
            except OSError as e:
                self.log(f'[ОШБ] Не создать 10-Tracks: {e}')

        self._close_modal()
        self.tree.refresh()
        self.tree.select_by_path(target)
        self._sync_path_to_selection()
        self.invalidate()

    # ---------- move_file (перенос между локальными папками) ----------
    def _build_move_modal(self):
        self.move_input = TextArea(
            height=1, prompt='Куда: ', multiline=False,
            accept_handler=self._apply_move_modal,
            style='class:modal.bg',
        )
        self._style_textarea_for_modal(self.move_input)
        self._override_tab(self.move_input)
        self._override_translit_keys(self.move_input)

        self.move_preview_window = Window(
            FormattedTextControl(text=self._move_preview_text),
            height=3, char=' ', style='class:modal.bg',
        )

        body = HSplit([
            self.move_preview_window,
            self.move_input,
            Window(
                FormattedTextControl(text=lambda: FormattedText([
                    ('class:dim',
                     '  Enter — переместить,  Esc — отмена,  '
                     'Ctrl+T — транслит')
                ])),
                height=1, char=' ', style='class:modal.bg',
            ),
        ], style='class:modal.bg')

        self._move_float = self._make_modal_float(
            body=body,
            title=' ▶ Перемещение файла — Ctrl+X ',
            cond=Condition(lambda: self.modal == 'move_file'),
            width=86, height=9,
        )

    def _move_preview_text(self) -> FormattedText:
        src = getattr(self, '_move_target', None)
        if src is None:
            return FormattedText([('', '')])
        try:
            size_str = ''
            sz = src.stat().st_size
            for unit in ('Б', 'КБ', 'МБ', 'ГБ'):
                if sz < 1024 or unit == 'ГБ':
                    size_str = (f'{int(sz)} {unit}' if unit == 'Б'
                                else f'{sz:.1f} {unit}')
                    break
                sz /= 1024
        except OSError:
            size_str = '?'
        return FormattedText([
            ('class:dim', '  Файл:  '),
            ('class:status.val', f'{src.name}'),
            ('class:dim', f'   ({size_str})\n'),
            ('class:dim', '  Из:    '),
            ('class:cfg.path', f'{src.parent}\n'),
            ('class:dim',
             '  Путь можно писать абсолютный (~ поддерживается) или\n'
             '  относительно текущей директории.\n'),
        ])

    def open_move_modal(self):
        """Открывает модалку переноса файла в другую локальную папку.

        Работает только на вкладке «Файлы» и только для файлов
        (не для папок). На FTP-вкладке вызов игнорируется.
        """
        if self.modal is not None:
            return
        if getattr(self, 'active_tab', 'files') != 'files':
            return
        if not self.tree.entries:
            self.log('[i] Нечего перемещать')
            return
        src, _ = self.tree.entries[self.tree.selected]
        if not src.is_file():
            self.log('[i] Перемещать можно только файлы')
            return
        self._move_target = src
        self.move_input.text = ''
        self.move_input.cursor_position = 0
        self.modal = 'move_file'
        self.app.layout.focus(self.move_input)
        self.invalidate()

    def _apply_move_modal(self, buffer):
        text = buffer.text.strip()
        src = getattr(self, '_move_target', None)
        if src is None or not text:
            self._close_modal()
            return
        if not src.exists():
            self.log(f'[ОШБ] Файл исчез: {src.name}')
            self._close_modal()
            return

        p = Path(text).expanduser()
        if not p.is_absolute():
            base_txt = (self.path_input.text or '').strip()
            base = Path(base_txt).expanduser() if base_txt else self.tree.root
            p = base / p
        try:
            p = p.resolve()
        except Exception:
            pass

        if not p.is_dir():
            self.log(f'[ОШБ] Не директория: {p}')
            return

        try:
            if p == src.parent.resolve():
                self.log(f'[i] Файл уже в этой папке: {src.name}')
                self._close_modal()
                return
        except Exception:
            pass

        dst = p / src.name
        if dst.exists():
            self.log(f'[ОШБ] Уже существует: {dst}')
            return

        try:
            shutil.move(str(src), str(dst))
            self.undo_stack.append((dst, src))
            self.log(f'[ПЕРЕНОС] {src.name} -> {p}')
        except OSError as e:
            self.log(f'[ОШБ] Перенос: {e}')
            return

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