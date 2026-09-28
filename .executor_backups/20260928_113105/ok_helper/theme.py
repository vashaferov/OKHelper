"""Цветовые темы: тёмная и светлая палитры + автодетект."""

import os
import re

from prompt_toolkit.styles import Style


_PALETTE_DARK = {
    'border':             'ansibrightblack',
    'title':              'default',
    'title.focus':        'bold reverse',
    'frame.border':       'ansibrightblack',
    'frame.title':        'default',

    'tree.dir':           'bold ansibrightcyan',
    'tree.file':          'default',
    'tree.err':           'bold ansibrightred',
    'tree.sel':           'reverse',

    'btn':                'bold default bg:ansigreen',
    'btn.med':            'bold default bg:ansicyan',
    'btn.warn':           'bold default bg:ansiyellow',
    'btn.ftp':            'bold default bg:ansiblue',
    'btn.dis':            'ansibrightblack',

    'dim':                'ansibrightblack',

    'status.sep':         'ansibrightblack',
    'status.key':         'ansibrightblue',
    'status.val':         'bold default',
    'status.err':         'bold ansibrightred',
    'status.ok':          'ansibrightgreen',
    'status.hint':        'ansibrightblue',
    'status.sugg':        'bold ansibrightyellow',
    'status.dl':          'bold ansibrightmagenta',

    'modal':              'default',
    'modal.bg':           'bg:#1c1c1c',
    'overlay':            'bg:#0a0a0a',

    'cfg.label':          'ansibrightblue',
    'cfg.path':           'default',
    'cfg.hint':           'ansibrightblack',

    'log.time':           'ansibrightblack',
    'log.msg':            'default',
    'log.tag.text':       'default',
    'log.tag.info':       'ansibrightblue',
    'log.tag.ok':         'bold ansibrightgreen',
    'log.tag.warn':       'bold ansibrightyellow',
    'log.tag.error':      'bold ansibrightred',
    'log.tag.dir':        'bold ansibrightcyan',
    'log.tag.dl':         'bold ansibrightmagenta',
    'log.tag.cfg':        'ansibrightblue',
    'log.tag.move':       'ansibrightcyan',
    'log.tag.open':       'ansicyan',
    'log.tag.undo':       'bold ansibrightyellow',
    'log.tag.translit':   'default',
}

_PALETTE_LIGHT = {
    'border':             'ansibrightblack',
    'title':              'default',
    'title.focus':        'bold reverse',
    'frame.border':       'ansibrightblack',
    'frame.title':        'default',

    'tree.dir':           'bold ansiblue',
    'tree.file':          'default',
    'tree.err':           'bold ansired',
    'tree.sel':           'reverse',

    'btn':                'bold default bg:ansigreen',
    'btn.med':            'bold default bg:ansicyan',
    'btn.warn':           'bold ansiblack bg:ansiyellow',
    'btn.ftp':            'bold default bg:ansiblue',
    'btn.dis':            'ansibrightblack',

    'dim':                'ansibrightblack',

    'status.sep':         'ansibrightblack',
    'status.key':         'ansiblue',
    'status.val':         'bold default',
    'status.err':         'bold ansired',
    'status.ok':          'ansigreen',
    'status.hint':        'ansiblue',
    'status.sugg':        'bold ansired',
    'status.dl':          'bold ansimagenta',

    'modal':              'default',
    'modal.bg':           'bg:#f0f0f0',
    'overlay':            'bg:#c8c8c8',

    'cfg.label':          'ansiblue',
    'cfg.path':           'default',
    'cfg.hint':           'ansibrightblack',

    'log.time':           'ansibrightblack',
    'log.msg':            'default',
    'log.tag.text':       'default',
    'log.tag.info':       'ansiblue',
    'log.tag.ok':         'bold ansigreen',
    'log.tag.warn':       'bold ansired',
    'log.tag.error':      'bold ansired',
    'log.tag.dir':        'bold ansiblue',
    'log.tag.dl':         'bold ansimagenta',
    'log.tag.cfg':        'ansiblue',
    'log.tag.move':       'ansicyan',
    'log.tag.open':       'ansicyan',
    'log.tag.undo':       'bold ansired',
    'log.tag.translit':   'default',
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
