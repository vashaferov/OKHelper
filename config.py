"""Конфиг ok-helper-tui.

Файл config.toml лежит в системной папке конфигов:
  Linux:   $XDG_CONFIG_HOME/ok-helper-tui/config.toml
           (или ~/.config/ok-helper-tui/config.toml)
  macOS:   ~/Library/Application Support/ok-helper-tui/config.toml
  Windows: %APPDATA%\\ok-helper-tui\\config.toml
"""

import os
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


DEFAULT_CONFIG = {
    'root_dir': '~',
    'downloads_dir': '~/Downloads',
    'watch_downloads': False,
    'theme': 'auto',
    'ftp_host': '',
    'ftp_port': 21,
    'ftp_user': '',
    'ftp_password': '',
    'ftp_path': '/',
    # Режим эмуляции FTP: подключение и чтение реальные, но любые
    # изменения на сервере (MKD / STOR / DELE) не выполняются.
    # Удобно для проверки имён папок и прав без риска.
    'ftp_readonly': False,
}


_LITERAL_KEYS = {
    'root_dir', 'downloads_dir',
    'ftp_host', 'ftp_user', 'ftp_password', 'ftp_path',
}


def config_path() -> Path:
    if sys.platform == 'win32':
        base = Path(os.environ.get('APPDATA') or Path.home())
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        xdg = os.environ.get('XDG_CONFIG_HOME')
        base = Path(xdg) if xdg else Path.home() / '.config'
    return base / 'ok-helper-tui' / 'config.toml'


def _as_path(value: str) -> Path:
    try:
        return Path(value).expanduser().resolve()
    except (OSError, RuntimeError):
        return Path(value).expanduser()


def _toml_value(key: str, value) -> str:
    """Возвращает TOML-представление значения.

    Для путей (см. _LITERAL_KEYS) используем literal string —
    одинарные кавычки. Внутри них обратный слэш сохраняется как есть.
    """
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)

    s = str(value)
    if key in _LITERAL_KEYS and "'" not in s and '\n' not in s:
        return f"'{s}'"

    esc = (s.replace('\\', '\\\\')
             .replace('"', '\\"')
             .replace('\n', '\\n')
             .replace('\r', '\\r')
             .replace('\t', '\\t'))
    return f'"{esc}"'


def _soft_parse(text: str) -> dict:
    """Аварийный построчный парсер TOML-подобного текста."""
    result: dict = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('#') or s.startswith('['):
            continue
        if '=' not in s:
            continue
        key, _, val = s.partition('=')
        key = key.strip()
        val = val.strip()
        if ' #' in val:
            val = val.split(' #', 1)[0].rstrip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        result[key] = val
    return result


def _read_toml(p: Path):
    if tomllib is None:
        return None
    try:
        text = p.read_text(encoding='utf-8-sig')
    except OSError as e:
        print(f'[config] не прочитать {p}: {e}', file=sys.stderr)
        return None

    try:
        return tomllib.loads(text)
    except Exception as e:
        print(f'[config] {p}: {e}; пробую мягкий разбор',
              file=sys.stderr)

    soft = _soft_parse(text)
    return soft if soft else None


def load_config() -> dict:
    p = config_path()
    cfg = dict(DEFAULT_CONFIG)

    if p.exists():
        data = _read_toml(p)
        if data is not None:
            for k in DEFAULT_CONFIG:
                if k in data:
                    cfg[k] = data[k]

    if cfg.get('theme') not in ('auto', 'dark', 'light'):
        cfg['theme'] = 'auto'

    try:
        cfg['ftp_port'] = int(cfg.get('ftp_port', 21))
    except (ValueError, TypeError):
        cfg['ftp_port'] = 21

    cfg['watch_downloads'] = bool(cfg.get('watch_downloads', False))
    cfg['ftp_readonly'] = bool(cfg.get('ftp_readonly', False))

    for k in ('root_dir', 'downloads_dir', 'ftp_host', 'ftp_user',
              'ftp_password', 'ftp_path'):
        cfg[k] = str(cfg.get(k, DEFAULT_CONFIG[k]))

    cfg['root_dir_resolved'] = _as_path(cfg['root_dir'])
    cfg['downloads_dir_resolved'] = _as_path(cfg['downloads_dir'])
    cfg['_path'] = p

    save_config(cfg)
    return cfg


def save_config(cfg: dict):
    p = cfg.get('_path') or config_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f'[config] не создать {p.parent}: {e}', file=sys.stderr)
        return

    try:
        port = int(cfg.get('ftp_port', 21))
    except (ValueError, TypeError):
        port = 21

    theme = cfg.get('theme', 'auto')
    if theme not in ('auto', 'dark', 'light'):
        theme = 'auto'

    watch = bool(cfg.get('watch_downloads', False))
    readonly = bool(cfg.get('ftp_readonly', False))

    lines = [
        '# Конфиг ok-helper-tui',
        '#',
        '# root_dir        — корневая директория, открывается при запуске',
        '# downloads_dir   — папка загрузок для мониторинга',
        '# watch_downloads — true/false: предлагать переносить новые файлы',
        '# theme           — auto / dark / light',
        '#',
        '# Пути можно писать с ~ — это раскроется в домашнюю директорию.',
        '# Обратные слэши Windows пишутся без удвоения:',
        '#   root_dir = \'C:\\Users\\you\\Tracks\'',
        '',
        f'root_dir        = {_toml_value("root_dir", cfg.get("root_dir", "~"))}',
        f'downloads_dir   = {_toml_value("downloads_dir", cfg.get("downloads_dir", "~/Downloads"))}',
        f'watch_downloads = {_toml_value("watch_downloads", watch)}',
        f'theme           = {_toml_value("theme", theme)}',
        '',
        '# --- FTP ---',
        '# ftp_host      — адрес сервера',
        '# ftp_port      — порт (по умолчанию 21)',
        '# ftp_user      — логин',
        '# ftp_password  — пароль',
        '# ftp_path      — базовый путь на сервере',
        '# ftp_readonly  — true: режим эмуляции (чтение реальное,',
        '#                 изменения — только в журнал, без записи)',
        '',
        f'ftp_host        = {_toml_value("ftp_host", cfg.get("ftp_host", ""))}',
        f'ftp_port        = {_toml_value("ftp_port", port)}',
        f'ftp_user        = {_toml_value("ftp_user", cfg.get("ftp_user", ""))}',
        f'ftp_password    = {_toml_value("ftp_password", cfg.get("ftp_password", ""))}',
        f'ftp_path        = {_toml_value("ftp_path", cfg.get("ftp_path", "/"))}',
        f'ftp_readonly    = {_toml_value("ftp_readonly", readonly)}',
        '',
    ]
    try:
        p.write_text('\n'.join(lines), encoding='utf-8')
    except OSError as e:
        print(f'[config] не записать {p}: {e}', file=sys.stderr)
