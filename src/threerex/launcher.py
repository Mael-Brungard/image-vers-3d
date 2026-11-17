"""
Lanceur de « ThreeRex » : démarre l'application ; si elle ne peut pas démarrer, affiche une fenêtre
d'erreur claire et écrit le détail dans le journal au lieu d'échouer en silence.

C'est le point d'entrée du raccourci du menu Démarrer :  pythonw -m threerex
"""

from __future__ import annotations

import sys
import traceback

from . import paths


def report(details: str) -> None:
    """Écrit la trace dans le journal et prévient l'utilisateur."""
    paths.ensure_user_dirs()
    try:
        paths.LOG_FILE.write_text(details, encoding="utf-8")
    except OSError:
        pass

    last_line = [ln for ln in details.strip().splitlines() if ln.strip()][-1:] or ["(erreur inconnue)"]
    message = (
        "L'application n'a pas pu démarrer.\n\n"
        "Cause la plus probable : l'installation est incomplète. Lance « Réparer l'installation » depuis "
        "le menu Démarrer (dossier « ThreeRex »), ou réinstalle l'application.\n"
        "Le raccourci « Diagnostic » indique ce qui manque.\n\n"
        f"Détail technique :\n{last_line[0]}\n\n"
        f"Trace complète : {paths.LOG_FILE}"
    )
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, "ThreeRex - démarrage impossible", 0x10)
            return
        except Exception:  # noqa: BLE001
            pass
    print(message, file=sys.stderr)


def set_windows_app_id() -> None:
    """Regroupe la fenêtre sous sa propre icône dans la barre des tâches de Windows."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ThreeRex.Studio")
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    set_windows_app_id()
    try:
        from . import studio  # charge PyTorch, Qt, pyqtgraph : c'est ici qu'une installation incomplète se voit

        return studio.main()
    except Exception:  # noqa: BLE001
        report(traceback.format_exc())
        return 1
