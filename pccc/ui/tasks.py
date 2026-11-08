"""Executa funções demoradas fora da thread da interface e entrega o resultado por sinal."""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QThread, Signal

from ..core.logger import get_logger

log = get_logger("tasks")
_running: set["BackgroundTask"] = set()  # mantém referência até terminar


class BackgroundTask(QThread):
    done = Signal(object)      # resultado
    failed = Signal(str)       # mensagem de erro
    progress = Signal(object)  # resultado parcial (opcional)

    def __init__(self, fn: Callable[..., Any], *args, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fn, self._args = fn, args

    def run(self) -> None:
        from ..core.com import ensure_com
        ensure_com()
        try:
            self.done.emit(self._fn(*self._args))
        except Exception as e:  # noqa: BLE001 — repassado à interface
            log.exception("Tarefa em segundo plano falhou")
            self.failed.emit(str(e))


def wait_all(timeout_ms: int = 5000) -> None:
    """Espera as tarefas em andamento terminarem. Chamar ao encerrar o app: o Qt aborta o
    processo se uma QThread for destruída ainda em execução."""
    for t in list(_running):
        if t.isRunning():
            t.wait(timeout_ms)


def run_task(fn: Callable[..., Any], *args, on_done: Callable[[Any], object] | None = None,
             on_error: Callable[[str], object] | None = None) -> BackgroundTask:
    t = BackgroundTask(fn, *args)
    if on_done:
        t.done.connect(on_done)
    if on_error:
        t.failed.connect(on_error)
    _running.add(t)
    t.finished.connect(lambda: _running.discard(t))
    t.start()
    return t
