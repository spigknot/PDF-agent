; Instalador do PDFagent — per-usuário (não pede admin).
; Duas tarefas marcadas por padrão: PATH do usuário e menu de contexto de PDFs.
; Compilar:  "C:\Users\<user>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" PDFagent.iss

#define Nome "PDFagent"
#define Versao "1.0.0"
#define Exe "PDFagent.exe"

[Setup]
AppId={{7A3F9C52-3B4E-4D7A-9C1E-2F5B8D6A4C31}
AppName={#Nome}
AppVersion={#Versao}
AppVerName={#Nome} {#Versao}
AppPublisher=Gustavo Almeida
DefaultDirName={localappdata}\Programs\{#Nome}
DefaultGroupName={#Nome}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PDFagent-Setup-{#Versao}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#Exe}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "addpath"; Description: "Adicionar ao PATH do usuário (permite chamar ""PDFagent"" pelo terminal)"
Name: "contextmenu"; Description: "Adicionar ""PDFagent > Comprimir"" ao menu de contexto de arquivos PDF"

[Files]
; onedir: pasta inteira (start ~0,3 s). O onefile continua na release como portátil.
Source: "..\dist\PDFagent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#Nome}"; Filename: "{app}\{#Exe}"
Name: "{group}\Desinstalar {#Nome}"; Filename: "{uninstallexe}"

[Registry]
; --- menu de contexto: PDFagent > Comprimir -------------------------------
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent"; ValueType: string; ValueName: "MUIVerb"; ValueData: "{#Nome}"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent"; ValueType: string; ValueName: "SubCommands"; ValueData: ""; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#Exe},0"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent\shell\comprimir"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Comprimir"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent\shell\comprimir\command"; ValueType: string; ValueData: """{app}\{#Exe}"" --in-place -n recommended --avisar ""%1"""; Flags: uninsdeletekey; Tasks: contextmenu
; --- submenu: Dividir (comprime antes; limite padrão de 10 MB) -------------
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent\shell\dividir"; ValueType: string; ValueName: "MUIVerb"; ValueData: "Dividir"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent\shell\dividir"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\{#Exe},0"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\PDFagent\shell\dividir\command"; ValueType: string; ValueData: """{app}\{#Exe}"" split ""%1"" --avisar"; Flags: uninsdeletekey; Tasks: contextmenu

[Run]
Filename: "{app}\{#Exe}"; Description: "Abrir o {#Nome} agora"; Flags: nowait postinstall skipifsilent

[Code]
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
  begin
    if WizardIsTaskSelected('addpath') then
      AdicionaAoPath();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RemoveDoPath();
end;
