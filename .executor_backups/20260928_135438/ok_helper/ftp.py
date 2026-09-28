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
    readonly: bool = False,
) -> None:
    """Загружает local_file в base_path/folder/ на FTP-сервере.

    readonly=True — режим эмуляции:
      • connect / login — реальные;
      • переход по base_path и папке назначения — реальный cwd;
      • проверка существования папки и файла — реальная (cwd, nlst);
      • но mkdir, STOR и любые другие изменения НЕ выполняются.
        В журнал пишется, что «было бы» сделано.
    """
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

        if readonly:
            _log('[FTP] *** РЕЖИМ ЭМУЛЯЦИИ: изменения на сервере '
                 'заблокированы ***')

        # --- базовый путь: спускаемся по компонентам ---
        base = (base_path or '/').strip()
        if base and base != '/':
            for part in base.strip('/').split('/'):
                if not part:
                    continue
                try:
                    ftp.cwd(part)
                except ftplib.error_perm:
                    if readonly:
                        _log(f'[FTP] [эмуляция] папка {part} отсутствует '
                             f'и была бы создана')
                        _log(f'[FTP] [эмуляция] {local_file.name} был бы '
                             f'загружен в {folder}/ (запись пропущена)')
                        return
                    _log(f'[FTP] Создаю папку {part}')
                    try:
                        ftp.mkd(part)
                    except ftplib.error_perm as e:
                        raise FtpError(f'не создать {part}: {e}')
                    ftp.cwd(part)

        # --- папка назначения ---
        folder_exists = True
        try:
            ftp.cwd(folder)
        except ftplib.error_perm:
            folder_exists = False

        if folder_exists:
            _log(f'[FTP] Папка {folder} уже существует')
            # Проверим, нет ли уже такого файла — это полезно и в
            # реальном режиме, и в эмуляции.
            try:
                names = ftp.nlst()
                if local_file.name in names:
                    _log(f'[FTP] Внимание: {local_file.name} уже есть '
                         f'на сервере — реальная загрузка перезапишет')
            except ftplib.all_errors:
                pass
        else:
            if readonly:
                _log(f'[FTP] [эмуляция] папка {folder} отсутствует '
                     f'и была бы создана')
            else:
                _log(f'[FTP] Создаю папку {folder}')
                try:
                    ftp.mkd(folder)
                except ftplib.error_perm as e:
                    raise FtpError(f'не создать папку {folder}: {e}')
                ftp.cwd(folder)

        # --- сама загрузка ---
        if readonly:
            try:
                size = local_file.stat().st_size
            except OSError:
                size = 0
            _log(f'[FTP] [эмуляция] {local_file.name} ({size} Б) был бы '
                 f'загружен в {folder}/ (запись пропущена)')
            _log(f'[FTP] [эмуляция] имитация завершена успешно')
            return

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
