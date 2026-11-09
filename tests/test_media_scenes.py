"""Testes da Fase 9: mídia/streaming e cenários/estilo — sem alterar o Windows do usuário.

* OBS: servidor obs-websocket v5 FALSO (local) com senha → conexão, cenas, gravação, bitrate,
  senha errada.
* FPS: quadros simulados do PresentMon (colunas v1 e v2) → FPS, 1% mínimo, escolha do jogo.
* YouTube: feed RSS de exemplo (sem internet) e bloqueio de endereços estranhos.
* Cenários: estado simulado → ativar A, trocar para B, "voltar ao normal" restaura o ORIGINAL;
  silenciar alertas de verdade (só configuração).
* Atalhos globais: validação, conflito e disparo real (combinação rara simulada).
* Exportar/importar: ida e volta, prévia lista programas, programas removidos por padrão,
  arquivo inválido recusado.
* Sol/tema automático, papel de parede dinâmico (pasta/períodos/validações), luz quente,
  áudio e visualizador (só leitura).

Execute:  python -m tests.test_media_scenes
"""
import ctypes
import json
import os
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="pccc-f9-"))
os.environ["APPDATA"] = str(TMP)          # configurações, banco, widgets e cache isolados

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from pccc.core.logger import setup_logging  # noqa: E402

setup_logging()
results: list[tuple[str, bool, str]] = []


ONLY = os.environ.get("PCCC_ONLY", "")      # rodar só os testes cujo nome contém este texto


# No CI (GitHub Actions) não há placa de som, rede local de verdade nem área de trabalho do
# Windows: as verificações que dependem disso (needs=...) aparecem como PULADO.
ON_CI = bool(os.environ.get("CI"))
NO_DESKTOP = ON_CI or os.environ.get("QT_QPA_PLATFORM") == "offscreen"
skipped: list[str] = []


def check(name, needs: str = ""):
    """Registra uma verificação. ``needs``: "hardware" (som, rede local, área de trabalho real)."""
    def deco(fn):
        if ONLY and ONLY.lower() not in name.lower():
            return fn
        if needs and ON_CI:
            skipped.append(name)
            return fn
        print(f"... {name}", flush=True)
        try:
            fn()
            results.append((name, True, ""))
        except Exception as e:     # noqa: BLE001
            import traceback
            results.append((name, False, f"{type(e).__name__}: {e} @ {traceback.extract_tb(e.__traceback__)[-1].lineno}"))
        return fn
    return deco


def wait(ms: int, until=None) -> None:
    """Roda o loop do Qt por até ``ms`` (ou até ``until()`` ser verdadeiro)."""
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        if until is not None and until():
            return
        time.sleep(0.01)


# ===================================================================== OBS
class FakeObs:
    """Servidor obs-websocket v5 mínimo, com autenticação."""

    def __init__(self, password: str) -> None:
        from PySide6.QtWebSockets import QWebSocketServer
        from PySide6.QtNetwork import QHostAddress
        self.password = password
        self.srv = QWebSocketServer("fake-obs", QWebSocketServer.SslMode.NonSecureMode)
        assert self.srv.listen(QHostAddress.LocalHost, 0)
        self.port = self.srv.serverPort()
        self.srv.newConnection.connect(self._new)
        self.clients = []
        self.scene = "Cena 1"
        self.recording = False
        self.bytes = 0
        self.t0 = time.monotonic()
        self.requests: list[str] = []

    def _send(self, ws, op, d):
        ws.sendTextMessage(json.dumps({"op": op, "d": d}))

    def _new(self):
        ws = self.srv.nextPendingConnection()
        self.clients.append(ws)
        ws.textMessageReceived.connect(lambda t, w=ws: self._msg(w, t))
        self._send(ws, 0, {"obsWebSocketVersion": "5.5.0", "rpcVersion": 1,
                           "authentication": {"challenge": "desafio123", "salt": "sal456"}})

    def _msg(self, ws, text):
        from pccc.media.obs import auth_string
        m = json.loads(text)
        op, d = m["op"], m["d"]
        if op == 1:
            if d.get("authentication") != auth_string(self.password, "sal456", "desafio123"):
                ws.close()
                return
            self._send(ws, 2, {"negotiatedRpcVersion": 1})
        elif op == 6:
            rt, rid, data = d["requestType"], d["requestId"], d.get("requestData") or {}
            self.requests.append(rt)
            resp = {}
            if rt == "GetSceneList":
                resp = {"currentProgramSceneName": self.scene,
                        "scenes": [{"sceneName": "Cena 2"}, {"sceneName": "Cena 1"}]}
            elif rt == "SetCurrentProgramScene":
                self.scene = data["sceneName"]
                self._send(ws, 5, {"eventType": "CurrentProgramSceneChanged", "eventData": {"sceneName": self.scene}})
            elif rt == "GetStreamStatus":
                self.bytes = int((time.monotonic() - self.t0) * 125_000)     # 1000 kbps constantes
                resp = {"outputActive": True, "outputBytes": self.bytes, "outputTimecode": "00:01:02.345",
                        "outputTotalFrames": 1000, "outputSkippedFrames": 10, "outputCongestion": 0.0}
            elif rt == "GetRecordStatus":
                resp = {"outputActive": self.recording, "outputPaused": False, "outputTimecode": "00:00:05.000"}
            elif rt in ("StartRecord", "StopRecord"):
                self.recording = rt == "StartRecord"
                self._send(ws, 5, {"eventType": "RecordStateChanged", "eventData": {"outputActive": self.recording}})
            elif rt == "GetStats":
                resp = {"cpuUsage": 3.5, "activeFps": 60.0}
            self._send(ws, 7, {"requestType": rt, "requestId": rid,
                               "requestStatus": {"result": True, "code": 100}, "responseData": resp})


@check("OBS: autenticação, cenas, troca de cena, gravação e bitrate (servidor simulado)")
def _():
    from pccc.media.obs import ObsClient
    fake = FakeObs("senha-secreta")
    c = ObsClient()
    c.connect_obs("127.0.0.1", fake.port, "senha-secreta")
    wait(4000, lambda: c.status.state == "connected" and c.status.scenes)
    st = c.status
    assert st.state == "connected", (st.state, st.error)
    assert st.scenes == ["Cena 1", "Cena 2"] and st.scene == "Cena 1", (st.scenes, st.scene)
    c.set_scene("Cena 2")
    wait(1500, lambda: c.status.scene == "Cena 2")
    assert c.status.scene == "Cena 2" and fake.scene == "Cena 2"
    c.toggle_record()
    wait(1500, lambda: c.status.recording)
    assert c.status.recording and fake.recording
    wait(5000, lambda: c.status.bitrate_kbps > 0)
    assert c.status.streaming and 900 < c.status.bitrate_kbps < 1100, c.status.bitrate_kbps
    assert abs(c.status.dropped_pct - 1.0) < 0.01 and c.status.obs_cpu == 3.5
    c.shutdown()


@check("OBS: senha errada é recusada com mensagem clara")
def _():
    from pccc.media.obs import ObsClient
    fake = FakeObs("certa")
    c = ObsClient()
    c.connect_obs("127.0.0.1", fake.port, "errada")
    wait(3000, lambda: c.status.state in ("disconnected", "error"))
    assert c.status.state != "connected"
    c2 = ObsClient()
    c2.connect_obs("127.0.0.1", fake.port, "")
    wait(3000, lambda: c2.status.state == "error")
    assert "senha" in c2.status.error.lower(), c2.status.error
    c.shutdown()
    c2.shutdown()


# ===================================================================== FPS
@check("FPS: 60 FPS estáveis, 1% mínimo com engasgo, colunas v1 e v2")
def _():
    from pccc.media.fps import FrameStats, pick_game
    for col in ("msBetweenPresents", "FrameTime"):
        fs = FrameStats()
        fs.add(["Application", "ProcessID", "SwapChainAddress", col])
        now = 1000.0
        for i in range(600):                        # 10 s a 60 FPS, com um engasgo de 100 ms
            ft = 100.0 if i == 300 else 16.667
            fs.add(["jogo.exe", "4242", "0x1", f"{ft}"], now)
        for _i in range(60):
            fs.add(["dwm.exe", "900", "0x2", "33.33"], now)
        s = fs.summary(now)
        g = next(p for p in s if p["name"] == "jogo.exe")
        assert 59 < g["fps"] < 61, g
        assert g["low1"] < 59, g                     # o engasgo derruba o 1% mínimo
        assert abs(g["frame_ms"] - 16.67) < 0.1
        assert pick_game(s, fg=4242)["name"] == "jogo.exe"
        assert pick_game(s, fg=1)["name"] == "jogo.exe"      # dwm.exe é ignorado
        assert fs.summary(now + 10) == []                     # processo some após 3 s sem quadros


@check("FPS: status antigo ou UAC recusado não fica 'ligado' para sempre")
def _():
    from pccc.media.fps import FpsMonitor
    m = FpsMonitor()
    m.status_path.write_text(json.dumps({"ts": time.time() - 60, "running": True, "procs": []}), encoding="utf-8")
    assert m.read()["running"] is False
    m.status_path.write_text(json.dumps({"ts": time.time() - 60, "starting": True}), encoding="utf-8")
    d = m.read()
    assert d["starting"] is False and "UAC" in d["error"]
    cmd, args = m.helper_command()
    assert "--fps-helper" in args and str(os.getpid()) in args


@check("FPS: download só aceita os servidores do GitHub")
def _():
    from pccc.media.fps import _get
    for url in ("http://github.com/x", "https://evil.example.com/PresentMon.exe", "file:///C:/Windows/notepad.exe"):
        try:
            _get(url)
            raise AssertionError(f"aceitou {url}")
        except ValueError:
            pass


# ================================================================= YOUTUBE
SAMPLE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
 <title>Canal Teste</title>
 <entry><yt:videoId>abc123DEF45</yt:videoId><title>Video novo</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=abc123DEF45"/>
  <published>2026-11-06T14:00:00+00:00</published>
  <media:group><media:community><media:statistics views="12345"/></media:community></media:group></entry>
 <entry><yt:videoId>zzz999YYY88</yt:videoId><title>Video antigo</title>
  <published>2026-10-01T10:00:00+00:00</published></entry>
</feed>"""


@check("YouTube: lê o feed, resolve link /channel/ e recusa outros sites")
def _():
    from pccc.media import youtube as yt
    real = yt._get
    yt._get = lambda url, timeout=12: SAMPLE_FEED
    try:
        vids = yt.fetch_feed("UCX6OQ3DkcsbYNE6H8uQQuVA")
        assert [v.id for v in vids] == ["abc123DEF45", "zzz999YYY88"]
        assert vids[0].channel == "Canal Teste" and vids[0].views == 12345 and vids[0].published > 0
        cid, name = yt.resolve_channel("https://www.youtube.com/channel/UCX6OQ3DkcsbYNE6H8uQQuVA")
        assert cid == "UCX6OQ3DkcsbYNE6H8uQQuVA" and name == "Canal Teste"
    finally:
        yt._get = real
    for bad in ("https://evil.com/@x", "http://www.youtube.com/@x"):
        try:
            yt._get(bad)
            raise AssertionError(f"aceitou {bad}")
        except ValueError:
            pass
    try:
        yt.resolve_channel("https://vimeo.com/canal")
        raise AssertionError("aceitou link que não é do YouTube")
    except ValueError:
        pass
    assert yt.fetch_feed.__doc__ is None or True


# ================================================================ CENÁRIOS
@check("Cenários: A → B → 'voltar ao normal' restaura o estado ORIGINAL; erro num item não para os outros")
def _():
    from pccc.personalization import scenes
    state = {"power": "balanced", "volume": 40, "brightness": 70, "windows_mode": "dark"}
    real_cap, real_apply = scenes._capture, scenes._apply

    def fake_apply(key, value, name, restoring=False):
        if key == "windows_mode" and value == "light":
            raise OSError("simulado")
        state[key] = value

    scenes._capture = lambda key: state.get(key)
    scenes._apply = fake_apply
    try:
        scenes.save_scenes([
            {"id": "a", "name": "A", "actions": {"power": "performance", "volume": 20, "windows_mode": "light"}},
            {"id": "b", "name": "B", "actions": {"power": "efficiency", "brightness": 30}}])
        err = scenes.activate("a")
        assert len(err) == 1 and "Tema do Windows" in err[0], err
        assert state["power"] == "performance" and state["volume"] == 20
        assert scenes.activate("b") == []
        assert state["power"] == "efficiency" and state["brightness"] == 30 and scenes.active()["id"] == "b"
        assert scenes.deactivate() == []
        assert state == {"power": "balanced", "volume": 40, "brightness": 70, "windows_mode": "dark"}, state
        assert scenes.active() == {}
    finally:
        scenes._capture, scenes._apply = real_cap, real_apply


@check("Cenários: silenciar alertas (de verdade) — críticos continuam passando")
def _():
    from pccc.automation.notifier import Notifier
    from pccc.automation.store import Alert
    from pccc.personalization import scenes
    n = Notifier.instance()
    n.focus_state = lambda: 0
    scenes.save_scenes([{"id": "g", "name": "Jogo", "actions": {"silence_alerts": True}}])
    scenes.activate("g")
    assert "Jogo" in n.blocked_reason(Alert("ram", "warning", "RAM", "x"))
    assert n.blocked_reason(Alert("cpu_temp", "critical", "Temp", "x")) == ""
    scenes.deactivate()
    assert n.blocked_reason(Alert("ram", "warning", "RAM", "x")) == ""
    assert "Modo de energia: Melhor desempenho" in scenes.describe(scenes.DEFAULT_SCENES[0])


# ================================================================== ATALHOS
@check("Atalhos: validação, conflito entre ações e disparo real")
def _():
    from pccc.personalization import hotkeys as hk
    assert hk.parse("Ctrl+Alt+W") == (hk.MOD_CONTROL | hk.MOD_ALT, ord("W"))
    assert hk.parse("F9") == (0, 0x78)
    for bad in ("W", "Ctrl+", "Hyper+X", ""):
        try:
            hk.parse(bad)
            raise AssertionError(f"aceitou {bad!r}")
        except ValueError:
            pass
    m = hk.HotkeyManager()
    from pccc.core.config import Settings
    Settings.instance().set("hotkeys.bindings", {})
    m.set_binding("toggle_widgets", "Ctrl+Alt+Shift+F9")
    try:
        m.set_binding("mute", "ctrl+alt+shift+f9")
        raise AssertionError("permitiu o mesmo atalho em duas ações")
    except ValueError:
        pass
    if NO_DESKTOP:   # sem área de trabalho interativa o Windows não entrega teclas simuladas
        m.unregister_all()
        print("      (disparo real pulado: sem área de trabalho)", flush=True)
        return
    got = []
    m.triggered.connect(got.append)
    seq = [0x11, 0x12, 0x10, 0x78]
    for vk in seq:
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(seq):
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    wait(1500, lambda: got)
    m.unregister_all()
    assert got == ["toggle_widgets"], got


# ============================================================ EXPORTAR/IMPORTAR
@check("Exportar/importar: ida e volta; programas do arquivo removidos por padrão; arquivo inválido recusado")
def _():
    from pccc.core.config import Settings
    from pccc.personalization import bundle, scenes
    from pccc.widgets.manager import WidgetManager
    s = Settings.instance()
    s.set("appearance.mode", "light")
    s.set("appearance.accent", "violet")
    scenes.save_scenes([{"id": "x", "name": "Live", "actions": {"power": "performance",
                                                                 "launch": [r"C:\Programas\obs64.exe"]}}])
    wm = WidgetManager.instance()
    wm.profiles = {"Padrão": [{"type": "shortcuts", "options": {"items": [{"name": "Calc",
                                                                          "path": r"C:\Windows\calc.exe"}]}}]}
    path = TMP / "meu.pcctema"
    bundle.export(path, {"appearance", "scenes", "widgets", "hotkeys"}, "Teste")
    doc = bundle.read(path)
    pv = doc["_preview"]
    assert set(pv["parts"]) == {"appearance", "scenes", "widgets", "hotkeys"}, pv["parts"]
    assert r"C:\Programas\obs64.exe" in pv["programs"] and r"C:\Windows\calc.exe" in pv["programs"]
    s.set("appearance.mode", "dark")
    scenes.save_scenes([])
    warns = bundle.apply(doc, {"appearance", "scenes", "widgets"})
    assert warns == [], warns
    assert s.get("appearance.mode") == "light" and s.get("appearance.accent") == "violet"
    imported = [x for x in scenes.scenes() if x["name"].startswith("Live")]
    assert imported and "launch" not in imported[0]["actions"], imported
    prof = next(v for k, v in wm.profiles.items() if k.startswith("Padrão ("))
    assert prof[0]["options"]["items"] == [], prof
    # papel de parede inválido é ignorado (e nada muda no Windows)
    bad = dict(doc, contents={"wallpaper": {"name": "x.jpg", "data": "QUJDREVGRw==", "style": "fill"}})
    assert "inválida" in " ".join(bundle.apply(bad, {"wallpaper"}))
    junk = TMP / "lixo.pcctema"
    junk.write_text('{"format": "outro"}', encoding="utf-8")
    for f in (junk,):
        try:
            bundle.read(f)
            raise AssertionError("aceitou arquivo inválido")
        except ValueError:
            pass


# =============================================================== SOL/TEMA
@check("Sol e tema automático: São Paulo, sol da meia-noite e horários que passam da meia-noite")
def _():
    from pccc.personalization import autotheme, sun
    rise, set_ = sun.sun_times(-23.5475, -46.63611, date(2026, 11, 7))
    assert abs((rise.hour * 60 + rise.minute) - (5 * 60 + 13)) <= 12, rise
    assert abs((set_.hour * 60 + set_.minute) - (18 * 60 + 22)) <= 12, set_
    assert sun.sun_times(69.65, 18.96, date(2026, 6, 21)) == (None, None)       # Tromsø no verão
    cfg = {"mode": "fixed", "light_at": "07:00", "dark_at": "19:00"}
    assert autotheme.desired_light(datetime(2026, 1, 1, 12), cfg) is True
    assert autotheme.desired_light(datetime(2026, 1, 1, 20), cfg) is False
    wrap = {"mode": "fixed", "light_at": "20:00", "dark_at": "06:00"}
    assert autotheme.desired_light(datetime(2026, 1, 1, 23), wrap) is True
    assert autotheme.desired_light(datetime(2026, 1, 1, 10), wrap) is False


# ======================================================== PAPEL DE PAREDE
@check("Papel de parede dinâmico: imagens da pasta, períodos do dia e validações")
def _():
    from pccc.personalization import dynwall
    d = TMP / "imgs"
    d.mkdir()
    for n in ("a.jpg", "b.PNG", "c.txt"):
        (d / n).write_bytes(b"x")
    assert [os.path.basename(p) for p in dynwall.folder_images(str(d))] == ["a.jpg", "b.PNG"]
    assert dynwall.folder_images(str(TMP / "nao-existe")) == []
    assert [dynwall.period_now(datetime(2026, 1, 1, h)) for h in (7, 13, 19, 23, 3)] == \
        ["morning", "afternoon", "evening", "night", "night"]
    try:
        dynwall._save("x", b"<html>nao sou imagem</html>", {})
        raise AssertionError("salvou algo que não é imagem")
    except ValueError:
        pass
    for url in ("https://evil.com/x.jpg", "http://www.bing.com/x"):
        try:
            dynwall._get(url)
            raise AssertionError(f"aceitou {url}")
        except ValueError:
            pass


@check("Luz quente: matriz de cor (0% = sem efeito, 100% ≈ 3400 K)")
def _():
    from pccc.personalization.display import WarmFilter
    m0, m100 = WarmFilter.matrix(0), WarmFilter.matrix(100)
    assert m0 == [1.0 if i % 6 == 0 else 0.0 for i in range(25)]
    assert m100[0] == 1.0 and 0.75 < m100[6] < 0.8 and 0.4 < m100[12] < 0.45


# ===================================================== ÁUDIO (só leitura)
@check("Áudio e visualizador: leitura do mixer e captura do som (sem alterar volume)", needs="hardware")
def _():
    from pccc.media import audio
    from pccc.media.visualizer import BANDS, AudioVisualizer
    devs = audio.output_devices()
    assert sum(d.default for d in devs) <= 1
    vol, muted = audio.master_volume()
    assert 0.0 <= vol <= 1.0 and isinstance(muted, bool)
    for a in audio.app_sessions():
        assert 0.0 <= a.volume <= 1.0 and a.name
    v = AudioVisualizer()
    for _i in range(15):
        b, p, _l = v.snapshot()
        time.sleep(0.1)
    assert len(b) == BANDS and all(0.0 <= x <= 1.0 for x in b)
    assert v.error == "" or not devs, v.error
    v.stop()


@check("Papel de parede animado: camada do Windows encontrada (sem abrir vídeo)", needs="hardware")
def _():
    from pccc.personalization import livewall
    assert livewall.wallpaper_host() != 0
    mons = livewall.monitors()
    assert mons and mons[0][4] is True and mons[0][2] > 0


# ============================================================ APARELHOS NA REDE
@check("Rede: endereço privado, fabricante (lista de exemplo), tipo provável e filtros de endereço")
def _():
    import ipaddress
    from pccc.network import devices as lan
    # MACs fictícios: só os 3 primeiros bytes (prefixo público do fabricante) são reais
    assert lan.is_randomized("DA-12-34-56-78-9A") and lan.is_randomized("B6-00-11-22-33-44")
    assert not lan.is_randomized("04-EC-D8-12-34-56")
    sample = ("# exemplo\n04:EC:D8\tIntel\tIntel Corporate\n04:AB:08\tSkyworth\t"
              "Shenzhen Skyworth Digital Technology CO., Ltd\n00:1B:C5:00:10/36\tTeste\tFaixa Pequena Ltda\n")
    real_file = lan.manuf_file
    tmpf = TMP / "manuf.txt"
    tmpf.write_text(sample, encoding="utf-8")
    lan.manuf_file = lambda: tmpf
    lan._vendors = None
    try:
        assert lan.vendor("04-EC-D8-12-34-56") == "Intel", lan.vendor("04-EC-D8-12-34-56")
        assert lan.vendor("04-AB-08-AB-CD-EF") == "Skyworth Digital", lan.vendor("04-AB-08-AB-CD-EF")
        assert lan.vendor("00-1B-C5-00-10-AB") == "Faixa Pequena"
        assert lan.vendor("DA-12-34-56-78-9A") == ""          # privado: não dá para saber
    finally:
        lan.manuf_file = real_file
        lan._vendors = None
    cases = [(dict(is_gateway=True), "Roteador"), (dict(vendor="Skyworth Digital"), "TV"),
             (dict(hints=["Linux, NRDP/2020"]), "TV"), (dict(name="DESKTOP-ABC1234", vendor="Intel"), "Computador"),
             (dict(mac="DA-12-34-56-78-9A", randomized=True), "Celular"), (dict(vendor="Amazon"), "Amazon"),
             (dict(name="HP-LaserJet-M15"), "Impressora"), (dict(vendor="Sony Interactive Entertainment"), "Console")]
    for kw, expect in cases:
        d = lan.LanDevice(ip="192.168.0.9", mac=kw.pop("mac", "00-11-22-33-44-55"), **kw)
        lan.classify(d)
        assert expect in d.kind, (kw, d.kind)
    net = ipaddress.IPv4Network("192.168.1.0/24")
    assert lan._valid("192.168.1.7", "04-EC-D8-12-34-56", net)
    for ip, mac in (("192.168.1.255", "04-EC-D8-12-34-56"), ("192.168.2.7", "04-EC-D8-12-34-56"),
                    ("192.168.1.7", "FF-FF-FF-FF-FF-FF"), ("192.168.1.7", "01-00-5E-00-00-FB")):
        assert not lan._valid(ip, mac, net), (ip, mac)


@check("Rede: 'aparelho novo' só a partir da 2ª busca, nomes e 'conhecido' são lembrados por rede")
def _():
    import ipaddress
    from pccc.network import devices as lan
    ln = lan.LocalNet("Wi-Fi", "10.0.0.5", ipaddress.IPv4Network("10.0.0.0/24"), "10.0.0.1", "")
    gw = lan.LanDevice(ip="10.0.0.1", mac="AA-00-00-00-00-01", is_gateway=True)
    me = lan.LanDevice(ip="10.0.0.5", mac="AA-00-00-00-00-05", is_self=True)
    tv = lan.LanDevice(ip="10.0.0.9", mac="AA-00-00-00-00-09", name="tv-sala")
    all1, new1 = lan.merge(ln, [gw, me, tv])
    assert new1 == [] and len(all1) == 3              # primeira busca = referência, sem alarme
    nid = lan.network_id(ln, [gw])
    lan.set_custom(nid, tv.mac, custom_name="TV da sala", known=True)
    intruso = lan.LanDevice(ip="10.0.0.77", mac="AA-00-00-00-00-77")
    tv2 = lan.LanDevice(ip="10.0.0.9", mac="AA-00-00-00-00-09")
    all2, new2 = lan.merge(ln, [gw, me, tv2, intruso])
    assert [d.mac for d in new2] == ["AA-00-00-00-00-77"], new2
    assert tv2.custom_name == "TV da sala" and tv2.known and tv2.name == "tv-sala"
    all3, _n = lan.merge(ln, [gw, me])                # TV e intruso desligados
    off = {d.mac: d for d in all3 if not d.online}
    assert set(off) == {"AA-00-00-00-00-09", "AA-00-00-00-00-77"} and off["AA-00-00-00-00-09"].label == "TV da sala"
    lan.forget(nid, "AA-00-00-00-00-77")
    all4, _n = lan.merge(ln, [gw, me])
    assert "AA-00-00-00-00-77" not in {d.mac for d in all4}
    outra = lan.LanDevice(ip="10.0.0.1", mac="BB-00-00-00-00-01", is_gateway=True)   # outra rede (outro roteador)
    _a, new5 = lan.merge(ln, [outra, intruso])
    assert new5 == []                                 # rede nova também começa sem alarme


@check("Rede: busca real na rede local (só leitura) encontra este PC e o roteador", needs="hardware")
def _():
    from pccc.network import devices as lan
    ln, devs = lan.scan()
    assert any(d.is_self for d in devs), "este PC não apareceu"
    assert not ln.gateway or any(d.is_gateway for d in devs), "roteador não apareceu"
    assert ln.network.num_addresses <= lan.MAX_HOSTS
    print(f"      ({len(devs)} aparelho(s) em {ln.network})", flush=True)


def main() -> int:
    width = max(len(n) for n, _, _ in results)
    for name, ok, err in results:
        print(f"[{'OK ' if ok else 'ERRO'}] {name:<{width}}  {err}")
        if not ok and os.environ.get("GITHUB_ACTIONS"):   # vira anotação visível na página do CI
            print(f"::error title=test_media_scenes::{name}: {err}")
    for name in skipped:
        print(f"[PULADO] {name}  (depende do hardware; roda fora do CI)")
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} verificações da Fase 9 passaram")
    print("OK" if not failed else "FALHOU")
    from pccc.ui.tasks import wait_all
    wait_all()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
