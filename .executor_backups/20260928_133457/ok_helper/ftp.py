"""FTP-загрузка и валидация имени папки назначения."""

import ftplib
import re
from pathlib import Path
from typing import Callable, Optional, Tuple

_FOLDER_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})_([A-Za-z0-9_-]+)$')


def validate_folder_name(name: str) -> Tuple[bool, str]:
    """Возвращает (ok, reason)."""
    if not name or not name.strip():
        return False, 'пустое имя'
    m = _FOLDER_RE.match(name.strip())
    if not m:
        return False, (
            'формат ГГГГ-ММ-ДД_Место; допустимы латиница, цифры, «_», «-»'
        )
    y, mo, d = m.group(1), m.group(2), m.group(3)
    try:
        if not (1 <= int(mo) <= 12 and 1 <= int(d) <= 31):
            return False, 'некорректная дата (месяц/день)'
    except ValueError:
        return False, 'некорректная дата'
    return True, ''


def find_target_folder(start: Path, max_levels: int = 5) -> Tuple[str, bool]:
    """Идёт от start вверх, ищет папку вида ГГГГ-ММ-ДД_Место."""
    cur = start
    for _ in range(max_levels + 1):
        if _FOLDER_RE.match(cur.name):
            return cur.name, True
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return start.name, False


class FtpError(Exception):
    pass


def upload_file(
    host: str,
    port: int,
    user: str,
    password: str,
    base_path: str,
    folder: str,
    local_file: Path,
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Загружает local_file в base_path/folder/ на FTP-сервере."""
    def _log(msg: str):
        if log:
            log(msg)

    if not host:
        raise FtpError('ftp_host не задан в конфиге')
    if not user:
        raise FtpError('ftp_user не задан в конфиге')

    ok, reason = validate_folder_name(folder)
    if not ok:
        raise FtpError(f'некорректное имя папки: {reason}')

    if not local_file.is_file():
        raise FtpError(f'локальный файл не найден: {local_file}')

    ftp = ftplib.FTP()
    try:
        _log(f'[FTP] Подключение к {host}:{port}...')
        ftp.connect(host, port, timeout=30)
        ftp.login(user, password)
        ftp.set_pasv(True)
        _log('[FTP] Авторизация OK')

        base = (base_path or '/').strip()
        if base and base != '/':
            for part in base.strip('/').split('/'):
                if not part:
                    continue
                try:
                    ftp.cwd(part)
                except ftplib.error_perm:
                    _log(f'[FTP] Создаю папку {part}')
                    try:
                        ftp.mkd(part)
                    except ftplib.error_perm as e:
                        raise FtpError(f'не создать {part}: {e}')
                    ftp.cwd(part)

        try:
            ftp.cwd(folder)
            _log(f'[FTP] Папка {folder} уже существует')
        except ftplib.error_perm:
            _log(f'[FTP] Создаю папку {folder}')
            try:
                ftp.mkd(folder)
            except ftplib.error_perm as e:
                raise FtpError(f'не создать папку {folder}: {e}')
            ftp.cwd(folder)

        size = local_file.stat().st_size
        _log(f'[FTP] Загружаю {local_file.name} ({size} Б)...')
        with open(local_file, 'rb') as f:
            ftp.storbinary(f'STOR {local_file.name}', f)
        _log(f'[FTP] Готово: {folder}/{local_file.name}')
    except ftplib.all_errors as e:
        raise FtpError(str(e))
    finally:
        try:
            ftp.quit()
        except Exception:
            try:
                ftp.close()
            except Exception:
                pass
