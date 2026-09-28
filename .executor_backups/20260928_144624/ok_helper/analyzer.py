"""Анализ имён файлов.

Правила валидации:

  • .gpx и .plt — общая проверка: имя должно быть
    либо в формате «ГГГГММДД_Позывной», либо распознаваемым
    «скачанным» (дата в начале и позывной в остатке).

  • <1-4 цифры>m.gpx — исключение: валидация не проводится
    (это «метровые» треки, у них своя структура имени).

  • .wpt — только в формате Waypoints_ГГГГММДД.

  • Прочие расширения — не проверяются.
"""

import re
from pathlib import Path
from typing import Optional, Tuple

from .translit import transliterate


_LATIN_CALLSIGN_RE = re.compile(r'^[A-Za-z0-9_-]+$')
_FILENAME_RE = re.compile(r'^(\d{8})_(.+)$')

# <1-4 цифры>m.gpx — «метровый» суффикс.
# Lookbehind (?<!\d) не даёт засчитаться последним 1-4 цифрам в
# более длинной числовой последовательности: без него `12345m`
# матчилось бы как `2345m` (search), что нарушает правило
# «ровно 1-4 цифры перед m».
_GPX_M_SUFFIX_RE = re.compile(r'(?<!\d)\d{1,4}m$', re.IGNORECASE)

# Waypoints_ГГГГММДД — единственный допустимый формат .wpt.
_WPT_NAME_RE = re.compile(r'^Waypoints_(\d{8})$', re.IGNORECASE)

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

_LEADING_SEP = ' \t_-–—.'


def _ok() -> dict:
    return {'has_error': False, 'new_name': None,
            'confidence': 'none', 'reason': ''}


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
    rest = rest.lstrip(_LEADING_SEP)
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


def _analyze_gpx_plt(stem: str, suffix: str) -> dict:
    """Общая проверка имён .gpx и .plt."""
    m = _FILENAME_RE.match(stem)
    if m:
        date, cs = m.groups()
        if _LATIN_CALLSIGN_RE.match(cs):
            return _ok()
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


def _analyze_wpt(stem: str, suffix: str) -> dict:
    """Проверка имён .wpt: только Waypoints_ГГГГММДД."""
    if _WPT_NAME_RE.match(stem):
        return _ok()

    date_str, _ = _extract_date_and_rest(stem)
    if date_str:
        return {'has_error': True,
                'new_name': f'Waypoints_{date_str}{suffix}',
                'confidence': 'medium',
                'reason': 'приведём к Waypoints_ГГГГММДД'}
    return {'has_error': True, 'new_name': None,
            'confidence': 'none',
            'reason': 'нужен формат Waypoints_ГГГГММДД'}


def analyze_file(path: Path) -> dict:
    """Возвращает: has_error, new_name, confidence, reason."""
    if not path.is_file():
        return _ok()

    suffix_lower = path.suffix.lower()
    stem = path.stem
    suffix = path.suffix

    # Правило 2: <1-4 цифры>m.gpx — валидация не проводится
    if suffix_lower == '.gpx' and _GPX_M_SUFFIX_RE.search(stem):
        return _ok()

    # Правило 3: .wpt — только Waypoints_ГГГГММДД
    if suffix_lower == '.wpt':
        return _analyze_wpt(stem, suffix)

    # Правило 1: .gpx и .plt — общая проверка
    if suffix_lower in ('.gpx', '.plt'):
        return _analyze_gpx_plt(stem, suffix)

    # Прочие расширения — не проверяем
    return _ok()


def human_size(n: int) -> str:
    x = float(n)
    for unit in ('Б', 'КБ', 'МБ', 'ГБ', 'ТБ'):
        if x < 1024 or unit == 'ТБ':
            if unit == 'Б':
                return f'{int(x)} {unit}'
            return f'{x:.1f} {unit}'
        x /= 1024
    return f'{x:.1f} ТБ'
