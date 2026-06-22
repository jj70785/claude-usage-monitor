; Inno Setup script for Claude Usage Monitor.
; Build the exe first:  pyinstaller --noconfirm --clean --workpath build/_work --distpath dist build/monitor.spec
; Then compile this:     "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" build\installer.iss
; Output: installer_output\ClaudeUsageMonitor-Setup.exe  (a one-click installer)

#define AppName "Claude Usage Monitor"
#define AppVersion "1.0.0"
#define AppPublisher "JDT Tech Help"
#define AppExe "ClaudeUsageMonitor.exe"

[Setup]
AppId={{9C3B6F2A-7E1D-4B0C-9A8E-CUM2025MONITOR}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\installer_output
OutputBaseFilename=ClaudeUsageMonitor-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "startupicon"; Description: "Start {#AppName} automatically when I log in"; GroupDescription: "Startup:"

[Files]
; The whole PyInstaller onedir output.
Source: "..\dist\ClaudeUsageMonitor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
; Startup-folder shortcut launches tray-only (no window popping up at login).
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: "--tray"; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent
