#!/usr/bin/env python3
"""
triposg_worker.py - Exécute TripoSG (image -> forme 3D détaillée) dans l'environnement runtime/triposg.

Lancé par l'application (triposg_runner.py) avec :  python -m threerex.triposg_worker ...
Jamais directement par l'utilisateur, sauf pour vérifier l'installation :
    runtime\\triposg\\Scripts\\python -m threerex.triposg_worker --check

Les lignes qui commencent par « @@ » sont des messages d'avancement destinés à l'application.
TripoSG (licence MIT) : https://github.com/VAST-AI-Research/TripoSG
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import threading
import time
from pathlib import Path

from . import paths  # noqa: E402

REPO = paths.TRIPOSG_DIR
WEIGHTS = paths.TRIPOSG_WEIGHTS
REPO_ID = "VAST-AI/TripoSG"
PREVIEW_FACES = 150_000  # maillage allégé pour la visionneuse ; l'export garde le maillage de EXPORT_FACES
EXPORT_FACES = 400_000   # TripoSG sort près d'un million de faces : 400 000 suffisent et allègent le fichier de moitié


class UserFacingError(Exception):
    """Erreur dont le message est destiné à l'utilisateur (affiché tel quel par l'application)."""


def say(message: str) -> None:
    print(f"@@ {message}", flush=True)


def note(message: str) -> None:
    """Remarque à montrer à l'utilisateur une fois le calcul terminé (« Couleurs non appliquées »...)."""
    print(f"@@NOTE {message}", flush=True)


def setup_paths() -> bool:
    """Rend le dépôt TripoSG importable ; renvoie True si le module factice `diso` est utilisé."""
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    try:
        importlib.import_module("diso")
        return False
    except Exception:  # noqa: BLE001 - absent ou extension inutilisable
        shims = str(paths.SHIMS_DIR)
        if shims not in sys.path:
            sys.path.insert(0, shims)
        return True


def import_pipeline():
    if not REPO.exists():
        raise UserFacingError(f"Le dossier {REPO} est introuvable : réinstalle l'application (composant « Moteur TripoSG »).")
    setup_paths()
    from triposg.pipelines.pipeline_triposg import TripoSGPipeline

    return TripoSGPipeline


def watch_download(stop: threading.Event) -> None:
    """Affiche la taille déjà téléchargée pendant le téléchargement des poids."""
    while not stop.wait(3.0):
        try:
            size = sum(f.stat().st_size for f in WEIGHTS.rglob("*") if f.is_file())
        except OSError:
            continue
        say(f"Téléchargement des poids de TripoSG (première utilisation) : {size / 1e9:.1f} Go reçus…")


def ensure_weights() -> None:
    from huggingface_hub import snapshot_download

    stop = threading.Event()
    watcher = threading.Thread(target=watch_download, args=(stop,), daemon=True)
    watcher.start()
    try:
        snapshot_download(repo_id=REPO_ID, local_dir=str(WEIGHTS))
    except Exception as exc:  # noqa: BLE001
        if (WEIGHTS / "model_index.json").exists():
            say(f"Hors ligne ou Hugging Face injoignable ({type(exc).__name__}) : poids déjà présents, on continue.")
        else:
            raise
    finally:
        stop.set()


def check() -> int:
    """Vérifie l'installation sans rien générer. Code de sortie 0 si tout est prêt."""
    problems = 0

    def line(ok: bool, text: str, fatal: bool = True) -> None:
        nonlocal problems
        print(("[ OK  ] " if ok else "[ECHEC] " if fatal else "[ avert] ") + text)
        if not ok and fatal:
            problems += 1

    print(f"Python {sys.version.split()[0]} ({sys.executable})")
    try:
        import torch

        line(True, f"torch {torch.__version__}")
        line(torch.cuda.is_available(), "GPU CUDA : " + (torch.cuda.get_device_name(0) if torch.cuda.is_available() else "aucun"))
    except Exception as exc:  # noqa: BLE001
        line(False, f"torch : {exc}")
    for name in ("diffusers", "transformers", "huggingface_hub", "trimesh", "skimage", "scipy", "einops", "peft", "jaxtyping"):
        try:
            module = __import__(name)
            line(True, f"{name} {getattr(module, '__version__', '')}".strip())
        except Exception as exc:  # noqa: BLE001
            line(False, f"{name} : {exc}")
    try:
        importlib.import_module("fast_simplification")
        line(True, "fast_simplification")
    except Exception as exc:  # noqa: BLE001
        line(False, f"fast_simplification : {exc} (l'aperçu sera plus lourd)", fatal=False)
    try:
        importlib.import_module("threerex.mesh_tools")
        line(True, "mesh_tools (nettoyage, allègement, couleurs)")
    except Exception as exc:  # noqa: BLE001
        line(False, f"mesh_tools : {exc}")
    line(REPO.exists(), f"dépôt TripoSG : {REPO}")
    if REPO.exists():
        try:
            fake = setup_paths()
            importlib.import_module("triposg.pipelines.pipeline_triposg")
            line(True, "import de TripoSGPipeline" + (" (diso remplacé par un module factice)" if fake else ""))
        except Exception as exc:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            line(False, f"import de TripoSGPipeline : {type(exc).__name__}: {exc}")
    line((WEIGHTS / "model_index.json").exists(), "poids déjà téléchargés (sinon ils le seront à la première génération)", fatal=False)
    print("\nRESULTAT :", "tout est prêt" if problems == 0 else f"{problems} problème(s)")
    return 1 if problems else 0


def generate(args) -> int:
    import numpy as np
    import torch
    import trimesh
    from PIL import Image

    if not torch.cuda.is_available():
        raise UserFacingError("Aucun GPU CUDA détecté : TripoSG est trop lent sur processeur, il n'est pas proposé.")

    say("Chargement de TripoSG…")
    TripoSGPipeline = import_pipeline()
    ensure_weights()
    say("Chargement du modèle sur le GPU…")
    pipe = TripoSGPipeline.from_pretrained(str(WEIGHTS)).to("cuda", torch.float16)

    image = Image.open(args.image).convert("RGB")
    steps = int(args.steps)
    started = time.time()

    def on_step(_pipe, step, _timestep, callback_kwargs):
        say(f"Génération de la forme : étape {step + 1}/{steps}")
        return callback_kwargs

    generator = torch.Generator(device=pipe.device).manual_seed(int(args.seed))
    samples = pipe(
        image=image,
        generator=generator,
        num_inference_steps=steps,
        guidance_scale=float(args.guidance),
        use_flash_decoder=False,  # extraction scikit-image : pas de compilation (diso)
        dense_octree_depth=8,
        hierarchical_octree_depth=int(args.octree),
        callback_on_step_end=on_step,
    ).samples[0]
    say("Extraction du maillage terminée.")

    vertices, faces = samples[0], samples[1]
    if vertices is None or faces is None or len(faces) == 0:
        raise UserFacingError("TripoSG n'a produit aucune surface pour cette image. Essaie une autre image.")
    mesh = trimesh.Trimesh(np.asarray(vertices, dtype=np.float32), np.ascontiguousarray(faces), process=False)
    if mesh.volume < 0:  # faces à l'envers : on retourne le maillage pour que les normales sortent
        mesh.invert()

    from . import mesh_tools

    mesh, removed = mesh_tools.remove_small_components(mesh)
    if removed:
        say(f"{removed} petit morceau flottant retiré.")
    target = int(args.faces)
    if target > 0 and len(mesh.faces) > target:
        say(f"Allègement du maillage ({len(mesh.faces):,} faces -> {target:,})…".replace(",", " "))
        lighter = mesh_tools.simplify(mesh, target)
        if len(lighter.faces) > target * 1.05:
            note("Allègement impossible (fast_simplification absent) : le fichier sera lourd.")
        mesh = lighter

    if args.cutout:
        say("Application des couleurs de l'image…")
        try:
            rgba = np.asarray(Image.open(args.cutout).convert("RGBA"))
            colors, direct, fit = mesh_tools.project_colors_front(mesh.vertices, mesh.faces, rgba)
            mesh.visual = trimesh.visual.ColorVisuals(mesh, vertex_colors=colors)
            say(f"Couleurs appliquées (calage de l'image sur la forme : {fit:.2f}).")
            if fit < 0.75:
                note("Le calage de l'image sur la forme est moyen : des couleurs peuvent déborder par endroits.")
        except Exception as exc:  # noqa: BLE001 - la forme reste utilisable en gris
            note(f"Couleurs non appliquées : {exc}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    say(f"Enregistrement du maillage ({len(mesh.faces):,} faces)…".replace(",", " "))
    mesh.export(str(out_dir / "mesh.ply"))
    preview = mesh_tools.simplify(mesh, PREVIEW_FACES)
    if preview is not mesh and getattr(mesh.visual, "kind", None) == "vertex":
        preview.visual = trimesh.visual.ColorVisuals(
            preview, vertex_colors=mesh_tools.transfer_vertex_colors(mesh, preview.vertices)
        )
    preview.export(str(out_dir / "preview.ply"))
    say(f"Terminé en {time.time() - started:.0f} s.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Worker TripoSG (utilisé par l'application).")
    parser.add_argument("--check", action="store_true", help="vérifie l'installation et quitte")
    parser.add_argument("--image", help="image préparée (objet centré sur fond blanc)")
    parser.add_argument("--out-dir", help="dossier de sortie (mesh.ply et preview.ply)")
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--guidance", type=float, default=7.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cutout", help="image de l'objet détouré (RGBA) : si présente, la forme est colorée d'après elle")
    parser.add_argument("--faces", type=int, default=EXPORT_FACES, help="nombre de faces visé pour l'export (0 = tout garder)")
    parser.add_argument("--octree", type=int, default=9, help="finesse du maillage (profondeur d'octree)")
    args = parser.parse_args(argv)

    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    if args.check:
        return check()
    if not args.image or not args.out_dir:
        parser.error("--image et --out-dir sont requis")
    try:
        return generate(args)
    except UserFacingError as exc:
        print(f"@@ERREUR {exc}", flush=True)
        return 3


if __name__ == "__main__":
    sys.exit(main())
