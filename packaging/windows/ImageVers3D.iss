; ImageVers3D.iss - Installateur Windows de "Image vers 3D" (Inno Setup 6).
;
; Compilation (depuis la racine du depot, apres packaging/build_stage.py) :
;   ISCC /DAppVersion=0.1.0 packaging\windows\ImageVers3D.iss
; Resultat : build\installer\ImageVers3D-Setup-<version>.exe
;
; L'installateur est petit : il embarque uv, le code de TripoSR et le logiciel. PyTorch et les bibliotheques sont
; telechargees a l'installation par setup_runtime.bat (voir docs/ARCHITECTURE.md).
; Parametres de la ligne de commande : /TORCH=cpu (PyTorch sur processeur, pour les tests), /VERYSILENT, /DIR=...
; Ce fichier est enregistre en UTF-8 avec BOM : ne pas le reenregistrer autrement.

#define AppName "Image vers 3D"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef StageDir
  #define StageDir "..\..\build\stage"
#endif

[Setup]
AppId={{33B63593-5A55-4289-935B-E503D4021F07}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Mael Brungard
DefaultDirName={autopf}\ImageVers3D
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\build\installer
OutputBaseFilename=ImageVers3D-Setup-{#AppVersion}
SetupIconFile={#StageDir}\icon.ico
UninstallDisplayIcon={app}\icon.ico
UninstallDisplayName={#AppName}
LicenseFile={#StageDir}\EULA.fr.txt
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UsePreviousAppDir=yes
CloseApplications=yes
; PyTorch avec CUDA et les bibliotheques occupent plusieurs Go une fois installes.
ExtraDiskSpaceRequired=9000000000

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Creer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "{#StageDir}\bin\*"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "{#StageDir}\vendor\*"; DestDir: "{app}\vendor"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\wheels\*"; DestDir: "{app}\wheels"; Flags: ignoreversion
Source: "{#StageDir}\requirements\*"; DestDir: "{app}\requirements"; Flags: ignoreversion
Source: "{#StageDir}\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion
Source: "{#StageDir}\setup_runtime.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\setup_config.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#StageDir}\EULA.fr.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}\{#AppName}"; Filename: "{app}\runtime\main\Scripts\pythonw.exe"; Parameters: "-m imagevers3d"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{autoprograms}\{#AppName}\Diagnostic"; Filename: "{cmd}"; Parameters: "/k """"{app}\runtime\main\Scripts\python.exe"" -m imagevers3d.diagnostic"""; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{autoprograms}\{#AppName}\Réparer l'installation"; Filename: "{app}\setup_runtime.bat"; Parameters: "cuda repair"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{autoprograms}\{#AppName}\Licences des composants"; Filename: "{app}\licenses"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\runtime\main\Scripts\pythonw.exe"; Parameters: "-m imagevers3d"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\runtime\main\Scripts\pythonw.exe"; Parameters: "-m imagevers3d"; WorkingDir: "{app}"; Description: "Lancer {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Ces dossiers sont crees par setup_runtime.bat : Inno Setup ne les connait pas.
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\logs"

[Code]
var
  RuntimeFailed: Boolean;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Flavor, Params, LogFile: String;
begin
  if CurStep <> ssPostInstall then
    Exit;
  Flavor := ExpandConstant('{param:TORCH|cuda}');
  ForceDirectories(ExpandConstant('{app}\logs'));
  LogFile := ExpandConstant('{app}\logs\setup_runtime.log');
  WizardForm.StatusLabel.Caption := 'Installation de PyTorch et des bibliotheques (plusieurs minutes)...';
  if WizardSilent then
  begin
    // Silencieux : fenetre cachee, tout est ecrit dans le journal.
    Params := '/c ""' + ExpandConstant('{app}\setup_runtime.bat') + '" ' + Flavor + ' silent > "' + LogFile + '" 2>&1"';
    RuntimeFailed := not Exec(ExpandConstant('{cmd}'), Params, ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0);
  end
  else
  begin
    // Interactif : on laisse la fenetre de commandes visible pour montrer l'avancement.
    Params := '/c ""' + ExpandConstant('{app}\setup_runtime.bat') + '" ' + Flavor + '"';
    RuntimeFailed := not Exec(ExpandConstant('{cmd}'), Params, ExpandConstant('{app}'), SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0);
  end;
  if RuntimeFailed and (not WizardSilent) then
    MsgBox('L''installation des composants (PyTorch, bibliotheques) a echoue.' + #13#10#13#10 +
           'Verifie ta connexion Internet et l''espace disque, puis lance "Réparer l''installation" depuis le menu Démarrer.' + #13#10 +
           'Journal : ' + LogFile, mbError, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  DataDir := ExpandConstant('{localappdata}\ImageVers3D');
  if DirExists(DataDir) and (not UninstallSilent) then
    if MsgBox('Supprimer aussi les modèles téléchargés, le cache et les journaux (dossier ' + DataDir + ') ?' + #13#10 +
              'Ils pèsent plusieurs Go. Garde-les si tu comptes réinstaller le logiciel.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(DataDir, True, True, True);
end;
