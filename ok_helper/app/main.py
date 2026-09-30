"""App: финальная сборка миксинов + async run()."""

import asyncio
from pathlib import Path

from .base import AppBase
from .ui import UIMixin
from .nav import NavMixin
from .modals import ModalsMixin
from .config_modal import ConfigModalMixin
from .actions import ActionsMixin
from .downloads import DownloadsMixin
from .upload_modal import UploadMixin
from .ftp_tab import FtpTabMixin

from config import config_path


class App(AppBase, UIMixin, NavMixin, ModalsMixin,
          ConfigModalMixin, ActionsMixin, DownloadsMixin, UploadMixin,
          FtpTabMixin):
    def __init__(self, initial_dir: Path, config: dict):
        self._init_state(initial_dir, config)
        self._init_inputs()
        self._init_tree()
        self._init_ftp_tab()
        self._init_log()
        self._init_modals()
        self._build_upload_modal()
        self._init_layout()
        self._init_application()


async def run(initial_dir: Path, config: dict):
    app = App(initial_dir, config)
    app.loop = asyncio.get_running_loop()

    app.log(f'[КОНФИГ] {config_path()}')
    app.log(f'[КАТАЛОГ] {initial_dir}')
    app.log('[i] F1 — справка, F7 — переименование, '
            'F8/F9 — загрузки, F10 — настройки, F12 — FTP')

    app.scan_dir(initial_dir)

    if config['watch_downloads']:
        app.start_downloads_watch()

    app.restart_watch()
    try:
        await app.app.run_async()
    finally:
        if app.observer:
            app.observer.stop()
            app.observer.join()
        if app.downloads_observer:
            app.downloads_observer.stop()
            app.downloads_observer.join()
