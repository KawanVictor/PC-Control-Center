# Segurança — PC Control Center

Para cada exigência de segurança da especificação: como ela é aplicada e qual teste a confere.
`tests/test_security.py` roda antes de todo build (`build.ps1`). Se ele falhar, o build é cancelado.

## Requisitos e implementação

| Requisito | Como é aplicado | Conferido por |
|---|---|---|
| **Pedir administrador só quando necessário** | O .EXE tem manifesto `asInvoker` e abre como usuário padrão. A elevação (UAC) existe em um único ponto (`winapi.shell_open(admin=True)`) e só é chamada por botões: *Reiniciar como administrador*, ferramentas marcadas com 🛡 (SFC/DISM) e desinstaladores que pedem elevação por conta própria. O instalador também é por usuário, sem administrador. | `test_security`: "Elevação (UAC) só via winapi…"; build: `uac_admin=False` |
| **Confirmar ações críticas** | Desinstalar, encerrar processo, desativar item de inicialização, reiniciar o Explorer, desfazer, restaurar padrões e remover atalho abrem uma caixa de confirmação. A caixa mostra o **comando exato** ou o **arquivo exato** afetado. | revisão + `ui_smoke` |
| **Registrar operações** | `log_operation()` grava em `logs\operations.log` (rotativo, 5 cópias) e na tabela `operations`. A lista aparece em *Configurações → Registro de operações*. Inclui as operações **recusadas** pelas regras de segurança. | `test_apps`, `test_personalization` |
| **Permitir desfazer** | Registro: backup em `registry_backups` antes de cada gravação. *Desfazer* restaura o valor e remove chaves que a alteração criou. Papel de parede: cópia da imagem anterior. Inicialização: mesmo mecanismo do Gerenciador de Tarefas (`StartupApproved`), que nunca apaga a entrada. Personalização: *Histórico* com desfazer individual. | `test_security` ("backup antes de gravar…"), `test_personalization`, `test_apps` |
| **Nunca alterar o Registro sem backup** | Só `core/regbackup.py` grava ou apaga valores, sempre com backup antes. A exceção é `core/autostart.py`, que cuida apenas do valor próprio `PCControlCenter` em `HKCU\…\Run`. Se o Windows recusar a gravação, o backup é descartado (sem registro órfão). | `test_security`: "Registro só é alterado por regbackup…", "gravação recusada não deixa backup órfão" |
| **Proteger arquivos essenciais** | `safety.safe_delete_file()` é a **única** função que apaga arquivos. Aceita só `.lnk`/`.url` (atalhos criados pelo app). Recusa Windows, Arquivos de Programas, ProgramData, a raiz das unidades e a pasta do usuário, além de pastas e links simbólicos. | `test_security`: "Arquivos só são apagados por…", "Pastas protegidas…", "Atalho criado pelo app…" |
| **Confirmar antes de excluir, mostrando o que será removido** | A remoção de atalho (pela lista ou pelo *Histórico*) mostra o caminho completo do arquivo. Na desinstalação do app, a pasta de dados só é apagada se o usuário aceitar, e a caixa mostra a pasta e o que ela contém (padrão: **Não**). | revisão + teste do instalador |
| **Nunca desativar serviços críticos automaticamente** | O app não altera serviços. *Serviços* abre o `services.msc` oficial. O código não contém `sc config`, `Set-Service`, `Stop-Service`, `bcdedit`, `vssadmin` etc. | `test_security`: "Sem comandos destrutivos…" |
| **Não encerrar processos essenciais / nada automático** | Lista `CRITICAL` (csrss, lsass, winlogon, svchost, dwm…) e PIDs 0/4 bloqueados, e o próprio app também. Antes de encerrar, confere se o PID ainda é o mesmo processo. O motor de alertas e o diagnóstico **só sugerem** e não encerram nada. | `test_security`: "Processos essenciais…", "Nenhum encerramento automático…" |
| **Sem limpeza forçada de RAM** | Não existe "limpar memória". O diagnóstico aponta quem consome e sugere ações manuais. | revisão |
| **Desinstalar só pelos meios oficiais** | Executa o `UninstallString` do programa, `msiexec /X{GUID}` ou `Remove-AppxPackage`. O app não apaga pastas nem chaves de programas. O nome do pacote da Store é validado e escapado (`ps_quote`). | `test_apps`, `test_security`: "Desinstalação da Store recusa…" |
| **Nunca executar comandos perigosos silenciosamente** | Sem `shell=True`, `os.system`, `eval`/`exec`. Comandos são listas de argumentos. Textos para o PowerShell passam por `ps_quote` (aspas simples, que o PowerShell não interpreta). Comandos de reparo abrem console visível. | `test_security`: "Sem shell=True…", "ps_quote impede injeção…" |

## Mídia, cenários e estilo (v1.1)

| Situação | Proteção | Conferido por |
|---|---|---|
| **Contador de FPS precisa de administrador** | A elevação só acontece ao clicar em *Ligar contador* (ou atalho/cenário que você configurou). Quem roda elevado é o próprio app em modo auxiliar, com argumentos fixos. Antes de cada uso, ele **trava** o PresentMon.exe contra alteração e confere a **assinatura digital da Intel** (`O=Intel Corporation`, status *Valid*). O auxiliar encerra apenas o PresentMon que ele mesmo iniciou e para sozinho se o app fechar. | `test_security` (lista de elevação), `test_media_scenes` (FPS) |
| **Download do PresentMon** | Só do GitHub oficial (`GameTechDev/PresentMon`), só por HTTPS e só nos servidores do GitHub (inclusive após redirecionamento). Arquivo com assinatura inválida é descartado. | `test_media_scenes`: "download só aceita os servidores do GitHub" |
| **Senha do OBS** | Criptografada com DPAPI (só a sua conta, neste PC, consegue ler). Nunca aparece no settings.json nem no log. | `test_security`: "Senha do OBS fica criptografada" |
| **Iniciar transmissão ao vivo** | Sempre pede confirmação (iniciar e encerrar). | revisão |
| **Importar `.pcctema`** | Só dados (JSON), com até 40 MB. Prévia completa antes de aplicar. Programas e sites que o arquivo abriria são **listados e removidos por padrão**. A imagem embutida precisa ser JPG/PNG/BMP válida. Tudo que muda no Windows vai para o Histórico. | `test_media_scenes`: "Exportar/importar..." |
| **Cache e arquivos baixados** | `safety.delete_app_file` só apaga dentro das pastas do app (`%APPDATA%\PCControlCenter` e `%LOCALAPPDATA%\PCControlCenter`). | `test_security`: "Arquivos internos (cache)..." |
| **Downloads de imagens/feeds** | Lista fixa de servidores por recurso (Bing, NASA, YouTube, GitHub) e só HTTPS. Imagens do papel de parede precisam ter assinatura JPG/PNG válida. | `test_media_scenes` |
| **Atalhos globais** | `RegisterHotKey`: se outro programa já usa a combinação, o Windows recusa e o app avisa. Nada é capturado do teclado além das combinações registradas. | `test_media_scenes`: "Atalhos..." |
| **Cenários e tema automático** | Gravam no Registro só via `regbackup` (com backup). Ao ligar o tema ou o papel de parede automático, o estado anterior vai para o Histórico. *Voltar ao normal* restaura o estado anterior aos cenários. | `test_media_scenes`: "Cenários..." |
| **Luz quente e papel de parede animado** | Nada fica gravado no sistema: o efeito de cor e a janela de vídeo pertencem ao processo e somem se o app fechar ou travar. | revisão + teste manual |
| **Busca de aparelhos na rede** | Só na faixa da **sua** rede local (interface ativa, no máximo 1024 endereços), só com os mecanismos normais de descoberta da rede local (ARP, DNS reverso, NetBIOS, UPnP). **Sem varredura de portas** e sem tentativa de acesso. A descrição UPnP só é baixada do próprio aparelho que respondeu, com limite de tamanho e tempo. A busca automática vem desligada. | `test_media_scenes`: "Rede: ..." |
| **Visualizador** | Lê uma cópia do som enviado aos alto-falantes (loopback). Não grava, não salva e não usa o microfone. | revisão |

## Robustez

- **Configurações danificadas:** o app abre com os padrões e guarda o arquivo original como
  `settings.corrompido-<data>.json` (não é sobrescrito).
- **Banco de dados danificado:** `PRAGMA quick_check` na abertura. Se falhar, o arquivo é
  guardado como `history.corrompido-<data>.db`, um novo é criado e o usuário é avisado.
- **Erro ao abrir o .EXE:** mensagem na tela com o caminho do log (o .EXE não tem console).
- **Erros inesperados:** vão para `logs\app.log` com o rastreamento completo.
- **Gravação atômica:** `settings.json` e `widgets.json` são escritos em arquivo temporário e
  depois renomeados, então nunca ficam pela metade.

## Privacidade

- Tudo fica no computador (`%APPDATA%\PCControlCenter`). Nada é enviado a servidores do app.
- Conexões externas: Open-Meteo (clima, só a cidade escolhida), Cloudflare (teste de velocidade,
  só quando você clica), ping ICMP para o servidor configurado e, só quando você liga cada recurso:
  feeds públicos do YouTube (canais que você adicionou), Bing/NASA (imagem do dia), GitHub (PresentMon)
  e o OBS local (127.0.0.1).

## Desinstalação

O desinstalador oficial (Configurações → Aplicativos) remove a pasta do programa, os atalhos e a
inicialização automática (só se ela apontar para a pasta desinstalada). Os dados do usuário são
mantidos, a menos que você confirme a remoção. As personalizações feitas no Windows **não** são
revertidas automaticamente: use *Personalização → Histórico → Desfazer* antes de desinstalar,
se quiser voltar ao estado anterior.
