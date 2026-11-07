"""Exportar/importar o visual completo num arquivo ``.pcctema`` (JSON).

Conteúdo (cada parte é opcional):
    appearance  tema, cor e transparência do PC Control Center
    widgets     perfis de widgets (posições, cores, opções)
    scenes      cenários
    hotkeys     atalhos de teclado
    windows     modo claro/escuro e cor de destaque do Windows
    wallpaper   imagem do papel de parede (embutida) e o ajuste

Segurança na importação:
* O arquivo é só dados (JSON) — nada é executado ao abrir.
* Programas que o arquivo mandaria abrir (atalhos de widgets e "abrir programas" dos
  cenários) são listados na prévia e, por padrão, REMOVIDOS; só ficam se você marcar.
* Tamanho máximo de 40 MB; a imagem embutida precisa ser JPG/PNG/BMP válida.
* Alterações no Windows entram no Histórico de personalização (desfazíveis).
"""
from __future__ import annotations

import base64
import copy
import json
import os
import re
import time
from pathlib import Path

from .. import __version__
from ..core.config import Settings
from ..core.logger import get_logger, log_operation
from ..core.paths import data_dir

log = get_logger("bundle")

FORMAT = "pccc-theme"
MAX_BYTES = 40 * 1024 * 1024
PARTS = {"appearance": "Aparência do app", "widgets": "Widgets e perfis", "scenes": "Cenários",
         "hotkeys": "Atalhos de teclado", "windows": "Tema e cor do Windows", "wallpaper": "Papel de parede"}
APPEARANCE_KEYS = ("mode", "accent", "transparency", "animations")


# ------------------------------------------------------------------ exportar
def export(path: str | Path, parts: set[str], name: str = "") -> int:
    s = Settings.instance()
    contents: dict = {}
    if "appearance" in parts:
        contents["appearance"] = {k: s.get(f"appearance.{k}") for k in APPEARANCE_KEYS}
    if "widgets" in parts:
        from ..widgets.manager import WidgetManager
        wm = WidgetManager.instance()
        contents["widgets"] = {"active": wm.active, "profiles": copy.deepcopy(wm.profiles)}
    if "scenes" in parts:
        from . import scenes
        contents["scenes"] = scenes.scenes()
    if "hotkeys" in parts:
        from .hotkeys import bindings
        contents["hotkeys"] = bindings()
    if "windows" in parts:
        from . import accent
        from .autotheme import windows_light
        apps, system = windows_light()
        contents["windows"] = {"apps_light": apps, "system_light": system, "accent": accent.current()["color"]}
    if "wallpaper" in parts:
        from . import wallpaper
        cur = wallpaper.current_path()
        if cur and os.path.isfile(cur) and os.path.getsize(cur) < 30 * 1024 * 1024:
            contents["wallpaper"] = {"name": os.path.basename(cur), "style": wallpaper.current_style(),
                                     "data": base64.b64encode(Path(cur).read_bytes()).decode("ascii")}
    doc = {"format": FORMAT, "version": 1, "app_version": __version__, "name": name or "Meu visual",
           "created": time.strftime("%Y-%m-%d %H:%M"), "contents": contents}
    data = json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")
    Path(path).write_bytes(data)
    log_operation("bundle.export", f"{path} ({', '.join(sorted(contents))})")
    return len(data)


# ------------------------------------------------------------------ importar
def _programs_in(contents: dict) -> list[str]:
    """Todos os programas/sites que o arquivo abriria (para a prévia de segurança)."""
    out = []
    for prof in (contents.get("widgets") or {}).get("profiles", {}).values():
        for w in prof if isinstance(prof, list) else []:
            if isinstance(w, dict) and w.get("type") == "shortcuts":
                for it in (w.get("options") or {}).get("items", []) or []:
                    if isinstance(it, dict) and it.get("path"):
                        out.append(str(it["path"]))
    for sc in contents.get("scenes") or []:
        if isinstance(sc, dict):
            out += [str(p) for p in (sc.get("actions") or {}).get("launch", []) or []]
    return out


def read(path: str | Path) -> dict:
    """Lê e valida o arquivo. Retorna o documento com um resumo em ``_preview``."""
    p = Path(path)
    if p.stat().st_size > MAX_BYTES:
        raise ValueError("Arquivo grande demais (máximo 40 MB).")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("Este arquivo não é um tema do PC Control Center.") from None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or not isinstance(doc.get("contents"), dict):
        raise ValueError("Este arquivo não é um tema do PC Control Center.")
    c = doc["contents"]
    summary = []
    if isinstance(c.get("appearance"), dict):
        a = c["appearance"]
        summary.append(f"Aparência do app: modo {a.get('mode', '?')}, cor {a.get('accent', '?')}")
    if isinstance(c.get("widgets"), dict):
        profs = c["widgets"].get("profiles") or {}
        n = sum(len(v) for v in profs.values() if isinstance(v, list))
        summary.append(f"Widgets: {len(profs)} perfil(is), {n} widget(s)")
    if isinstance(c.get("scenes"), list):
        summary.append("Cenários: " + ", ".join(str(s.get("name", "?")) for s in c["scenes"] if isinstance(s, dict)))
    if isinstance(c.get("hotkeys"), dict):
        summary.append(f"Atalhos de teclado: {len(c['hotkeys'])}")
    if isinstance(c.get("windows"), dict):
        w = c["windows"]
        summary.append(f"Windows: modo {'claro' if w.get('apps_light') else 'escuro'}, cor {w.get('accent', '?')}")
    if isinstance(c.get("wallpaper"), dict):
        size = len(c["wallpaper"].get("data", "")) * 3 // 4
        summary.append(f"Papel de parede: {c['wallpaper'].get('name', 'imagem')} ({size / 1e6:.1f} MB)")
    doc["_preview"] = {"summary": summary, "programs": _programs_in(c), "parts": [k for k in PARTS if k in c]}
    return doc


def _strip_programs(contents: dict) -> None:
    for prof in (contents.get("widgets") or {}).get("profiles", {}).values():
        for w in prof if isinstance(prof, list) else []:
            if isinstance(w, dict) and w.get("type") == "shortcuts":
                (w.setdefault("options", {}))["items"] = []
    for sc in contents.get("scenes") or []:
        if isinstance(sc, dict):
            (sc.setdefault("actions", {})).pop("launch", None)


def _image_ok(data: bytes) -> bool:
    return data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"BM"))


def apply(doc: dict, parts: set[str], keep_programs: bool = False) -> list[str]:
    """Aplica as partes escolhidas. Retorna avisos (vazio = tudo certo)."""
    c = copy.deepcopy(doc["contents"])
    if not keep_programs:
        _strip_programs(c)
    s = Settings.instance()
    warnings: list[str] = []
    name = re.sub(r"[^\w\- ]", "", str(doc.get("name", "Importado")))[:40].strip() or "Importado"

    if "appearance" in parts and isinstance(c.get("appearance"), dict):
        a = c["appearance"]
        if a.get("mode") in ("dark", "light"):
            s.set("appearance.mode", a["mode"])
        if isinstance(a.get("accent"), str) and len(a["accent"]) < 40:
            s.set("appearance.accent", a["accent"])
        if isinstance(a.get("transparency"), (int, float)):
            s.set("appearance.transparency", max(0.0, min(1.0, float(a["transparency"]))))
        if isinstance(a.get("animations"), bool):
            s.set("appearance.animations", a["animations"])

    if "widgets" in parts and isinstance(c.get("widgets"), dict):
        from ..widgets.manager import WidgetManager
        from ..widgets.types import REGISTRY
        wm = WidgetManager.instance()
        imported = c["widgets"].get("profiles") or {}
        first = None
        for pname, lst in imported.items():
            if not isinstance(lst, list):
                continue
            clean = [w for w in lst if isinstance(w, dict) and w.get("type") in REGISTRY]
            target = f"{pname} ({name})" if pname in wm.profiles else str(pname)
            wm.profiles[target[:60]] = clean
            if pname == c["widgets"].get("active") or first is None:
                first = target[:60]
        wm.save()
        if first:
            wm.switch_profile(first)

    if "scenes" in parts and isinstance(c.get("scenes"), list):
        from . import scenes
        lst = scenes.scenes()
        ids = {x["id"] for x in lst}
        for sc in c["scenes"]:
            if not isinstance(sc, dict) or not sc.get("name"):
                continue
            sc = {k: sc[k] for k in ("id", "name", "glyph", "color", "description", "actions") if k in sc}
            if sc.get("id") in ids:
                sc["id"] = scenes.new_scene("")["id"]
                sc["name"] = f"{sc['name']} ({name})"
            lst.append(sc)
        scenes.save_scenes(lst)

    if "hotkeys" in parts and isinstance(c.get("hotkeys"), dict):
        from .hotkeys import HotkeyManager, parse
        valid = {}
        for action, text in c["hotkeys"].items():
            try:
                parse(str(text))
                valid[str(action)] = str(text)
            except ValueError:
                warnings.append(f"Atalho inválido ignorado: {text}")
        s.set("hotkeys.bindings", valid)
        errs = HotkeyManager.instance().apply()
        warnings += [f"Atalho em uso por outro programa: {v}" for v in errs.values()]

    if "windows" in parts and isinstance(c.get("windows"), dict):
        from . import accent
        from .tweaks import TWEAK_BY_ID
        w = c["windows"]
        for tid, key in (("apps_mode", "apps_light"), ("system_mode", "system_light")):
            if w.get(key) in (0, 1):
                TWEAK_BY_ID[tid].apply(int(w[key]))
        col = w.get("accent")
        if isinstance(col, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", col):
            accent.set_accent(col.upper())

    if "wallpaper" in parts and isinstance(c.get("wallpaper"), dict):
        from . import wallpaper
        try:
            data = base64.b64decode(c["wallpaper"].get("data", ""), validate=True)
        except ValueError:
            data = b""
        if not data or not _image_ok(data):
            warnings.append("A imagem do papel de parede no arquivo é inválida e foi ignorada.")
        else:
            ext = ".png" if data.startswith(b"\x89PNG") else ".bmp" if data.startswith(b"BM") else ".jpg"
            d = data_dir() / "wallpapers" / "importados"
            d.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^\w-]", "_", name)
            dest = d / f"{safe}_{int(time.time())}{ext}"
            dest.write_bytes(data)
            style = c["wallpaper"].get("style") if c["wallpaper"].get("style") in wallpaper.STYLES else "fill"
            wallpaper.set_wallpaper(str(dest), style)

    log_operation("bundle.import", f"{doc.get('name', '')} ({', '.join(sorted(parts))})",
                  "ok" if not warnings else "; ".join(warnings))
    return warnings
