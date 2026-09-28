"""Тесты FTP-специфичной валидации (ok_helper.ftp)."""

import pytest
from pathlib import Path

from ok_helper.ftp import (
    ALLOWED_UPLOAD_EXTENSIONS,
    find_target_folder,
    is_uploadable,
    upload_extensions_hint,
    upload_reason_for,
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
    ('',                  'пустое'),
    ('   ',               'пустое'),
    ('2026-09-23_Москва', 'формат'),
    ('2026-09-23_',       'формат'),
    ('2026-09-23',        'формат'),
    ('23-09-2026_Moscow', 'формат'),
    ('2026/09/23_Moscow', 'формат'),
    ('2026-09-23 Moscow', 'формат'),
    ('2026-09-23_Moscow/', 'формат'),
    ('Moscow_2026-09-23', 'формат'),
    ('2026-13-01_Moscow', 'дата'),
    ('2026-00-15_Moscow', 'дата'),
    ('2026-09-32_Moscow', 'дата'),
    ('2026-09-00_Moscow', 'дата'),
])
def test_folder_name_invalid(name, reason_part):
    ok, reason = validate_folder_name(name)
    assert ok is False
    assert reason_part in reason


def test_folder_name_whitespace_trimmed():
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
    assert name == 'bar'


def test_find_target_folder_respects_max_levels(tmp_path):
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
    assert ALLOWED_UPLOAD_EXTENSIONS == {'.gpx', '.plt', '.wpt'}


@pytest.mark.parametrize('ext', [
    '.txt', '.mp3', '.jpg', '.zip', '.kml', '.csv', '.pdf',
])
def test_is_uploadable_rejects_other_extensions(tmp_path, ext):
    p = tmp_path / f'20260923_ivanov{ext}'
    assert is_uploadable(p, {'has_error': False}) is False


def test_is_uploadable_no_extension(tmp_path):
    p = tmp_path / '20260923_ivanov'
    assert is_uploadable(p, {'has_error': False}) is False


# --- .gpx: разрешён ТОЛЬКО как <1-4 цифры>m.gpx ---

@pytest.mark.parametrize('name', [
    '1m.gpx',
    '12m.gpx',
    '100m.gpx',
    '999m.gpx',
    '9999m.gpx',
    '20260917_100m.gpx',
    '20260917_9999m.gpx',
    'track_5M.gpx',
    '_100m.gpx',
])
def test_is_uploadable_gpx_with_m_suffix(tmp_path, name):
    """<1-4 цифры>m.gpx — можно отправить."""
    p = touch(tmp_path / name)
    assert is_uploadable(p) is True


@pytest.mark.parametrize('name', [
    # Валидное имя по общей валидации, но НЕ *m.gpx → НЕ отправляем
    '20260917_lisa_1.gpx',
    '20260917_ivanov.gpx',
    '20260923_A1B2.gpx',
    # «Скачанные» — тоже нет
    '2026-09-17_11-55_бабушка.gpx',
    # Не проходят и общую валидацию
    'track.gpx',
    'm.gpx',
    '12345m.gpx',
    'track_100ms.gpx',
    'track_m100.gpx',
    # Заглушка
    '2026-09-23 Безымянный трек.gpx',
])
def test_is_uploadable_gpx_without_m_suffix_rejected(tmp_path, name):
    """Любой .gpx, не оканчивающийся на <1-4 цифры>m, отправить нельзя."""
    p = touch(tmp_path / name)
    assert is_uploadable(p) is False


def test_is_uploadable_gpx_case_insensitive_m(tmp_path):
    """Регистр и расширения, и суффикса m не важен."""
    p = touch(tmp_path / '100M.GPX')
    assert is_uploadable(p) is True


# --- .plt: общая валидация ---

def test_is_uploadable_plt_valid(tmp_path):
    p = touch(tmp_path / '20260923_ivanov.plt')
    assert is_uploadable(p) is True


def test_is_uploadable_plt_invalid_name(tmp_path):
    p = touch(tmp_path / 'track.plt')
    assert is_uploadable(p) is False


# --- .wpt: только Waypoints_ГГГГММДД ---

def test_is_uploadable_wpt_valid(tmp_path):
    p = touch(tmp_path / 'Waypoints_20260923.wpt')
    assert is_uploadable(p) is True


def test_is_uploadable_wpt_wrong_name(tmp_path):
    p = touch(tmp_path / 'random.wpt')
    assert is_uploadable(p) is False


def test_is_uploadable_uses_precomputed_info(tmp_path):
    """Если info передан явно — analyze_file не вызывается повторно."""
    p = touch(tmp_path / '20260923_ivanov.plt')
    assert is_uploadable(p, {'has_error': True}) is False


# ─────────────────────────────────────────────────────────────────
# 4. upload_extensions_hint и upload_reason_for
# ─────────────────────────────────────────────────────────────────

def test_upload_extensions_hint_mentions_all():
    hint = upload_extensions_hint()
    assert '.gpx' in hint
    assert '.plt' in hint
    assert '.wpt' in hint
    assert 'цифр' in hint or 'm.gpx' in hint


def test_upload_reason_gpx_non_m(tmp_path):
    p = tmp_path / '20260917_lisa_1.gpx'
    reason = upload_reason_for(p)
    assert 'цифр' in reason or 'm.gpx' in reason


def test_upload_reason_other_extension(tmp_path):
    p = tmp_path / 'notes.txt'
    reason = upload_reason_for(p)
    assert 'расширение' in reason


# ─────────────────────────────────────────────────────────────────
# 5. Сквозные сценарии: имя и расширение вместе
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name,expected', [
    # .gpx — только *m.gpx
    ('1m.gpx',                      True),
    ('100m.gpx',                    True),
    ('20260917_9999m.gpx',          True),
    ('20260917_lisa_1.gpx',         False),  # регресс-тест
    ('20260917_ivanov.gpx',         False),
    ('track.gpx',                   False),
    ('12345m.gpx',                  False),
    # .plt — общая валидация
    ('20260923_ivanov.plt',         True),
    ('20260923_Иванов.plt',         False),  # нужен транслит
    # .wpt — только Waypoints_ГГГГММДД
    ('Waypoints_20260923.wpt',      True),
    ('random.wpt',                  False),
    # прочие расширения
    ('notes.txt',                   False),
    ('20260923_ivanov.mp3',         False),
])
def test_upload_matrix(tmp_path, name, expected):
    p = touch(tmp_path / name)
    assert is_uploadable(p) is expected
