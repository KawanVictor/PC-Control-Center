"""Regras de alerta: padrões sensatos + ajustes do usuário (settings.json → alerts.rules).

Cada regra só dispara quando a condição se mantém por ``duration`` segundos e respeita
``cooldown`` minutos entre repetições — evita alertas por picos de 1 segundo e spam.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ..core.config import Settings


@dataclass
class Rule:
    kind: str
    title: str
    description: str
    unit: str                 # %, °C, GB, s ...
    threshold: float
    duration: int             # segundos que a condição precisa durar
    cooldown: int             # minutos entre repetições
    enabled: bool = True
    min_value: float = 0
    max_value: float = 100
    step: float = 1
    action: str = ""          # página sugerida ao clicar (apps:procs, performance:mem...)


DEFAULTS: list[Rule] = [
    Rule("cpu", "Uso de CPU elevado", "CPU total acima do limite", "%", 90, 120, 30, max_value=100,
         action="apps:procs"),
    Rule("ram", "Memória RAM quase cheia", "RAM em uso acima do limite", "%", 92, 120, 30, min_value=50,
         max_value=99, action="apps:procs"),
    Rule("commit", "Memória virtual quase esgotada", "Memória confirmada perto do limite (risco de travamentos)",
         "%", 90, 60, 30, min_value=50, max_value=99, action="performance:mem"),
    Rule("cpu_temp", "Temperatura da CPU alta", "Temperatura do processador acima do limite", "°C", 90, 60, 20,
         min_value=50, max_value=110, action="performance:cpu"),
    Rule("gpu_temp", "Temperatura da GPU alta", "Temperatura da placa de vídeo acima do limite", "°C", 85, 60, 20,
         min_value=50, max_value=110, action="performance:gpu"),
    Rule("disk_free", "Armazenamento quase cheio", "Espaço livre de alguma unidade abaixo do limite", "% livre",
         10, 0, 360, min_value=1, max_value=50, action="tools"),
    Rule("internet", "Conexão com a internet caiu", "Sem resposta da internet ou Wi-Fi desconectado", "s",
         15, 15, 0, min_value=5, max_value=300, step=5, action="network"),
    Rule("app_cpu", "Programa com consumo excessivo de CPU", "Um aplicativo usando mais que o limite da CPU total",
         "%", 50, 300, 60, min_value=10, max_value=100, action="apps:procs"),
    Rule("app_ram", "Programa com consumo excessivo de memória", "Um aplicativo usando mais que o limite de RAM",
         "GB", 2.5, 120, 60, min_value=0.5, max_value=32, step=0.5, action="apps:procs"),
    Rule("battery", "Bateria fraca", "Carga abaixo do limite e fora da tomada", "%", 20, 0, 30, min_value=5,
         max_value=50, action=""),
]
# Limite crítico de temperatura: acima disso o alerta fura o "não perturbe".
CRITICAL_TEMP = {"cpu_temp": 97, "gpu_temp": 95}


def load_rules() -> dict[str, Rule]:
    saved = Settings.instance().get("alerts.rules", {}) or {}
    rules = {}
    for r in DEFAULTS:
        rule = Rule(**asdict(r))
        for k in ("threshold", "duration", "cooldown", "enabled"):
            if k in saved.get(r.kind, {}):
                setattr(rule, k, type(getattr(rule, k))(saved[r.kind][k]))
        rules[r.kind] = rule
    return rules


def save_rule(rule: Rule) -> None:
    s = Settings.instance()
    saved = dict(s.get("alerts.rules", {}) or {})
    saved[rule.kind] = {"threshold": rule.threshold, "duration": rule.duration, "cooldown": rule.cooldown,
                        "enabled": rule.enabled}
    s.set("alerts.rules", saved)


def reset_rules() -> None:
    Settings.instance().set("alerts.rules", {})
