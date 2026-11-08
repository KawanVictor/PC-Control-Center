# Histórico de versões

## Não lançado
- `widgets/types.py` virou um pacote com um módulo por tipo de widget.
- Lint (ruff) e checagem de tipos (mypy) no CI, com versões fixas em `requirements-dev.txt`. Os
  ajustes que eles pediram corrigiram nomes que escondiam métodos do Qt (`render`, `actions`),
  variáveis reaproveitadas com outro tipo e acessos a valores que podem ser nulos.
- Enums do Qt na forma completa (`Qt.AlignmentFlag.AlignCenter`), a única que os tipos do PySide6
  reconhecem.
- Saudação do painel entre meia-noite e 5h corrigida ("Boa noite").

## 1.2.1
- Capturas de tela no README, geradas em modo demonstração (`build_tools/readme_shots.py`), sem
  dados pessoais.
- Versões exatas das dependências em `requirements.lock` e `requirements-build.lock`: setup, build
  e CI instalam a partir delas.
- CI roda também os alertas e relatórios (relógio simulado), mídia e cenários (OBS simulado) e o
  desenho dos widgets.
- As quatro páginas maiores (Aplicativos, Mídia, Cenários e Personalização) viraram pacotes com um
  módulo por aba; auxiliares compartilhados em `pccc/ui/pages/common.py`.

## 1.2.0
- **Dispositivos na rede** (página Rede e Wi-Fi): aparelhos conectados com nome, tipo provável, IP,
  fabricante e MAC. Permite dar nomes, marcar como conhecido e vigiar a rede, com aviso quando um
  aparelho novo entrar.
- Autoteste do executável confere a descoberta da rede local.

## 1.1.0
- **Mídia e streaming:** saída de som, volume por aplicativo, visualizador de áudio, integração com
  o OBS (obs-websocket v5), vídeos novos do YouTube e contador de FPS (PresentMon).
- **Cenários e estilo:** cenários de um clique com "voltar ao normal", tema automático pelo
  nascer/pôr do sol, papel de parede dinâmico (Bing, NASA, pasta, períodos) e animado (vídeo/GIF),
  brilho e luz quente, atalhos de teclado globais e exportar/importar o visual (`.pcctema`).
- 5 widgets novos: visualizador, volume e mixer, OBS, YouTube e FPS.

## 1.0.0
- Fase 8: revisão de segurança (`core/safety.py`, `docs/SECURITY.md`), recuperação de arquivos
  danificados, autoteste (`--selftest`), executável (PyInstaller) e instalador por usuário (Inno Setup).

## 0.1.0 – 0.7.0
- Fases 1 a 7: interface e painel, monitoramento de hardware, rede e Wi-Fi, aplicativos e processos,
  widgets, personalização do Windows, alertas, automações e relatórios.
