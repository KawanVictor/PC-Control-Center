"""Ponto de entrada do PC Control Center.

Uso:
    python main.py              abre a janela
    python main.py --minimized  inicia na bandeja do sistema
    python main.py --debug      log detalhado
    python main.py --selftest   verificação rápida sem interface (usada para validar o .EXE)
"""
import sys


def _fatal(exc: BaseException) -> None:
    """Erro ao abrir: registra no log e mostra uma mensagem (o .EXE não tem console)."""
    import ctypes
    import traceback
    detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        from pccc.core.logger import get_logger
        get_logger("app").critical("Falha ao iniciar:\n%s", detail)
    except Exception:
        pass
    if sys.stderr is not None:
        print(detail, file=sys.stderr)
    try:
        import os
        logs = os.path.join(os.environ.get("APPDATA", ""), "PCControlCenter", "logs")
        ctypes.windll.user32.MessageBoxW(
            None, f"O PC Control Center não conseguiu iniciar:\n\n{exc}\n\nDetalhes em:\n{logs}\\app.log",
            "PC Control Center", 0x10)
    except Exception:
        pass


if __name__ == "__main__":
    if "--fps-helper" in sys.argv:          # auxiliar elevado do contador de FPS (pccc.media.fps)
        from pccc.media.fps import helper_main
        i = sys.argv.index("--fps-helper")
        sys.exit(helper_main(sys.argv[i + 1:i + 5]))
    if "--selftest" in sys.argv:
        from pccc.selftest import main as selftest
        sys.exit(selftest())
    try:
        from pccc.app import run
        sys.exit(run())
    except SystemExit:
        raise
    except BaseException as e:   # noqa: BLE001 — último recurso, sempre informa o usuário
        _fatal(e)
        sys.exit(1)
