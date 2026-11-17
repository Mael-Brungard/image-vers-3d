"""
triposg_runner.py - Côté application : lance le worker TripoSG dans son environnement dédié.

TripoSG a des dépendances qui s'entendent mal avec celles de TripoSR (versions de transformers,
diffusers...). Il vit donc dans un second environnement (`runtime/triposg`, créé par l'installateur) et
tourne dans un processus séparé (`python -m threerex.triposg_worker`). Ce module ne dépend ni de PyTorch
ni de TripoSG.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from collections import deque
from pathlib import Path

import trimesh
from PIL import Image

from . import paths

log = logging.getLogger("triposg_runner")

INSTALL_HINT = (
    "Le moteur TripoSG n'est pas fourni avec ce logiciel : sa licence (code dérivé de HunyuanDiT) exclut l'Union "
    "européenne. Utilise le moteur TripoSR."
)


def venv_python(root: Path | None = None) -> Path:
    """Interpréteur de l'environnement TripoSG (THREEREX_TRIPOSG_PYTHON le remplace s'il est défini)."""
    override = os.environ.get("THREEREX_TRIPOSG_PYTHON")
    return Path(override) if override else paths.venv_python("triposg", root)


class WorkerOutput(Exception):
    """Dernières lignes affichées par le worker : jointes à l'erreur pour les détails techniques."""


class TripoSGRunner:
    def __init__(self, root: Path | None = None, python: Path | None = None, worker: Path | None = None) -> None:
        """`worker` : script de remplacement (tests) ; sans lui, le worker est le module threerex.triposg_worker."""
        self.root = Path(root) if root else paths.APP_ROOT
        self.python = Path(python) if python else venv_python(self.root)
        self.worker = Path(worker) if worker else None

    def available(self) -> bool:
        worker_ok = self.worker.exists() if self.worker else True
        return self.python.exists() and (self.root / "vendor" / "TripoSG").exists() and worker_ok

    def command(self) -> list[str]:
        """Début de la ligne de commande du worker."""
        target = [str(self.worker)] if self.worker else ["-m", "threerex.triposg_worker"]
        return [str(self.python), "-u", *target]

    def generate(self, prepared: Image.Image, steps: int, progress, seed: int = 42, cutout: Image.Image | None = None):
        """Image préparée (objet centré sur fond blanc) -> (maillage d'aperçu, maillage complet, remarques).

        `cutout` : le même objet détouré (RGBA) ; s'il est fourni, la forme est colorée d'après l'image.
        Les remarques sont des textes à montrer à l'utilisateur (couleurs non appliquées, etc.).
        """
        if not self.available():
            raise RuntimeError("Le moteur TripoSG n'est pas installé. " + INSTALL_HINT)

        work = Path(tempfile.mkdtemp(prefix="triposg_"))
        try:
            image_path = work / "entree.png"
            prepared.convert("RGB").save(image_path)
            out_dir = work / "sortie"
            cutout_path = None
            if cutout is not None:
                cutout_path = work / "objet.png"
                cutout.convert("RGBA").save(cutout_path)
            notes = self._run(image_path, out_dir, steps, seed, progress, cutout_path)

            full_path, preview_path = out_dir / "mesh.ply", out_dir / "preview.ply"
            if not full_path.exists():
                raise RuntimeError("TripoSG n'a produit aucun fichier. Voir le journal pour le détail.")
            full = trimesh.load(str(full_path), force="mesh", process=False)
            preview = trimesh.load(str(preview_path), force="mesh", process=False) if preview_path.exists() else full
            full.metadata.clear()  # le chemin du fichier temporaire n'a rien à faire dans un export
            preview.metadata.clear()
            return preview, full, notes
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _run(self, image_path: Path, out_dir: Path, steps: int, seed: int, progress, cutout_path=None) -> list[str]:
        cmd = [
            *self.command(),
            "--image", str(image_path), "--out-dir", str(out_dir),
            "--steps", str(int(steps)), "--seed", str(int(seed)),
        ]
        if cutout_path is not None:
            cmd += ["--cutout", str(cutout_path)]
        env = self.environment()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        log.info("Lancement du worker TripoSG : %s", " ".join(cmd))
        proc = subprocess.Popen(
            cmd, cwd=str(self.root), env=env, creationflags=flags,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
        tail: deque[str] = deque(maxlen=80)
        user_error = None
        notes: list[str] = []
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip()
            if not line:
                continue
            if line.startswith("@@ERREUR"):
                user_error = line[len("@@ERREUR"):].strip()
            elif line.startswith("@@NOTE"):
                notes.append(line[len("@@NOTE"):].strip())
            elif line.startswith("@@"):
                message = line[2:].strip()
                log.info("worker : %s", message)
                progress(message)
            else:
                tail.append(line[-400:])
        code = proc.wait()
        if code != 0:
            detail = "\n".join(list(tail)[-40:]) or "(aucune sortie)"
            raise RuntimeError(user_error or self._explain(code, list(tail))) from WorkerOutput(detail)
        return notes

    def environment(self) -> dict[str, str]:
        """Environnement du worker : il doit retrouver ce paquet, la racine de l'application et les données."""
        package_parent = str(paths.PACKAGE_DIR.parent)
        pythonpath = os.pathsep.join(p for p in (package_parent, os.environ.get("PYTHONPATH", "")) if p)
        return dict(
            os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
            PYTHONPATH=pythonpath, THREEREX_HOME=str(self.root),
        )

    @staticmethod
    def _explain(code: int, tail: list[str]) -> str:
        text = "\n".join(tail)
        log.error("Le worker TripoSG a échoué (code %s) :\n%s", code, text)
        if "OutOfMemoryError" in text or "out of memory" in text.lower():
            return (
                "Mémoire GPU insuffisante pour TripoSG. Ferme les autres programmes qui utilisent "
                "le GPU, ou utilise TripoSR."
            )
        last = tail[-1] if tail else "aucun détail"
        return f"TripoSG a échoué (code {code}) : {last}\n\nPour vérifier l'installation, ouvre « Diagnostic » dans le menu Démarrer."
