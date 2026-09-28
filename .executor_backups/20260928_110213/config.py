"""Конфиг ok-helper-tui.

Файл config.toml лежит в системной папке конфигов:
  Linux:   $XDG_CONFIG_HOME/ok-helper-tui/config.toml
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
    'theme': 'auto',           # 'auto' | 'dark' | 'light'
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


def load_config() -> dict:
    p = config_path()
    cfg = dict(DEFAULT_CONFIG)

    if p.exists() and tomllib is not None:
        try:
            with open(p, 'rb') as f:
                data = tomllib.load(f)
            for k in DEFAULT_CONFIG:
                if k in data:
                    cfg[k] = data[k]
        except Exception as e:
            print(f'[config] ошибка чтения {p}: {e}', file=sys.stderr)
    elif not p.exists():
        save_config(cfg)

    # валидация theme
    if cfg.get('theme') not in ('auto', 'dark', 'light'):
        cfg['theme'] = 'auto'

    cfg['root_dir_resolved'] = _as_path(cfg['root_dir'])
    cfg['downloads_dir_resolved'] = _as_path(cfg['downloads_dir'])
    cfg['_path'] = p
    return cfg


def save_config(cfg: dict):
    p = cfg.get('_path') or config_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f'[config] не создать {p.parent}: {e}', file=sys.stderr)
        return

    def _s(key: str, default: str = '') -> str:
        v = cfg.get(key, default)
        return str(v).replace('"', '\\"')

    watch = 'true' if cfg.get('watch_downloads') else 'false'
    theme = cfg.get('theme', 'auto')
    if theme not in ('auto', 'dark', 'light'):
        theme = 'auto'

    lines = [
        '# Конфиг ok-helper-tui',
        '#',
        '# root_dir        — корневая директория, открывается при запуске',
        '# downloads_dir   — папка загрузок для мониторинга',
        '# watch_downloads — true/false: предлагать переносить новые файлы',
        '# theme           — auto / dark / light: цветовая тема интерфейса',
        '#                   auto — определит по переменной COLORFGBG',
        '#',
        '# Пути можно писать с ~ — это раскроется в домашнюю директорию.',
        '',
        f'root_dir        = "{_s("root_dir", "~")}"',
        f'downloads_dir   = "{_s("downloads_dir", "~/Downloads")}"',
        f'watch_downloads = {watch}',
        f'theme           = "{theme}"',
        '',
    ]
    try:
        p.write_text('\n'.join(lines), encoding='utf-8')
    except OSError as e:
        print(f'[config] не записать {p}: {e}', file=sys.stderr)