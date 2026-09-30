"""Цветовые темы: тёмная и светлая палитры + автодетект.

Основные цвета схемы:
  • оранжевый (#ff8700 / #d75f00) — акценты, папки, активные элементы;
  • белый     (#ffffff)           — основной текст, значения;
  • жёлтый    (#ffd700)           — предупреждения, подсказки;
  • серый     (#a8a8a8 / #808080) — второстепенный текст, рамки.
"""

import os
import re

from prompt_toolkit.styles import Style


_PALETTE_DARK = {
    'border':             '#585858',
    'title':              '#a8a8a8',
    'title.focus':        'bold #000000 bg:#ff8700',
    'frame.border':       '#585858',
    'frame.title':        '#a8a8a8',

    'tree.dir':           'bold #ff8700',
    'tree.file':          '#ffffff',
    'tree.err':           'bold #ff5f5f',
    'tree.sel':           'reverse',

    'btn':                'bold #000000 bg:#87d787',
    'btn.med':            'bold #000000 bg:#ffd700',
    'btn.warn':           'bold #000000 bg:#ff8700',
    'btn.ftp':            'bold #000000 bg:#5fd7ff',
    'btn.del':            'bold #ffffff bg:#af0000',
    'btn.dis':            '#808080',

    'dim':                '#808080',

    'status.sep':         '#585858',
    'status.key':         '#a8a8a8',
    'status.val':         'bold #ffffff',
    'status.err':         'bold #ff5f5f',
    'status.ok':          '#87d787',
    'status.hint':        '#ffd700',
    'status.sugg':        'bold #ff8700',
    'status.dl':          'bold #ffaf5f',

    'modal':              'default bg:#2d2d2d',
    'modal.bg':           'default bg:#2d2d2d',
    'modal.border':       'bold #ff8700 bg:#2d2d2d',
    'modal.title':        'bold #000000 bg:#ff8700',

    'cfg.label':          '#a8a8a8 bg:#2d2d2d',
    'cfg.path':           '#ffffff bg:#2d2d2d',
    'cfg.hint':           '#808080 bg:#2d2d2d',

    'log.time':           '#808080',
    'log.msg':            '#e4e4e4',
    'log.tag.text':       '#e4e4e4',
    'log.tag.info':       '#a8a8a8',
    'log.tag.ok':         'bold #87d787',
    'log.tag.warn':       'bold #ffd700',
    'log.tag.error':      'bold #ff5f5f',
    'log.tag.dir':        'bold #ff8700',
    'log.tag.dl':         'bold #ffaf5f',
    'log.tag.cfg':        '#a8a8a8',
    'log.tag.move':       '#ffaf5f',
    'log.tag.open':       '#5fd7ff',
    'log.tag.undo':       'bold #ffd700',
    'log.tag.translit':   '#ffffff',

    'tab.active':         'bold #000000 bg:#ff8700',
    'tab.inactive':       '#a8a8a8 bg:#2d2d2d',
}


_PALETTE_LIGHT = {
    'border':             '#808080',
    'title':              '#585858',
    'title.focus':        'bold #ffffff bg:#d75f00',
    'frame.border':       '#808080',
    'frame.title':        '#585858',

    'tree.dir':           'bold #d75f00',
    'tree.file':          '#000000',
    'tree.err':           'bold #d70000',
    'tree.sel':           'reverse',

    'btn':                'bold #ffffff bg:#5faf5f',
    'btn.med':            'bold #000000 bg:#d7af00',
    'btn.warn':           'bold #ffffff bg:#d75f00',
    'btn.ftp':            'bold #ffffff bg:#0087af',
    'btn.del':            'bold #ffffff bg:#d70000',
    'btn.dis':            '#808080',

    'dim':                '#585858',

    'status.sep':         '#808080',
    'status.key':         '#585858',
    'status.val':         'bold #000000',
    'status.err':         'bold #d70000',
    'status.ok':          '#008700',
    'status.hint':        '#875f00',
    'status.sugg':        'bold #d75f00',
    'status.dl':          'bold #af5f00',

    'modal':              'default bg:#f0f0f0',
    'modal.bg':           'default bg:#f0f0f0',
    'modal.border':       'bold #d75f00 bg:#f0f0f0',
    'modal.title':        'bold #ffffff bg:#d75f00',

    'cfg.label':          '#585858 bg:#f0f0f0',
    'cfg.path':           '#000000 bg:#f0f0f0',
    'cfg.hint':           '#808080 bg:#f0f0f0',

    'log.time':           '#808080',
    'log.msg':            '#000000',
    'log.tag.text':       '#000000',
    'log.tag.info':       '#585858',
    'log.tag.ok':         'bold #008700',
    'log.tag.warn':       'bold #875f00',
    'log.tag.error':      'bold #d70000',
    'log.tag.dir':        'bold #d75f00',
    'log.tag.dl':         'bold #af5f00',
    'log.tag.cfg':        '#585858',
    'log.tag.move':       '#af5f00',
    'log.tag.open':       '#0087af',
    'log.tag.undo':       'bold #875f00',
    'log.tag.translit':   '#000000',

    'tab.active':         'bold #ffffff bg:#d75f00',
    'tab.inactive':       '#585858 bg:#f0f0f0',
}


def _detect_terminal_theme() -> str:
    val = os.environ.get('COLORFGBG', '')
    if not val:
        return 'dark'
    parts = [p for p in re.split(r'[;:]', val) if p.strip().isdigit()]
    if not parts:
        return 'dark'
    try:
        bg = int(parts[-1])
    except ValueError:
        return 'dark'
    return 'light' if bg in (7, 9, 10, 11, 12, 13, 14, 15) else 'dark'


def build_style(theme: str) -> Style:
    if theme not in ('auto', 'dark', 'light'):
        theme = 'auto'
    if theme == 'auto':
        theme = _detect_terminal_theme()
    palette = _PALETTE_LIGHT if theme == 'light' else _PALETTE_DARK
    return Style.from_dict(palette)
