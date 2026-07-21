#ifndef MyAppVersion
#define MyAppVersion "0.4.0"
#endif

[Setup]
AppId={{6A58BA50-92BB-4F2B-9F47-D7E5C7271DA2}
AppName=Lunchtab Product Initialization
AppVersion={#MyAppVersion}
AppPublisher=Internal
DefaultDirName={localappdata}\Programs\Lunchtab Product Initialization
DefaultGroupName=Lunchtab Product Initialization
DisableProgramGroupPage=yes
OutputDir=..\release\v{#MyAppVersion}
OutputBaseFilename=Lunchtab-Product-Initialization-Setup-v{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\Lunchtab Product Initialization.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\Lunchtab Product Initialization\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Lunchtab Product Initialization"; Filename: "{app}\Lunchtab Product Initialization.exe"
Name: "{autodesktop}\Lunchtab Product Initialization"; Filename: "{app}\Lunchtab Product Initialization.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Lunchtab Product Initialization.exe"; Description: "{cm:LaunchProgram,Lunchtab Product Initialization}"; Flags: nowait postinstall skipifsilent
