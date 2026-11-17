"""
Emplacements des fichiers de l'application : un seul endroit où les chercher.

Trois mondes à distinguer :
  - le code (ce paquet), installé dans un environnement Python ;
  - la racine de l'application (`APP_ROOT`) : elle contient `runtime/` (les environnements Python créés par
    l'installateur) et `vendor/` (les dépôts TripoSR et TripoSG, aux versions épinglées) ;
  - les données de l'utilisateur (`DATA_DIR`) : journaux, poids des modèles. Elles survivent à une mise à jour.

Ce module n'importe rien de lourd : le programme de calcul TripoSG et le lanceur l'utilisent aussi.
Variables d'environnement qui prennent le pas (utiles aux tests et aux installations particulières) :
  THREEREX_HOME     racine de l'application
  THREEREX_DATA     dossier des données de l'utilisateur
  THREEREX_TRIPOSG_PYTHON   interpréteur Python de l'environnement TripoSG
  THREEREX_TRELLIS_EXE / THREEREX_TRELLIS_QUANT   moteur Qualité maximale (voir trellis_runner.py)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PACKAGE_DIR / "assets"
SHIMS_DIR = PACKAGE_DIR / "shims"


def find_app_root(environ=None, prefix: str | None = None, package_dir: Path | None = None) -> Path:
    """Racine de l'application, dans l'ordre : variable THREEREX_HOME, installation Windows
    (`<racine>/runtime/<environnement>`), dépôt de développement (`<racine>/src/threerex`), dossier courant."""
    environ = os.environ if environ is None else environ
    if environ.get("THREEREX_HOME"):
        return Path(environ["THREEREX_HOME"]).resolve()
    venv = Path(prefix or sys.prefix).resolve()
    if venv.parent.name == "runtime":
        return venv.parent.parent
    candidate = (package_dir or PACKAGE_DIR).parents[1]
    if (candidate / "pyproject.toml").exists():
        return candidate
    return Path.cwd()


def find_data_dir(environ=None, platform: str | None = None) -> Path:
    """Dossier des données de l'utilisateur (journaux, poids des modèles)."""
    environ = os.environ if environ is None else environ
    if environ.get("THREEREX_DATA"):
        return Path(environ["THREEREX_DATA"])
    platform = platform or sys.platform
    if platform == "win32":
        base = environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ThreeRex"
    base = environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "threerex"


def venv_python(name: str, root: Path | None = None, windows: bool | None = None) -> Path:
    """Interpréteur Python d'un environnement (`main` ou `triposg`) : `<racine>/runtime/<nom>` (installateur),
    sinon `<racine>/.venv-<nom>` (développement). Renvoie le premier candidat s'il n'existe nulle part."""
    root = APP_ROOT if root is None else Path(root)
    windows = (os.name == "nt") if windows is None else windows
    relative = Path("Scripts") / "python.exe" if windows else Path("bin") / "python"
    candidates = [root / "runtime" / name / relative, root / f".venv-{name}" / relative]
    return next((c for c in candidates if c.exists()), candidates[0])


APP_ROOT = find_app_root()
RUNTIME_DIR = APP_ROOT / "runtime"
VENDOR_DIR = APP_ROOT / "vendor"
TRIPOSR_DIR = VENDOR_DIR / "TripoSR"
TRIPOSG_DIR = VENDOR_DIR / "TripoSG"

DATA_DIR = find_data_dir()
LOG_DIR = DATA_DIR / "logs"
MODELS_DIR = DATA_DIR / "models"
TRIPOSG_WEIGHTS = MODELS_DIR / "TripoSG"
TRELLIS_DIR = DATA_DIR / "engines" / "trellis"  # moteur « Qualité maximale » : programme et poids téléchargés
CREATIONS_DIR = DATA_DIR / "creations"  # liste de « Mes créations » et vignettes
LOG_FILE = LOG_DIR / "studio.log"
CONSOLE_LOG_FILE = LOG_DIR / "studio_console.log"


def configure_environment(environ=None) -> None:
    """Range les modèles téléchargés (TripoSR, détourage) dans le dossier de données de l'application plutôt que dans
    le profil de l'utilisateur : une seule chose à sauvegarder ou à supprimer. Une variable déjà définie reste prioritaire.
    À appeler avant d'importer huggingface_hub ou rembg, qui lisent ces variables à l'import."""
    environ = os.environ if environ is None else environ
    environ.setdefault("HF_HOME", str(MODELS_DIR / "huggingface"))
    environ.setdefault("U2NET_HOME", str(MODELS_DIR / "rembg"))


def legacy_data_dir(environ=None, platform: str | None = None) -> Path | None:
    """Ancien dossier de données, du temps où le logiciel s'appelait « Image vers 3D » (aucun avec THREEREX_DATA)."""
    environ = os.environ if environ is None else environ
    if environ.get("THREEREX_DATA"):
        return None
    platform = platform or sys.platform
    if platform == "win32":
        base = environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ImageVers3D"
    base = environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "imagevers3d"


def migrate_legacy_data(new: Path, old: Path | None) -> bool:
    """Reprend le dossier de l'ancien nom : déplacé d'un bloc (même disque, donc instantané), il garde les modèles de plusieurs
    Go déjà téléchargés. Sans effet si l'ancien n'existe pas ou si le nouveau contient déjà des fichiers. Renvoie vrai si déplacé."""
    try:
        if old is None or not old.is_dir() or old.resolve() == new.resolve():
            return False
        if new.exists():
            if any(p.is_file() for p in new.rglob("*")):
                return False
            for folder in sorted((p for p in new.rglob("*") if p.is_dir()), reverse=True):
                folder.rmdir()  # restes vides d'un lancement précédent
            new.rmdir()
        new.parent.mkdir(parents=True, exist_ok=True)
        old.rename(new)
        return True
    except OSError:  # ancien dossier utilisé par un autre programme : on repart d'un dossier neuf
        return False


def ensure_user_dirs() -> None:
    """Crée les dossiers de données (après avoir repris ceux de l'ancien nom) ; sans conséquence s'ils existent déjà ou si
    le disque refuse."""
    migrate_legacy_data(DATA_DIR, legacy_data_dir())
    for folder in (LOG_DIR, MODELS_DIR, CREATIONS_DIR):
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
