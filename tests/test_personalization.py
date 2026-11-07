"""Testes da Fase 6 — toda alteração é aplicada e DESFEITA, conferindo o estado original.

* Backup em grupo + remoção das chaves criadas (chave de teste própria)
* Motor de ajustes (Tweak) com valor de teste
* Cor de destaque: reaplica a cor atual e desfaz — confere os 7 valores byte a byte
* Papel de parede: reaplica a imagem atual e desfaz — confere caminho e estilo
* Animações (SystemParametersInfo): reaplica o valor atual e desfaz
* Menu de contexto clássico: liga e desfaz — confere que a chave sumiu
* Atalho: cria numa pasta temporária e desfaz
* Leitura: temas e aplicativos padrão
No final, as entradas do teste são removidas do histórico do usuário.

Execute:  python -m tests.test_personalization
"""
import os
import sys
import tempfile
import winreg
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pccc.core import regbackup  # noqa: E402
from pccc.core.logger import setup_logging  # noqa: E402
from pccc.personalization import accent, changes, defaults, shortcuts, themes, tweaks, wallpaper  # noqa: E402

HKCU = winreg.HKEY_CURRENT_USER
TEST_KEY = r"Software\PCControlCenterTeste"


def snap(values):
    return {(p, n): regbackup.read_value(HKCU, p, n, "<ausente>") for p, n in values}


def key_exists(path):
    try:
        winreg.OpenKey(HKCU, path).Close()
        return True
    except OSError:
        return False


def main() -> int:
    setup_logging()
    db = regbackup._db()
    changes._db()
    with db._lock:
        start_bk = db._conn.execute("SELECT COALESCE(MAX(id), 0) FROM registry_backups").fetchone()[0]
        start_log = db._conn.execute("SELECT COALESCE(MAX(id), 0) FROM personalization_log").fetchone()[0]
    results = {}
    try:
        # 1. grupo + chaves criadas
        assert not key_exists(TEST_KEY)
        g = regbackup.new_group()
        regbackup.set_value(HKCU, TEST_KEY + r"\A\B", "v1", winreg.REG_DWORD, 7, "teste", g)
        regbackup.set_value(HKCU, TEST_KEY + r"\A\B", "v2", winreg.REG_SZ, "x", "teste", g)
        assert regbackup.read_value(HKCU, TEST_KEY + r"\A\B", "v1") == 7
        n = regbackup.restore_group(g)
        results["backup em grupo desfaz tudo e remove chaves criadas"] = n == 2 and not key_exists(TEST_KEY)

        # 2. motor de ajustes
        t = tweaks.Tweak("teste", "x", "Ajuste de teste", "", HKCU, TEST_KEY, "Valor",
                         [(0, "Desligado"), (1, "Ligado")], 0, toggle=True)
        assert t.current_index() == 0
        cid = t.apply(1)
        ok = t.current_index() == 1
        changes.undo(cid)
        results["ajuste aplica e desfaz"] = ok and t.current_index() == 0 and not key_exists(TEST_KEY)

        # 3. cor de destaque (mesma cor → sem mudança visível)
        acc_vals = [(accent.ACCENT, "AccentPalette"), (accent.ACCENT, "AccentColorMenu"),
                    (accent.ACCENT, "StartColorMenu"), (accent.DWM, "AccentColor"),
                    (accent.DWM, "ColorizationColor"), (accent.DWM, "ColorizationAfterglow"),
                    (accent.DESKTOP, "AutoColorization")]
        before = snap(acc_vals)
        color = accent.current()["color"]
        cid = accent.set_accent(color)
        applied = accent.current()["color"] == color
        changes.undo(cid)
        results[f"cor de destaque {color}: aplica e restaura os 7 valores"] = applied and snap(acc_vals) == before

        # 4. papel de parede (mesma imagem)
        wp, style = wallpaper.current_path(), wallpaper.current_style()
        if wp and os.path.isfile(wp):
            cid = wallpaper.set_wallpaper(wp, style)
            entry = next(h for h in changes.history(5) if h["id"] == cid)
            copy = entry["data"]["previous"]
            changes.undo(cid)
            ok = wallpaper.current_path().lower() == wp.lower() and wallpaper.current_style() == style \
                and os.path.isfile(copy)
            os.remove(copy)
            results["papel de parede: cópia de segurança, aplica e restaura"] = ok
        else:
            results["papel de parede (sem imagem atual — pulado)"] = True

        # 5. animações
        anim = tweaks.get_animations()
        cid = tweaks.set_animations(anim)
        changes.undo(cid)
        results["animações: aplica e restaura"] = tweaks.get_animations() == anim

        # 6. menu de contexto clássico
        was = tweaks.classic_menu_enabled()
        if not was:
            cid = tweaks.set_classic_menu(True)
            on = tweaks.classic_menu_enabled()
            changes.undo(cid)
            results["menu clássico: liga e desfaz (chave removida)"] = on and not tweaks.classic_menu_enabled() \
                and not key_exists(tweaks.CLASSIC_MENU)

        # 7. atalho em pasta temporária
        folder = Path(tempfile.mkdtemp())
        cid = shortcuts.create_shortcut("Teste PCCC", os.path.join(os.environ["WINDIR"], "System32", "notepad.exe"),
                                        folder=folder)
        lnk = folder / "Teste PCCC.lnk"
        made = lnk.exists()
        changes.undo(cid)
        results["atalho: cria e remove"] = made and not lnk.exists()

        # 8. leituras
        results[f"temas listados ({len(themes.list_themes())})"] = len(themes.list_themes()) > 0
        apps = defaults.list_defaults()
        results[f"apps padrão lidos ({apps[0].app_name})"] = all(a.app_name for a in apps)
        pal = accent.palette("#0078D4")
        results["paleta: 7 tons do claro ao escuro"] = len(pal) == 7 and pal[3] == (0, 120, 212) \
            and sum(pal[0]) > sum(pal[3]) > sum(pal[6])
    finally:
        # limpa o histórico do usuário (entradas criadas pelo teste) e a chave de teste
        with db._lock:
            db._conn.execute("DELETE FROM registry_backups WHERE id > ?", (start_bk,))
            db._conn.execute("DELETE FROM personalization_log WHERE id > ?", (start_log,))
            db._conn.commit()
        for sub in (TEST_KEY + r"\A\B", TEST_KEY + r"\A", TEST_KEY):
            try:
                winreg.DeleteKey(HKCU, sub)
            except OSError:
                pass

    for k, v in results.items():
        print(f"{'OK ' if v else 'FALHOU'}  {k}")
    ok = all(results.values())
    print("OK" if ok else "FALHOU")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
