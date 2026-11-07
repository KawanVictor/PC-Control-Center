"""Diagnóstico de gargalos e sugestões de otimização baseadas nos dados coletados.

Nada aqui altera o sistema: cada sugestão explica o motivo (com números reais) e oferece
um botão que abre a ferramenta certa — a decisão é sempre do usuário.
Não há "limpeza de RAM" nem encerramento automático de processos (de propósito: isso
deixa o Windows mais lento e pode perder dados).
"""
from __future__ import annotations

import os
import re
import time
import winreg
from dataclasses import dataclass

from ..core.database import Database
from ..core.winapi import run_hidden
from ..ui.fmt import fmt_bytes, fmt_uptime

SEV_ORDER = {"critical": 0, "warning": 1, "tip": 2, "ok": 3}


@dataclass
class Suggestion:
    severity: str          # critical | warning | tip | ok
    title: str
    detail: str
    action_label: str = ""
    action: str = ""       # page:<chave> | shell:<alvo> | open:<caminho>


@dataclass
class Bottleneck:
    resource: str          # CPU, Memória RAM, Disco, GPU, Rede, Nenhum
    level: float           # % médio do recurso mais ocupado
    detail: str
    scores: dict


def _stats_since(seconds: int) -> dict[str, list[float]]:
    rows = Database.instance().query_metrics(int(time.time() - seconds),
                                             ("cpu", "ram", "gpu", "cpu_temp", "disk_read", "disk_write"),
                                             max_points=5000)
    keys = ("cpu", "ram", "gpu", "cpu_temp", "disk_read", "disk_write")
    return {k: [r[i + 1] for r in rows if r[i + 1] is not None] for i, k in enumerate(keys)}


def _avg(v):
    return sum(v) / len(v) if v else None


def _p95(v):
    if not v:
        return None
    s = sorted(v)
    return s[min(len(s) - 1, int(len(s) * 0.95))]


def bottleneck(sys_snap, hist_hour: dict, history_live=None) -> Bottleneck:
    """Recurso mais saturado na última hora (ou nos dados ao vivo se ainda não há histórico)."""
    scores = {}
    if hist_hour.get("cpu"):
        scores["CPU"] = _avg(hist_hour["cpu"])
        scores["Memória RAM"] = _avg(hist_hour["ram"])
        scores["GPU"] = _avg(hist_hour["gpu"]) or 0
    elif sys_snap is not None:
        scores["CPU"] = sys_snap.cpu.percent
        scores["Memória RAM"] = sys_snap.memory.percent
        g = sys_snap.primary_gpu
        scores["GPU"] = g.percent if g else 0
    if sys_snap is not None:
        scores["Disco"] = sys_snap.disk_io.active_percent
    if not scores:
        return Bottleneck("Nenhum", 0, "Ainda sem dados suficientes.", {})
    # RAM "cheia" pesa mais cedo que CPU: acima de ~85% o Windows começa a paginar
    weighted = {k: v * (1.15 if k == "Memória RAM" else 1.0) for k, v in scores.items() if v is not None}
    res = max(weighted, key=weighted.get)
    level = scores[res]
    limits = {"CPU": 75, "Memória RAM": 80, "GPU": 85, "Disco": 70}
    if level < limits.get(res, 80):
        return Bottleneck("Nenhum", level, "Nenhum recurso está saturado — o computador tem folga.", scores)
    detail = {
        "CPU": "O processador passa boa parte do tempo ocupado: programas demoram a responder.",
        "Memória RAM": "A memória está quase sempre cheia: o Windows usa o disco como extensão e tudo fica lento.",
        "GPU": "A placa de vídeo está no limite: jogos e vídeos podem perder quadros.",
        "Disco": "O disco está muito ocupado: aberturas de programas e arquivos ficam lentas.",
    }[res]
    return Bottleneck(res, level, detail, scores)


def _reboot_pending() -> bool:
    keys = [r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"]
    for k in keys:
        try:
            winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, k).Close()
            return True
        except OSError:
            continue
    return False


def _temp_size(limit_s: float = 4.0) -> int:
    """Tamanho aproximado de %TEMP% (para no tempo limite, para não demorar)."""
    total, t0 = 0, time.time()
    for root, _dirs, files in os.walk(os.environ.get("TEMP", "")):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
        if time.time() - t0 > limit_s:
            break
    return total


def _power_plan() -> tuple[str, str]:
    try:
        out = run_hidden(["powercfg", "/getactivescheme"], timeout=5)
        m = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27})\s*\((.+?)\)", out, re.I)
        if m:
            return m.group(1).lower(), m.group(2)
    except Exception:
        pass
    return "", ""


POWER_SAVER = "a1841308-3541-4fab-bc81-f71556f20b4a"


def analyze(sys_snap=None, net_snap=None) -> tuple[Bottleneck, list[Suggestion]]:
    day = _stats_since(86400)
    hour = _stats_since(3600)
    out: list[Suggestion] = []
    add = out.append
    s = sys_snap

    # ------------------------------------------------------------ memória
    ram_avg, ram_p95 = _avg(day["ram"]), _p95(day["ram"])
    if s is not None:
        total = s.memory.total
        if (ram_avg or s.memory.percent) >= 80:
            top = sorted(s.processes.apps, key=lambda a: a.memory, reverse=True)[:3]
            tops = ", ".join(f"{a.name.removesuffix('.exe')} ({fmt_bytes(a.memory)})" for a in top)
            upgrade = (f" Com {fmt_bytes(total)} instalados, ampliar para 16 GB resolveria de vez."
                       if total < 12 * 2 ** 30 else "")
            avg_txt = f"{ram_avg:.0f}% em média nas últimas 24 h" if ram_avg else f"{s.memory.percent:.0f}% agora"
            add(Suggestion("warning" if (ram_p95 or s.memory.percent) >= 90 else "tip",
                           "Memória RAM no limite",
                           f"Uso de {avg_txt}. Quem mais usa agora: {tops}. Feche abas e programas que não estiver "
                           f"usando e desative apps que iniciam com o Windows.{upgrade}",
                           "Ver processos", "page:apps:procs"))
        if s.memory.commit_limit and s.memory.commit_used / s.memory.commit_limit >= 0.85:
            add(Suggestion("warning", "Memória virtual perto do limite",
                           f"{fmt_bytes(s.memory.commit_used)} de {fmt_bytes(s.memory.commit_limit)} confirmados. "
                           "Deixe o arquivo de paginação no tamanho automático (gerenciado pelo sistema) "
                           "para evitar que programas fechem sozinhos.",
                           "Abrir Memória virtual", "shell:SystemPropertiesPerformance.exe"))

    # --------------------------------------------------------------- CPU
    cpu_p95 = _p95(day["cpu"])
    if cpu_p95 is not None and cpu_p95 >= 85 and s is not None:
        top = sorted(s.processes.apps, key=lambda a: a.cpu, reverse=True)[:3]
        add(Suggestion("warning", "Processador muito ocupado",
                       f"Em 5% do tempo a CPU passou de {cpu_p95:.0f}%. Programas que mais usam agora: "
                       + ", ".join(f"{a.name.removesuffix('.exe')} ({a.cpu:.0f}%)" for a in top) + ".",
                       "Ver processos", "page:apps:procs"))

    # --------------------------------------------------------- temperatura
    tmax = max(day["cpu_temp"]) if day["cpu_temp"] else (s.temps.cpu if s and s.temps.cpu else None)
    tavg = _avg(day["cpu_temp"])
    if tmax is not None and (tmax >= 90 or (tavg or 0) >= 80):
        add(Suggestion("critical" if tmax >= 95 else "warning", "Processador esquentando",
                       f"Pico de {tmax:.0f} °C" + (f" e média de {tavg:.0f} °C" if tavg else "") +
                       " nas últimas 24 h. Use o notebook em superfície rígida, mantenha as saídas de ar livres e "
                       "limpe a poeira. Temperatura alta reduz o desempenho (o processador desacelera).",
                       "Opções de energia", "shell:powercfg.cpl"))

    # ------------------------------------------------------------- disco
    if s is not None:
        for p in s.partitions:
            free = 100 - p.percent
            if free <= 15:
                add(Suggestion("critical" if free <= 5 else "warning", f"Pouco espaço em {p.mount.rstrip(chr(92))}",
                               f"Só {fmt_bytes(p.free)} livres ({free:.0f}%). Abaixo de ~10% o Windows fica lento e "
                               "pode falhar em atualizações.", "Sensor de Armazenamento", "shell:ms-settings:storagesense"))
        sysdisk = next((d for d in s.physical_disks if d.media == "HDD"), None)
        if sysdisk and len(s.physical_disks) == 1:
            add(Suggestion("tip", "Considere um SSD",
                           f"O disco {sysdisk.name} é um HD mecânico. Trocar por SSD deixa a inicialização e a "
                           "abertura de programas várias vezes mais rápidas."))
    tmp = _temp_size()
    if tmp >= 1.5 * 2 ** 30:
        add(Suggestion("tip", "Arquivos temporários acumulados",
                       f"A pasta de temporários ocupa cerca de {fmt_bytes(tmp)}. A Limpeza de Disco do Windows "
                       "remove com segurança o que não é mais usado.", "Abrir Limpeza de Disco", "shell:cleanmgr.exe"))

    # -------------------------------------------------------- inicialização
    try:
        from ..apps.startup import list_startup
        enabled = [i for i in list_startup() if i.enabled]
        if len(enabled) >= 8:
            add(Suggestion("tip", "Muitos programas iniciam com o Windows",
                           f"{len(enabled)} itens abrem sozinhos ao ligar o PC, consumindo memória o tempo todo. "
                           "Desative os que não precisa logo ao ligar.", "Gerenciar inicialização", "page:apps:startup"))
    except Exception:
        pass

    # -------------------------------------------------------- reinicialização
    if s is not None and s.uptime_s >= 7 * 86400:
        add(Suggestion("tip", "Computador ligado há muitos dias",
                       f"Ligado há {fmt_uptime(s.uptime_s)}. Reiniciar libera memória presa por programas e "
                       "conclui atualizações."))
    if _reboot_pending():
        add(Suggestion("warning", "Reinicialização pendente",
                       "O Windows instalou atualizações que só terminam após reiniciar.",
                       "Abrir Windows Update", "shell:ms-settings:windowsupdate"))

    # ------------------------------------------------------------- energia
    guid, name = _power_plan()
    bat = None
    try:
        import psutil
        bat = psutil.sensors_battery()
    except Exception:
        pass
    if guid == POWER_SAVER and (bat is None or bat.power_plugged):
        add(Suggestion("tip", "Plano de energia em economia",
                       f"O plano ativo é “{name}”, que limita o processador mesmo na tomada.",
                       "Opções de energia", "shell:powercfg.cpl"))

    # ---------------------------------------------------------------- rede
    if net_snap is not None:
        w = net_snap.wifi
        p = net_snap.ping_internet
        if w.connected and w.signal and w.signal < 50:
            add(Suggestion("tip", "Sinal de Wi-Fi fraco",
                           f"Sinal em {w.signal}% ({w.rssi} dBm). Aproxime-se do roteador ou use a rede de 5 GHz "
                           "se estiver perto dele.", "Ver rede", "page:network"))
        if w.connected and w.band.startswith("2,4"):
            add(Suggestion("tip", "Wi-Fi em 2,4 GHz",
                           "Se o roteador tiver rede de 5 GHz e você estiver no mesmo cômodo, ela costuma ser bem "
                           "mais rápida e estável.", "Ver rede", "page:network"))
        if p.loss_pct >= 2 or net_snap.drops_24h >= 3:
            add(Suggestion("warning", "Conexão instável",
                           f"Perda de pacotes de {p.loss_pct:.0f}% e {net_snap.drops_24h} queda(s) nas últimas 24 h. "
                           "Reinicie o roteador; se continuar, contate o provedor com o relatório de rede.",
                           "Ver rede", "page:network"))

    if not out:
        out.append(Suggestion("ok", "Tudo em ordem",
                              "Nenhum problema encontrado nos dados coletados. Continue usando normalmente."))
    out.sort(key=lambda x: SEV_ORDER.get(x.severity, 9))
    return bottleneck(s, hour), out


# Ferramentas de manutenção seguras (todas oficiais do Windows)
MAINTENANCE = [
    ("Limpeza de Disco", "Remove temporários, cache de atualizações e a lixeira com segurança.", "cleanmgr.exe", ""),
    ("Sensor de Armazenamento", "Libera espaço automaticamente com regras que você define.",
     "ms-settings:storagesense", ""),
    ("Otimizar unidades", "Otimiza SSDs (TRIM) e desfragmenta HDs.", "dfrgui.exe", ""),
    ("Windows Update", "Instala correções de segurança e desempenho.", "ms-settings:windowsupdate", ""),
    ("Plano de energia", "Escolha entre economia e desempenho.", "powercfg.cpl", ""),
    ("Memória virtual", "Configure o arquivo de paginação (recomendado: automático).",
     "SystemPropertiesPerformance.exe", ""),
    ("Segurança do Windows", "Verificação de vírus e proteção em tempo real.", "windowsdefender:", ""),
    ("Diagnóstico de Memória", "Testa a RAM em busca de defeitos (pede para reiniciar).", "mdsched.exe", ""),
]
