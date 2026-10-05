"""ActionsMixin: fix, fix_all, undo, open, scan, path, copy."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from config import save_config
from ..analyzer import analyze_file


class ActionsMixin:
    def on_path_change(self, buffer):
        """Пользователь нажал Enter в поле «Путь:» на вкладке «Файлы»."""
        text = buffer.text.strip()
        p = Path(text).expanduser()
        if not p.is_dir():
            self.log(f'[ОШБ] Не директория: {p}')
            return
        p = p.resolve()
        self.watch_dir = p
        buffer.text = str(p)
        buffer.cursor_position = len(str(p))
        self.tree.set_root(p)

        self.config['root_dir'] = str(p)
        save_config(self.config)

        self.restart_watch()
        self.log(f'[КАТАЛОГ] {p}')
        self.scan_dir(p)
        self.invalidate()

    def copy_selected_name(self):
        """Копирует имя выделенного элемента в системный буфер обмена.

        Работает для файлов И для папок, на обеих вкладках.
        """
        name: Optional[str] = None

        if getattr(self, 'active_tab', 'files') == 'ftp':
            entries = getattr(self, 'ftp_entries', None) or []
            idx = getattr(self, 'ftp_selected', 0)
            if 0 <= idx < len(entries):
                name = entries[idx][0]
        else:
            if self.tree.entries:
                path, _ = self.tree.entries[self.tree.selected]
                name = path.name

        if not name:
            self.log('[i] Ничего не выделено')
            return

        from ..clipboard import copy_to_clipboard
        if copy_to_clipboard(name):
            self.log(f'[БУФЕР] Скопировано: {name}')
        else:
            self.log('[ОШБ] Не удалось скопировать в буфер обмена. '
                     'Установите xclip или wl-copy (Linux), '
                     'или pyperclip (любая ОС)')

    def handle_tree_enter(self):
        if not self.tree.entries:
            return
        path, _ = self.tree.entries[self.tree.selected]
        if path.is_dir():
            self.tree.toggle()
            return
        info = analyze_file(path)
        if not info['has_error']:
            self.log(f'[i] {path.name} — ок')
            return
        if not info['new_name']:
            self.log(f'[!] {path.name} — {info["reason"]}')
            return
        if info['confidence'] in ('high', 'medium'):
            self.do_fix(path, info['new_name'])
        else:
            self.open_edit_for_selection()

    def do_fix(self, path: Path, new_name: str):
        new_path = path.with_name(new_name)
        if new_path.exists():
            self.log(f'[ОШБ] Уже существует: {new_name}')
            return
        try:
            path.rename(new_path)
            self.undo_stack.append((new_path, path))
            self.log(f'[OK] {path.name} -> {new_name}')
        except OSError as e:
            self.log(f'[ОШБ] {e}')
        self.tree.refresh()
        self.invalidate()

    def on_fix_all(self):
        files: List[Tuple[str, str, Path, str]] = []
        for p, _ in self.tree.entries:
            if p.is_file():
                info = analyze_file(p)
                if (info['has_error'] and info['new_name']
                        and info['confidence'] in ('high', 'medium')):
                    files.append((p.name, info['new_name'], p,
                                  info['new_name']))
        if not files:
            self.log('[i] Нет файлов для автоисправления (уверенные случаи)')
            return
        self._pending_fix_list = files
        self._open_modal('confirm_fix_all')

    def _confirm_fix_all(self):
        count = 0
        for old_name, new_name, path, _ in self._pending_fix_list:
            new_path = path.with_name(new_name)
            if new_path.exists():
                self.log(f'[ОШБ] Уже существует: {new_name}')
                continue
            try:
                path.rename(new_path)
                self.undo_stack.append((new_path, path))
                count += 1
            except OSError as e:
                self.log(f'[ОШБ] {old_name}: {e}')
        self.log(f'[OK] Исправлено: {count}')
        self._close_modal()
        self.tree.refresh()
        self.invalidate()

    def undo(self):
        """Отменяет последнее переименование или перенос.

        Используем shutil.move (а не Path.rename), чтобы корректно
        откатывать перенос между разными файловыми системами.
        """
        if not self.undo_stack:
            self.log('[i] Нечего отменять')
            return
        new_path, old_path = self.undo_stack.pop()
        try:
            shutil.move(str(new_path), str(old_path))
            self.log(f'[ОТМЕНА] {new_path.name} -> {old_path}')
        except OSError as e:
            self.log(f'[ОШБ] Отмена: {e}')
        self.tree.refresh()
        self.invalidate()

    def open_selected(self):
        if not self.tree.entries:
            return
        path, _ = self.tree.entries[self.tree.selected]
        if not path.is_file():
            self.log(f'[i] Не файл: {path.name}')
            return
        try:
            if sys.platform.startswith('linux'):
                subprocess.Popen(['xdg-open', str(path)],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', str(path)],
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            elif sys.platform == 'win32':
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                self.log(f'[ОШБ] Открытие не поддержано: {sys.platform}')
                return
            self.log(f'[ОТКР] {path.name}')
        except Exception as e:
            self.log(f'[ОШБ] Открыть не удалось: {e}')

    def scan_dir(self, path: Path):
        problems = 0
        if path.is_dir():
            for p in sorted(path.iterdir()):
                if p.is_file():
                    info = analyze_file(p)
                    if info['has_error']:
                        problems += 1
                        tag = {'high': 'Правка', 'medium': 'Правка',
                               'low': 'Правка?', 'none': '—'}[info['confidence']]
                        self.log(f'[!] {p.name} — {info["reason"]} [{tag}]')
        if problems:
            self.log(f'[КАТАЛОГ] Проблем: {problems} — F5 (уверенные), '
                     f'F7 для ручной правки')
        else:
            self.log('[КАТАЛОГ] Все имена корректны')
