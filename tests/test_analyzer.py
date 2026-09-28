"""Тесты общей валидации имён файлов (ok_helper.analyzer)."""

import pytest
from pathlib import Path

from ok_helper.analyzer import analyze_file, sanitize_callsign


def touch(p: Path) -> Path:
    """Создаёт пустой файл — analyze_file() требует path.is_file()."""
    p.write_text('')
    return p


# ─────────────────────────────────────────────────────────────────
# 1. Уже валидный формат ГГГГММДД_Позывной для .gpx / .plt
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name', [
    '20260923_ivanov.gpx',
    '20260923_Ivanov.plt',
    '20260923_ivan-1.gpx',
    '20260923_ivan_1.plt',
    '20260923_A1B2.gpx',
    '20260923_x.plt',
])
def test_gpx_plt_already_valid(tmp_path, name):
    info = analyze_file(touch(tmp_path / name))
    assert info['has_error'] is False
    assert info['new_name'] is None


@pytest.mark.parametrize('name', [
    '20260923_ivanov.GPX',   # верхний регистр расширения
    '20260923_ivanov.Plt',
])
def test_gpx_plt_extension_case_insensitive(tmp_path, name):
    info = analyze_file(touch(tmp_path / name))
    assert info['has_error'] is False


# ─────────────────────────────────────────────────────────────────
# 2. Общая валидация .gpx / .plt: транслит позывного
# ─────────────────────────────────────────────────────────────────

def test_gpx_translit_callsign(tmp_path):
    info = analyze_file(touch(tmp_path / '20260923_Иванов.gpx'))
    assert info['has_error'] is True
    assert info['new_name'] == '20260923_Ivanov.gpx'
    assert info['confidence'] == 'high'


def test_plt_translit_callsign_with_dash(tmp_path):
    info = analyze_file(touch(tmp_path / '20260923_Радио-1.plt'))
    assert info['has_error'] is True
    assert info['new_name'] == '20260923_Radio-1.plt'
    assert info['confidence'] == 'high'


def test_gpx_callsign_unfixable(tmp_path):
    # Позывной состоит только из недопустимых символов без букв
    info = analyze_file(touch(tmp_path / '20260923_!!!.gpx'))
    assert info['has_error'] is True
    assert info['new_name'] is None


# ─────────────────────────────────────────────────────────────────
# 3. «Скачанные» имена .gpx / .plt
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name,expected', [
    ('2026-09-17_11-55_бабушка.gpx',       '20260917_babushka.gpx'),
    ('2026-09-17-11-55-бабушка.gpx',       '20260917_babushka.gpx'),
    ('2026-09-17_бабушка.gpx',             '20260917_babushka.gpx'),
    ('2026.09.17_бабушка.gpx',             '20260917_babushka.gpx'),
    ('20260917_бабушка.gpx',               '20260917_babushka.gpx'),
    ('2026-09-17_11-55_babushka.gpx',      '20260917_babushka.gpx'),
    ('2026-09-17_11-55_babushka (Копия 2).gpx',
     '20260917_babushka_Kopiya_2.gpx'),
    ('2026-09-17_11-55_бабушка (Копия 2).plt',
     '20260917_babushka_Kopiya_2.plt'),
    ('2026-09-17_11.55_бабушка.gpx',       '20260917_babushka.gpx'),
    ('2026-09-17-113045-бабушка.gpx',      '20260917_babushka.gpx'),
    ('17-09-2026_11-55_бабушка.gpx',       '20260917_babushka.gpx'),
])
def test_downloaded_gpx_plt_to_canonical(tmp_path, name, expected):
    info = analyze_file(touch(tmp_path / name))
    assert info['has_error'] is True
    assert info['new_name'] == expected
    assert info['confidence'] in ('high', 'medium')


# ─────────────────────────────────────────────────────────────────
# 4. Заглушки (низкая уверенность)
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name', [
    '2026-09-23 Безымянный трек.gpx',
    '2026-09-23-1803 Безымянный трек.gpx',
    '2026-09-23_untitled.gpx',
    '2026-09-23_track.gpx',
])
def test_placeholder_is_low_confidence(tmp_path, name):
    info = analyze_file(touch(tmp_path / name))
    assert info['has_error'] is True
    assert info['confidence'] == 'low'
    assert 'заглушк' in info['reason']


# ─────────────────────────────────────────────────────────────────
# 5. Нет даты в имени
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name', [
    'track.gpx',
    'бабушка.gpx',
    'some_random_file.plt',
])
def test_no_date_means_no_suggestion(tmp_path, name):
    info = analyze_file(touch(tmp_path / name))
    assert info['has_error'] is True
    assert info['new_name'] is None
    assert 'дата' in info['reason']


# ─────────────────────────────────────────────────────────────────
# 6. Исключение: <1-4 цифры>m.gpx — валидация не проводится
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name', [
    '1m.gpx',
    '12m.gpx',
    '999m.gpx',
    '9999m.gpx',
    '20260923_100m.gpx',
    'track_5M.gpx',      # регистронезависимо
    '1m.GPX',
    '_100m.gpx',         # цифры предварены не-цифрой
])
def test_gpx_with_m_suffix_skips_validation(tmp_path, name):
    info = analyze_file(touch(tmp_path / name))
    assert info['has_error'] is False
    assert info['new_name'] is None


@pytest.mark.parametrize('name', [
    'm.gpx',              # нет цифр
    '12345m.gpx',         # 5 цифр (>4)
    '123456m.gpx',        # 6 цифр
    'track.gpx',          # нет m-суффикса
    'track_100ms.gpx',    # после m идёт s
    'track_m100.gpx',     # m не в конце
])
def test_gpx_without_valid_m_suffix_falls_through(tmp_path, name):
    """Не подходит под исключение → идёт в общую валидацию.
    Ни одно из этих имён не пройдёт её, поэтому has_error=True."""
    info = analyze_file(touch(tmp_path / name))
    assert info['has_error'] is True


# ─────────────────────────────────────────────────────────────────
# 7. .wpt — только Waypoints_ГГГГММДД
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name', [
    'Waypoints_20260923.wpt',
    'waypoints_20260923.wpt',   # регистронезависимо
    'WAYPOINTS_20260923.WPT',
])
def test_wpt_valid(tmp_path, name):
    info = analyze_file(touch(tmp_path / name))
    assert info['has_error'] is False


def test_wpt_from_downloaded_name(tmp_path):
    info = analyze_file(touch(tmp_path / '2026-09-23_waypoints.wpt'))
    assert info['has_error'] is True
    assert info['new_name'] == 'Waypoints_20260923.wpt'
    assert info['confidence'] == 'medium'


def test_wpt_no_date(tmp_path):
    info = analyze_file(touch(tmp_path / 'waypoints.wpt'))
    assert info['has_error'] is True
    assert info['new_name'] is None
    assert 'Waypoints' in info['reason']


def test_wpt_wrong_suffix_not_canonical(tmp_path):
    # Расширение .wpt, но имя не Waypoints_ГГГГММДД и даты нет
    info = analyze_file(touch(tmp_path / 'random.wpt'))
    assert info['has_error'] is True


# ─────────────────────────────────────────────────────────────────
# 8. Прочие расширения — не проверяются
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name', [
    'notes.txt',
    'track.mp3',
    'picture.jpg',
    'archive.zip',
    'no_extension_at_all',
    'data.json',
    'script.py',
])
def test_other_extensions_not_validated(tmp_path, name):
    info = analyze_file(touch(tmp_path / name))
    assert info['has_error'] is False
    assert info['new_name'] is None


# ─────────────────────────────────────────────────────────────────
# 9. Не файл (директория, несуществующий путь)
# ─────────────────────────────────────────────────────────────────

def test_directory_is_not_checked(tmp_path):
    d = tmp_path / 'somedir'
    d.mkdir()
    info = analyze_file(d)
    assert info['has_error'] is False


def test_missing_file_is_not_checked(tmp_path):
    info = analyze_file(tmp_path / 'does_not_exist.gpx')
    assert info['has_error'] is False


# ─────────────────────────────────────────────────────────────────
# 10. sanitize_callsign — вспомогательная функция
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('inp,expected', [
    ('Ivanov',    'Ivanov'),       # уже валидный
    ('ivan-1',    'ivan-1'),
    ('Ivan_1',    'Ivan_1'),
    ('Иванов',    'Ivanov'),       # транслит
    ('Радио-1',   'Radio-1'),
    ('тест!@#',   'test'),         # вырезаем всё, кроме [A-Za-z0-9_-]
    ('Ёжик',      'Yozhik'),
    ('',          ''),
])
def test_sanitize_callsign(inp, expected):
    assert sanitize_callsign(inp) == expected
