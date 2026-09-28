"""FTP-загрузка и валидация имени папки назначения."""

import ftplib
import re
from pathlib import Path
from typing import Callable, Optional, Tuple

_FOLDER_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})_([A-Za-z0-9_-]+)$')

# Расширения файлов, разрешённых к загрузке на FTP.
# Сравнение регистронезависимое — .PLT и .plt равнозначны.
ALLOWED_UPLOAD_EXTENSIONS = {'.plt', '.wpt', 'm.gpx'}


def is_uploadable(path: Path) -> bool:
    """True, если файл разрешено загружать на FTP.

    Политика: только *.plt, *.wpt, *.gpx. Всё остальное
    (в том числе временные .crdownload, .part и пр.) — блокируем.
    """
    return path.suffix.lower() in ALLOWED_UPLOAD_EXTENSIONS


def upload_extensions_hint() -> str:
    """Строка для сообщений об ошибке: '*.gpx, *.plt, *.wpt'."""
    return ', '.join(f'*{e}' for e in sorted(ALLOWED_UPLOAD_EXTENSIONS))


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
    """
    def _log(msg: str):
        if log:
            log(msg)

    if not host:
        raise FtpError('ftp_host не задан в конфиге')
    if not user:
        raise FtpError('ftp_user не задан в конфиге')

    # Единая точка проверки: не пропустить нештатный формат, даже
    # если вызов пришёл из обходного места кода.
    if not is_uploadable(local_file):
        raise FtpError(
            f'недопустимый формат файла: {local_file.name}; '
            f'разрешены {upload_extensions_hint()}'
        )

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

        folder_exists = True
        try:
            ftp.cwd(folder)
        except ftplib.error_perm:
            folder_exists = False

        if folder_exists:
            _log(f'[FTP] Папка {folder} уже существует')
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
