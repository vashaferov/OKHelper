"""Тесты FTP-специфичной валидации (ok_helper.ftp)."""

import pytest
from pathlib import Path

from ok_helper.ftp import (
    ALLOWED_UPLOAD_EXTENSIONS,
    find_target_folder,
    is_uploadable,
    upload_extensions_hint,
    validate_folder_name,
)


def touch(p: Path) -> Path:
    p.write_text('')
    return p


# ─────────────────────────────────────────────────────────────────
# 1. validate_folder_name — формат ГГГГ-ММ-ДД_Место
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name', [
    '2026-09-23_Moscow',
    '2026-09-23_moscow',
    '2026-09-23_Moscow-1',
    '2026-09-23_ivan_1',
    '2026-09-23_a',
    '2026-09-23_123',
    '2026-12-31_NewYear',
    '2026-01-01_Start',
])
def test_folder_name_valid(name):
    ok, reason = validate_folder_name(name)
    assert ok is True, f'{name}: {reason}'


@pytest.mark.parametrize('name,reason_part', [
    ('',                  'пустое'),       # пусто
    ('   ',               'пустое'),       # пробелы
    ('2026-09-23_Москва', 'формат'),       # кириллица в Месте
    ('2026-09-23_',       'формат'),       # пустое Место
    ('2026-09-23',        'формат'),       # нет Места
    ('23-09-2026_Moscow', 'формат'),       # порядок даты
    ('2026/09/23_Moscow', 'формат'),       # неверный разделитель
    ('2026-09-23 Moscow', 'формат'),       # пробел
    ('2026-09-23_Moscow/', 'формат'),      # слэш
    ('Moscow_2026-09-23', 'формат'),       # порядок частей
    ('2026-13-01_Moscow', 'дата'),         # месяц 13
    ('2026-00-15_Moscow', 'дата'),         # месяц 0
    ('2026-09-32_Moscow', 'дата'),         # день 32
    ('2026-09-00_Moscow', 'дата'),         # день 0
])
def test_folder_name_invalid(name, reason_part):
    ok, reason = validate_folder_name(name)
    assert ok is False
    assert reason_part in reason


def test_folder_name_whitespace_trimmed():
    """Ведущие/хвостовые пробелы обрезаются, имя валидно."""
    ok, _ = validate_folder_name('  2026-09-23_Moscow  ')
    assert ok is True


# ─────────────────────────────────────────────────────────────────
# 2. find_target_folder — идём вверх по дереву
# ─────────────────────────────────────────────────────────────────

def test_find_target_folder_direct(tmp_path):
    folder = tmp_path / '2026-09-23_Moscow'
    folder.mkdir()
    name, found = find_target_folder(folder)
    assert found is True
    assert name == '2026-09-23_Moscow'


def test_find_target_folder_walks_up(tmp_path):
    folder = tmp_path / '2026-09-23_Moscow'
    folder.mkdir()
    sub = folder / '10-Tracks'
    sub.mkdir()
    name, found = find_target_folder(sub)
    assert found is True
    assert name == '2026-09-23_Moscow'


def test_find_target_folder_deep_walk_up(tmp_path):
    folder = tmp_path / '2026-09-23_Moscow'
    folder.mkdir()
    deep = folder / 'a' / 'b' / 'c'
    deep.mkdir(parents=True)
    name, found = find_target_folder(deep)
    assert found is True
    assert name == '2026-09-23_Moscow'


def test_find_target_folder_not_found(tmp_path):
    sub = tmp_path / 'foo' / 'bar'
    sub.mkdir(parents=True)
    name, found = find_target_folder(sub)
    assert found is False
    assert name == 'bar'    # возвращает имя start'а


def test_find_target_folder_respects_max_levels(tmp_path):
    """Глубокое дерево без подходящей папки — не находим."""
    deep = tmp_path
    for i in range(10):
        deep = deep / f'lvl{i}'
    deep.mkdir(parents=True)
    name, found = find_target_folder(deep, max_levels=3)
    assert found is False


# ─────────────────────────────────────────────────────────────────
# 3. is_uploadable — расширение + общая валидация
# ─────────────────────────────────────────────────────────────────

def test_allowed_extensions_constant():
    """Проверяем ожидаемый состав разрешённых расширений."""
    assert ALLOWED_UPLOAD_EXTENSIONS == {'.gpx', '.plt', '.wpt'}


@pytest.mark.parametrize('ext', ['.txt', '.mp3', '.jpg', '.zip', '.GPX '.strip(), ''])
def test_is_uploadable_rejects_other_extensions(tmp_path, ext):
    """Нецелевые расширения → False даже если имя идеально."""
    p = tmp_path / f'20260923_ivanov{ext}'
    assert is_uploadable(p, {'has_error': False}) is False


def test_is_uploadable_gpx_valid(tmp_path):
    p = touch(tmp_path / '20260923_ivanov.gpx')
    assert is_uploadable(p) is True


def test_is_uploadable_plt_valid(tmp_path):
    p = touch(tmp_path / '20260923_ivanov.plt')
    assert is_uploadable(p) is True


def test_is_uploadable_wpt_valid(tmp_path):
    p = touch(tmp_path / 'Waypoints_20260923.wpt')
    assert is_uploadable(p) is True


def test_is_uploadable_gpx_with_m_suffix(tmp_path):
    """Исключение <1-4 цифры>m.gpx проходит валидацию."""
    p = touch(tmp_path / '100m.gpx')
    assert is_uploadable(p) is True


def test_is_uploadable_gpx_invalid_name(tmp_path):
    """Правильное расширение, но имя без даты → False."""
    p = touch(tmp_path / 'track.gpx')
    assert is_uploadable(p) is False


def test_is_uploadable_gpx_placeholder(tmp_path):
    """Заглушка с ошибкой → не отправляем, пока не поправят."""
    p = touch(tmp_path / '2026-09-23 Безымянный трек.gpx')
    assert is_uploadable(p) is False


def test_is_uploadable_wpt_wrong_name(tmp_path):
    p = touch(tmp_path / 'random.wpt')
    assert is_uploadable(p) is False


def test_is_uploadable_case_insensitive_extension(tmp_path):
    p = touch(tmp_path / '20260923_ivanov.GPX')
    assert is_uploadable(p) is True


def test_is_uploadable_uses_precomputed_info(tmp_path):
    """Если info передан явно — analyze_file не вызывается повторно.
    Передаём заведомо неверный info на валидный файл — ждём False."""
    p = touch(tmp_path / '20260923_ivanov.gpx')
    assert is_uploadable(p, {'has_error': True}) is False


# ─────────────────────────────────────────────────────────────────
# 4. upload_extensions_hint — подсказка для сообщений
# ─────────────────────────────────────────────────────────────────

def test_upload_extensions_hint_mentions_all():
    hint = upload_extensions_hint()
    assert '.gpx' in hint
    assert '.plt' in hint
    assert '.wpt' in hint
    assert 'цифр' in hint or 'm.gpx' in hint


# ─────────────────────────────────────────────────────────────────
# 5. Сквозные сценарии: имя и расширение вместе
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name,expected', [
    # всё ок
    ('20260923_ivanov.gpx',         True),
    ('20260923_ivanov.plt',         True),
    ('100m.gpx',                    True),
    ('9999m.gpx',                   True),
    ('Waypoints_20260923.wpt',      True),
    # имя не проходит общую валидацию
    ('track.gpx',                   False),
    ('2026-09-23 Иванов.gpx',       False),  # в исходном виде — ошибка
    ('20260923_Иванов.gpx',         False),  # без [Правки] не отправляем
    ('12345m.gpx',                  False),  # >4 цифр
    ('random.wpt',                  False),
    # расширение вне списка
    ('notes.txt',                   False),
    ('20260923_ivanov.mp3',         False),
])
def test_upload_matrix(tmp_path, name, expected):
    p = touch(tmp_path / name)
    assert is_uploadable(p) is expected
