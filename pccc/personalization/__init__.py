"""Personalização do Windows (Fase 6).

Toda alteração passa por ``changes.py``: é registrada no histórico e pode ser desfeita.
Valores do Registro sempre ganham backup antes (core/regbackup.py).

* changes.py   — histórico desfazível + avisos ao Windows (WM_SETTINGCHANGE) e Explorer
* tweaks.py    — ajustes simples de Registro (modo claro/escuro, barra de tarefas, Explorer...)
* accent.py    — cor de destaque (paleta completa, como o app Configurações faz)
* wallpaper.py — papel de parede (com cópia de segurança da imagem anterior)
* themes.py    — temas instalados (.theme)
* shortcuts.py — criação de atalhos personalizados
* defaults.py  — aplicativos padrão (leitura; alteração pelo Configurações, exigência do Windows)
"""
