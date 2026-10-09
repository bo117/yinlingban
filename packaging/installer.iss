; Inno Setup installer for the PyInstaller onedir output.
#define MyAppName "银龄伴"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "银龄伴项目组"
#define MyAppExeName "Yinlingban.exe"

[Setup]
AppId={{A8D6F4D7-9D55-4F72-8E48-5C2C9B8A1B31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Yinlingban
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=Yinlingban-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
; Add a signed icon and publisher certificate before public distribution.

[Files]
Source: "..\dist\Yinlingban\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载{#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动{#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  MsgBox('银龄伴桌面版需要 Microsoft Edge WebView2 Runtime。' + #13#10 +
    'Windows 10/11 通常已预装；如果启动失败，请先安装 WebView2 Runtime。',
    mbInformation, MB_OK);
end;
