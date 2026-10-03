"""Кроссплатформенное копирование текста в системный буфер обмена.

Порядок попыток:
  1. pyperclip, если он установлен (опциональная зависимость).
  2. Системные утилиты:
       • Windows — clip.exe (передаём UTF-16-LE, иначе кириллица
         превратится в кракозябры);
       • macOS   — pbcopy;
       • Linux   — wl-copy (Wayland), xclip или xsel.

Функция никогда не бросает исключений — если ничего не сработало,
возвращает False, а вызывающий код пишет понятное сообщение в журнал.
"""

import shutil
import subprocess
import sys
from typing import List


def _try_run(cmd: List[str], data: bytes) -> bool:
    try:
        subprocess.run(
            cmd, input=data, check=True, timeout=5,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def copy_to_clipboard(text: str) -> bool:
    """Копирует text в системный буфер обмена. Возвращает True при успехе."""
    if not text:
        return False

    # 1) pyperclip (если установлен)
    try:
        import pyperclip  # type: ignore
        pyperclip.copy(text)
        return True
    except Exception:
        pass

    # 2) системные утилиты
    if sys.platform == 'darwin':
        return _try_run(['pbcopy'], text.encode('utf-8'))

    if sys.platform == 'win32':
        return _try_run(['clip'], text.encode('utf-16-le'))

    # Linux / *nix
    for cmd in (
        ['wl-copy'],
        ['xclip', '-selection', 'clipboard'],
        ['xsel', '--clipboard', '--input'],
    ):
        if shutil.which(cmd[0]):
            if _try_run(cmd, text.encode('utf-8')):
                return True

    return False
