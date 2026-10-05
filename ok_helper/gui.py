"""GUI-версия ok-helper на PySide6 (Qt 6).

Полностью заменяет tkinter-версию. Логика анализа имён и FTP берётся
из существующих модулей ok_helper.*.

Особенности:
  • современный вид: Fusion-стиль Qt с QSS, скруглённые панели,
    акцентные кнопки, тонкие заголовки, hover-эффекты;
  • светлая / тёмная / авто тема (по системной через реестр Windows);
  • рекурсивное дерево файлов с ленивой загрузкой;
  • пометки ошибок и «залито на FTP» прямо в списке;
  • длительные операции FTP — в фоновых потоках, GUI не блокируется;
  • модель-представление — корректная работа с большими папками.
"""

import os
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from PySide6.QtCore import (
    QModelIndex, QObject, Qt, QTimer, Signal, Slot,
)
from PySide6.QtGui import (
    QAction, QColor, QKeySequence,
    QStandardItem, QStandardItemModel, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QSplitter, QStyle,
    QStatusBar, QTabWidget, QToolBar, QTreeView, QVBoxLayout, QWidget,
)

from config import config_path, save_config
from ok_helper.analyzer import (
    analyze_file, human_size, normalize_callsign, sanitize_callsign,
    validate_new_folder_name,
)
from ok_helper.clipboard import copy_to_clipboard
from ok_helper.ftp import (
    delete_file, find_target_folder, is_uploadable, list_folder,
    upload_extensions_hint, upload_file, upload_reason_for,
    validate_folder_name, validate_upload_target,
)
from ok_helper.handlers import DirHandler
from ok_helper.translit import transliterate

from watchdog.observers import Observer


STUB_TEXT = '(загрузка…)'
ROLE_PATH = Qt.UserRole + 1
ROLE_FTP_NAME = Qt.UserRole + 2


# ====================== тема ======================

def _system_is_dark() -> bool:
    if sys.platform == 'win32':
        try:
            import winreg  # type: ignore
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion'
                r'\Themes\Personalize',
            ) as key:
                value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
                return int(value) == 0
        except Exception:
            return False
    return False


def resolve_theme(setting: str) -> str:
    if setting == 'auto':
        return 'dark' if _system_is_dark() else 'light'
    return setting if setting in ('dark', 'light') else 'light'


THEMES: Dict[str, Dict[str, str]] = {
    'dark': {
        'bg':         '#1f1f1f',
        'bg_alt':     '#252526',
        'bg_elev':    '#2d2d30',
        'text':       '#e6e6e6',
        'text_dim':   '#9c9c9c',
        'border':     '#3c3c3c',
        'accent':     '#0a84ff',
        'accent_h':   '#1a8fff',
        'sel_bg':     '#0a3d91',
        'sel_fg':     '#ffffff',
        'tree_dir':   '#ffaf5f',
        'tree_file':  '#e6e6e6',
        'tree_err':   '#ff5f5f',
        'tree_up':    '#5fd75f',
        'log_bg':     '#141414',
        'log_fg':     '#e0e0e0',
    },
    'light': {
        'bg':         '#f3f3f3',
        'bg_alt':     '#ffffff',
        'bg_elev':    '#fafafa',
        'text':       '#1f1f1f',
        'text_dim':   '#606060',
        'border':     '#d0d0d0',
        'accent':     '#0078d4',
        'accent_h':   '#1a8dde',
        'sel_bg':     '#cce4f7',
        'sel_fg':     '#000000',
        'tree_dir':   '#d75f00',
        'tree_file':  '#000000',
        'tree_err':   '#c10000',
        'tree_up':    '#007800',
        'log_bg':     '#ffffff',
        'log_fg':     '#1c1c1c',
    },
}


def build_stylesheet(name: str) -> str:
    c = THEMES[name]
    return f"""
        QWidget {{
            background: {c['bg']};
            color: {c['text']};
            font-family: 'Segoe UI', sans-serif;
            font-size: 10pt;
        }}
        QMainWindow {{
            background: {c['bg']};
        }}
        QLabel {{ background: transparent; }}
        QLabel#Heading {{
            font-weight: 600;
            color: {c['text']};
            padding: 2px 0;
        }}
        QLabel#Dim {{ color: {c['text_dim']}; }}
        QFrame#Card {{
            background: {c['bg_alt']};
            border: 1px solid {c['border']};
            border-radius: 6px;
        }}
        QLineEdit, QComboBox {{
            background: {c['bg_alt']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            padding: 4px 8px;
            selection-background-color: {c['accent']};
            selection-color: #ffffff;
        }}
        QLineEdit:focus, QComboBox:focus {{
            border: 1px solid {c['accent']};
        }}
        QPushButton {{
            background: {c['bg_alt']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            padding: 5px 14px;
            min-width: 60px;
        }}
        QPushButton:hover {{
            background: {c['bg_elev']};
            border-color: {c['accent']};
        }}
        QPushButton:pressed {{
            background: {c['accent']};
            color: #ffffff;
        }}
        QPushButton#Accent {{
            background: {c['accent']};
            color: #ffffff;
            border: 1px solid {c['accent']};
        }}
        QPushButton#Accent:hover {{
            background: {c['accent_h']};
        }}
        QToolBar {{
            background: {c['bg_alt']};
            border: none;
            border-bottom: 1px solid {c['border']};
            spacing: 2px;
            padding: 4px 6px;
        }}
        QToolBar QToolButton {{
            background: transparent;
            color: {c['text']};
            border: 1px solid transparent;
            border-radius: 4px;
            padding: 5px 10px;
        }}
        QToolBar QToolButton:hover {{
            background: {c['bg_elev']};
            border-color: {c['border']};
        }}
        QToolBar QToolButton:pressed {{
            background: {c['accent']};
            color: #ffffff;
        }}
        QTabWidget::pane {{
            border: 1px solid {c['border']};
            border-radius: 4px;
            top: -1px;
            background: {c['bg_alt']};
        }}
        QTabBar::tab {{
            background: transparent;
            color: {c['text_dim']};
            padding: 7px 18px;
            border: 1px solid transparent;
            border-bottom: 2px solid transparent;
            margin-right: 2px;
        }}
        QTabBar::tab:hover {{ color: {c['text']}; }}
        QTabBar::tab:selected {{
            color: {c['text']};
            border-bottom: 2px solid {c['accent']};
        }}
        QTreeView {{
            background: {c['bg_alt']};
            color: {c['text']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            selection-background-color: {c['sel_bg']};
            selection-color: {c['sel_fg']};
            alternate-background-color: {c['bg']};
            outline: 0;
        }}
        QTreeView::item {{
            padding: 3px 4px;
            border: none;
        }}
        QTreeView::item:hover {{
            background: {c['bg_elev']};
        }}
        QTreeView::item:selected {{
            background: {c['sel_bg']};
            color: {c['sel_fg']};
        }}
        QHeaderView::section {{
            background: {c['bg_elev']};
            color: {c['text_dim']};
            border: none;
            border-right: 1px solid {c['border']};
            border-bottom: 1px solid {c['border']};
            padding: 6px 8px;
            font-weight: 600;
        }}
        QPlainTextEdit {{
            background: {c['log_bg']};
            color: {c['log_fg']};
            border: 1px solid {c['border']};
            border-radius: 4px;
            font-family: Consolas, 'Cascadia Mono', monospace;
            font-size: 10pt;
        }}
        QStatusBar {{
            background: {c['bg_alt']};
            color: {c['text_dim']};
            border-top: 1px solid {c['border']};
        }}
        QMenu {{
            background: {c['bg_alt']};
            color: {c['text']};
            border: 1px solid {c['border']};
            padding: 4px;
        }}
        QMenu::item {{
            padding: 5px 24px 5px 20px;
            border-radius: 3px;
        }}
        QMenu::item:selected {{
            background: {c['accent']};
            color: #ffffff;
        }}
        QMenuBar {{
            background: {c['bg_alt']};
            color: {c['text']};
            padding: 2px 0;
        }}
        QMenuBar::item {{
            padding: 5px 12px;
            background: transparent;
        }}
        QMenuBar::item:selected {{
            background: {c['accent']};
            color: #ffffff;
        }}
        QSplitter::handle {{
            background: {c['border']};
        }}
        QCheckBox {{ spacing: 6px; }}
        QCheckBox::indicator {{
            width: 16px; height: 16px;
            border: 1px solid {c['border']};
            border-radius: 3px;
            background: {c['bg_alt']};
        }}
        QCheckBox::indicator:checked {{
            background: {c['accent']};
            border-color: {c['accent']};
        }}
        QScrollBar:vertical {{
            background: {c['bg']};
            width: 12px; margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {c['border']};
            border-radius: 5px;
            min-height: 24px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {c['text_dim']};
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{
            background: {c['bg']};
            height: 12px; margin: 0;
        }}
        QScrollBar::handle:horizontal {{
            background: {c['border']};
            border-radius: 5px;
            min-width: 24px;
            margin: 2px;
        }}
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{ width: 0; }}
    """


# ====================== модель дерева ======================

class FileTreeModel(QStandardItemModel):
    COL_NAME = 0
    COL_SIZE = 1
    COL_STATUS = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(['Имя', 'Размер', 'Статус'])

        self.root_path: Optional[Path] = None
        self.expanded_paths: Set[Path] = set()
        self.ftp_sync_folder: str = ''
        self.ftp_sync_names: Set[str] = set()
        self._theme_name = 'light'

    def set_theme(self, name: str):
        self._theme_name = name
        self.refresh()

    def set_root(self, path: Path):
        self.root_path = path.resolve()
        self.expanded_paths = {self.root_path}
        self.refresh()

    def set_ftp_sync(self, folder: str, names: Set[str]):
        self.ftp_sync_folder = folder
        self.ftp_sync_names = set(names)
        self.refresh()

    def clear_ftp_sync(self):
        self.ftp_sync_folder = ''
        self.ftp_sync_names = set()
        self.refresh()

    def refresh(self):
        if self.root_path is None:
            return
        self.removeRows(0, self.rowCount())

        c = THEMES[self._theme_name]
        style = QApplication.style()

        root_item = QStandardItem(self.root_path.name or str(self.root_path))
        root_item.setEditable(False)
        root_item.setData(str(self.root_path), ROLE_PATH)
        root_item.setIcon(style.standardIcon(QStyle.SP_DirIcon))
        f = root_item.font()
        f.setBold(True)
        root_item.setFont(f)
        root_item.setForeground(QColor(c['tree_dir']))

        size_item = QStandardItem('')
        size_item.setEditable(False)

        status_item = QStandardItem(str(self.root_path))
        status_item.setEditable(False)
        status_item.setForeground(QColor(c['text_dim']))

        self.appendRow([root_item, size_item, status_item])
        self._populate(root_item, self.root_path)

    def find_item(self, path: Path) -> Optional[QStandardItem]:
        if self.root_path is None:
            return None
        try:
            path = path.resolve()
        except Exception:
            return None
        if not path.is_relative_to(self.root_path):
            return None
        if path == self.root_path:
            return self.item(0)

        parts = path.relative_to(self.root_path).parts
        item = self.item(0)
        if item is None:
            return None
        for part in parts:
            found = None
            for row in range(item.rowCount()):
                child = item.child(row)
                p_str = child.data(ROLE_PATH)
                if p_str and Path(p_str).name == part:
                    found = child
                    break
            if found is None:
                return None
            self.load_children_if_stub(found)
            item = found
        return item

    def load_children_if_stub(self, item: QStandardItem):
        if item.rowCount() != 1:
            return
        if item.child(0).text() != STUB_TEXT:
            return
        item.removeRow(0)
        p_str = item.data(ROLE_PATH)
        if not p_str:
            return
        path = Path(p_str)
        if not path.is_dir():
            return
        self._populate(item, path)

    # ---------- наполнение ----------
    def _is_uploaded(self, path: Path) -> bool:
        f = self.ftp_sync_folder
        if not f or '/' in f:
            return False
        if path.parent.name != f:
            return False
        return path.name in self.ftp_sync_names

    def _populate(self, parent_item: QStandardItem, path: Path):
        c = THEMES[self._theme_name]
        style = QApplication.style()
        dir_icon = style.standardIcon(QStyle.SP_DirIcon)
        file_icon = style.standardIcon(QStyle.SP_FileIcon)

        try:
            children = sorted(
                path.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except OSError:
            return

        for child_path in children:
            if child_path.is_dir():
                name_item = QStandardItem(child_path.name)
                name_item.setEditable(False)
                name_item.setData(str(child_path), ROLE_PATH)
                name_item.setIcon(dir_icon)
                f = name_item.font()
                f.setBold(True)
                name_item.setFont(f)
                name_item.setForeground(QColor(c['tree_dir']))

                size_item = QStandardItem('')
                size_item.setEditable(False)

                status_item = QStandardItem('папка')
                status_item.setEditable(False)
                status_item.setForeground(QColor(c['text_dim']))

                parent_item.appendRow([name_item, size_item, status_item])

                try:
                    has_children = any(child_path.iterdir())
                except OSError:
                    has_children = False
                if has_children:
                    stub = QStandardItem(STUB_TEXT)
                    stub.setEditable(False)
                    stub.setForeground(QColor(c['text_dim']))
                    name_item.appendRow(
                        [stub, QStandardItem(''), QStandardItem('')])
                continue

            info = analyze_file(child_path)
            try:
                size_str = human_size(child_path.stat().st_size)
            except OSError:
                size_str = '?'

            uploaded = self._is_uploaded(child_path)

            status_parts: List[str] = []
            if uploaded:
                status_parts.append('✓ на FTP')
            if info['has_error']:
                if info['new_name']:
                    status_parts.append(f'правка → {info["new_name"]}')
                else:
                    status_parts.append(info['reason'] or 'ошибка')
            if is_uploadable(child_path, info):
                status_parts.append('можно на FTP')

            name_item = QStandardItem(child_path.name)
            name_item.setEditable(False)
            name_item.setData(str(child_path), ROLE_PATH)
            name_item.setIcon(file_icon)

            if info['has_error']:
                name_item.setForeground(QColor(c['tree_err']))
                f = name_item.font()
                f.setBold(True)
                name_item.setFont(f)
            elif uploaded:
                name_item.setForeground(QColor(c['tree_up']))
            else:
                name_item.setForeground(QColor(c['tree_file']))

            size_item = QStandardItem(size_str)
            size_item.setEditable(False)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

            status_item = QStandardItem('; '.join(status_parts))
            status_item.setEditable(False)
            if info['has_error']:
                status_item.setForeground(QColor(c['tree_err']))
            elif uploaded:
                status_item.setForeground(QColor(c['tree_up']))
            else:
                status_item.setForeground(QColor(c['text_dim']))

            parent_item.appendRow([name_item, size_item, status_item])


# ====================== модель FTP ======================

class FtpListModel(QStandardItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalHeaderLabels(['Имя', 'Размер'])
        self._theme_name = 'light'
        self._entries: List[Tuple[str, bool, int]] = []

    def set_theme(self, name: str):
        self._theme_name = name
        self.refresh()

    def set_entries(self, entries: List[Tuple[str, bool, int]]):
        self._entries = entries
        self.refresh()

    def entry_for_name(self, name: str) -> Optional[Tuple[str, bool, int]]:
        for n, is_dir, size in self._entries:
            if n == name:
                return (n, is_dir, size)
        return None

    def refresh(self):
        self.removeRows(0, self.rowCount())
        c = THEMES[self._theme_name]
        style = QApplication.style()
        dir_icon = style.standardIcon(QStyle.SP_DirIcon)
        file_icon = style.standardIcon(QStyle.SP_FileIcon)

        for name, is_dir, size in self._entries:
            if is_dir:
                name_item = QStandardItem(name)
                name_item.setIcon(dir_icon)
                f = name_item.font()
                f.setBold(True)
                name_item.setFont(f)
                name_item.setForeground(QColor(c['tree_dir']))
                size_item = QStandardItem('')
            else:
                name_item = QStandardItem(name)
                name_item.setIcon(file_icon)
                name_item.setForeground(QColor(c['tree_file']))
                size_item = QStandardItem(
                    human_size(size) if size else '')
                size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            name_item.setEditable(False)
            size_item.setEditable(False)
            name_item.setData(name, ROLE_FTP_NAME)
            self.appendRow([name_item, size_item])


# ====================== фоновые задачи ======================

class FtpListTask(QObject):
    done = Signal(list, str, str)   # entries, err, folder

    def __init__(self, parent, host, port, user, password, base, folder):
        super().__init__(parent)
        self._args = (host, port, user, password, base, folder)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        host, port, user, password, base, folder = self._args
        try:
            entries = list_folder(host, port, user, password, base, folder)
            self.done.emit(entries, '', folder)
        except Exception as e:
            self.done.emit([], str(e), folder)


class FtpUploadTask(QObject):
    finished = Signal(str, str, str)   # folder, filename, err

    def __init__(self, parent, host, port, user, password,
                 base, folder, src: Path, readonly: bool,
                 log_cb):
        super().__init__(parent)
        self._args = (host, port, user, password, base, folder, src)
        self._readonly = readonly
        self._log_cb = log_cb

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        host, port, user, password, base, folder, src = self._args

        def cb(msg: str):
            self._log_cb(msg)

        try:
            upload_file(host, port, user, password, base, folder,
                        src, cb, readonly=self._readonly)
            if not self._readonly:
                self.finished.emit(folder, src.name, '')
            else:
                self.finished.emit('', '', '')
        except Exception as e:
            self.finished.emit(folder, src.name, str(e))


class FtpDeleteTask(QObject):
    finished = Signal(str, str, str)   # folder, filename, err

    def __init__(self, parent, host, port, user, password,
                 base, folder, filename):
        super().__init__(parent)
        self._args = (host, port, user, password, base, folder, filename)

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        host, port, user, password, base, folder, filename = self._args
        try:
            delete_file(host, port, user, password, base, folder, filename)
            self.finished.emit(folder, filename, '')
        except Exception as e:
            self.finished.emit(folder, filename, str(e))


# ====================== главное окно ======================

class MainWindow(QMainWindow):
    def __init__(self, config: dict, initial_dir: Path):
        super().__init__()
        self.config = config
        self.tree_root = initial_dir.resolve()
        self.watch_dir = self.tree_root
        self.observer: Optional[Observer] = None

        self.ftp_folder = ''
        self.ftp_connected = False
        self.ftp_loading = False

        self._refresh_pending = False

        self.setWindowTitle('ok-helper')
        self.resize(1280, 800)

        self._build_ui()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()

        self.apply_theme()

        self._start_watch()
        self.set_tree_root(self.tree_root, save=False)
        self.scan_dir(self.tree_root)

    # ---------- UI ----------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)
        outer.addWidget(splitter, 1)

        left = QFrame()
        left.setObjectName('Card')
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(6)

        h = QLabel('Журнал')
        h.setObjectName('Heading')
        left_layout.addWidget(h)

        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(2000)
        left_layout.addWidget(self.log_edit, 1)

        clear_btn = QPushButton('Очистить журнал')
        clear_btn.clicked.connect(self.on_clear_log)
        left_layout.addWidget(clear_btn)

        splitter.addWidget(left)

        right = QFrame()
        right.setObjectName('Card')
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(6)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        right_layout.addWidget(self.tabs, 1)

        self._build_files_tab()
        self._build_ftp_tab()

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([400, 880])

    def _build_files_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        nav = QHBoxLayout()
        nav.setSpacing(6)

        self.btn_up = QPushButton('↑ Вверх')
        self.btn_up.clicked.connect(self.on_up)
        nav.addWidget(self.btn_up)

        nav.addWidget(QLabel('Путь:'))
        self.path_edit = QLineEdit(str(self.tree_root))
        self.path_edit.returnPressed.connect(self.on_path_entered)
        nav.addWidget(self.path_edit, 1)

        self.btn_browse = QPushButton('Обзор…')
        self.btn_browse.clicked.connect(self.on_browse_dir)
        nav.addWidget(self.btn_browse)

        layout.addLayout(nav)

        self.tree_model = FileTreeModel(self)
        self.tree_model.set_theme(resolve_theme(self.config.get('theme', 'auto')))

        self.tree_view = QTreeView()
        self.tree_view.setModel(self.tree_model)
        self.tree_view.setAlternatingRowColors(True)
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.setSelectionBehavior(QTreeView.SelectRows)
        self.tree_view.setEditTriggers(QTreeView.NoEditTriggers)
        self.tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(
            self.on_tree_context_menu)

        header = self.tree_view.header()
        header.setSectionResizeMode(
            FileTreeModel.COL_NAME, QHeaderView.Stretch)
        header.setSectionResizeMode(
            FileTreeModel.COL_SIZE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(
            FileTreeModel.COL_STATUS, QHeaderView.ResizeToContents)

        self.tree_view.expanded.connect(self.on_tree_expanded)
        self.tree_view.collapsed.connect(self.on_tree_collapsed)
        self.tree_view.doubleClicked.connect(self.on_tree_double_click)
        self.tree_view.activated.connect(self.on_tree_activated)

        layout.addWidget(self.tree_view, 1)

        actions = QHBoxLayout()
        actions.setSpacing(6)

        for label, slot in (
            ('+ Папка', self.on_new_folder),
            ('Переименовать', self.on_rename),
            ('Переместить', self.on_move),
            ('Копировать имя', self.on_copy_name),
            ('Открыть', self.on_open_selected),
            ('⇪ FTP', self.on_upload_selected),
            ('Правка', self.on_apply_fix),
        ):
            b = QPushButton(label)
            b.clicked.connect(slot)
            actions.addWidget(b)
        actions.addStretch(1)

        layout.addLayout(actions)

        hint = QLabel(
            'Двойной клик по папке — раскрыть / свернуть; '
            'Enter — сделать корнем дерева; правый клик — меню.')
        hint.setObjectName('Dim')
        layout.addWidget(hint)

        self.tabs.addTab(tab, 'Файлы')

    def _build_ftp_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        nav = QHBoxLayout()
        nav.setSpacing(6)

        nav.addWidget(QLabel('Путь:'))
        self.ftp_path_edit = QLineEdit()
        self.ftp_path_edit.returnPressed.connect(self.on_ftp_connect)
        nav.addWidget(self.ftp_path_edit, 1)

        btn_connect = QPushButton('Подключиться')
        btn_connect.setObjectName('Accent')
        btn_connect.clicked.connect(self.on_ftp_connect)
        nav.addWidget(btn_connect)

        btn_refresh = QPushButton('↻ Обновить')
        btn_refresh.clicked.connect(self.on_ftp_refresh)
        nav.addWidget(btn_refresh)

        layout.addLayout(nav)

        follow_row = QHBoxLayout()
        self.follow_checkbox = QCheckBox(
            'Следить за папкой из вкладки «Файлы» '
            '(автоподстановка при переходе)')
        self.follow_checkbox.setChecked(True)
        self.follow_checkbox.toggled.connect(self._on_follow_changed)
        follow_row.addWidget(self.follow_checkbox)
        follow_row.addStretch(1)
        layout.addLayout(follow_row)

        self.ftp_model = FtpListModel(self)
        self.ftp_model.set_theme(resolve_theme(self.config.get('theme', 'auto')))

        self.ftp_view = QTreeView()
        self.ftp_view.setModel(self.ftp_model)
        self.ftp_view.setAlternatingRowColors(True)
        self.ftp_view.setUniformRowHeights(True)
        self.ftp_view.setSelectionBehavior(QTreeView.SelectRows)
        self.ftp_view.setEditTriggers(QTreeView.NoEditTriggers)
        self.ftp_view.doubleClicked.connect(self.on_ftp_double_click)

        header = self.ftp_view.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)

        layout.addWidget(self.ftp_view, 1)

        actions = QHBoxLayout()
        actions.setSpacing(6)

        btn_del = QPushButton('Удалить выделенное')
        btn_del.clicked.connect(self.on_ftp_delete_selected)
        actions.addWidget(btn_del)

        btn_up = QPushButton('Загрузить файл сюда…')
        btn_up.clicked.connect(self.on_ftp_upload_here)
        actions.addWidget(btn_up)

        actions.addStretch(1)
        layout.addLayout(actions)

        hint = QLabel(
            'Двойной клик по папке — войти. '
            'Удаление доступно только при ftp_readonly = false.')
        hint.setObjectName('Dim')
        layout.addWidget(hint)

        self.tabs.addTab(tab, 'FTP')

    def _build_menu(self):
        menubar = self.menuBar()

        m_file = menubar.addMenu('Файл')
        self._act(m_file, 'Выбрать директорию…', 'Ctrl+O',
                  self.on_browse_dir)
        m_file.addSeparator()
        self._act(m_file, 'Настройки…', 'F10', self.open_settings)
        m_file.addSeparator()
        self._act(m_file, 'Выход', 'Ctrl+Q', self.close)

        m_edit = menubar.addMenu('Правка')
        self._act(m_edit, 'Обновить', 'F5', self.on_refresh)
        m_edit.addSeparator()
        self._act(m_edit, 'Создать папку…', 'Ctrl+N', self.on_new_folder)
        self._act(m_edit, 'Переименовать…', 'F2', self.on_rename)
        self._act(m_edit, 'Переместить…', 'Ctrl+X', self.on_move)
        self._act(m_edit, 'Копировать имя', 'Ctrl+Y', self.on_copy_name)
        m_edit.addSeparator()
        self._act(m_edit, 'Применить автоправку', None, self.on_apply_fix)
        self._act(m_edit, 'Исправить все', 'Ctrl+F5', self.on_fix_all)

        m_ftp = menubar.addMenu('FTP')
        self._act(m_ftp, 'Загрузить выделенный на FTP', 'F12',
                  self.on_upload_selected)
        self._act(m_ftp, 'Загрузить файл в текущую папку FTP…', None,
                  self.on_ftp_upload_here)
        m_ftp.addSeparator()
        self._act(m_ftp, 'Обновить листинг FTP', None, self.on_ftp_refresh)
        self._act(m_ftp, 'Удалить файл на FTP', 'Del',
                  self.on_ftp_delete_selected)

        m_help = menubar.addMenu('Справка')
        self._act(m_help, 'Справка', 'F1', self.open_help)
        self._act(m_help, 'О программе', None, self.open_about)

    def _act(self, menu: QMenu, text: str, shortcut: Optional[str], slot):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.triggered.connect(slot)
        menu.addAction(a)
        self.addAction(a)
        return a

    def _build_toolbar(self):
        tb = QToolBar('Основные')
        tb.setMovable(False)
        self.addToolBar(tb)

        def add(text, slot, tooltip=None):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if tooltip:
                a.setToolTip(tooltip)
            tb.addAction(a)

        add('↑ Вверх', self.on_up, 'Перейти в родительскую папку')
        tb.addSeparator()
        add('Обновить', self.on_refresh, 'Перечитать содержимое (F5)')
        add('Исправить все', self.on_fix_all,
            'Переименовать все уверенные случаи')
        tb.addSeparator()
        add('+ Папка', self.on_new_folder, 'Создать папку')
        add('Переименовать', self.on_rename, 'Переименовать файл')
        add('Переместить', self.on_move, 'Переместить в другую папку')
        tb.addSeparator()
        add('На FTP', self.on_upload_selected,
            'Загрузить выделенный файл на FTP')

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_label = QLabel('Готово.')
        sb.addWidget(self.status_label, 1)

    # ---------- тема ----------
    def apply_theme(self):
        name = resolve_theme(self.config.get('theme', 'auto'))
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(name))
        if hasattr(self, 'tree_model'):
            self.tree_model.set_theme(name)
        if hasattr(self, 'ftp_model'):
            self.ftp_model.set_theme(name)
        if hasattr(self, 'log_edit'):
            c = THEMES[name]
            self.log_edit.setStyleSheet(
                f'background:{c["log_bg"]};color:{c["log_fg"]};'
                f'border:1px solid {c["border"]};border-radius:4px;'
                f'font-family:Consolas,monospace;'
            )

    # ---------- лог ----------
    def log(self, msg: str, level: str = 'info'):
        if threading.current_thread() is threading.main_thread():
            self._append_log(msg, level)
        else:
            QTimer.singleShot(0, lambda: self._append_log(msg, level))

    def _append_log(self, msg: str, level: str):
        name = resolve_theme(self.config.get('theme', 'auto'))
        c = THEMES[name]
        color_map = {
            'info':  c['log_fg'],
            'ok':    c['tree_up'],
            'warn':  '#ffd700',
            'error': c['tree_err'],
            'cfg':   '#5fd7ff',
        }
        color = color_map.get(level, c['log_fg'])

        ts = datetime.now().strftime('%H:%M:%S')
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.insertText(f'{ts}  {msg}\n', fmt)

        self.log_edit.setTextCursor(cursor)
        self.log_edit.ensureCursorVisible()

    def set_status(self, text: str):
        self.status_label.setText(text)

    def on_clear_log(self):
        self.log_edit.clear()
        self.log('Журнал очищен', 'info')

    # ---------- watchdog ----------
    def _start_watch(self):
        self._stop_watch()
        try:
            handler = DirHandler(self._on_fs_event)
            obs = Observer()
            obs.schedule(handler, str(self.watch_dir), recursive=True)
            obs.start()
            self.observer = obs
        except Exception as e:
            self.log(f'[watchdog] не удалось запустить: {e}', 'error')

    def _stop_watch(self):
        if self.observer:
            try:
                self.observer.stop()
                self.observer.join(timeout=2)
            except Exception:
                pass
            self.observer = None

    def _on_fs_event(self, _path: Optional[Path]):
        QTimer.singleShot(0, self._schedule_refresh)

    def _schedule_refresh(self):
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(200, self._do_refresh)

    def _do_refresh(self):
        self._refresh_pending = False
        self.rebuild_tree()

    # ---------- дерево ----------
    def rebuild_tree(self):
        self.tree_model.refresh()
        self._restore_expansion()
        self.path_edit.setText(str(self.tree_root))
        self.update_status()

    def _restore_expansion(self):
        for p in sorted(self.tree_model.expanded_paths,
                        key=lambda x: len(x.parts)):
            item = self.tree_model.find_item(p)
            if item is None:
                continue
            idx = self.tree_model.indexFromItem(item)
            self.tree_view.setExpanded(idx, True)

    def _selected_path(self) -> Optional[Path]:
        idx = self.tree_view.currentIndex()
        if not idx.isValid():
            return None
        item = self.tree_model.itemFromIndex(idx)
        if item is None:
            return None
        p_str = item.data(ROLE_PATH)
        if not p_str:
            return None
        return Path(p_str)

    def _path_from_index(self, index: QModelIndex) -> Optional[Path]:
        item = self.tree_model.itemFromIndex(index)
        if item is None:
            return None
        p_str = item.data(ROLE_PATH)
        return Path(p_str) if p_str else None

    def on_tree_expanded(self, index: QModelIndex):
        item = self.tree_model.itemFromIndex(index)
        if item is None:
            return
        p_str = item.data(ROLE_PATH)
        if not p_str:
            return
        self.tree_model.expanded_paths.add(Path(p_str))
        self.tree_model.load_children_if_stub(item)

    def on_tree_collapsed(self, index: QModelIndex):
        item = self.tree_model.itemFromIndex(index)
        if item is None:
            return
        p_str = item.data(ROLE_PATH)
        if not p_str:
            return
        self.tree_model.expanded_paths.discard(Path(p_str))

    def on_tree_double_click(self, index: QModelIndex):
        path = self._path_from_index(index)
        if path is None:
            return
        if path.is_dir():
            item = self.tree_model.itemFromIndex(index)
            if item is not None:
                self.tree_model.load_children_if_stub(item)
        else:
            self.open_path(path)

    def on_tree_activated(self, index: QModelIndex):
        path = self._path_from_index(index)
        if path is None:
            return
        if path.is_dir():
            self.set_tree_root(path)

    def on_tree_context_menu(self, pos):
        index = self.tree_view.indexAt(pos)
        if not index.isValid():
            return
        path = self._path_from_index(index)
        if path is None:
            return

        self.tree_view.setCurrentIndex(index)

        menu = QMenu(self)
        if path.is_dir():
            a = menu.addAction('Сделать корнем дерева')
            a.triggered.connect(lambda: self.set_tree_root(path))
            a2 = menu.addAction('Раскрыть / скрыть')
            a2.triggered.connect(
                lambda: self.tree_view.setExpanded(
                    index, not self.tree_view.isExpanded(index)))
            menu.addSeparator()
        a3 = menu.addAction('Копировать имя')
        a3.triggered.connect(self.on_copy_name)
        if path.is_file():
            menu.addSeparator()
            menu.addAction('Переименовать…', self.on_rename)
            menu.addAction('Переместить…', self.on_move)
            menu.addAction('Открыть', self.on_open_selected)
        menu.exec(self.tree_view.viewport().mapToGlobal(pos))

    def set_tree_root(self, p: Path, save: bool = True):
        try:
            p = p.resolve()
        except Exception:
            return
        if not p.is_dir():
            return
        self.tree_root = p
        self.watch_dir = p
        self.config['root_dir'] = str(p)
        if save:
            try:
                save_config(self.config)
            except Exception:
                pass
        self._start_watch()
        self.tree_model.set_root(p)
        self._restore_expansion()
        self.path_edit.setText(str(p))
        self.scan_dir(p)
        self.update_status()

        if (self.tabs.currentIndex() == 1
                and self.follow_checkbox.isChecked()):
            self._on_tab_changed(1)

    # ---------- статус ----------
    def update_status(self):
        total = 0
        errors = 0
        uploaded = 0

        for p in self._iter_loaded_files():
            total += 1
            info = analyze_file(p)
            if info['has_error']:
                errors += 1
            if self._is_uploaded_to_ftp(p):
                uploaded += 1

        self.set_status(
            f'Файлов: {total}   ·   ошибок: {errors}   ·   '
            f'залито на FTP: {uploaded}   ·   {self.tree_root}')

    def _iter_loaded_files(self):
        def walk(parent: QStandardItem):
            for row in range(parent.rowCount()):
                child = parent.child(row)
                p_str = child.data(ROLE_PATH)
                if p_str:
                    p = Path(p_str)
                    if p.is_file():
                        yield p
                yield from walk(child)
        root = self.tree_model.invisibleRootItem()
        yield from walk(root)

    def _is_uploaded_to_ftp(self, path: Path) -> bool:
        f = self.tree_model.ftp_sync_folder
        if not f or '/' in f:
            return False
        if path.parent.name != f:
            return False
        return path.name in self.tree_model.ftp_sync_names

    # ---------- навигация ----------
    def on_up(self):
        parent = self.tree_root.parent
        if parent == self.tree_root:
            return
        self.set_tree_root(parent)

    def on_browse_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, 'Выберите директорию', str(self.tree_root))
        if not d:
            return
        self.set_tree_root(Path(d))

    def on_path_entered(self):
        text = self.path_edit.text().strip()
        p = Path(text).expanduser()
        if not p.is_dir():
            QMessageBox.critical(self, 'Ошибка', f'Не директория:\n{p}')
            return
        self.set_tree_root(p)

    def on_refresh(self):
        self.rebuild_tree()
        self.scan_dir(self.tree_root)

    # ---------- scan ----------
    def scan_dir(self, path: Path):
        if not path.is_dir():
            return
        problems = 0
        for p in sorted(path.iterdir()):
            if not p.is_file():
                continue
            info = analyze_file(p)
            if info['has_error']:
                problems += 1
                tag = {'high': 'правка', 'medium': 'правка',
                       'low': 'правка?', 'none': '—'}[info['confidence']]
                self.log(f'[!] {p.name} — {info["reason"]} [{tag}]', 'warn')
        if problems:
            self.log(f'[КАТАЛОГ] Проблем: {problems}', 'info')
        else:
            self.log('[КАТАЛОГ] Все имена корректны', 'ok')

    # ---------- вкладки ----------
    def _on_tab_changed(self, idx: int):
        if idx != 1:
            return
        if not self.follow_checkbox.isChecked():
            return

        start: Optional[Path] = None
        sel = self._selected_path()
        if sel is not None:
            start = sel.parent if sel.is_file() else sel
        if start is None:
            start = self.tree_root

        folder, found = find_target_folder(start)
        if not found:
            self.log(
                f'[FTP] Автоподстановка: начиная от «{start}» не найдено '
                f'имя вида ГГГГ-ММ-ДД_Место. Выделите нужную папку или '
                f'введите путь вручную.', 'warn')
            return
        if folder == self.ftp_folder and self.ftp_connected:
            return
        if folder == self.ftp_path_edit.text().strip() and self.ftp_loading:
            return

        self.ftp_path_edit.setText(folder)
        self.log(f'[FTP] Автоподстановка папки: {folder} '
                 f'(источник: {start})', 'cfg')
        self.ftp_load(folder)

    def _on_follow_changed(self, checked: bool):
        self.log(f'[FTP] Слежение за папкой из «Файлы»: '
                 f'{"вкл" if checked else "выкл"}', 'cfg')

    # ---------- операции с файлами ----------
    def on_new_folder(self):
        dlg = NewFolderDialog(self, self.config, self.tree_root)
        if dlg.exec() != QDialog.Accepted or dlg.result is None:
            return
        target = dlg.result
        if target.exists():
            QMessageBox.critical(self, 'Ошибка',
                                 f'Уже существует: {target.name}')
            return
        try:
            target.mkdir(parents=False, exist_ok=False)
            self.log(f'[OK] Создана папка: {target}', 'ok')
        except OSError as e:
            self.log(f'[ОШБ] Не создать папку: {e}', 'error')
            return
        if dlg.with_10_tracks:
            sub = target / '10-Tracks'
            try:
                sub.mkdir(parents=False, exist_ok=False)
                self.log(f'[OK] Создана папка: {sub}', 'ok')
            except OSError as e:
                self.log(f'[ОШБ] Не создать 10-Tracks: {e}', 'error')
        self.rebuild_tree()

    def on_rename(self):
        p = self._selected_path()
        if p is None or not p.is_file():
            QMessageBox.information(self, 'Переименование',
                                    'Выберите файл')
            return
        dlg = RenameDialog(self, p)
        if dlg.exec() != QDialog.Accepted or dlg.result is None:
            return
        new_name = dlg.result
        if new_name == p.name:
            return
        new_path = p.with_name(new_name)
        if new_path.exists():
            QMessageBox.critical(self, 'Ошибка',
                                 f'Уже существует: {new_name}')
            return
        try:
            p.rename(new_path)
            self.log(f'[OK] {p.name} -> {new_name}', 'ok')
        except OSError as e:
            self.log(f'[ОШБ] {e}', 'error')
            return
        self.rebuild_tree()

    def on_move(self):
        p = self._selected_path()
        if p is None or not p.is_file():
            QMessageBox.information(self, 'Перемещение', 'Выберите файл')
            return
        dlg = MoveDialog(self, p, self.tree_root)
        if dlg.exec() != QDialog.Accepted or dlg.result is None:
            return
        dst_dir = dlg.result
        dst = dst_dir / p.name
        if dst.exists():
            QMessageBox.critical(self, 'Ошибка', f'Уже существует: {dst}')
            return
        try:
            shutil.move(str(p), str(dst))
            self.log(f'[ПЕРЕНОС] {p.name} -> {dst_dir}', 'ok')
        except OSError as e:
            self.log(f'[ОШБ] Перенос: {e}', 'error')
            return
        self.rebuild_tree()

    def on_copy_name(self):
        p = self._selected_path()
        if p is None:
            idx = self.ftp_view.currentIndex()
            if idx.isValid():
                item = self.ftp_model.itemFromIndex(idx)
                if item is not None:
                    name = (item.data(ROLE_FTP_NAME)
                            or item.text())
                    if copy_to_clipboard(name):
                        self.log(f'[БУФЕР] Скопировано: {name}', 'ok')
                    else:
                        self.log('[ОШБ] Буфер обмена недоступен', 'error')
            return
        if copy_to_clipboard(p.name):
            self.log(f'[БУФЕР] Скопировано: {p.name}', 'ok')
        else:
            self.log('[ОШБ] Буфер обмена недоступен', 'error')

    def open_path(self, p: Path):
        try:
            os.startfile(str(p))  # type: ignore[attr-defined]
            self.log(f'[ОТКР] {p.name}', 'ok')
        except Exception as e:
            self.log(f'[ОШБ] Открыть не удалось: {e}', 'error')

    def on_open_selected(self):
        p = self._selected_path()
        if p is None or not p.is_file():
            return
        self.open_path(p)

    def on_apply_fix(self):
        p = self._selected_path()
        if p is None or not p.is_file():
            QMessageBox.information(self, 'Правка', 'Выберите файл')
            return
        info = analyze_file(p)
        if not info['has_error']:
            self.log(f'[i] {p.name} — ок', 'info')
            return
        if not info['new_name']:
            self.log(f'[!] {p.name} — {info["reason"]}', 'warn')
            return
        new_path = p.with_name(info['new_name'])
        if new_path.exists():
            self.log(f'[ОШБ] Уже существует: {info["new_name"]}', 'error')
            return
        try:
            p.rename(new_path)
            self.log(f'[OK] {p.name} -> {info["new_name"]}', 'ok')
        except OSError as e:
            self.log(f'[ОШБ] {e}', 'error')
            return
        self.rebuild_tree()

    def on_fix_all(self):
        files: List[Tuple[Path, str]] = []
        for p in self._iter_loaded_files():
            info = analyze_file(p)
            if (info['has_error'] and info['new_name']
                    and info['confidence'] in ('high', 'medium')):
                files.append((p, info['new_name']))
        if not files:
            self.log('[i] Нет файлов для автоисправления', 'info')
            return
        if QMessageBox.question(
                self, 'Исправить все',
                f'Переименовать {len(files)} файлов?'
        ) != QMessageBox.Yes:
            return
        count = 0
        for path, new_name in files:
            new_path = path.with_name(new_name)
            if new_path.exists():
                self.log(f'[ОШБ] Уже существует: {new_name}', 'error')
                continue
            try:
                path.rename(new_path)
                self.log(f'[OK] {path.name} -> {new_name}', 'ok')
                count += 1
            except OSError as e:
                self.log(f'[ОШБ] {path.name}: {e}', 'error')
        self.log(f'[OK] Исправлено: {count}', 'ok')
        self.rebuild_tree()

    # ---------- FTP ----------
    def on_ftp_connect(self):
        folder = self.ftp_path_edit.text().strip()
        if not folder:
            QMessageBox.information(self, 'FTP', 'Укажите папку на сервере')
            return
        first = folder.split('/')[0]
        ok, reason = validate_folder_name(first)
        if not ok:
            QMessageBox.critical(self, 'FTP',
                                 f'Первый компонент пути: {reason}')
            return
        self.ftp_load(folder)

    def on_ftp_refresh(self):
        folder = self.ftp_path_edit.text().strip()
        if not folder:
            QMessageBox.information(self, 'FTP', 'Укажите папку на сервере')
            return
        self.ftp_load(folder)

    def ftp_load(self, folder: str):
        host = self.config.get('ftp_host', '')
        user = self.config.get('ftp_user', '')
        if not host or not user:
            QMessageBox.critical(
                self, 'FTP',
                'Задайте ftp_host и ftp_user в настройках (F10)')
            return
        if self.ftp_loading:
            return

        port = int(self.config.get('ftp_port', 21))
        password = self.config.get('ftp_password', '')
        base = self.config.get('ftp_path', '/') or '/'

        self.ftp_loading = True
        self.set_status(f'Подключение к FTP: {folder}…')
        self.log(f'[FTP] Обновление папки {folder}', 'cfg')

        task = FtpListTask(self, host, port, user, password, base, folder)
        task.done.connect(self._on_ftp_result)
        task.start()

    @Slot(list, str, str)
    def _on_ftp_result(self, entries, err, folder):
        self.ftp_loading = False
        if err:
            self.log(f'[FTP] Ошибка: {err}', 'error')
            self.set_status('FTP: ошибка')
            self.ftp_connected = False
            self.tree_model.clear_ftp_sync()
            self.ftp_model.set_entries([])
            self.rebuild_tree()
            return

        self.ftp_connected = True
        self.ftp_folder = folder

        self.ftp_model.set_entries(entries)

        if folder and '/' not in folder:
            self.tree_model.set_ftp_sync(
                folder, {n for n, is_d, _ in entries if not is_d})
        else:
            self.tree_model.clear_ftp_sync()

        self.log(f'[FTP] Открыта папка {folder} '
                 f'({len(entries)} элементов)', 'ok')
        self.set_status(f'FTP: {folder}')
        self.rebuild_tree()

    def on_ftp_double_click(self, index: QModelIndex):
        item = self.ftp_model.itemFromIndex(index)
        if item is None:
            return
        name = item.data(ROLE_FTP_NAME)
        if not name:
            return
        entry = self.ftp_model.entry_for_name(name)
        if entry is None:
            return
        _, is_dir, _ = entry
        if is_dir:
            current = self.ftp_path_edit.text().strip()
            new_folder = f'{current}/{name}' if current else name
            self.ftp_path_edit.setText(new_folder)
            self.ftp_load(new_folder)

    def on_ftp_delete_selected(self):
        if self.tabs.currentIndex() != 1:
            return
        index = self.ftp_view.currentIndex()
        if not index.isValid():
            QMessageBox.information(self, 'FTP', 'Выберите файл на сервере')
            return
        item = self.ftp_model.itemFromIndex(index)
        if item is None:
            return
        name = item.data(ROLE_FTP_NAME)
        if not name:
            return
        entry = self.ftp_model.entry_for_name(name)
        if entry is None:
            return
        _, is_dir, _ = entry
        if is_dir:
            QMessageBox.information(self, 'FTP',
                                    'Удаление папок не поддерживается')
            return
        if self.config.get('ftp_readonly', False):
            QMessageBox.information(
                self, 'FTP',
                'Удаление запрещено: ftp_readonly = true')
            return
        if QMessageBox.question(
                self, 'Подтверждение',
                f'Удалить файл на сервере?\n{name}'
        ) != QMessageBox.Yes:
            return

        host = self.config.get('ftp_host', '')
        port = int(self.config.get('ftp_port', 21))
        user = self.config.get('ftp_user', '')
        password = self.config.get('ftp_password', '')
        base = self.config.get('ftp_path', '/') or '/'
        folder = self.ftp_folder

        task = FtpDeleteTask(self, host, port, user, password,
                             base, folder, name)
        task.finished.connect(self._on_ftp_delete_done)
        task.start()

    @Slot(str, str, str)
    def _on_ftp_delete_done(self, folder: str, name: str, err: str):
        if err:
            self.log(f'[FTP] Ошибка удаления {name}: {err}', 'error')
        else:
            self.log(f'[FTP] Удалён: {folder}/{name}', 'ok')
            if self.tree_model.ftp_sync_folder == folder:
                self.tree_model.ftp_sync_names.discard(name)
                self.rebuild_tree()
        self.ftp_load(folder)

    def on_ftp_upload_here(self):
        folder = self.ftp_path_edit.text().strip()
        if not folder:
            QMessageBox.information(
                self, 'FTP', 'Сначала укажите папку на сервере')
            return
        path, _ = QFileDialog.getOpenFileName(
            self, 'Файл для загрузки на FTP', str(self.tree_root))
        if not path:
            return
        p = Path(path)
        info = analyze_file(p)
        if not is_uploadable(p, info):
            reason = upload_reason_for(p, info)
            QMessageBox.critical(
                self, 'FTP',
                f'Нельзя отправить {p.name}\n{reason}\n\n'
                f'Разрешены: {upload_extensions_hint()}')
            return
        self.do_upload(p, folder)

    def on_upload_selected(self):
        p = self._selected_path()
        if p is None or not p.is_file():
            QMessageBox.information(self, 'FTP', 'Выберите файл')
            return
        info = analyze_file(p)
        if not is_uploadable(p, info):
            reason = upload_reason_for(p, info)
            QMessageBox.critical(
                self, 'FTP',
                f'Нельзя отправить {p.name}\n{reason}\n\n'
                f'Разрешены: {upload_extensions_hint()}')
            return
        folder, found = find_target_folder(p.parent)
        if not found:
            folder, ok = QInputDialog.getText(
                self, 'FTP',
                'Папка не найдена по имени. Введите вручную '
                '(ГГГГ-ММ-ДД_Место):')
            folder = folder.strip()
            if not ok or not folder:
                return
        ok, reason = validate_folder_name(folder)
        if not ok:
            QMessageBox.critical(self, 'FTP', reason)
            return
        base = self.config.get('ftp_path', '/') or '/'
        ok, reason = validate_upload_target(base, folder)
        if not ok:
            QMessageBox.critical(self, 'FTP', reason)
            return
        self.do_upload(p, folder)

    def do_upload(self, src: Path, folder: str):
        host = self.config.get('ftp_host', '')
        port = int(self.config.get('ftp_port', 21))
        user = self.config.get('ftp_user', '')
        password = self.config.get('ftp_password', '')
        base = self.config.get('ftp_path', '/') or '/'
        readonly = bool(self.config.get('ftp_readonly', False))

        if readonly:
            self.log(f'[FTP] [эмуляция] {src.name} → {base}/{folder}/',
                     'cfg')
        else:
            self.log(f'[FTP] Начинаю загрузку {src.name} → '
                     f'{base}/{folder}/', 'cfg')

        task = FtpUploadTask(self, host, port, user, password,
                             base, folder, src, readonly, self.log)
        task.finished.connect(self._on_upload_done)
        task.start()

    @Slot(str, str, str)
    def _on_upload_done(self, folder: str, filename: str, err: str):
        if err:
            self.log(f'[FTP] Ошибка: {err}', 'error')
            return
        if not folder:
            return
        self.log(f'[FTP] Успешно: {folder}/{filename}', 'ok')
        if '/' not in folder and \
                self.tree_model.ftp_sync_folder == folder:
            self.tree_model.ftp_sync_names.add(filename)
            self.rebuild_tree()

    # ---------- настройки / справка ----------
    def open_settings(self):
        dlg = SettingsDialog(self, self.config)
        if dlg.exec() == QDialog.Accepted:
            self._on_settings_saved()

    def _on_settings_saved(self):
        try:
            save_config(self.config)
        except Exception as e:
            self.log(f'[НАСТР] Не сохранить конфиг: {e}', 'error')
            return
        self.log(f'[НАСТР] Сохранено: {config_path()}', 'ok')
        self.apply_theme()

        new_root = Path(self.config['root_dir']).expanduser().resolve()
        if new_root.is_dir() and new_root != self.tree_root:
            self.set_tree_root(new_root)

    def open_help(self):
        dlg = HelpDialog(self, self.config)
        dlg.exec()
        try:
            save_config(self.config)
        except Exception:
            pass

    def open_about(self):
        QMessageBox.information(
            self, 'О программе',
            'ok-helper (Qt GUI)\n\n'
            'Транслит и умная проверка имён файлов; работа с FTP.\n'
            'Интерфейс на PySide6.\n\n'
            f'Конфиг: {config_path()}')

    # ---------- close ----------
    def closeEvent(self, event):
        self._stop_watch()
        super().closeEvent(event)


# ====================== диалоги ======================

class SettingsDialog(QDialog):
    def __init__(self, parent, config: dict):
        super().__init__(parent)
        self.setWindowTitle('Настройки')
        self.setMinimumWidth(620)
        self.config = config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setSpacing(8)

        self.fields: Dict[str, QLineEdit] = {}

        def add_field(label: str, key: str, password=False):
            e = QLineEdit(str(config.get(key, '')))
            if password:
                e.setEchoMode(QLineEdit.Password)
            self.fields[key] = e
            form.addRow(label, e)

        add_field('Корневая папка', 'root_dir')
        add_field('Папка загрузок', 'downloads_dir')

        layout.addLayout(form)

        self.watch_cb = QCheckBox('Следить за папкой загрузок')
        self.watch_cb.setChecked(bool(config.get('watch_downloads', False)))
        layout.addWidget(self.watch_cb)

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel('Тема интерфейса'))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(['auto', 'light', 'dark'])
        self.theme_combo.setCurrentText(config.get('theme', 'auto'))
        theme_row.addWidget(self.theme_combo)
        theme_row.addWidget(QLabel('  auto — по системной теме'))
        theme_row.addStretch(1)
        layout.addLayout(theme_row)

        self.help_cb = QCheckBox('Показывать справку при старте')
        self.help_cb.setChecked(
            bool(config.get('help_visible_at_start', True)))
        layout.addWidget(self.help_cb)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        ftp_form = QFormLayout()
        ftp_form.setSpacing(8)

        def add_ftp(label: str, key: str, password=False):
            e = QLineEdit(str(config.get(key, '')))
            if password:
                e.setEchoMode(QLineEdit.Password)
            self.fields[key] = e
            ftp_form.addRow(label, e)

        add_ftp('FTP хост', 'ftp_host')
        add_ftp('FTP порт', 'ftp_port')
        add_ftp('FTP логин', 'ftp_user')
        add_ftp('FTP пароль', 'ftp_password', password=True)
        add_ftp('FTP путь', 'ftp_path')

        layout.addLayout(ftp_form)

        self.ftp_readonly_cb = QCheckBox(
            'FTP: режим эмуляции (read-only)')
        self.ftp_readonly_cb.setChecked(
            bool(config.get('ftp_readonly', False)))
        layout.addWidget(self.ftp_readonly_cb)

        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('Сохранить')
        buttons.button(QDialogButtonBox.Cancel).setText('Отмена')
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self):
        root = self.fields['root_dir'].text().strip()
        if not Path(root).expanduser().is_dir():
            QMessageBox.critical(self, 'Ошибка',
                                 f'root_dir не директория:\n{root}')
            return
        dl = self.fields['downloads_dir'].text().strip()
        if not Path(dl).expanduser().is_dir():
            QMessageBox.critical(self, 'Ошибка',
                                 f'downloads_dir не директория:\n{dl}')
            return
        try:
            port = int(self.fields['ftp_port'].text() or 21)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            QMessageBox.critical(self, 'Ошибка',
                                 'Некорректный FTP порт')
            return

        theme = self.theme_combo.currentText().strip() or 'auto'
        if theme not in ('auto', 'dark', 'light'):
            theme = 'auto'

        c = self.config
        c['root_dir'] = root
        c['downloads_dir'] = dl
        c['watch_downloads'] = bool(self.watch_cb.isChecked())
        c['theme'] = theme
        c['help_visible_at_start'] = bool(self.help_cb.isChecked())
        c['ftp_host'] = self.fields['ftp_host'].text().strip()
        c['ftp_port'] = port
        c['ftp_user'] = self.fields['ftp_user'].text().strip()
        c['ftp_password'] = self.fields['ftp_password'].text()
        c['ftp_path'] = self.fields['ftp_path'].text().strip() or '/'
        c['ftp_readonly'] = bool(self.ftp_readonly_cb.isChecked())
        c['root_dir_resolved'] = Path(root).expanduser().resolve()
        c['downloads_dir_resolved'] = Path(dl).expanduser().resolve()

        self.accept()


class HelpDialog(QDialog):
    HELP_TEXT = """\
Горячие клавиши:
  F1        Справка
  Ctrl+O    Выбрать директорию
  F5        Обновить список файлов
  Ctrl+F5   Исправить все файлы
  F2        Переименовать выделенный файл
  Ctrl+N    Создать папку
  Ctrl+X    Переместить файл в другую папку
  Ctrl+Y    Копировать имя выделенного
  F12       Загрузить файл на FTP
  Delete    Удалить файл на FTP (во вкладке FTP)
  F10       Настройки

Работа с деревом «Файлы»:
  Двойной клик по папке  — раскрыть / свернуть
  Двойной клик по файлу  — открыть системным приложением
  Enter на папке         — сделать корнем дерева
  Правый клик            — контекстное меню

FTP — автоподстановка пути:
  На вкладке FTP есть чек-бокс «Следить за папкой из «Файлы»».
  Если он включён, при переходе на вкладку FTP сервис ищет вверх по
  дереву папку вида ГГГГ-ММ-ДД_Место от выделенного элемента (или от
  корня, если ничего не выделено). Если находит — подставляет её в
  путь FTP и грузит листинг.

Правила именования:
  .gpx / .plt — формат ГГГГММДД_Позывной.
    – первая буква позывного — заглавная (lisa → Lisa);
    – хвостовой номер — минимум 2 разряда, разделитель _/- перед
      цифрами убирается:
        lisa_1        → Lisa01
        lisa1         → Lisa01
        lisa-2        → Lisa02
        lisa_12       → Lisa12
      то же для номера в середине:
        Lisa_03_Test  → Lisa03_Test
        Lisa_04_1     → Lisa04_1
    – если база уже оканчивается цифрой — хвостовая группа _N/-N не
      трогается: Lisa01_1 → Lisa01_1;
    – дата может быть взята из содержимого .gpx (последняя <time>),
      если её нет в имени;
    – имена вида <1-4 цифры>m.gpx (100m.gpx) не проверяются.

  .wpt — только Waypoints_ГГГГММДД.
  Остальные расширения не проверяются.

FTP — что можно отправить:
  • .plt — с корректным именем;
  • .wpt — только Waypoints_ГГГГММДД;
  • .gpx — только <1-4 цифры>m.gpx;
  • файлы из папки 10-Tracks не отправляются;
  • папка назначения обязательна (залить в корень нельзя).

FTP-синхронизация:
  Файлы, залитые на FTP, помечаются в дереве «Файлы» значком ✓.
  Сверка выполняется при каждой загрузке листинга FTP и после каждой
  успешной загрузки файла.

Режим эмуляции FTP:
  ftp_readonly = true — сервис реально подключается и читает папки,
  но не создаёт папки, не загружает и не удаляет файлы.

Тема интерфейса:
  Настройка «theme» в F10:
    auto  — по системной теме Windows;
    light — светлая;
    dark  — тёмная.
"""

    def __init__(self, parent, config: dict):
        super().__init__(parent)
        self.setWindowTitle('Справка')
        self.setMinimumSize(760, 560)
        self.config = config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        self.show_cb = QCheckBox('Показывать при старте')
        self.show_cb.setChecked(
            bool(config.get('help_visible_at_start', True)))
        self.show_cb.toggled.connect(
            lambda v: self.config.__setitem__(
                'help_visible_at_start', bool(v)))
        layout.addWidget(self.show_cb)

        edit = QPlainTextEdit()
        edit.setPlainText(self.HELP_TEXT)
        edit.setReadOnly(True)
        layout.addWidget(edit, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText('Закрыть')
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


class RenameDialog(QDialog):
    def __init__(self, parent, path: Path):
        super().__init__(parent)
        self.setWindowTitle('Переименование')
        self.setMinimumWidth(620)
        self.path = path
        self.result: Optional[str] = None

        info = analyze_file(path)
        self.suggestion = info['new_name'] or path.name

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(8)

        lbl_old = QLabel(path.name)
        lbl_old.setObjectName('Dim')
        form.addRow('Было:', lbl_old)

        lbl_sugg = QLabel(self.suggestion)
        lbl_sugg.setStyleSheet('font-weight:600;')
        form.addRow('Предложение:', lbl_sugg)

        self.edit = QLineEdit(self.suggestion)
        self.edit.selectAll()
        form.addRow('Новое имя:', self.edit)

        layout.addLayout(form)

        hint = QLabel('Ctrl+T — транслит + нормализация')
        hint.setObjectName('Dim')
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Применить')
        buttons.button(QDialogButtonBox.Cancel).setText('Отмена')
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        act = QAction(self)
        act.setShortcut(QKeySequence('Ctrl+T'))
        act.triggered.connect(self._translit)
        self.addAction(act)

        self.edit.setFocus()

    def _translit(self):
        text = self.edit.text()
        new = transliterate(text)
        stem, dot, suffix = new.partition('.')
        if '_' in stem:
            date, _, callsign = stem.partition('_')
            if date.isdigit() and len(date) == 8 and callsign:
                callsign = normalize_callsign(sanitize_callsign(callsign))
                new = f'{date}_{callsign}{dot}{suffix}'
        self.edit.setText(new)

    def _apply(self):
        value = self.edit.text().strip()
        if not value:
            return
        self.result = value
        self.accept()


class NewFolderDialog(QDialog):
    def __init__(self, parent, config: dict, default_dir: Path):
        super().__init__(parent)
        self.setWindowTitle('Новая папка')
        self.setMinimumWidth(620)
        self.config = config
        self.default_dir = default_dir
        self.result: Optional[Path] = None
        self.with_10_tracks = False

        is_root = False
        root_dir = config.get('root_dir_resolved')
        if root_dir:
            try:
                is_root = (Path(root_dir).resolve()
                           == default_dir.resolve())
            except Exception:
                is_root = False
        self.is_root = is_root

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(8)

        lbl_dir = QLabel(str(default_dir))
        lbl_dir.setObjectName('Dim')
        form.addRow('Где:', lbl_dir)

        initial = datetime.now().strftime('%Y-%m-%d_') if is_root else ''
        self.edit = QLineEdit(initial)
        self.edit.setFocus()
        form.addRow('Имя:', self.edit)
        layout.addLayout(form)

        hint = QLabel('Ctrl+T — транслит в латиницу')
        hint.setObjectName('Dim')
        layout.addWidget(hint)

        if is_root:
            self.tracks_cb = QCheckBox('Создать внутри 10-Tracks')
            self.tracks_cb.setChecked(False)
            layout.addWidget(self.tracks_cb)
        else:
            self.tracks_cb = None

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Создать')
        buttons.button(QDialogButtonBox.Cancel).setText('Отмена')
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        act = QAction(self)
        act.setShortcut(QKeySequence('Ctrl+T'))
        act.triggered.connect(
            lambda: self.edit.setText(transliterate(self.edit.text())))
        self.addAction(act)

    def _apply(self):
        value = self.edit.text().strip()
        if not value:
            return
        ok, reason = validate_new_folder_name(value)
        if not ok:
            QMessageBox.critical(self, 'Ошибка', reason)
            return
        self.result = self.default_dir / value
        if self.tracks_cb is not None:
            self.with_10_tracks = bool(self.tracks_cb.isChecked())
        self.accept()


class MoveDialog(QDialog):
    def __init__(self, parent, src: Path, initial_dir: Path):
        super().__init__(parent)
        self.setWindowTitle('Перемещение файла')
        self.setMinimumSize(620, 480)
        self.src = src
        self.result: Optional[Path] = None
        self.current_dir = initial_dir.resolve()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        lbl_file = QLabel(f'Файл: {src.name}')
        f = lbl_file.font()
        f.setBold(True)
        lbl_file.setFont(f)
        layout.addWidget(lbl_file)

        lbl_from = QLabel(f'Из: {src.parent}')
        lbl_from.setObjectName('Dim')
        layout.addWidget(lbl_from)

        nav = QHBoxLayout()
        btn_up = QPushButton('↑ Вверх')
        btn_up.clicked.connect(self._up)
        nav.addWidget(btn_up)
        self.path_lbl = QLabel(str(self.current_dir))
        self.path_lbl.setObjectName('Dim')
        nav.addWidget(self.path_lbl, 1)
        layout.addLayout(nav)

        self.model = QStandardItemModel(self)
        self.model.setHorizontalHeaderLabels(['Имя', 'Тип'])
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setUniformRowHeights(True)
        self.tree.doubleClicked.connect(self._enter)
        self.tree.activated.connect(self._enter)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        layout.addWidget(self.tree, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('Переместить сюда')
        buttons.button(QDialogButtonBox.Cancel).setText('Отмена')
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._populate()

    def _populate(self):
        self.model.removeRows(0, self.model.rowCount())
        self.path_lbl.setText(str(self.current_dir))
        style = QApplication.style()
        try:
            children = sorted(
                self.current_dir.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except OSError:
            return
        for p in children:
            name_item = QStandardItem(p.name)
            name_item.setEditable(False)
            name_item.setData(str(p), Qt.UserRole + 3)
            if p.is_dir():
                name_item.setIcon(style.standardIcon(QStyle.SP_DirIcon))
                type_item = QStandardItem('папка')
            else:
                name_item.setIcon(style.standardIcon(QStyle.SP_FileIcon))
                type_item = QStandardItem('файл')
            type_item.setEditable(False)
            self.model.appendRow([name_item, type_item])

    def _up(self):
        parent = self.current_dir.parent
        if parent == self.current_dir:
            return
        self.current_dir = parent
        self._populate()

    def _enter(self, index: QModelIndex):
        item = self.model.itemFromIndex(index)
        if item is None:
            return
        p_str = item.data(Qt.UserRole + 3)
        if not p_str:
            return
        p = Path(p_str)
        if p.is_dir():
            self.current_dir = p
            self._populate()

    def _accept(self):
        if self.current_dir.resolve() == self.src.parent.resolve():
            QMessageBox.information(self, 'Перемещение',
                                    'Файл уже в этой папке')
            return
        self.result = self.current_dir
        self.accept()


# ====================== точка входа ======================

def run_gui(initial_dir: Path, config: dict):
    config = dict(config)
    if initial_dir and initial_dir.is_dir():
        config['root_dir_resolved'] = initial_dir

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName('ok-helper')

    window = MainWindow(config, initial_dir)
    window.show()

    if config.get('first_run', True):
        config['first_run'] = False
        try:
            save_config(config)
        except Exception:
            pass

        def on_first_run():
            dlg = SettingsDialog(window, config)
            if dlg.exec() == QDialog.Accepted:
                window._on_settings_saved()
            if config.get('help_visible_at_start', True):
                HelpDialog(window, config).exec()
                try:
                    save_config(config)
                except Exception:
                    pass

        QTimer.singleShot(150, on_first_run)
    elif config.get('help_visible_at_start', True):
        QTimer.singleShot(150,
                          lambda: HelpDialog(window, config).exec())

    sys.exit(app.exec())