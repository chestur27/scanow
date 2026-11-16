#define MyAppName "ScaNow"
#define MyAppVersion "2.0.0"
#define MyAppExeName "scanow.exe"
#define Naps2Version "8.6.0"

#if !FileExists("payload\naps2\App\NAPS2.Console.exe")
  #error Run installer\prepare_naps2.ps1 before compiling the installer.
#endif
#if !FileExists("payload\licenses\naps2-v8.6.0-source.zip")
  #error The matching NAPS2 source archive must accompany the installer.
#endif

[Setup]
AppId={{DDE9A41B-1CE0-4E85-A785-9C642FC8B879}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\ScaNow
DefaultGroupName=ScaNow
OutputDir=output
OutputBaseFilename=ScaNow-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\app\assets\scanow.ico

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\build\windows\scanow\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "payload\naps2\*"; DestDir: "{app}\tools\naps2"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "payload\licenses\*"; DestDir: "{app}\licenses"; Flags: recursesubdirs createallsubdirs ignoreversion

[Dirs]
Name: "{app}\tools\naps2\Data"

[Icons]
Name: "{group}\ScaNow"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\ScaNow"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch ScaNow"; Flags: nowait postinstall skipifsilent
