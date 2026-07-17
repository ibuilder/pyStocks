; Inno Setup script for stockpredict.
; Build the one-folder app first, then compile this with Inno Setup (ISCC.exe):
;     set STOCKPREDICT_ONEDIR=1
;     pyinstaller --clean --noconfirm stockpredict.spec      ; -> dist\stockpredict\
;     iscc installer\stockpredict.iss                        ; -> installer\Output\stockpredict-setup.exe
;
; Produces a Start-menu shortcut + uninstaller. User data lives in
; %LOCALAPPDATA%\stockpredict and is left intact on uninstall.

#define AppName "stockpredict"
#define AppVersion "1.0.0"
#define AppPublisher "stockpredict"
#define AppExe "stockpredict.exe"

[Setup]
AppId={{7F3C1E2A-9B44-4E0D-8A1C-STOCKPREDICT01}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
OutputBaseFilename=stockpredict-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; SignTool=signtool $f          ; enable once a code-signing cert is configured

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; The one-folder PyInstaller output.
Source: "..\dist\stockpredict\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
