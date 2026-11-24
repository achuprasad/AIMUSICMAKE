; Inno Setup script for Local Audio Studio (offline build).  Built by scripts\build-windows.ps1.
; Per-user install: no administrator rights needed, installs to %LOCALAPPDATA%\Programs.
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef SourceDir
  #error SourceDir must point at the PyInstaller output folder
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif

[Setup]
AppId={{8F3B9C2E-6A1D-4E7B-9C55-2D4A7E1B3F90}
AppName=Local Audio Studio
AppVersion={#AppVersion}
AppVerName=Local Audio Studio {#AppVersion}
AppPublisher=Local Audio Studio
DefaultDirName={autopf}\Local Audio Studio
DefaultGroupName=Local Audio Studio
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=LocalAudioStudio-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\LocalAudioStudio.exe
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

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Local Audio Studio"; Filename: "{app}\LocalAudioStudio.exe"
Name: "{group}\Uninstall Local Audio Studio"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Local Audio Studio"; Filename: "{app}\LocalAudioStudio.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LocalAudioStudio.exe"; Description: "Launch Local Audio Studio"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; app logs and the app window's browser profile. Your songs in Music\Local Audio Studio are NOT deleted.
Type: filesandordirs; Name: "{localappdata}\LocalAudioStudio"
