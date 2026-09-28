#!/usr/bin/env python3
"""Точка входа ok-helper-tui."""

import argparse
import asyncio
import sys
from pathlib import Path

from config import load_config, config_path
from ok_helper.app import run


def main():
    parser = argparse.ArgumentParser(
        description='ok-helper-tui: транслит + умная проверка имён файлов.')
    parser.add_argument(
        'directory', nargs='?', default=None,
        help='Начальная директория. Если не задана — берётся из конфига.',
    )
    args = parser.parse_args()

    config = load_config()

    if args.directory is None:
        d = config['root_dir_resolved']
    else:
        d = Path(args.directory).expanduser().resolve()

    if not d.is_dir():
        print(f'Не директория: {d}', file=sys.stderr)
        print(f'Проверьте root_dir в {config_path()}', file=sys.stderr)
        sys.exit(1)

    try:
        asyncio.run(run(d, config))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
