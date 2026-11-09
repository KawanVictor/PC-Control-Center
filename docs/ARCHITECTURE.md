# Arquitetura — PC Control Center

## Decisões técnicas

| Escolha | Motivo |
|---|---|
| **Python 3.12** | As melhores bibliotecas de monitoramento (psutil, pywin32, WMI) e iteração rápida. |
| **PySide6 (Qt 6)** | Interface nativa e acelerada, com QSS para temas, bandeja, animações e janelas sem borda para os widgets da Fase 5. Licença LGPL (a do PyQt6 é GPL). |
| **pyqtgraph** | Gráficos em tempo real muito mais leves que matplotlib; integra direto ao Qt. |
| **psutil** | CPU por núcleo, memória, discos, rede — rápido e estável. |
| **PDH (contadores do Windows)** via pywin32 | Uso de GPU por engine, VRAM, frequência real da CPU e memória confirmada — a mesma fonte do Gerenciador de Tarefas. Usamos `AddEnglishCounter`, que funciona com o Windows em português. |
| **DXGI** via ctypes | Nome, LUID e VRAM total de cada GPU, para qualquer fabricante (AMD, Intel, NVIDIA). |
| **NtQuerySystemInformation** via ctypes | Lista todos os processos em ~5 ms numa só chamada. Consultar processo a processo com psutil levou 4,5 s (processos protegidos forçam um caminho lento). |
| **WMI** | Discos físicos (SSD/HDD, barramento, saúde) e sensores do LibreHardwareMonitor. |
| **SQLite** | Histórico local sem servidor; modo WAL; médias por minuto (30 dias ≈ 43 mil linhas). |
| **Segoe Fluent Icons** | Ícones nativos do Windows 11 sem arquivos de imagem (fallback: Segoe MDL2 Assets). |

## Visão geral

```
                ┌──────────────────────── Thread do coletor ─────────────────────────┐
                │  MonitorWorker (QTimers)                                           │
 Windows ──────►│   rápido 1 s : PDH, psutil (CPU, RAM, GPU, E/S, rede, temperatura)│
 (PDH, DXGI,    │   2 s        : processos (NtQuerySystemInformation)                │
  WMI, ntdll)   │   5 s        : partições, nvidia-smi, temperatura de discos        │
                │   60 s       : discos físicos (WMI) e média gravada no SQLite      │
                └───────────────┬────────────────────────────────────────────────────┘
                                │ Signal(Snapshot)  — fila do Qt, entre threads
                                ▼
            MonitorService ──► MainWindow ──► History (últimos 120 pontos)
                                     │
                                     └──► página visível.on_snapshot()
```

A rede tem um serviço próprio, com a mesma ideia:

```
 NetworkService (thread "NetworkThread")             PingMonitor (1 thread por alvo)
   1 s : tráfego por interface (psutil),     ◄──────   internet: 1.1.1.1 (configurável)
         Wi-Fi (wlanapi), status, eventos              gateway : roteador da interface ativa
   5 s : GetAdaptersAddresses (IPs, DNS...)            janela de 120 amostras (NaN = perda)
  60 s : consumo gravado em net_usage (SQLite)
        │ Signal(NetworkSnapshot)
        ▼
 MainWindow ──► páginas com on_net_snapshot() (Rede e Painel)
 SpeedTestRunner (QThread sob demanda) ──► speed.cloudflare.com
```

A interface **nunca** consulta o sistema diretamente; ela só recebe `Snapshot`s. Assim, uma
consulta WMI lenta não congela a janela. Com a janela oculta na bandeja, nenhuma página é
redesenhada.

**Consumo medido (Ryzen 5 4600H):** serviços de sistema e rede juntos ~0,1% da CPU total na
bandeja; ~1,6% com o painel completo aberto e animado.

## Estrutura de pastas

```
PC/
├── main.py                     ponto de entrada (+ --selftest; mensagem de erro se não abrir)
├── requirements.txt          faixas de versão aceitas
├── requirements.lock         versões exatas (setup, build e CI instalam daqui)
├── requirements-build.lock   + PyInstaller, para o build.ps1
├── setup.ps1 / run.bat         instalação e execução (modo desenvolvimento)
├── build.ps1                   gera o .EXE, o instalador e o .zip portátil (Fase 8)
├── pccc.spec                   configuração do PyInstaller
├── installer.iss               instalador por usuário (Inno Setup)
├── build_tools/make_assets.py  ícone .ico e metadados de versão do .EXE
├── build_tools/readme_shots.py capturas do README em modo demonstração (dados fictícios)
├── docs/img/                   capturas usadas no README
├── assets/app.ico              ícone (gerado do mesmo desenho usado no app)
├── release/                    resultado do build (instalador e .zip)
├── config/
│   └── default_settings.json   valores padrão (mesclados com as configurações do usuário)
├── pccc/
│   ├── app.py                  bootstrap: instância única, tema, coletor, janela
│   ├── selftest.py             autoteste sem interface (valida o .EXE)
│   ├── core/                   infraestrutura
│   │   ├── safety.py           regras de segurança: ps_quote, pastas protegidas, safe_delete_file
│   │   ├── paths.py            caminhos (%APPDATA%, recursos do .exe)
│   │   ├── config.py           Settings (JSON, gravação atômica, sinal changed)
│   │   ├── logger.py           app.log + operations.log (auditoria)
│   │   ├── database.py         SQLite: histórico e operações
│   │   ├── autostart.py        inicialização com o Windows (HKCU\Run)
│   │   ├── regbackup.py        backup/restauração de valores do Registro (tabela registry_backups)
│   │   ├── fileinfo.py         fabricante/descrição de executáveis (recurso de versão)
│   │   ├── com.py              ensure_com(): COM em toda thread de trabalho (ver "Threads e COM")
│   │   └── winapi.py           DWM, UAC/elevação, ShellExecute, comandos ocultos
│   ├── monitoring/             coleta de dados reais
│   │   ├── models.py           dataclasses (Snapshot, CpuSample, GpuSample...)
│   │   ├── pdh.py              wrapper dos contadores de desempenho
│   │   ├── cpu.py              uso total/por núcleo, frequência real
│   │   ├── memory.py           física, confirmada, paginação
│   │   ├── gpu.py              DXGI + engines + VRAM + nvidia-smi
│   │   ├── storage.py          partições, discos físicos, E/S de disco e rede
│   │   ├── temperature.py      LibreHardwareMonitor → ACPI → discos
│   │   ├── processes.py        processos (NtQuerySystemInformation), classificação, consumo por app
│   │   ├── winproc.py          janelas visíveis por PID e caminho do executável
│   │   ├── system.py           versão do Windows, tempo ligado
│   │   └── collector.py        thread do coletor + MonitorService
│   ├── network/                rede e Wi-Fi (Fase 3)
│   │   ├── models.py           WifiInfo, InterfaceInfo, PingStats, NetworkSnapshot...
│   │   ├── wifi.py             Native Wifi API: SSID, sinal, RSSI, canal, padrão, segurança
│   │   ├── adapters.py         GetAdaptersAddresses: IPv4/IPv6, gateway, DNS, MAC, DHCP
│   │   ├── ping.py             ICMP nativo (IcmpSendEcho) + PingMonitor
│   │   ├── speedtest.py        teste de velocidade (Cloudflare) + SpeedTestRunner
│   │   ├── devices.py          aparelhos na rede: ARP, nomes (DNS/NetBIOS/UPnP), fabricante, LanWatcher
│   │   └── monitor.py          NetworkService: tráfego, status, eventos, consumo
│   ├── apps/                   aplicativos e processos (Fase 4)
│   │   ├── installed.py        inventário (Registro + Store), categorias, plano de desinstalação
│   │   ├── startup.py          itens de inicialização e ativar/desativar (StartupApproved)
│   │   └── processes.py        encerramento seguro (lista de processos protegidos)
│   ├── widgets/                widgets da área de trabalho (Fase 5)
│   │   ├── base.py             WidgetConfig, Renderer, Canvas (desenho vetorial), Style
│   │   ├── types/            os 20 tipos: um módulo por tipo (clock, cpu, weather...), _common e REGISTRY no __init__
│   │   ├── window.py           janela sem borda: arrastar, encaixar, redimensionar, menu
│   │   ├── hub.py              DataHub: dados compartilhados + histórico curto
│   │   ├── weather.py          Open-Meteo (geocodificação + previsão)
│   │   ├── media.py            MediaService (WinRT, thread própria)
│   │   └── manager.py          perfis, persistência, ciclo de vida, vigia da área de trabalho
│   ├── personalization/        personalização do Windows (Fase 6)
│   │   ├── changes.py          histórico desfazível, WM_SETTINGCHANGE, reiniciar Explorer
│   │   ├── tweaks.py           ajustes declarativos (Tweak), menu clássico, animações, ocultar barra
│   │   ├── accent.py           cor de destaque (paleta de 8 tons + DWM)
│   │   ├── wallpaper.py        papel de parede (cópia de segurança da imagem anterior)
│   │   ├── themes.py           temas .theme (nomes, prévia, aplicar)
│   │   ├── shortcuts.py        atalhos .lnk e modelos
│   │   └── defaults.py         aplicativos padrão (leitura)
│   ├── automation/             alertas e inteligência (Fase 7)
│   │   ├── rules.py            regras padrão + ajustes do usuário (settings: alerts.rules)
│   │   ├── engine.py           AlertEngine: duração, intervalo, por app/unidade, rede, relatório semanal
│   │   ├── notifier.py         balões da bandeja com respeito a foco/tela cheia/silêncio
│   │   ├── usage.py            uso acumulado de CPU/RAM por aplicativo
│   │   ├── advisor.py          gargalo principal + sugestões + ferramentas de manutenção
│   │   ├── reports.py          relatório (estatísticas) → HTML com SVG / CSV
│   │   └── store.py            tabelas alerts e app_usage
│   ├── media/                  mídia e streaming (v1.1)
│   │   ├── audio.py            saída padrão (IPolicyConfig), volume geral e por app, nível (pycaw)
│   │   ├── visualizer.py       espectro do som (loopback WASAPI + FFT), thread sob demanda
│   │   ├── obs.py              ObsClient: obs-websocket v5 (QWebSocket), status, cenas, comandos
│   │   ├── youtube.py          feed RSS por canal, resolução de @nome, cache, YouTubeFeed (Qt)
│   │   └── fps.py              PresentMon: download/assinatura, auxiliar elevado, FrameStats
│   ├── personalization/        (v1.1, além dos módulos acima)
│   │   ├── scenes.py           cenários: ações, captura do estado anterior, ativar/voltar ao normal
│   │   ├── autotheme.py        tema automático e luz quente automática (relógio de 1 min)
│   │   ├── sun.py              nascer/pôr do sol (NOAA), local do tema automático
│   │   ├── dynwall.py          papel de parede dinâmico (Bing, NASA, pasta, períodos)
│   │   ├── livewall.py         papel de parede animado (vídeo/GIF dentro do WorkerW)
│   │   ├── display.py          brilho (WMI/DDC-CI) e WarmFilter (Magnification API)
│   │   ├── power.py            modo de energia (overlay) e planos (powercfg)
│   │   ├── hotkeys.py          atalhos globais (RegisterHotKey numa janela invisível)
│   │   └── bundle.py           exportar/importar .pcctema
│   └── ui/
│       ├── theme.py            tokens de cor, QSS, claro/escuro, cor de destaque
│       ├── icons.py            glifos e ícone do app (desenhado em código)
│       ├── components.py       GlassCard, RingGauge, LiveChart, MetricCard, ToggleSwitch...
│       ├── history.py          buffers dos gráficos em tempo real
│       ├── fmt.py              formatação pt-BR
│       ├── main_window.py      janela, barra lateral, bandeja, transições
│       └── pages/
│           ├── dashboard.py    painel principal
│           ├── performance.py  CPU, memória, GPU, discos, histórico
│           ├── network.py      Wi-Fi, velocidade, ping, estabilidade, consumo, speedtest
│           ├── common.py       auxiliares das páginas: tabela, confirmação (ask), linha de ajuste, ícones
│           ├── apps/           Aplicativos: __init__ (página) + installed, processes, startup
│           ├── widgets.py      galeria com miniaturas ao vivo, perfis, opções
│           ├── personalization/  página + uma classe por aba (LookTab, WallpaperTab, ThemesTab,
│           │                   ExplorerTab, ShortcutsTab, DefaultsTab, HistoryTab) e tweak_row
│           ├── alerts.py       central, regras/notificações, diagnóstico, relatórios
│           ├── tools.py        atalhos para ferramentas do Windows
│           ├── settings.py     configurações e registro de operações
│           ├── media/          Mídia e streaming: audio, obs, youtube, fps + charts (desenhos)
│           ├── scenes/         Cenários e estilo: scene_list, autotheme, livewall, display,
│           │                   hotkeys, bundle
│           └── lan.py          aba "Dispositivos na rede"
├── tests/
│   ├── test_collector.py       teste de integração do coletor
│   ├── test_network.py         rede real (+ --speed para o teste de velocidade)
│   ├── test_ping.py            perda de pacotes e nota de estabilidade
│   ├── test_apps.py            ações reais com entradas fictícias (inicialização, processo, desinstalação)
│   ├── test_widgets.py         desenho dos 15 tipos + gerenciador/perfis (arquivo temporário)
│   ├── test_widget_windows.py  janelas reais: mouse, encaixe, redimensionar, estilo da janela
│   ├── test_personalization.py aplica e desfaz cada tipo de alteração (Registro conferido)
│   ├── test_automation.py      13 cenários do motor de alertas (relógio simulado) + relatórios
│   ├── test_security.py        17 verificações de segurança (análise do código + comportamento)
│   ├── test_media_scenes.py    18 verificações: OBS simulado, FPS, YouTube, cenários, atalhos, temas
│   ├── run_all.py              executa todas as baterias e resume (--full, --exe)
│   └── ui_smoke.py             teste de fumaça da interface com capturas
└── docs/
    ├── ARCHITECTURE.md
    └── SECURITY.md             cada requisito de segurança → onde é aplicado → qual teste confere
```

## Documentação dos módulos

### core
- **config.Settings**: `get("a.b")` / `set("a.b", v)`. Salva de forma atômica (arquivo
  temporário + `os.replace`) e emite `changed(chave, valor)`. O tema e o coletor reagem a esse sinal.
- **logger**: `log_operation(ação, detalhes, resultado)` grava em `operations.log` e na tabela
  `operations`. Toda ação que muda algo no sistema deve chamar essa função.
- **database.Database**: `insert_metrics`, `query_metrics(since, cols, max_points)` (reduz para
  ~600 pontos com média por blocos), `prune(dias)`, `log_operation`, `recent_operations`.
- **autostart**: `is_enabled()`, `set_enabled(bool)`, `sync()`. O comando aponta para o `.exe`
  quando empacotado, ou para `pythonw.exe main.py --minimized`.
- **safety**: `ps_quote(texto)` (literal seguro para PowerShell), `is_protected_path(caminho)`,
  `safe_delete_file(caminho, motivo)`, que é a ÚNICA função do app que apaga arquivos (só
  `.lnk`/`.url`, fora de pastas protegidas, com registro).
- **Recuperação**: `settings.json` ilegível é guardado como `settings.corrompido-*.json` e o app
  abre com os padrões. Um `history.db` danificado (`PRAGMA quick_check`) é guardado como
  `history.corrompido-*.db`, um banco novo é criado e o usuário é avisado.
- **winapi**: `is_admin()`, `relaunch_as_admin()`, `shell_open(alvo, args, admin)`,
  `apply_window_effects(hwnd, dark)`, `run_hidden(cmd)`.

### monitoring
- **PdhQuery**: recebe `{apelido: caminho_em_inglês}`. Caminhos com `(*)` retornam
  `{instância: valor}`.
- **GpuMonitor**: o uso da GPU é o da engine mais ocupada, somando todos os processos por engine
  (regra do Gerenciador de Tarefas). A GPU principal é a de maior VRAM dedicada.
- **TemperatureMonitor**: volta a procurar o LibreHardwareMonitor a cada 60 s, para detectar se
  ele foi aberto depois do app.
- **ProcessMonitor**: o % de CPU vem do delta de (tempo de usuário + kernel) dividido pelo
  intervalo e pelo nº de threads. A memória é o *conjunto de trabalho privado*. Processos são
  identificados por (pid, horário de criação), para não confundir PIDs reutilizados.
- **MonitorService**: singleton; `start()`, `stop()`, `set_interval(ms)`, sinal
  `snapshot(Snapshot)` e o atributo `latest`.

### network
- **WifiReader.read() → WifiInfo**: interface conectada, SSID, BSSID, qualidade (0–100), RSSI (dBm),
  canal/banda, padrão (Wi-Fi 4/5/6/7), segurança e taxa do link. Se o Windows negar o SSID por
  falta da permissão de localização, preenche `error` com a explicação.
- **list_interfaces() / pick_active()**: a interface ativa é a que está ligada, tem gateway IPv4 e a
  menor métrica (a mesma regra da rota padrão). Adaptadores virtuais (Hyper-V, VPN, Wi-Fi Direct)
  são classificados como "Virtual" e ficam fora do consumo.
- **PingMonitor**: `set_target(nome, host)`, `stats(nome) → PingStats` (último, média, mín/máx,
  jitter = média das diferenças entre pings seguidos, perda nos últimos 60) e
  `consecutive_failures(nome)`.
- **Status**: `offline` (sem interface ativa) → `no_internet` (3 pings seguidos sem resposta) →
  `online`. Cada transição vira um evento (`net_events`). A Fase 7 vai usar esses eventos para os
  alertas de queda.
- **stability_score(perda, jitter, média, quedas)**: começa em 100 e desconta 3 por % de perda,
  até 30 por jitter, até 20 por latência acima de 60 ms e até 20 por quedas nas últimas 24 h.
- **Consumo**: soma por interface física. Contador zerado (adaptador reiniciado) é tratado como
  recomeço, sem gerar valores negativos.
- **Teste de velocidade**: a latência vem do handshake TCP (RTT puro), já que medir por HTTP inflava
  o valor. Download e upload usam 4 conexões por ~7 s cada, descartando o 1º segundo (aceleração
  do TCP). O upload usa dados aleatórios, que não comprimem.

### apps
- **installed.list_installed()**: lê as três chaves `Uninstall` (64 bits, 32 bits, usuário), ignora
  atualizações e entradas-filhas e remove duplicatas. Os apps da Store vêm de uma única chamada ao
  PowerShell (`Get-AppxPackage` + `Get-StartApps`); o nome e o fabricante saem do `AppxManifest.xml`.
  Na interface, o Registro aparece na hora e a Store chega alguns segundos depois.
- **Data de instalação**: usa `InstallDate`; quando falta, usa a data da última gravação da chave.
- **uninstall_plan(app)**: devolve (programa, argumentos, texto legível). MSI usa `/X{GUID}` (o `/I`
  do registro abriria o modo de reparo). A execução usa `ShellExecuteEx` e espera o processo; o UAC
  do desinstalador é respeitado. No fim, confere se a entrada sumiu do registro.
- **startup**: o estado vem de `StartupApproved` (1º byte par = ativado, ímpar = desativado) ou do
  `State` da StartupTask. Para desativar grava `03 00 00 00` + FILETIME, igual ao Gerenciador de Tarefas.
- **regbackup.set_value()**: abre a chave para escrita, copia o valor antigo para `registry_backups`
  e só então grava. `restore(id)` desfaz. Toda alteração de Registro do app deve passar por aqui.
- **Classificação de processos** (`monitoring/processes.py`): *Aplicativo* = mesmo executável de
  uma janela visível, sem dono e não oculta pelo DWM; *Windows* = sessão 0, pasta do Windows ou
  processo conhecido do sistema; o resto é *Segundo plano*. O caminho do executável é consultado
  uma vez por processo, com cache por (PID, horário de criação).
- **apps/processes.terminate()**: recusa os processos da lista `CRITICAL`, confere o horário de
  criação (PIDs são reaproveitados) e espera até 3 s pelo fim. Roda fora da thread da interface.

### widgets
- **Renderer**: cada tipo declara `type_id`, `title`, `description`, `glyph`, `base_size` (canvas
  virtual), `defaults` (opções próprias) e implementa `draw(canvas)`. Elementos clicáveis declaram
  `hit_areas()` e tratam o clique em `on_click(id)`. O widget de Atalhos tem `base_size` dinâmico
  (cresce com a quantidade de itens).
- **paint_widget()**: desenha fundo + conteúdo aplicando `QPainter.scale(largura / base_w)`. A
  janela da área de trabalho e a miniatura da galeria usam a mesma função, por isso a prévia é fiel.
- **Canvas**: `text` (corta com "…" automaticamente), `glyph`, `ring`, `bar`, `spark`, `rounded`.
  As fontes ficam em cache por widget (`Style`).
- **DesktopWidgetWindow**: `FramelessWindowHint | Tool | WindowDoesNotAcceptFocus` e fundo
  translúcido. Camadas: *bottom* (`WindowStaysOnBottomHint`), *normal* e *top*. O encaixe considera
  as bordas da área útil da tela e os outros widgets (12 px). Cada widget redesenha no próprio
  intervalo (`refresh_ms`) lendo os dados do DataHub — nenhum widget consulta o sistema.
- **WidgetManager**: `add/remove/set_visible/set_all_visible/lock_all/arrange/apply_suggested`,
  perfis (`create/rename/delete/switch_profile`) e gravação atômica com atraso de 400 ms. Antes de
  `start()` ele nunca grava, para não sobrescrever o layout salvo. Se o monitor de um widget foi
  desconectado, o widget volta para a tela principal. O "vigia" traz os widgets da camada *atrás*
  para cima quando a área de trabalho fica em primeiro plano e os devolve ao fundo depois.
- **DataHub**: reaproveita os snapshots dos serviços de sistema e rede e guarda 60 pontos de
  histórico. Lê a bateria a cada 30 s. Busca o clima sob demanda (cache de 15 min; sem internet,
  tenta de novo a cada 2 min). O MediaService só inicia quando um widget de player é desenhado.
- **Custo medido:** 6 widgets visíveis ≈ +0,13% da CPU total.

### personalization
- **Fluxo de toda alteração:** `regbackup.set_value/delete_value` (backup, num *grupo* por ação) →
  aviso ao Windows (`WM_SETTINGCHANGE` com a área certa: `ImmersiveColorSet` para cores,
  `TraySettings` para a barra de tarefas; `SHChangeNotify` para a área de trabalho) →
  `changes.record(kind, título, **dados para desfazer)`.
- **changes.undo(id)** desfaz conforme o tipo: `registry` (restaura o grupo), `wallpaper` (volta à imagem
  original ou, se ela sumiu, à cópia de segurança), `theme` (reabre o .theme anterior), `shortcut`
  (apaga o .lnk criado), `spi` (animações) e `appbar` (ocultar a barra de tarefas).
- **regbackup** guarda, para cada valor, as chaves que a gravação precisou criar (`created_keys`). Ao
  restaurar, elas são removidas se estiverem vazias. Exemplo: o menu clássico cria
  `CLSID\{86ca…}\InprocServer32`, e desfazer remove a árvore inteira.
- **Tweak** é declarativo: valor do Registro, opções `[(valor | None = padrão do Windows, rótulo)]`,
  valor assumido quando o valor não existe, área de aviso, build mínima, se exige administrador e
  se exige reiniciar o Explorer. Para criar um ajuste novo basta acrescentar uma entrada em `TWEAKS`.
- **Cor de destaque:** grava os mesmos 7 valores que o app Configurações (paleta de 8 tons em RGBA, menus
  em ABGR, DWM em ARGB com alfa 0xC4). O 8º tom do Windows é preservado e `AutoColorization` mantém o
  tipo original (DWORD).
- **Ocultar a barra de tarefas** usa `SHAppBarMessage(ABM_SETSTATE)` (efeito imediato, sem reiniciar o
  Explorer). **Animações** usam `SPI_SETCLIENTAREAANIMATION`.
- **Apps padrão:** só leitura. O Windows protege `UserChoice` com hash, e alterar por fora seria
  burlar uma proteção do sistema.
- **Reiniciar o Explorer:** encerra apenas o `explorer.exe` do usuário atual e o inicia de novo se o
  Windows não fizer isso sozinho. Sempre com confirmação.

### automation
- **AlertEngine** recebe os mesmos snapshots da interface (thread principal; a avaliação custa
  microssegundos). `_check(chave, regra, condição, fábrica_de_alerta)` guarda desde quando a condição é
  verdadeira e quando disparou pela última vez. Chaves por item (`app_cpu:chrome.exe`, `disk:C:\`)
  fazem cada app e cada unidade ter seu próprio contador; apps que fecham têm o contador zerado.
- O relógio é injetável (`AlertEngine(clock=...)`), o que permite testar "RAM alta por 2 minutos" em
  milissegundos.
- **Rede:** um alerta quando fica fora por `threshold` segundos e um aviso informativo quando volta,
  com a duração da queda.
- **Notifier.blocked_reason()** segue esta ordem: desligado → (alertas críticos param aqui e
  aparecem) → silenciado por 1 h → horário de silêncio (atravessa a meia-noite) →
  `SHQueryUserNotificationState` (tela cheia D3D, apresentação, "Não incomodar"). O balão usa
  `QSystemTrayIcon.showMessage`, e clicar abre a Central.
- **UsageTracker:** soma `CPU% × Δt` e `memória × Δt` por app a cada nova lista de processos (2 s) e
  grava em `app_usage` a cada 5 min e ao sair. O relatório divide pelo tempo observado para obter a
  memória média.
- **Advisor:** só sugere com evidência (médias/P95 das últimas 24 h, estado atual, itens de
  inicialização, reinicialização pendente, tamanho de %TEMP%, plano de energia, sinal Wi-Fi e perda de
  pacotes). Cada sugestão traz uma ação `page:...` ou `shell:...`, resolvida por `MainWindow.navigate`.
- **Relatórios:** `build_report` lê o histórico, que tem uma média por minuto. O HTML é autocontido:
  CSS com tema claro/escuro e gráficos SVG gerados no próprio Python, sem bibliotecas nem internet. O
  CSV usa `;` e BOM para abrir direto no Excel em português.

### Threads e COM
Objetos COM/WinRT presos em ciclos de referência podem ser liberados pelo coletor de lixo do Python
em qualquer thread. Numa thread sem COM inicializado, o Windows encerra o processo
(`CO_E_NOTINITIALIZED`). Regras:
1. Toda thread de trabalho chama `core.com.ensure_com()` ao iniciar (tarefas, ping, rede, mídia,
   teste de velocidade).
2. O coletor reaproveita a conexão WMI e chama `gc.collect()` na própria thread após a leitura lenta.
3. Ao sair, `ui.tasks.wait_all()` espera as tarefas em andamento (o Qt aborta o processo se uma
   QThread é destruída rodando) e o `MediaService.stop()` espera a thread WinRT terminar.

### ui
- **ThemeManager**: gera a folha de estilo QSS a partir de `Theme(mode, accent, transparency)` e
  emite `changed(theme)`. Componentes desenhados à mão (medidores, gráficos) se redesenham ao
  receber esse sinal.
- **Page**: base das páginas, com título e área rolável. Sobrescreva `on_snapshot(snap)`
  (chamado só quando a página está visível) e `on_shown()`.
- **ResponsiveGrid**: reorganiza o número de colunas conforme a largura da janela.
- **Otimizações de pintura**: o fundo é renderizado uma vez em cache; os medidores usam
  `QStaticText` e fontes em cache; variações menores que 1,5 ponto não são animadas.

## Mídia, cenários e estilo (v1.1)
- **Threads:** áudio (pycaw) roda na thread da interface (chamadas < 50 ms; o widget usa
  `audio.cached()`, no máximo 1 leitura/s). O visualizador tem thread própria, que só existe enquanto
  algo o desenha e para 5 s depois. O soundcard é importado **antes** do `ensure_com` nessa thread,
  porque ele trata "COM já iniciado" (S_FALSE) como erro.
- **OBS:** `QWebSocket` na thread da interface. Hello → Identify (SHA-256 com sal/desafio) →
  Identified. Status a cada 2 s. O bitrate é medido com ≥ 1 s entre leituras. Reconecta sozinho
  (a cada 10 s) só se a integração estiver ligada e o processo do OBS existir.
- **FPS:** o app (sem privilégios) inicia `--fps-helper` com UAC. O auxiliar trava o PresentMon.exe
  (`CreateFile` sem compartilhamento de escrita), confere a assinatura da Intel, lê o CSV pelo
  stdout e grava `fps\status.json` (atômico, 2x/s). Ele para quando aparece o arquivo `stop` ou
  quando o PID do app some. 1% mínimo = média dos 1% quadros mais lentos em 10 s.
- **Cenários:** `activate()` guarda em `scenes.active.restore` o valor de cada item **antes** de
  mudar. Ativar outro cenário só acrescenta itens novos ao `restore`, então `deactivate()` sempre volta
  ao estado original. Cada ação é independente: uma falha vira aviso e as outras continuam.
- **Papel de parede animado:** `0x052C` para o Progman cria o WorkerW. No Windows 11 24H2 ele é filho
  do Progman, atrás do `SHELLDLL_DefView`. A janela de vídeo vira `WS_CHILD` desse WorkerW, com
  coordenadas físicas por monitor. Ao parar, o papel de parede é reaplicado (SPI) para redesenhar.
- **Desfazer:** `changes.undo` entende `autotheme` (volta o modo anterior e desliga) e `dynwall`
  (volta a imagem e o ajuste anteriores e desliga).

## Dispositivos na rede (v1.2)
- **Faixa:** IPv4 e máscara da interface ativa (`psutil.net_if_addrs`), limitada a 1024 endereços
  (redes maiores usam a /24 deste PC).
- **Descoberta:** tabela ARP do Windows + `SendARP` para cada endereço, todos de uma vez (~3 s,
  até 256 threads). Em paralelo: DNS reverso, NetBIOS (UDP 137) e SSDP/UPnP (multicast 1900).
  A descrição UPnP só é lida do **próprio IP que respondeu** (privado), com limite de 64 KB e 2 s.
  Tempo total ~10 s.
- **Fabricante:** arquivo `manuf` do Wireshark (gerado da lista IEEE) em
  `%LOCALAPPDATA%\PCControlCenter\cache`, renovado a cada 120 dias. Faixas /28 e /36 também
  são consideradas. MAC com o bit "administrado localmente" = endereço privado (sem fabricante).
- **Histórico:** tabela `lan_devices` (chave: MAC do roteador + MAC do aparelho), então cada rede tem
  sua lista. A primeira busca numa rede serve de referência (não alerta). Nas seguintes, MACs
  inéditos viram `LanWatcher.new` e, com *Vigiar a rede* ligado, um alerta `lan_new`.
- **UI:** `ui/pages/lan.py` (aba da página de rede, criada com a troca temporária de
  `Page.layout_` para separar o conteúdo das duas abas).

## Empacotamento (Fase 8)
- **Formato pasta (onedir)** + instalador: abre mais rápido que um .EXE único (nada é
  descompactado a cada abertura) e gera menos alarmes falsos de antivírus. Sem UPX.
- **Manifesto `asInvoker`**: o .EXE nunca pede administrador ao abrir.
- **`paths.resource_path`** encontra `config/` dentro de `_internal` quando empacotado; os dados
  do usuário continuam em `%APPDATA%`, então atualizar ou reinstalar preserva tudo.
- **`autostart.sync()`**: ao abrir o .EXE, se a inicialização automática apontar para outra cópia
  (ex.: a versão em Python), o caminho é atualizado.
- **Mutex `PCControlCenter.Running`**: o instalador e o desinstalador pedem para fechar o app antes.
- **`--selftest`**: carrega os 81 módulos, monta a janela e as 9 páginas fora da tela, desenha os
  15 widgets, lê hardware, rede, WMI e WinRT, gera relatórios e confere as proteções. O
  `build.ps1` só entrega o pacote se o autoteste do .EXE passar. Foi ele que detectou a falta do
  `PySide6.QtOpenGL` (exigido pelo pyqtgraph) no primeiro build.
- **Build fora do OneDrive**: arquivos intermediários em `%LOCALAPPDATA%\PCControlCenter\build`;
  só o resultado final vai para `release\`.

## Segurança (princípios aplicados desde a Fase 1)
Detalhes, com o teste que confere cada item, em [SECURITY.md](SECURITY.md).
- O app roda como usuário padrão. A elevação só acontece por ação explícita: o botão "Reiniciar
  como administrador" ou as ferramentas SFC/DISM marcadas com 🛡.
- Ações que alteram o sistema pedem confirmação e mostram o comando exato que será executado.
- Toda ação fica registrada (arquivo + SQLite) e aparece em Configurações → Registro de operações.
- Nada roda escondido: comandos de reparo abrem um console visível.
- Nenhum valor é inventado: quando um sensor não está disponível, a interface mostra N/D com o motivo.
