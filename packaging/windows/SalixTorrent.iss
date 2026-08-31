#ifndef MyAppVersion
  #define MyAppVersion "0.3.0"
#endif
#ifndef BuildDir
  #define BuildDir "..\..\dist\phase10\standalone"
#endif

#define MyAppName "SalixTorrent"
#define MyAppPublisher "Ebdsaleh"
#define MyAppExeName "SalixTorrent.exe"
#define MyAppCliExeName "SalixTorrentCLI.exe"

[Setup]
AppId=SalixTorrent.Ebdsaleh
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\SalixTorrent
DefaultGroupName=SalixTorrent
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
OutputBaseFilename=SalixTorrent-{#MyAppVersion}-Setup
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "torrentassoc"; Description: "Register SalixTorrent as a handler for .torrent files"; GroupDescription: "BitTorrent integration:"
Name: "magnetassoc"; Description: "Use SalixTorrent for magnet: links"; GroupDescription: "BitTorrent integration:"; Flags: unchecked

[Files]
Source: "{#BuildDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#BuildDir}\{#MyAppCliExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SalixTorrent"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\SalixTorrent CLI"; Filename: "{app}\{#MyAppCliExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\SalixTorrent"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--register-torrent-handler --quiet"; Flags: runhidden waituntilterminated; Tasks: torrentassoc
Filename: "{app}\{#MyAppExeName}"; Parameters: "--register-magnet-handler --quiet"; Flags: runhidden waituntilterminated; Tasks: magnetassoc
Filename: "{app}\{#MyAppExeName}"; Description: "Launch SalixTorrent"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--unregister-torrent-handler --unregister-magnet-handler --quiet"; Flags: runhidden waituntilterminated; RunOnceId: "SalixTorrentShellCleanup"
