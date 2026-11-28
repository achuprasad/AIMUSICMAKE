; Inno Setup script for Mixlumo (offline build).  Built by scripts\build-windows.ps1.
; Per-user install: no administrator rights needed, installs to %LOCALAPPDATA%\Programs.
#ifndef AppVersion
  #define AppVersion "1.3.0"
#endif
#ifndef SourceDir
  #error SourceDir must point at the PyInstaller output folder
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

[Setup]
AppId={{8F3B9C2E-6A1D-4E7B-9C55-2D4A7E1B3F90}
AppName=Mixlumo
AppVersion={#AppVersion}
AppVerName=Mixlumo {#AppVersion}
AppPublisher=Mixlumo
AppCopyright=Copyright (c) 2026 Achu Prasad. All rights reserved.
DefaultDirName={autopf}\Mixlumo
DefaultGroupName=Mixlumo
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=Mixlumo-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\Mixlumo.exe
WizardStyle=modern
Compression=lzma2/normal
SolidCompression=no
LZMANumBlockThreads=4
; The app is ~6 GB unpacked; split into slices (setup .exe + .bin files). 2,000,000,000 bytes keeps
; every slice under GitHub's 2 GiB per-release-asset limit ("max" produced a 2.55 GB slice).
DiskSpanning=yes
DiskSliceSize=2000000000
CloseApplications=yes
DisableProgramGroupPage=yes
; 1.0.0 was called "Local Audio Studio": always use the new folder and Start-menu name instead of
; reusing the previous ones, and clean the old ones up in [InstallDelete]
UsePreviousAppDir=no
UsePreviousGroup=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[InstallDelete]
; upgrade from Local Audio Studio 1.0.0: remove the old program files and shortcuts (never user songs,
; which live in the Music folder)
Type: filesandordirs; Name: "{autopf}\Local Audio Studio"
Type: filesandordirs; Name: "{userprograms}\Local Audio Studio"
Type: files; Name: "{userdesktop}\Local Audio Studio.lnk"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Mixlumo"; Filename: "{app}\Mixlumo.exe"
Name: "{group}\Uninstall Mixlumo"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Mixlumo"; Filename: "{app}\Mixlumo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Mixlumo.exe"; Description: "Launch Mixlumo"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; app logs and the app window's browser profile. Your songs in Music\Mixlumo are NOT deleted.
Type: filesandordirs; Name: "{localappdata}\Mixlumo"
