@echo off
rem ===========================================================================
rem  setup_runtime.bat - Cree l'environnement Python de "Image vers 3D"
rem  (PyTorch + dependances verrouillees + le logiciel).
rem
rem  Lance par l'installateur, et par le raccourci "Reparer l'installation".
rem  Usage : setup_runtime.bat [cuda|cpu] [silent] [repair]
rem    cuda    PyTorch pour carte NVIDIA (par defaut)
rem    cpu     PyTorch sur processeur (tests, ou ordinateur sans carte NVIDIA)
rem    silent  aucune pause ni question (installation silencieuse)
rem    repair  efface l'environnement existant avant de le recreer
rem  Variable facultative : IMAGEVERS3D_TORCH_INDEX = autre source de PyTorch.
rem
rem  Sans danger a relancer : les etapes deja faites sont rapides.
rem  Fichier volontairement en ASCII : cmd.exe ne lit pas bien les accents.
rem ===========================================================================
setlocal EnableExtensions
cd /d "%~dp0"

set "FLAVOR=cuda"
set "SILENT=0"
set "REPAIR=0"
for %%A in (%*) do (
  if /I "%%~A"=="cpu" set "FLAVOR=cpu"
  if /I "%%~A"=="cuda" set "FLAVOR=cuda"
  if /I "%%~A"=="silent" set "SILENT=1"
  if /I "%%~A"=="repair" set "REPAIR=1"
)

if not exist setup_config.bat (
  echo setup_config.bat est introuvable : l'installation de l'application est incomplete.
  goto fail
)
call setup_config.bat
if /I "%FLAVOR%"=="cpu" (set "TORCH_INDEX=%TORCH_INDEX_CPU%") else (set "TORCH_INDEX=%TORCH_INDEX_CUDA%")
if defined IMAGEVERS3D_TORCH_INDEX set "TORCH_INDEX=%IMAGEVERS3D_TORCH_INDEX%"

set "UV=%~dp0bin\uv.exe"
set "VENV=%~dp0runtime\main"
set "VENV_PYTHON=%VENV%\Scripts\python.exe"
set "UV_PYTHON_INSTALL_DIR=%~dp0runtime\python"
set "UV_CACHE_DIR=%LOCALAPPDATA%\ImageVers3D\uv-cache"
set "UV_PYTHON_DOWNLOADS=automatic"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if not exist "%UV%" (
  echo bin\uv.exe est introuvable : l'installation de l'application est incomplete.
  goto fail
)

echo.
echo ==== Image vers 3D : installation des composants (%FLAVOR%) ====
echo Cette etape telecharge PyTorch et les bibliotheques (plusieurs Go) : elle peut durer 10 a 30 minutes.
echo Ne ferme pas cette fenetre.
echo.

if "%REPAIR%"=="1" (
  echo == Reparation : suppression de l'environnement existant
  if exist "%VENV%" rmdir /s /q "%VENV%"
  if exist "%~dp0runtime\ready.txt" del /q "%~dp0runtime\ready.txt"
)
if exist "%~dp0runtime\ready.txt" del /q "%~dp0runtime\ready.txt"

echo == [1/5] Python %PYTHON_VERSION% (copie privee, sans toucher a ton Python)
"%UV%" python install %PYTHON_VERSION%
if errorlevel 1 goto fail

echo == [2/5] Environnement
"%UV%" venv "%VENV%" --python %PYTHON_VERSION% --managed-python --allow-existing
if errorlevel 1 goto fail

echo == [3/5] PyTorch %TORCH_VERSION% depuis %TORCH_INDEX%
"%UV%" pip install --python "%VENV_PYTHON%" "torch==%TORCH_VERSION%" --index-url "%TORCH_INDEX%"
if errorlevel 1 goto fail

echo == [4/5] Bibliotheques
"%UV%" pip install --python "%VENV_PYTHON%" --require-hashes -r "%~dp0requirements\windows-py311.lock"
if errorlevel 1 goto fail

echo == [5/5] Image vers 3D
set "WHEEL="
for %%F in ("%~dp0wheels\imagevers3d-*.whl") do set "WHEEL=%%~fF"
if not defined WHEEL (
  echo Aucun fichier wheels\imagevers3d-*.whl : l'installation de l'application est incomplete.
  goto fail
)
"%UV%" pip install --python "%VENV_PYTHON%" --no-deps --reinstall-package imagevers3d "%WHEEL%"
if errorlevel 1 goto fail

echo.
echo == Verification
"%VENV_PYTHON%" -m imagevers3d.diagnostic
if errorlevel 1 goto fail

echo ok> "%~dp0runtime\ready.txt"
echo.
echo Installation des composants terminee.
endlocal
exit /b 0

:fail
echo.
echo ================================================================
echo  L'installation des composants s'est arretee a cause de l'erreur
echo  ci-dessus. Verifie ta connexion Internet et l'espace disque
echo  (10 Go libres), puis lance "Reparer l'installation" depuis le
echo  menu Demarrer. Si l'erreur persiste, copie les dernieres lignes
echo  de cette fenetre (ou le fichier logs\setup_runtime.log) pour
echo  demander de l'aide.
echo ================================================================
if not "%SILENT%"=="1" pause
endlocal
exit /b 1
