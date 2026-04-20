; Inno Setup script for IR Spectra Analyzer
; -------------------------------------------
; Produces IR-Spectra-Analyzer-Setup-<version>.exe that installs the
; PyInstaller-built folder into %ProgramFiles%\IR Spectra Analyzer and
; creates Start Menu + optional Desktop shortcuts. Also registers
; .spa and .irproj file associations.
;
; Build prerequisites:
;   1. Run PyInstaller first:
;        pyinstaller packaging/ir-spectra-analyzer.spec --clean --noconfirm
;   2. Install Inno Setup 6 (https://jrsoftware.org/isinfo.php).
;   3. Compile this script:
;        iscc packaging/installer.iss
;      The signed installer lands in dist/installer/.
;
; The CI workflow (.github/workflows/release.yml) performs steps 1–3
; automatically whenever a vX.Y.Z tag is pushed.

#define MyAppName "IR Spectra Analyzer"
#define MyAppVersion "0.4.1"
#define MyAppPublisher "IRSpectra"
#define MyAppURL "https://github.com/kubikhavran/ir-spectra-analyzer"
#define MyAppExeName "IR Spectra Analyzer.exe"
#define MySourceDir "..\dist\IR Spectra Analyzer"

[Setup]
AppId={{A1B4FA77-17DF-4C7F-B0B5-4F6D2A6A7C21}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DisableDirPage=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=IR-Spectra-Analyzer-Setup-{#MyAppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequiredOverridesAllowed=dialog commandline
LicenseFile=..\LICENSE
WizardSmallImageFile=
DisableWelcomePage=no
ShowLanguageDialog=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "associateSpa"; Description: "Associate .spa files with {#MyAppName}"; GroupDescription: "File associations:"
Name: "associateIrproj"; Description: "Associate .irproj files with {#MyAppName}"; GroupDescription: "File associations:"

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"
Name: "{group}\{cm:ProgramOnTheWeb,{#MyAppName}}"; Filename: "{#MyAppURL}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon

[Registry]
; .spa file association (scoped under IRSpectraAnalyzer.spa to avoid clobbering OMNIC)
Root: HKCR; Subkey: ".spa"; ValueType: string; ValueName: ""; ValueData: "IRSpectraAnalyzer.spa"; Flags: uninsdeletevalue; Tasks: associateSpa
Root: HKCR; Subkey: "IRSpectraAnalyzer.spa"; ValueType: string; ValueName: ""; ValueData: "IR Spectrum (.spa)"; Flags: uninsdeletekey; Tasks: associateSpa
Root: HKCR; Subkey: "IRSpectraAnalyzer.spa\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\assets\icon.ico"; Tasks: associateSpa
Root: HKCR; Subkey: "IRSpectraAnalyzer.spa\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associateSpa

; .irproj file association (native project format)
Root: HKCR; Subkey: ".irproj"; ValueType: string; ValueName: ""; ValueData: "IRSpectraAnalyzer.Project"; Flags: uninsdeletevalue; Tasks: associateIrproj
Root: HKCR; Subkey: "IRSpectraAnalyzer.Project"; ValueType: string; ValueName: ""; ValueData: "IR Spectra Analyzer Project"; Flags: uninsdeletekey; Tasks: associateIrproj
Root: HKCR; Subkey: "IRSpectraAnalyzer.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\assets\icon.ico"; Tasks: associateIrproj
Root: HKCR; Subkey: "IRSpectraAnalyzer.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: associateIrproj

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
