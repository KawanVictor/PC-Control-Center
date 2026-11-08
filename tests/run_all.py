"""Executa todas as baterias de teste e mostra um resumo.

    python -m tests.run_all            padrão (~2 min): tudo, exceto o que aparece na tela
    python -m tests.run_all --full     inclui as janelas reais dos widgets e o teste de velocidade
    python -m tests.run_all --exe "dist\\PC Control Center\\PC Control Center.exe"
                                       também roda o autoteste do executável gerado

Nenhum teste altera os dados reais do usuário: os que mexem em configurações, Registro ou
widgets usam cópias temporárias, chaves de teste ou desfazem o que fizeram.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SUITES = [
    # (módulo, argumentos, descrição, só no --full)
    ("tests.test_security", [], "segurança (código e comportamento)", False),
    ("tests.test_collector", [], "coleta de hardware", False),
    ("tests.test_network", [], "Wi-Fi, interfaces e consumo", False),
    ("tests.test_ping", [], "ping, perda e estabilidade", False),
    ("tests.test_apps", [], "inicialização, processos, desinstalação", False),
    ("tests.test_widgets", [], "widgets (desenho e perfis)", False),
    ("tests.test_personalization", [], "personalização (aplica e desfaz)", False),
    ("tests.test_automation", [], "alertas, relatórios e sugestões", False),
    ("tests.test_media_scenes", [], "mídia, OBS, FPS, cenários e estilo", False),
    ("tests.ui_smoke", ["{tmp}"], "interface: todas as páginas", False),
    ("tests.test_widget_windows", [], "janelas reais dos widgets (aparecem na tela)", True),
    ("tests.test_network", ["--speed"], "teste de velocidade real (100–400 MB)", True),
]


def _run(cmd: list[str], timeout: int) -> tuple[int, float, str]:
    t = time.perf_counter()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=timeout, env=env)
        out = (p.stdout + p.stderr).decode("utf-8", "replace")
        code = p.returncode
    except subprocess.TimeoutExpired:
        code, out = -1, f"tempo esgotado ({timeout} s)"
    return code, time.perf_counter() - t, out


def main() -> int:
    full = "--full" in sys.argv
    exe = sys.argv[sys.argv.index("--exe") + 1] if "--exe" in sys.argv else None
    tmp = tempfile.mkdtemp(prefix="pccc-tests-")
    rows, failures = [], []
    jobs = [(m, a, d) for m, a, d, only_full in SUITES if full or not only_full]
    for i, (mod, args, desc) in enumerate(jobs, 1):
        print(f"[{i}/{len(jobs)}] {desc}...", flush=True)
        args = [a.format(tmp=tmp) for a in args]
        code, secs, out = _run([sys.executable, "-m", mod, *args], timeout=300)
        rows.append((desc, code == 0, secs))
        if code != 0:
            failures.append((desc, out))
    if exe:
        print("[+] autoteste do executável...", flush=True)
        code, secs, out = _run([exe, "--selftest"], timeout=120)
        log = Path(os.environ["APPDATA"]) / "PCControlCenter" / "logs" / "selftest.txt"
        rows.append(("executável --selftest", code == 0, secs))
        if code != 0:
            failures.append(("executável --selftest", log.read_text(encoding="utf-8") if log.exists() else out))

    print("\n" + "=" * 64)
    for desc, ok, secs in rows:
        print(f"  {'OK  ' if ok else 'ERRO'}  {desc:<46} {secs:5.1f} s")
    print("=" * 64)
    for desc, out in failures:
        print(f"\n--- {desc} (últimas linhas) ---")
        print("\n".join(out.strip().splitlines()[-25:]))
    passed = sum(ok for _, ok, _ in rows)
    print(f"\n{passed}/{len(rows)} baterias passaram" + ("" if full else "  (use --full para incluir as visuais)"))
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
