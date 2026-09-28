"""Общие фикстуры и настройка импорта для тестов."""

import sys
from pathlib import Path

# Корень проекта — на sys.path, чтобы `import ok_helper` работал
# независимо от того, из какой директории запущен pytest.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
