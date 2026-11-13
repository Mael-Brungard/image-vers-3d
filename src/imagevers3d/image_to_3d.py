#!/usr/bin/env python3
"""
image_to_3d.py - Transforme une image en modèle 3D, 100 % en local.

S'appuie sur TripoSR (licence MIT, https://github.com/VAST-AI-Research/TripoSR).
Le code de TripoSR est fourni dans vendor/TripoSR par l'installateur (version épinglée) ;
les poids du modèle sont téléchargés une seule fois depuis Hugging Face,
puis tout fonctionne hors ligne.

Utilisation en ligne de commande (depuis l'environnement de l'application) :
    python -m imagevers3d.image_to_3d photo.png
    python -m imagevers3d.image_to_3d photo.png --format glb --texture --output-dir sortie/
    python -m imagevers3d.image_to_3d a.png b.jpg c.webp --format obj

Ce module est aussi importé par l'interface (studio.py).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from . import license as licensing
from . import mcubes_fallback, paths
from .geometry import ORIENTATION

# --- Rend le dépôt TripoSR importable (module "tsr") ---------------------------
TRIPOSR_DIR = paths.TRIPOSR_DIR
if TRIPOSR_DIR.is_dir() and str(TRIPOSR_DIR) not in sys.path:
    sys.path.insert(0, str(TRIPOSR_DIR))

import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

# TripoSR a besoin de torchmcubes, une extension qu'il faut compiler (souvent pénible sous
# Windows). S'il est absent, on utilise un remplaçant équivalent sans compilation.
USING_MCUBES_FALLBACK = mcubes_fallback.install_if_needed()

try:
    import rembg  # noqa: E402
    from tsr.bake_texture import bake_texture  # noqa: E402
    from tsr.system import TSR  # noqa: E402
    from tsr.utils import remove_background, resize_foreground  # noqa: E402
except ImportError as exc:  # message clair plutôt qu'une trace obscure
    raise SystemExit(
        f"Import impossible : {exc}\n"
        "Le dossier vendor/TripoSR est-il présent et les dépendances installées ?\n"
        "Lance « Réparer l'installation » depuis le menu Démarrer, ou réinstalle l'application."
    ) from exc

log = logging.getLogger("image_to_3d")

MODEL_ID = "stabilityai/TripoSR"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


# --- Chargement du modèle -------------------------------------------------------
def pick_device(requested: str = "auto") -> str:
    """Choisit le GPU NVIDIA s'il est disponible, sinon le processeur."""
    if requested != "auto":
        return requested
    return "cuda:0" if torch.cuda.is_available() else "cpu"


def load_model(device: str = "auto", chunk_size: int = 8192) -> tuple[TSR, str]:
    """Charge TripoSR (télécharge les poids au premier lancement).

    chunk_size : plus petit = moins de VRAM mais plus lent (0 = pas de découpage).
    Avec 12 Go de VRAM (RTX 4070 Ti), 8192 est confortable.
    """
    licensing.require()
    device = pick_device(device)
    if device == "cpu":
        log.warning("Aucun GPU CUDA détecté : le calcul se fera sur le processeur (lent).")
    if USING_MCUBES_FALLBACK:
        log.info("torchmcubes absent : extraction du maillage avec le remplaçant scikit-image (processeur).")
    log.info("Chargement du modèle %s sur %s ...", MODEL_ID, device)
    model = TSR.from_pretrained(MODEL_ID, config_name="config.yaml", weight_name="model.ckpt")
    model.renderer.set_chunk_size(chunk_size)
    model.to(device)
    return model, device


# Modèle de détourage, toujours nommé explicitement : le modèle « par défaut » de rembg a changé (il s'agit
# aujourd'hui de RMBG-2.0 de Bria, sous licence non commerciale), ce qui rendrait une revente impossible.
# U²-Net : dépôt sous licence Apache-2.0, environ 170 Mo. Ne pas le remplacer sans relire la licence des poids.
REMBG_MODEL = "u2net"


def new_rembg_session():
    """Session de retrait de fond (télécharge un modèle d'environ 170 Mo au premier usage)."""
    return rembg.new_session(REMBG_MODEL)


# --- Pré-traitement de l'image --------------------------------------------------
def preprocess(
    image: Image.Image,
    remove_bg: bool = True,
    foreground_ratio: float = 0.85,
    rembg_session=None,
    background: float = 0.5,
) -> Image.Image:
    """Prépare l'image : objet centré sur fond uni (gris pour TripoSR, blanc pour TripoSG).

    background : niveau du fond uni, de 0.0 (noir) à 1.0 (blanc) ; 0.5 = gris attendu par TripoSR.

    - remove_bg=True  : détoure l'objet automatiquement puis le recadre/centre.
    - remove_bg=False : à n'utiliser que si l'image est déjà détourée (PNG
      transparent) ou déjà centrée sur fond uni.
    """
    licensing.require()

    def fill_gray(rgba: Image.Image) -> Image.Image:
        arr = np.asarray(rgba).astype(np.float32) / 255.0
        alpha = arr[:, :, 3:4]
        arr = arr[:, :, :3] * alpha + (1.0 - alpha) * background
        return Image.fromarray((arr * 255.0).astype(np.uint8))

    if remove_bg:
        if rembg_session is None:
            rembg_session = new_rembg_session()
        cut = remove_background(image.convert("RGB"), rembg_session)
        cut = resize_foreground(cut, foreground_ratio)
        return fill_gray(cut)

    if image.mode == "RGBA":
        return fill_gray(image)
    return image.convert("RGB")


def cutout(
    image: Image.Image,
    remove_bg: bool = True,
    foreground_ratio: float = 0.85,
    rembg_session=None,
) -> Image.Image:
    """Objet détouré en RGBA (fond transparent), recadré et centré comme `preprocess`.

    Sert au moteur TripoSG : l'image de l'objet donne ses couleurs à la forme 3D.
    - remove_bg=True  : détourage automatique, puis recadrage/centrage.
    - remove_bg=False : on garde la transparence de l'image si elle en a ; sinon le fond est estimé
      à partir des bords de l'image (fond uni supposé).
    """
    licensing.require()
    if remove_bg:
        if rembg_session is None:
            rembg_session = new_rembg_session()
        return resize_foreground(remove_background(image.convert("RGB"), rembg_session), foreground_ratio)

    rgba = image.convert("RGBA")
    if image.mode == "RGBA" and np.asarray(rgba)[:, :, 3].min() < 255:
        return rgba
    # Pas de transparence : fond estimé = couleur médiane des bords, objet = pixels qui s'en écartent.
    from scipy import ndimage

    arr = np.asarray(rgba)[:, :, :3].astype(np.int16)
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    background = np.median(border, axis=0)
    mask = np.abs(arr - background).max(axis=2) > 12
    mask = ndimage.binary_fill_holes(ndimage.binary_closing(mask, iterations=2))
    out = np.asarray(rgba).copy()
    out[:, :, 3] = np.where(mask, 255, 0)
    return Image.fromarray(out)


# --- Génération du maillage -----------------------------------------------------
def generate_mesh(model: TSR, image: Image.Image, device: str, mc_resolution: int = 256):
    """Image pré-traitée -> maillage trimesh (couleurs par sommet).

    mc_resolution : finesse du maillage (marching cubes). 256 est un bon
    compromis ; 320 donne plus de détails au prix de plus de temps/mémoire.
    """
    licensing.require()
    with torch.no_grad():
        scene_codes = model([image], device=device)
    mesh = model.extract_mesh(scene_codes, True, resolution=mc_resolution)[0]
    return mesh, scene_codes


def export_mesh(
    model: TSR,
    mesh,
    scene_codes,
    out_path: Path,
    bake: bool = False,
    texture_resolution: int = 2048,
) -> Path:
    """Exporte le maillage en .glb ou .obj (le format vient de l'extension).

    bake=True : crée une vraie texture (atlas UV) au lieu de couleurs par
    sommet. Dans ce mode, la sortie est toujours un .obj + une image
    *_texture.png (comme dans le script officiel de TripoSR).
    """
    licensing.require()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if bake:
        import xatlas  # import tardif : seulement nécessaire pour la texture

        out_path = out_path.with_suffix(".obj")
        data = bake_texture(mesh, model, scene_codes[0], texture_resolution)
        texture = Image.fromarray((data["colors"] * 255.0).astype(np.uint8))
        texture = texture.transpose(Image.FLIP_TOP_BOTTOM)

        # La texture est calculée avec les positions d'origine du modèle ; on
        # applique ensuite la même rotation que pour l'export sans texture.
        vertices = np.asarray(mesh.vertices[data["vmapping"]]) @ ORIENTATION.T
        normals = np.asarray(mesh.vertex_normals[data["vmapping"]]) @ ORIENTATION.T

        xatlas.export(str(out_path), vertices, data["indices"], data["uvs"], normals)
        texture.save(out_path.with_name(out_path.stem + "_texture.png"))
        return out_path

    # Objet "debout" (Y vers le haut) et tourné vers +Z : de face dans Blender, les
    # visionneuses glTF et la plupart des logiciels 3D (voir geometry.ORIENTATION).
    transform = np.eye(4)
    transform[:3, :3] = ORIENTATION
    mesh.apply_transform(transform)
    mesh.export(str(out_path))
    return out_path


def convert_image(
    model: TSR,
    device: str,
    image_path: Path,
    out_dir: Path,
    fmt: str = "glb",
    remove_bg: bool = True,
    foreground_ratio: float = 0.85,
    mc_resolution: int = 256,
    bake: bool = False,
    texture_resolution: int = 2048,
    rembg_session=None,
) -> Path:
    """Chaîne complète pour une image : charge -> prépare -> 3D -> exporte."""
    licensing.require()
    t0 = time.time()
    image = Image.open(image_path)
    prepared = preprocess(image, remove_bg, foreground_ratio, rembg_session)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prepared.save(out_dir / f"{Path(image_path).stem}_entree.png")

    mesh, scene_codes = generate_mesh(model, prepared, device, mc_resolution)
    out_path = out_dir / f"{Path(image_path).stem}.{fmt}"
    out_path = export_mesh(model, mesh, scene_codes, out_path, bake, texture_resolution)
    log.info("%s -> %s (%.1f s)", Path(image_path).name, out_path, time.time() - t0)
    return out_path


# --- Ligne de commande ----------------------------------------------------------
def collect_images(inputs: list[str]) -> list[Path]:
    """Accepte des fichiers et/ou des dossiers d'images."""
    found: list[Path] = []
    for p in map(Path, inputs):
        if p.is_dir():
            found += sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS)
        elif p.is_file():
            found.append(p)
        else:
            log.error("Introuvable : %s", p)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Image -> modèle 3D (local, TripoSR).")
    parser.add_argument("images", nargs="+", help="Image(s) ou dossier(s) d'images.")
    parser.add_argument("--output-dir", default="sortie", help="Dossier de sortie (défaut : sortie/).")
    parser.add_argument("--format", choices=["glb", "obj"], default="glb", help="Format 3D (défaut : glb).")
    parser.add_argument("--device", default="auto", help="auto, cuda:0 ou cpu (défaut : auto).")
    parser.add_argument("--chunk-size", type=int, default=8192, help="Réduire si manque de VRAM (défaut : 8192).")
    parser.add_argument("--mc-resolution", type=int, default=256, help="Finesse du maillage, 32 à 320 (défaut : 256).")
    parser.add_argument("--no-remove-bg", action="store_true", help="Ne pas retirer le fond (image déjà détourée).")
    parser.add_argument("--foreground-ratio", type=float, default=0.85, help="Part de l'image occupée par l'objet (défaut : 0.85).")
    parser.add_argument("--texture", action="store_true", help="Cuire une vraie texture (atlas UV) au lieu des couleurs par sommet. Sortie : .obj + _texture.png.")
    parser.add_argument("--texture-resolution", type=int, default=2048, help="Taille de la texture (défaut : 2048).")
    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s  %(message)s", datefmt="%H:%M:%S", level=logging.INFO)

    try:
        licensing.require()
    except licensing.LicenseError as exc:
        raise SystemExit(f"Licence : {exc.message}") from None

    images = collect_images(args.images)
    if not images:
        raise SystemExit("Aucune image à traiter.")

    model, device = load_model(args.device, args.chunk_size)
    session = None if args.no_remove_bg else new_rembg_session()

    for path in images:
        try:
            convert_image(
                model, device, path, Path(args.output_dir),
                fmt=args.format,
                remove_bg=not args.no_remove_bg,
                foreground_ratio=args.foreground_ratio,
                mc_resolution=args.mc_resolution,
                bake=args.texture,
                texture_resolution=args.texture_resolution,
                rembg_session=session,
            )
        except licensing.LicenseError:
            raise
        except torch.cuda.OutOfMemoryError:
            log.error("Mémoire GPU insuffisante sur %s : essaie --chunk-size 2048 ou --mc-resolution 192.", path.name)
            torch.cuda.empty_cache()
        except Exception:
            log.exception("Échec sur %s", path.name)


if __name__ == "__main__":
    main()
