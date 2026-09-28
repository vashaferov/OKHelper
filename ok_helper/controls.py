"""FormattedTextControl с перехватом прокрутки колесиком мыши."""

from typing import Callable

from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType


class _ScrollableControl(FormattedTextControl):
    def __init__(self, on_scroll: Callable[[int], None], **kwargs):
        super().__init__(**kwargs)
        self._on_scroll = on_scroll

    def mouse_handler(self, mouse_event: MouseEvent):
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self._on_scroll(-3)
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self._on_scroll(3)
            return None
        return super().mouse_handler(mouse_event)


class TreeControl(_ScrollableControl):
    """Дерево: перехват скролла над всей панелью."""


class LogControl(_ScrollableControl):
    """Журнал: перехват скролла над всей панелью."""
