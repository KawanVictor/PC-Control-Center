"""Base das classes de aba da Personalização.

Cada aba é uma classe auxiliar que a PersonalizationPage herda. Para o verificador de tipos, a
base descreve o que as abas usam da página (Page, cartões, histórico...). Ao rodar, é só ``object``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...components import GlassCard
    from ..base import Page
    from .tweak_row import TweakRow

    class _PageParts(Page):
        rows: list[TweakRow]
        restart_card: GlassCard
        _loaded: set[str]

        def _section(self, title: str, glyph: str) -> GlassCard: ...
        def _tweak_rows(self, card: GlassCard, section: str) -> None: ...
        def changed(self, needs_restart: bool = False) -> None: ...
        def _load_history(self) -> None: ...
else:
    _PageParts = object


class PersonalizationTab(_PageParts):
    """Base das abas: herdada junto com Page pela PersonalizationPage."""
