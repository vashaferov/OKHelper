"""Анализ имён файлов: формат ГГГГММДД_Позывной и «скачанные» имена."""

import re
from pathlib import Path
from typing import Optional, Tuple

from .translit import transliterate


_LATIN_CALLSIGN_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_FILENAME_RE = re.compile(r'^(\d{8})_(.+)$')

_DATE_PATTERNS = [
    (re.compile(r'^(\d{4})[-_.](\d{2})[-_.](\d{2})'), 'ymd'),
    (re.compile(r'^(\d{4})(\d{2})(\d{2})'),          'ymd'),
    (re.compile(r'^(\d{2})[-_.](\d{2})[-_.](\d{4})'), 'dmy'),
    (re.compile(r'^(\d{2})(\d{2})(\d{4})'),          'dmy'),
]

_STOPWORDS_LATIN = {
    'bezymyannyy', 'bezymyannaya', 'bez', 'imeni', 'untitled',
    'unnamed', 'track', 'trek', 'treka', 'gpx', 'record',
    'zapis', 'download', 'zagruzka', 'new', 'novyy', 'novaya',
}

_TIME_PREFIX_RE = re.compile(r'^\s*\d{1,2}[-_:.]?\d{2}(?:[-_:.]?\d{2})?\s*')


def sanitize_callsign(cs: str) -> str:
    if _LATIN_CALLSIGN_RE.match(cs):
        return cs
    return re.sub(r'[^A-Za-z0-9_-]', '', transliterate(cs))


def _extract_date_and_rest(stem: str) -> Tuple[Optional[str], str]:
    for pat, kind in _DATE_PATTERNS:
        m = pat.match(stem)
        if not m:
            continue
        a, b, c = m.groups()
        try:
            if kind == 'ymd':
                y, mo, d = a, b, c
            else:
                d, mo, y = a, b, c
            if not (1 <= int(mo) <= 12 and 1 <= int(d) <= 31):
                continue
            return f'{y}{mo}{d}', stem[m.end():]
        except (ValueError, IndexError):
            continue
    return None, stem


def _clean_rest(rest: str) -> Tuple[str, bool]:
    rest = rest.strip()
    rest = _TIME_PREFIX_RE.sub('', rest)
    rest = re.sub(r'[\s\-–—_.]+', '_', rest)
    rest = transliterate(rest)
    rest = re.sub(r'[^A-Za-z0-9_-]', '', rest)
    rest = re.sub(r'_+', '_', rest).strip('_-')
    if not rest:
        return '', True
    words = [w for w in re.split(r'[_-]+', rest.lower()) if w]
    is_placeholder = bool(words) and all(w in _STOPWORDS_LATIN for w in words)
    return rest, is_placeholder


def analyze_file(path: Path) -> dict:
    """Возвращает: has_error, new_name, confidence, reason."""
    if not path.is_file():
        return {'has_error': False, 'new_name': None,
                'confidence': 'none', 'reason': ''}

    stem = path.stem
    suffix = path.suffix

    m = _FILENAME_RE.match(stem)
    if m:
        date, cs = m.groups()
        if _LATIN_CALLSIGN_RE.match(cs):
            return {'has_error': False, 'new_name': None,
                    'confidence': 'none', 'reason': ''}
        new_cs = sanitize_callsign(cs)
        if new_cs and new_cs != cs:
            return {'has_error': True,
                    'new_name': f'{date}_{new_cs}{suffix}',
                    'confidence': 'high',
                    'reason': 'транслит позывного'}
        return {'has_error': True, 'new_name': None,
                'confidence': 'none', 'reason': 'позывной не исправить'}

    date_str, rest = _extract_date_and_rest(stem)
    if date_str is None:
        return {'has_error': True, 'new_name': None,
                'confidence': 'none', 'reason': 'дата в имени не найдена'}

    cleaned, is_placeholder = _clean_rest(rest)
    if not cleaned:
        return {'has_error': True, 'new_name': None,
                'confidence': 'low',
                'reason': f'дата найдена ({date_str}), позывной пуст'}
    if is_placeholder:
        return {'has_error': True,
                'new_name': f'{date_str}_{cleaned}{suffix}',
                'confidence': 'low',
                'reason': f'похоже на заглушку «{cleaned}»'}
    return {'has_error': True,
            'new_name': f'{date_str}_{cleaned}{suffix}',
            'confidence': 'medium',
            'reason': 'дата + позывной из имени'}


def human_size(n: int) -> str:
    x = float(n)
    for unit in ('Б', 'КБ', 'МБ', 'ГБ', 'ТБ'):
        if x < 1024 or unit == 'ТБ':
            if unit == 'Б':
                return f'{int(x)} {unit}'
            return f'{x:.1f} {unit}'
        x /= 1024
    return f'{x:.1f} ТБ'
