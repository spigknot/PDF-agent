; Instalador do PDFagent — per-usuário (não pede admin).
; Duas tarefas marcadas por padrão: PATH do usuário e menu de contexto de PDFs.
; Compilar:  "C:\Users\<user>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" PDFagent.iss

#define Nome "PDFagent"
#define Versao "1.3.6"
#define Exe "PDFagent.exe"

[Setup]
AppId={{7A3F9C52-3B4E-4D7A-9C1E-2F5B8D6A4C31}
AppName={#Nome}
AppVersion={#Versao}
AppVerName={#Nome} {#Versao}
AppPublisher=Gustavo Almeida
DefaultDirName={autopf}\{#Nome}
DefaultGroupName={#Nome}
DisableProgramGroupPage=yes
; O UAC e' pedido pelo PROPRIO instalador (um clique em Sim): o usuario nao
; precisa de "Executar como administrador". A pasta fica gravavel pelo
; usuario (ver [Dirs]) para o updater por diff funcionar sem admin.
PrivilegesRequired=admin
OutputDir=..\dist
OutputBaseFilename=PDFagent-Setup-{#Versao}
SetupIconFile=..\assets\pdfagent.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#Exe}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes
; NUNCA reutilizar a pasta de uma instalacao anterior: se alguem instalou
; como admin em C:\Program Files, o registro grava esse caminho e a
; proxima execucao sem admin falha com 'Erro 5: Acesso negado'.
UsePreviousAppDir=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"


[Dirs]
; O app e o updater escrevem na pasta em runtime (staged/updates) SEM admin.
Name: "{app}"; Permissions: users-modify

[Files]
; onedir: pasta inteira (start ~0,3 s). O onefile continua na release como portátil.
Source: "..\dist\PDFagent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; icone do menu de contexto (entrada principal; os submenus nao tem icone)
Source: "..\assets\pdfagent.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#Nome}"; Filename: "{app}\{#Exe}"
Name: "{group}\Atualizador do {#Nome}"; Filename: "{app}\PDFagentUpdater.exe"
Name: "{group}\Desinstalar {#Nome}"; Filename: "{uninstallexe}"

[Registry]
; --- menu de contexto: UM item "PDFagent" -> tela única (comprimir|dividir) --
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent"; ValueType: string; ValueName: "MUIVerb"; ValueData: "{#Nome}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\pdfagent.ico"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent\command"; ValueType: string; ValueData: """{app}\{#Exe}"" menu ""%1"""; Flags: uninsdeletekey
; --- migração: remove submenu e valores da era com-submenu ------------------
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent"; ValueType: string; ValueName: "SubCommands"; Flags: deletevalue uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent\shell\comprimir"; Flags: deletekey uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent\shell\dividir"; Flags: deletekey uninsdeletekey

[Run]
Filename: "{app}\{#Exe}"; Description: "Abrir o {#Nome} agora"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
  Antigo: String;
  Codigo: Integer;
  Erro: Integer;
begin
  Result := True;

  { O Inno 6.7 usa loader asInvoker e nem sempre pede elevacao: garantimos aqui.
    Program Files exige admin, e o uninstaller precisa rodar no mesmo modo.
    GetCmdTail preserva /DIR, /TASKS, /VERYSILENT... — sem isso a instancia
    elevada reinstalava no diretorio padrao (e o teste em pasta temporaria
    acabava sobrescrevendo a instalacao real). }
  if not IsAdmin then
  begin
    ShellExec('runas', ExpandConstant('{srcexe}'), GetCmdTail, '',
              SW_SHOWNORMAL, ewNoWait, Erro);
    Result := False;
    exit;
  end;

  Antigo := ExpandConstant('{localappdata}\Programs\{#Nome}\unins000.exe');
  if FileExists(Antigo) then
  begin
    if MsgBox('Foi encontrada uma instalacao antiga por usuario em:' + #13#10 +
              ExpandConstant('{localappdata}\Programs\{#Nome}') + #13#10#13#10 +
              'Ela sera removida para o {#Nome} ficar em uma pasta so. Continuar?',
              mbConfirmation, MB_YESNO) = IDYES then
      Exec(Antigo, '/VERYSILENT /NORESTART', '', SW_HIDE, ewWaitUntilTerminated, Codigo)
    else
      Result := False;
  end;
end;

procedure InitializeWizard();
begin
  { PDFagent e' per-usuario: ignora o que o registro tiver de instalacao antiga. }
  WizardForm.DirEdit.Text := ExpandConstant('{autopf}\{#Nome}');
end;

function SendMessageTimeout(hWnd: Longint; Msg: Longint; wParam: Longint;
  lParam: Longint; fuFlags: Longint; uTimeout: Longint;
  var lpdwResult: Longint): Longint;
  external 'SendMessageTimeoutA@user32.dll stdcall';

procedure AvisaAmbiente();
var
  r: Longint;
begin
  { HWND_BROADCAST=$FFFF, WM_SETTINGCHANGE=$001A, SMTO_ABORTIFHUNG=$0002 }
  SendMessageTimeout($FFFF, $001A, 0, 0, $0002, 5000, r);
end;

{ Lê o PATH do usuário (HKCU\Environment). }
function LePath(): string;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', Result) then
    Result := '';
end;

procedure GravaPath(const Novo: string);
begin
  RegWriteExpandStringValue(HKCU, 'Environment', 'Path', Novo);
end;

procedure AdicionaAoPath();
var
  Atual, Alvo: string;
begin
  Alvo := ExpandConstant('{app}');
  Atual := LePath();
  if Pos(Lowercase(Alvo), Lowercase(Atual)) > 0 then
    exit;
  if (Atual <> '') and (Atual[Length(Atual)] <> ';') then
    Atual := Atual + ';';
  GravaPath(Atual + Alvo);
  AvisaAmbiente();
end;

procedure RemoveDoPath();
var
  Atual, Alvo, Novo: string;
  p: Integer;
begin
  Alvo := ExpandConstant('{app}');
  Atual := LePath();
  if Atual = '' then
    exit;
  p := Pos(Lowercase(Alvo), Lowercase(Atual));
  if p = 0 then
    exit;
  Delete(Atual, p, Length(Alvo));
  { limpa separadores duplicados/sobrando }
  while Pos(';;', Atual) > 0 do
    StringChangeEx(Atual, ';;', ';', True);
  if (Atual <> '') and (Atual[1] = ';') then
    Delete(Atual, 1, 1);
  if (Atual <> '') and (Atual[Length(Atual)] = ';') then
    Delete(Atual, Length(Atual), 1);
  Novo := Atual;
  GravaPath(Novo);
  AvisaAmbiente();
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    { PATH é sempre adicionado: sem pergunta, sem task para o usuário marcar }
    AdicionaAoPath();
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveDoPath();
end;
