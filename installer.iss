; Instalador do PC Control Center (Inno Setup 6). Gerado pelo build.ps1 — que passa as
; variáveis AppVersion, DistDir, OutDir e WorkDir. Para compilar manualmente:
;   ISCC.exe /DAppVersion=0.8.0 /DDistDir=... /DOutDir=... /DWorkDir=... installer.iss
;
; Instala POR USUÁRIO (sem administrador) em %LOCALAPPDATA%\Programs\PC Control Center.
; O desinstalador aparece em Configurações > Aplicativos e no Painel de Controle.

#define AppName "PC Control Center"
#define AppExe  "PC Control Center.exe"

[Setup]
AppId={{6B1E2F4A-8C3D-4E7B-9A51-2D7C0F3E9B84}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=PCControlCenter-Setup-{#AppVersion}
SetupIconFile=assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardSmallImageFile={#WorkDir}\installer_small.bmp
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.18362
; O app cria este mutex enquanto está aberto: instalar/desinstalar pede para fechá-lo antes.
AppMutex=PCControlCenter.Running
CloseApplications=no
ShowLanguageDialog=no

[Languages]
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"
Name: "autostart"; Description: "Iniciar com o Windows (minimizado na bandeja)"; GroupDescription: "Inicialização:"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Atualização: remove a pasta interna da versão anterior para não sobrar biblioteca antiga.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Mesmo valor usado pela opção "Iniciar com o Windows" do app (HKCU, sem administrador).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
    ValueName: "PCControlCenter"; ValueData: """{app}\{#AppExe}"" --minimized"; Tasks: autostart
; A remoção na desinstalação fica no [Code]: só apaga se apontar para ESTA instalação.

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir o {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
// Os dados do usuário ficam em %APPDATA%\PCControlCenter. Por padrão são mantidos (reinstalar
// preserva tudo); só são apagados se o usuário confirmar, vendo exatamente a pasta.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dir, RunCmd: string;
begin
  if CurUninstallStep = usUninstall then
  begin
    // Inicialização automática (ligada pelo instalador ou pelo app): remove só se for desta pasta.
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'PCControlCenter', RunCmd) then
      if Pos(Lowercase(ExpandConstant('{app}\{#AppExe}')), Lowercase(RunCmd)) > 0 then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'PCControlCenter');
  end;
  if CurUninstallStep = usPostUninstall then
  begin
    Dir := ExpandConstant('{userappdata}\PCControlCenter');
    if DirExists(Dir) and (not UninstallSilent) then
      if MsgBox('Apagar também os seus dados do PC Control Center?' + #13#10#13#10 +
                'Pasta: ' + Dir + #13#10 +
                '(configurações, histórico, alertas, layouts de widgets, logs e cópias de papéis de parede)' + #13#10#13#10 +
                'Atenção: sem esses dados, as personalizações feitas pelo app não poderão mais ser desfeitas por ele. ' +
                'Os relatórios salvos em Documentos não são apagados.' + #13#10#13#10 +
                'Escolha "Não" para manter (recomendado se for reinstalar).',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Dir, True, True, True);
  end;
end;
