"""DownloadsMixin: мониторинг папки загрузок."""

import shutil
from pathlib import Path
from typing import Optional

from config import save_config
from ..analyzer import human_size
from ..handlers import DirHandler
from watchdog.observers import Observer


class DownloadsMixin:
    def start_downloads_watch(self):
        d = self.config['downloads_dir_resolved']
        if not d.is_dir():
            self.log(f'[ЗАГР] Папка загрузок не найдена: {d}')
            self.watch_downloads = False
            return
        if d == self.tree.root:
            self.log('[ЗАГР] Папка загрузок совпадает с текущей '
                     'директорией; мониторинг выключен')
            self.watch_downloads = False
            return
        handler = DirHandler(self.on_download_event)
        obs = Observer()
        obs.schedule(handler, str(d), recursive=False)
        obs.start()
        self.downloads_observer = obs
        self.watch_downloads = True
        self.log(f'[ЗАГР] Мониторинг загрузок: {d}')

    def stop_downloads_watch(self):
        if self.downloads_observer:
            self.downloads_observer.stop()
            self.downloads_observer.join()
            self.downloads_observer = None
        self.watch_downloads = False

    def toggle_downloads_watch(self):
        if self.watch_downloads:
            self.stop_downloads_watch()
            self.config['watch_downloads'] = False
            save_config(self.config)
            self.log('[i] Мониторинг загрузок: выкл (сохранено в конфиг)')
        else:
            self.config['watch_downloads'] = True
            save_config(self.config)
            self.start_downloads_watch()
            self.log('[i] Мониторинг загрузок: вкл (сохранено в конфиг)')
        self.invalidate()

    def on_download_event(self, path: Optional[Path]):
        if path is None or self.loop is None:
            return
        self.loop.call_soon_threadsafe(self._on_download_event_main, path)

    def _on_download_event_main(self, path: Path):
        if path.name.startswith('.'):
            return
        if any(p == path for p in self.pending_downloads):
            return
        self.pending_downloads.append(path)
        try:
            size = human_size(path.stat().st_size)
        except OSError:
            size = '?'
        self.log(f'[ЗАГР] Новый файл в Загрузках: {path.name} ({size})')
        if self.modal is None:
            self.show_move_modal()
        self.invalidate()

    def accept_move(self):
        if not self.pending_downloads:
            self._close_modal()
            return
        src = self.pending_downloads[0]
        dst_dir = self.tree.root
        if not src.exists():
            self.log(f'[ОШБ] Файл исчез: {src.name}')
            self.pending_downloads.pop(0)
            self._after_move_action()
            return
        dst = dst_dir / src.name
        if dst.exists():
            self.log(f'[ОШБ] Уже существует: {dst}')
            self.pending_downloads.pop(0)
        else:
            try:
                shutil.move(str(src), str(dst))
                self.pending_downloads.pop(0)
                self.log(f'[ПЕРЕНОС] {src.name} -> {dst_dir}')
            except OSError as e:
                self.log(f'[ОШБ] Перенос: {e}')
                self.pending_downloads.pop(0)
        self._after_move_action()

    def reject_move(self):
        if not self.pending_downloads:
            self._close_modal()
            return
        src = self.pending_downloads.pop(0)
        self.log(f'[ЗАГР] Пропущен: {src.name}')
        self._after_move_action()

    def _after_move_action(self):
        if self.pending_downloads:
            self.invalidate()
        else:
            self._close_modal()
