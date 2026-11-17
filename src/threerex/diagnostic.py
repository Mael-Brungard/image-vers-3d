#!/usr/bin/env python3
"""
diagnostic.py - Vérifie que tout est en place pour « ThreeRex ».

Lancé par l'installateur à la fin de l'installation, par le raccourci « Diagnostic » du menu Démarrer, ou à la
main :  python -m threerex.diagnostic
Affiche un rapport OK / ECHEC, facile à copier-coller pour demander de l'aide.
Code de sortie : 0 si tout est prêt, 1 sinon.
L'absence de carte graphique NVIDIA n'est qu'un avertissement : l'application démarre, mais calcule sur processeur.
"""

from __future__ import annotations

import importlib
import platform
import subprocess
import sys
from . import __version__, paths

if paths.TRIPOSR_DIR.is_dir() and str(paths.TRIPOSR_DIR) not in sys.path:
    sys.path.insert(0, str(paths.TRIPOSR_DIR))

problems: list[str] = []


def line(ok: bool, label: str, detail: str = "") -> None:
    print(f"  [{'OK' if ok else 'ECHEC'}] {label}" + (f" : {detail}" if detail else ""))
    if not ok:
        problems.append(label)


def try_import(module: str, label: str | None = None, required: bool = True) -> object | None:
    try:
        mod = importlib.import_module(module)
        line(True, label or module, str(getattr(mod, "__version__", "")))
        return mod
    except BaseException as exc:  # noqa: BLE001 - on veut tout rapporter, y compris SystemExit
        detail = f"{exc.__class__.__name__}: {exc}".splitlines()[0][:200]
        if required:
            line(False, label or module, detail)
        else:
            print(f"  [----] {label or module} (facultatif) : {detail}")
        return None


def check_triposg() -> None:
    """Moteur TripoSG : facultatif, il ne compte jamais comme un problème de l'installation principale."""
    print("\nMoteur TripoSG (facultatif) :")
    try:
        from .triposg_runner import TripoSGRunner

        runner = TripoSGRunner()
    except BaseException as exc:  # noqa: BLE001
        print(f"  [----] vérification impossible : {exc.__class__.__name__}: {exc}")
        return
    if not runner.available():
        print("  [----] non installé (réinstalle l'application en cochant « Moteur TripoSG » pour l'ajouter)")
        return
    result = subprocess.run(
        [*runner.command(), "--check"], env=runner.environment(),
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(runner.root),
    )
    for out in (result.stdout + result.stderr).splitlines():
        print("    " + out)
    if result.returncode == 0:
        print("  [OK] TripoSG est prêt")
    else:
        print("  [ATTENTION] TripoSG est incomplet : lance « Réparer l'installation » depuis le menu Démarrer")


def check_trellis() -> None:
    """Moteur « Qualité maximale » (TRELLIS.2) : facultatif, installé à la demande depuis la fenêtre du logiciel."""
    print("\nMoteur Qualité maximale (TRELLIS.2, facultatif) :")
    try:
        from .trellis_runner import RELEASE_TAG, TrellisRunner

        runner = TrellisRunner()
    except BaseException as exc:  # noqa: BLE001
        print(f"  [----] vérification impossible : {exc.__class__.__name__}: {exc}")
        return
    if not runner.supported():
        print("  [----] prévu pour Windows avec une carte NVIDIA")
        return
    if runner.ready():
        print(f"  [OK] prêt (programme {RELEASE_TAG}, modèles {runner.quant}) : {runner.base}")
        return
    missing = len(runner.missing_models())
    print(f"  [----] pas encore installé ({missing} fichier(s) de modèle manquant(s), programme "
          f"{'présent' if runner.program_ready() else 'absent'}). Choisis « TRELLIS.2 » dans le logiciel puis « Installer le moteur ».")


def main() -> int:
    print(f"=== Diagnostic ThreeRex {__version__} ===")
    print(f"Racine de l'application : {paths.APP_ROOT}")
    print(f"Données de l'utilisateur : {paths.DATA_DIR}")
    print(f"Système : {platform.platform()}")
    print(f"Python  : {sys.version.split()[0]} ({sys.executable})")
    version_ok = (3, 10) <= sys.version_info[:2] <= (3, 12)
    line(version_ok, "Version de Python (3.10 à 3.12 attendue)", f"{sys.version_info[0]}.{sys.version_info[1]}")

    print("\nDossier TripoSR :")
    line((paths.TRIPOSR_DIR / "tsr").is_dir(), "vendor/TripoSR/tsr présent")

    print("\nPyTorch :")
    torch = try_import("torch", "torch")
    if torch is not None:
        if torch.cuda.is_available():
            line(True, "CUDA disponible (GPU NVIDIA utilisable)", torch.cuda.get_device_name(0))
        else:
            # Avertissement seulement : l'application fonctionne, mais sur processeur (très lent).
            print("  [ATTENTION] CUDA indisponible : calcul sur processeur, très lent. "
                  "Mets à jour le pilote NVIDIA, puis lance « Réparer l'installation ».")

    print("\nMoteur 3D :")
    # torchmcubes (à compiler) est facultatif : sans lui, le remplaçant scikit-image est utilisé.
    if try_import("torchmcubes", "torchmcubes (extraction du maillage sur GPU)", required=False) is None:
        from . import mcubes_fallback

        mcubes_fallback.install_if_needed()
        try_import("skimage", "scikit-image (extraction du maillage, remplace torchmcubes)")
    try_import("tsr.system", "TripoSR (tsr.system)")
    try_import("rembg", "rembg (retrait du fond)")
    try_import("onnxruntime", "onnxruntime")
    try_import("trimesh", "trimesh")
    try_import("xatlas", "xatlas (texture cuite)", required=False)
    try_import("moderngl", "moderngl (texture cuite)", required=False)

    print("\nInterface :")
    try_import("PySide6", "PySide6 (fenêtre)")
    try_import("pyqtgraph", "pyqtgraph (visionneuse 3D)")
    try_import("OpenGL", "PyOpenGL")

    check_triposg()
    check_trellis()

    print()
    if problems:
        print(f"RESULTAT : {len(problems)} problème(s) : " + " ; ".join(problems))
        print("Lance « Réparer l'installation » ; si l'erreur persiste, copie ce rapport pour demander de l'aide.")
        return 1
    print("RESULTAT : tout est prêt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
