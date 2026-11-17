"""
trellis_runner.py - Moteur « Qualité maximale » : TRELLIS.2 (Microsoft, licence MIT) exécuté par trellis.cpp.

trellis.cpp (https://github.com/pwilkin/trellis.cpp, licence MIT) est un programme Windows autonome : il lit une
image et écrit un fichier .glb avec une vraie texture PBR (couleur, métal, rugosité). Il n'a besoin ni de Python ni
de PyTorch, il utilise la carte NVIDIA directement. Ce module :

  - télécharge le programme (version épinglée, somme SHA-256 vérifiée) et les poids du modèle au premier usage,
    sous `<données>/engines/trellis` ; les poids sont des GGUF « q4 » (6,5 Go, prévus pour les cartes de 12 Go) ;
  - lance le programme dans un processus séparé et relaie son avancement ;
  - si la mémoire vidéo ne suffit pas en 1024, refait automatiquement le calcul en 512 ;
  - charge le .glb obtenu pour l'aperçu et sait l'exporter (GLB identique, ou OBJ avec texture).

Ce module n'importe ni PyTorch ni Qt : il se teste seul, avec un faux programme (tests/scenarios/trellis_runner.py).
Variables d'environnement : THREEREX_TRELLIS_QUANT (q4 par défaut, q8 = plus fidèle mais ~10 Go),
THREEREX_TRELLIS_EXE (programme de remplacement, pour les tests ou une version compilée à la main).
"""

from __future__ import annotations

import atexit
import contextlib
import hashlib
import http.client
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib import error, request

import numpy as np
import trimesh
from PIL import Image

from . import paths

log = logging.getLogger("trellis_runner")

# --- Ce qui est téléchargé -------------------------------------------------------------------------------------------
# Programme : version épinglée ; somme SHA-256 relevée sur le fichier téléchargé le 17 novembre 2026.
RELEASE_TAG = "v0.8.1"
PROGRAM_ASSET = "trellis-cuda-windows-x64.zip"
PROGRAM_URL = f"https://github.com/pwilkin/trellis.cpp/releases/download/{RELEASE_TAG}/{PROGRAM_ASSET}"
PROGRAM_SHA256 = "d2ea7b57174d3bff438064faf0b5fbcc55c29c31e6bba5f41030936fa366ed48"
PROGRAM_BYTES = 715_040_905
EXE_NAME = "trellis-cli.exe"

# Poids : conversions GGUF de TRELLIS.2-4B ; la somme de contrôle de chaque fichier est celle que Hugging Face annonce
# (en-tête X-Linked-ETag), vérifiée à la fin du téléchargement.
WEIGHTS_BASE = "https://huggingface.co"
WEIGHTS_REPO = "ilintar/trellis2-gguf"
# Révision épinglée (vérifiée sur la page du dépôt le 17 novembre 2026) : un changement de format en amont ne casse pas le logiciel.
WEIGHTS_REVISION = "a57397bd3d351599d9729fc144b3f87c3f87d65b"
DEFAULT_QUANT = "q4"
WEIGHTS_BYTES = {"q4": 6_550_000_000, "q8": 10_000_000_000}  # ordres de grandeur affichés par Hugging Face
MODEL_FILES = (
    "birefnet.gguf", "dinov3.gguf", "ss_flow.gguf", "ss_dec.gguf", "shape_dec.gguf", "tex_dec.gguf",
    "shape_flow_512.gguf", "shape_flow_1024.gguf", "tex_flow_512.gguf", "tex_flow_1024.gguf",
)

SMOKE_TIMEOUT = 60  # contrôle de démarrage du programme après son installation
TIMEOUT_SECONDS = 45 * 60  # un calcul en 1024 dure quelques minutes ; au-delà, le programme est arrêté
HEARTBEAT_SECONDS = 2.0


@dataclass(frozen=True)
class Preset:
    label: str
    res: int  # résolution de la géométrie : 512 (léger) ou 1024 (cascade)
    steps: int  # étapes d'échantillonnage (12 = valeur d'origine du modèle)


PRESETS = {
    "rapide": Preset("Rapide (512)", 512, 12),
    "detaille": Preset("Détaillé (1024)", 1024, 12),
    "maximum": Preset("Maximum (1024, 24 étapes)", 1024, 24),
    # 1536 : accepté par le programme (--res 1536) mais jamais vu sur une carte de 12 Go. Si la mémoire manque, le calcul
    # est refait en 1024 puis en 512 (voir _ladder).
    "ultra": Preset("Ultra (1536, expérimental)", 1536, 12),
}
# Texture « très fine » : atlas UV de 4096 px et décodage PBR en 1024 (le programme choisit sinon seul : 2048 px, et un
# décodage PBR en 512 quand la grille 1024 est dense). Plus lourd en mémoire et en temps ; repli sur la texture standard.
TEXTURE_FINE_ARGS = ("--atlas", "4096", "--tex-res", "1024")
QUANTS = ("q4", "q8")

NOT_INSTALLED = (
    "Le moteur Qualité maximale n'est pas encore installé. Clique sur « Installer le moteur » : le téléchargement "
    "(environ 7,5 Go) n'est à faire qu'une fois."
)
DRIVER_HINT = (
    "Le moteur Qualité maximale n'a pas pu utiliser la carte NVIDIA. Mets à jour le pilote NVIDIA (version 580 ou plus "
    "récente) depuis nvidia.com ou GeForce Experience, redémarre, puis réessaie. En attendant, le moteur TripoSR "
    "fonctionne sans ces exigences."
)
MEMORY_HINT = (
    "Mémoire vidéo insuffisante, même en 512. Ferme les autres programmes qui utilisent la carte graphique "
    "(jeux, navigateur avec accélération, autres générateurs 3D) puis réessaie, ou utilise le moteur TripoSR."
)
FALLBACK_NOTE = "Mémoire vidéo insuffisante en {old} : le modèle a été refait en {new}."
FALLBACK_TEXTURE_NOTE = "Mémoire vidéo insuffisante avec la texture très fine : le modèle a été refait avec la texture standard."
MEMORY_HINT_Q8 = " Tu utilises la précision Haute (poids q8) : repasse en Standard, elle demande moins de mémoire."
START_HINT = (
    "Le programme du moteur Qualité maximale ne démarre pas. Mets Windows à jour, installe le dernier pilote NVIDIA et les "
    "« Visual C++ Redistributable » de Microsoft, vérifie que ton antivirus n'a pas mis un fichier du moteur en quarantaine "
    "(dossier engines\\trellis), puis réinstalle le moteur (supprime ce dossier et clique sur « Installer le moteur »)."
)
CANCELLED = "Opération annulée."

# Codes de sortie Windows d'un programme qui n'a pas pu démarrer (DLL absente, DLL de mauvaise version, exécutable bloqué…).
_LOADER_FAILURES = {0xC0000135, 0xC000007B, 0xC0000139, 0xC0000142}
_MEMORY = ("out of memory", "alloc failed", "failed to allocate", "cudamalloc", "unable to allocate", "buffer allocation",
           "std::bad_alloc", "cuda error: out of memory")
_GPU = ("no usable gpu backend", "cuda init failed", "cudagetdevicecount", "cuda driver version is insufficient")


_CANCEL = threading.Event()
_LIVE: set[subprocess.Popen] = set()  # programmes en cours


def cancel_all() -> None:
    """Interrompt tout téléchargement et tout calcul en cours (fermeture de la fenêtre) : le programme est arrêté, la carte
    graphique libérée."""
    _CANCEL.set()
    for proc in list(_LIVE):
        try:
            proc.kill()
        except OSError:
            pass


def _retry_io(action, tries: int = 10, delay: float = 0.5):
    """Windows : l'antivirus ou l'indexeur tiennent parfois un gros fichier quelques secondes après son écriture."""
    for attempt in range(tries):
        try:
            return action()
        except PermissionError:
            if attempt == tries - 1:
                raise
            time.sleep(delay)


@contextlib.contextmanager
def _quiet_errors():
    """Windows : sans cela, un programme dont une DLL manque affiche une boîte de dialogue qui bloque tout (le calcul
    semble figé). Le processus lancé hérite de ce réglage ; il est rétabli aussitôt après."""
    if os.name != "nt":
        yield
        return
    import ctypes

    kernel = ctypes.windll.kernel32  # type: ignore[attr-defined]
    previous = kernel.SetErrorMode(0x0001 | 0x0002 | 0x8000)  # critical errors, GP fault box, open-file error box
    try:
        yield
    finally:
        kernel.SetErrorMode(previous)


class DownloadError(RuntimeError):
    """Téléchargement impossible ou fichier corrompu ; le message est montré tel quel à l'utilisateur."""


class WorkerOutput(Exception):
    """Dernières lignes affichées par le programme : jointes à l'erreur pour les détails techniques."""


class MemoryFailure(RuntimeError):
    """Le programme a manqué de mémoire vidéo (déclenche le repli en 512)."""


# =============================================================================
#  Téléchargement
# =============================================================================
class _Redirects(request.HTTPRedirectHandler):
    """Garde la somme SHA-256 que Hugging Face annonce dans la réponse de redirection (en-tête X-Linked-ETag)."""

    linked_etag: str | None = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        etag = headers.get("X-Linked-ETag") or headers.get("x-linked-etag")
        if etag:
            self.linked_etag = etag.strip().strip('"')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _hash_file(path: Path, hasher) -> None:
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)


def sha256_of(path: Path) -> str:
    hasher = hashlib.sha256()
    _hash_file(path, hasher)
    return hasher.hexdigest()


def has_nvidia_driver(windows: bool | None = None, system_root: str | None = None) -> bool:
    """Un pilote NVIDIA est installé (`nvcuda.dll` sous Windows). Le moteur n'est proposé qu'à ce prix : sans carte NVIDIA,
    il échouerait après 7 Go de téléchargement."""
    if (sys.platform == "win32") if windows is None else windows:
        system = Path(system_root or os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        if (system / "nvcuda.dll").is_file():
            return True
    return shutil.which("nvidia-smi") is not None


def human_size(n: float) -> str:
    return f"{n / 1e9:.1f} Go".replace(".", ",") if n >= 1e9 else f"{n / 1e6:.0f} Mo"


def download(url: str, dest: Path, *, sha256: str | None = None, progress=None, label: str = "", chunk: int = 1 << 20) -> Path:
    """Télécharge `url` vers `dest`, en reprenant un téléchargement interrompu. Vérifie la somme SHA-256 donnée, sinon
    celle annoncée par Hugging Face. Le fichier n'apparaît sous son vrai nom qu'une fois complet et vérifié."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    hasher = hashlib.sha256()
    offset = part.stat().st_size if part.exists() else 0
    if offset:  # relecture avant d'ouvrir la connexion : sur un disque lent, elle ferait expirer le serveur
        if progress:
            progress(f"{label} — vérification de la partie déjà téléchargée ({human_size(offset)})…")
        _hash_file(part, hasher)
    redirects = _Redirects()
    opener = request.build_opener(redirects)
    headers = {"User-Agent": "ThreeRex"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    try:
        try:
            response = opener.open(request.Request(url, headers=headers), timeout=60)
        except error.HTTPError as exc:
            if exc.code == 416 and offset:  # le fichier partiel est déjà complet
                response = None
            else:
                raise
        if response is not None:
            status = getattr(response, "status", 200)
            total = None
            if status == 206 and offset:
                match = re.search(r"/(\d+)$", response.headers.get("Content-Range", ""))
                total = int(match.group(1)) if match else None
            else:
                offset, hasher = 0, hashlib.sha256()  # le serveur renvoie tout le fichier : on repart de zéro
                length = response.headers.get("Content-Length")
                total = int(length) if length else None
            done, last = offset, 0.0
            with open(part, "ab" if offset else "wb") as out, response:
                for block in iter(lambda: response.read(chunk), b""):
                    if _CANCEL.is_set():
                        raise DownloadError(CANCELLED)
                    out.write(block)
                    hasher.update(block)
                    done += len(block)
                    now = time.monotonic()
                    if progress and now - last >= 0.5:
                        last = now
                        share = f" {100 * done / total:.0f} % ({human_size(done)} sur {human_size(total)})" if total else f" {human_size(done)}"
                        progress(f"{label}{share}")
            if total is not None and done != total:
                raise DownloadError(f"Fichier incomplet ({done} octets sur {total}). Relance : le téléchargement reprendra.")
    except error.HTTPError as exc:
        raise DownloadError(
            f"Le serveur a répondu « {exc.code} » pour {dest.name}. Le fichier a peut-être été déplacé : vérifie ta connexion, "
            "relance ; si cela continue, le moteur est à mettre à jour."
        ) from exc
    except (error.URLError, http.client.HTTPException, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise DownloadError(
            f"Téléchargement interrompu ({reason}). Vérifie ta connexion Internet puis relance : il reprendra là où il s'est arrêté."
        ) from exc

    expected = (sha256 or redirects.linked_etag or "").lower()
    if re.fullmatch(r"[0-9a-f]{64}", expected):
        if hasher.hexdigest() != expected:
            part.unlink(missing_ok=True)
            raise DownloadError(f"Le fichier téléchargé est corrompu ({dest.name}). Relance le téléchargement.")
    else:
        log.warning("Aucune somme de contrôle disponible pour %s : seule la taille a été vérifiée", dest.name)
    _retry_io(lambda: os.replace(part, dest))
    return dest


def extract_program(archive: Path, target: Path) -> None:
    """Décompresse l'archive du programme dans `target` (refuse les chemins qui sortent du dossier)."""
    tmp = target.with_name(target.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    root = tmp.resolve()
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                if info.is_dir():
                    continue
                path = (tmp / info.filename).resolve()
                if root not in path.parents:
                    raise DownloadError("Archive du moteur invalide (chemin suspect).")
                path.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, open(path, "wb") as out:
                    shutil.copyfileobj(source, out)
        if not (tmp / EXE_NAME).exists():
            raise DownloadError(f"Archive du moteur invalide : {EXE_NAME} est absent.")
        (tmp / "VERSION.txt").write_text(RELEASE_TAG, encoding="utf-8")
        shutil.rmtree(target, ignore_errors=True)
        try:
            _retry_io(lambda: tmp.rename(target))
        except OSError as exc:
            raise DownloadError(
                "Impossible d'installer le programme du moteur : un fichier est utilisé par un autre programme (antivirus, "
                f"calcul en cours ?). Ferme-les puis relance l'installation. ({exc})"
            ) from exc
    except zipfile.BadZipFile as exc:
        raise DownloadError("Archive du moteur illisible. Relance l'installation.") from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# =============================================================================
#  Image, aperçu, export
# =============================================================================
def has_real_alpha(image: Image.Image) -> bool:
    """Vrai pour une image déjà détourée (au moins 0,5 % de pixels transparents) ; quelques pixels de coin transparents
    dans une photo ne comptent pas."""
    if image.mode not in ("RGBA", "LA"):
        return False
    return float((np.asarray(image.getchannel("A")) < 128).mean()) >= 0.005


def background_mode(image: Image.Image, remove_bg: bool) -> str:
    """Mode de détourage du programme : une image déjà détourée garde sa transparence ; sinon BiRefNet (précis) si on
    demande le détourage, ou un simple seuil (fond uni) si on ne le demande pas."""
    if has_real_alpha(image):
        return "auto"
    return "birefnet" if remove_bg else "threshold"


def load_preview(glb_path: Path) -> trimesh.Trimesh:
    """Charge le .glb et le convertit en maillage à couleurs par sommet (la visionneuse n'affiche pas les textures)."""
    mesh = trimesh.load(str(glb_path), force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise RuntimeError("Le moteur a produit un fichier sans maillage utilisable.")
    preview = mesh.copy()
    try:
        preview.visual = preview.visual.to_color()
    except Exception:  # noqa: BLE001 - texture illisible : l'aperçu reste gris, l'export garde la vraie texture
        log.warning("Couleurs de l'aperçu non calculées", exc_info=True)
    preview.metadata.clear()
    return preview


def export_glb(glb: bytes, path: Path, rotation: np.ndarray | None = None) -> Path:
    """Écrit le résultat. .glb sans correction : octets identiques à ceux du moteur (texture PBR intacte). Avec une
    rotation (« Pivoter », « Redresser »), ou en .obj, le fichier est réécrit par trimesh."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    turned = rotation is not None and not np.allclose(rotation, np.eye(3))
    if path.suffix.lower() == ".glb" and not turned:
        path.write_bytes(glb)
        return path
    transform = np.eye(4)
    if turned:
        transform[:3, :3] = rotation
    if path.suffix.lower() == ".glb":
        scene = trimesh.load(io.BytesIO(glb), file_type="glb", force="scene")
        scene.apply_transform(transform)
        scene.export(str(path))
    else:
        mesh = trimesh.load(io.BytesIO(glb), file_type="glb", force="mesh")
        mesh.apply_transform(transform)
        mesh.metadata.clear()
        material = getattr(mesh.visual, "material", None)
        if material is not None:  # fichiers propres à ce modèle : deux exports dans le même dossier ne s'écrasent pas
            material.name = f"{path.stem}_texture"
        mesh.export(str(path), mtl_name=f"{path.stem}.mtl")
    return path


# =============================================================================
#  Le moteur
# =============================================================================
atexit.register(cancel_all)  # le logiciel se ferme : on n'abandonne pas un calcul GPU en arrière-plan


def reset_cancel() -> None:
    """Réarme le moteur après `cancel_all` (tests uniquement : le logiciel se ferme juste après)."""
    _CANCEL.clear()


class TrellisRunner:
    def __init__(self, base: Path | None = None, launcher: list[str] | None = None, quant: str | None = None,
                 windows: bool | None = None, nvidia: bool | None = None) -> None:
        """`launcher` : commande de remplacement du programme (tests) ; sinon `trellis-cli.exe` installé sous `base`.
        `windows`, `nvidia` : forcent le système et la présence d'un pilote NVIDIA (tests) ; par défaut, ceux de la machine."""
        self.base = Path(base) if base else paths.TRELLIS_DIR
        self.quant = quant or os.environ.get("THREEREX_TRELLIS_QUANT") or DEFAULT_QUANT
        override = os.environ.get("THREEREX_TRELLIS_EXE")
        self.launcher = launcher or ([override] if override else None)
        self.windows = (sys.platform == "win32") if windows is None else windows
        self.nvidia = has_nvidia_driver() if nvidia is None else nvidia
        self.program_dir = self.base / f"program-{RELEASE_TAG}"  # une version = un dossier : jamais de mélange de fichiers
        self.models_dir = self.base / "models" / self.quant

    def set_quant(self, quant: str) -> None:
        """Précision des poids : « q4 » (6,5 Go, standard) ou « q8 » (10 Go, texture plus fidèle, plus de mémoire)."""
        if quant not in QUANTS:
            raise ValueError(f"Précision inconnue : {quant}")
        self.quant = quant
        self.models_dir = self.base / "models" / quant

    # ---- état -----------------------------------------------------------------------------------------------------
    def supported(self) -> bool:
        """Le programme fourni est un exécutable Windows pour carte NVIDIA : proposé seulement dans ce cas."""
        return self.launcher is not None or (self.windows and self.nvidia)

    def command(self) -> list[str]:
        return list(self.launcher) if self.launcher else [str(self.program_dir / EXE_NAME)]

    def program_ready(self) -> bool:
        if self.launcher:
            return True
        version = self.program_dir / "VERSION.txt"
        return (self.program_dir / EXE_NAME).exists() and version.exists() and version.read_text(encoding="utf-8").strip() == RELEASE_TAG

    def missing_models(self) -> list[str]:
        return [n for n in MODEL_FILES if not (self.models_dir / n).is_file() or (self.models_dir / n).stat().st_size == 0]

    def ready(self) -> bool:
        return self.supported() and self.program_ready() and not self.missing_models()

    def download_size(self) -> int:
        """Octets restant à télécharger (approximatif pour les poids)."""
        size = 0 if self.program_ready() else PROGRAM_BYTES
        missing = self.missing_models()
        if missing:
            size += int(WEIGHTS_BYTES.get(self.quant, WEIGHTS_BYTES["q8"]) * len(missing) / len(MODEL_FILES))
        return size

    # ---- installation ---------------------------------------------------------------------------------------------
    def install(self, progress, smoke_test: bool = True) -> None:
        if not self.supported():
            raise RuntimeError("Le moteur Qualité maximale est prévu pour Windows avec une carte NVIDIA.")
        self.base.mkdir(parents=True, exist_ok=True)
        need = self.download_size() + (1_800_000_000 if not self.program_ready() else 0) + 1_000_000_000
        free = shutil.disk_usage(self.base).free
        if free < need:
            raise DownloadError(
                f"Pas assez de place sur le disque : {human_size(need)} nécessaires pour le moteur, {human_size(free)} libres "
                f"({self.base})."
            )
        if not self.program_ready():
            archive = self.base / "downloads" / PROGRAM_ASSET
            if not (archive.is_file() and sha256_of(archive) == PROGRAM_SHA256):  # archive d'un essai précédent : réutilisée
                download(PROGRAM_URL, archive, sha256=PROGRAM_SHA256, progress=progress, label="Téléchargement du moteur (programme)")
            progress("Installation du programme…")
            extract_program(archive, self.program_dir)
            if smoke_test:
                progress("Vérification du programme…")
                try:
                    self._smoke_test(self.command())
                except RuntimeError:
                    shutil.rmtree(self.program_dir, ignore_errors=True)  # l'archive reste : la prochaine tentative la réutilise
                    raise
            archive.unlink(missing_ok=True)
            self._remove_old_programs()
        missing = self.missing_models()
        for index, name in enumerate(missing, start=1):
            url = f"{WEIGHTS_BASE}/{WEIGHTS_REPO}/resolve/{WEIGHTS_REVISION}/{self.quant}/{name}"
            download(url, self.models_dir / name, progress=progress,
                     label=f"Téléchargement du modèle d'IA, fichier {index}/{len(missing)} ({name})")
        log.info("Moteur Qualité maximale installé dans %s", self.base)
        progress("Moteur Qualité maximale installé.")

    def _smoke_test(self, command: list[str]) -> None:
        """Lance le programme avec --help : s'il démarre (même en affichant une erreur d'usage), ses DLL sont présentes et
        l'antivirus ne le bloque pas. Évite de découvrir le problème après 7 Go de téléchargement."""
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            with _quiet_errors():
                done = subprocess.run([*command, "--help"], cwd=str(self.base), creationflags=flags, stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=SMOKE_TIMEOUT)
        except subprocess.TimeoutExpired:
            return  # il a démarré (et attend) : c'est tout ce qu'on voulait savoir
        except (OSError, subprocess.SubprocessError) as exc:
            log.error("Le programme du moteur ne démarre pas : %s", exc)
            raise RuntimeError(START_HINT) from exc
        if (done.returncode & 0xFFFFFFFF) in _LOADER_FAILURES:
            log.error("Le programme du moteur ne démarre pas (code %#x)", done.returncode & 0xFFFFFFFF)
            raise RuntimeError(START_HINT)

    def _remove_old_programs(self) -> None:
        """Supprime les versions précédentes du programme (dossiers `program` et `program-*` autres que la version courante)."""
        for old in [self.base / "program", *self.base.glob("program-*")]:
            if old.is_dir() and old != self.program_dir and not old.name.endswith(".tmp"):
                shutil.rmtree(old, ignore_errors=True)

    # ---- calcul ---------------------------------------------------------------------------------------------------
    def _rel(self, path: Path) -> str:
        """Chemin relatif au dossier du moteur. Le programme est lancé depuis ce dossier et ne reçoit que des chemins ASCII :
        un nom d'utilisateur Windows avec accents (« Maël ») ne peut ainsi pas lui poser problème."""
        try:
            return os.path.relpath(path, self.base)
        except ValueError:  # autre lecteur
            return str(path)

    def _new_work(self) -> Path:
        root = self.base / "work"
        root.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - 6 * 3600
        for old in root.iterdir():  # restes d'un calcul interrompu par une coupure ou un arrêt brutal
            try:
                if old.is_dir() and old.stat().st_mtime < cutoff:
                    shutil.rmtree(old, ignore_errors=True)
            except OSError:
                pass
        return Path(tempfile.mkdtemp(prefix="t", dir=root))

    @staticmethod
    def _ladder(preset: Preset, fine: bool) -> list[tuple[Preset, bool]]:
        """Essais successifs si la mémoire vidéo manque : texture très fine -> texture standard, puis 1536 -> 1024 -> 512."""
        attempts: list[tuple[Preset, bool]] = []
        if fine and preset.res >= 1024:
            attempts.append((preset, True))
        attempts.append((preset, False))
        if preset.res > 1024:
            attempts.append((PRESETS["detaille"], False))
        if preset.res > 512:
            attempts.append((PRESETS["rapide"], False))
        return attempts

    def generate(self, image: Image.Image, quality: str, remove_bg: bool, seed: int, progress, texture: str = "standard") -> dict:
        """Image -> {"glb": octets du .glb, "mesh": maillage d'aperçu, "notes": [...], "res": résolution utilisée,
        "fine": texture très fine utilisée}. `texture` : « standard » ou « fine »."""
        if not self.ready():
            raise RuntimeError(NOT_INSTALLED)
        preset = PRESETS[quality]
        work = self._new_work()
        try:
            source = self._save_input(image, work)
            mode = background_mode(image, remove_bg)
            attempts = self._ladder(preset, texture == "fine")
            notes: list[str] = []
            for position, (current, fine) in enumerate(attempts):
                output = work / f"sortie_{position}.glb"
                try:
                    self._run(source, output, current, mode, seed, fine, progress)
                    break
                except MemoryFailure as exc:
                    if position == len(attempts) - 1:
                        hint = MEMORY_HINT + (MEMORY_HINT_Q8 if self.quant == "q8" else "")
                        raise RuntimeError(hint) from exc
                    following = attempts[position + 1][0]
                    if following.res == current.res:
                        note = FALLBACK_TEXTURE_NOTE
                    else:
                        note = FALLBACK_NOTE.format(old=current.res, new=following.res)
                    log.warning("Manque de mémoire vidéo (%s, texture fine : %s) : nouvel essai. %s", current.res, fine, note)
                    notes.append(note)
                    progress(note)
            if not output.exists() or output.stat().st_size == 0:
                raise RuntimeError("Le moteur n'a produit aucun fichier. Voir le journal pour le détail.")
            progress("Lecture du modèle…")
            return {"glb": output.read_bytes(), "mesh": load_preview(output), "notes": notes, "res": current.res, "fine": fine}
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def cutout(self, image: Image.Image, remove_bg: bool, progress) -> Image.Image | None:
        """Détourage tel que le moteur le fait (BiRefNet), pour l'aperçu ; None si le programme n'a rien écrit."""
        if not self.ready():
            return None
        work = self._new_work()
        try:
            source = self._save_input(image, work)
            command = [*self.command(), self._rel(source), self._rel(work / "decoupe.glb"), "--models", self._rel(self.models_dir),
                       "--bg-only", "--dump-bg", "--require-gpu", "--bg-removal", background_mode(image, remove_bg)]
            self._launch(command, progress, "Détourage de l'image (BiRefNet)…")
            found = sorted(p for p in work.glob("*.png") if p.name != source.name)  # nom exact du fichier non vérifié : tolérant
            return Image.open(found[0]).convert("RGBA").copy() if found else None
        except (RuntimeError, OSError) as exc:
            log.warning("Aperçu du détourage par le moteur impossible : %s", exc)
            return None
        finally:
            shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _save_input(image: Image.Image, work: Path) -> Path:
        source = work / "entree.png"
        (image.convert("RGBA") if has_real_alpha(image) else image.convert("RGB")).save(source)
        return source

    def _run(self, source: Path, output: Path, preset: Preset, mode: str, seed: int, fine: bool, progress) -> None:
        command = [
            *self.command(), self._rel(source), self._rel(output),
            "--models", self._rel(self.models_dir),
            "--res", str(preset.res), "--steps", str(preset.steps), "--seed", str(int(seed)),
            "--bg-removal", mode, "--webp", "off", "--require-gpu", "--verbose",
            *(TEXTURE_FINE_ARGS if fine else ()),
        ]
        self._launch(command, progress, f"Génération du modèle 3D ({preset.res})")

    def _launch(self, command: list[str], progress, title: str) -> None:
        if _CANCEL.is_set():
            raise RuntimeError(CANCELLED)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        self.base.mkdir(parents=True, exist_ok=True)
        log.info("Lancement du moteur Qualité maximale : %s", " ".join(command))
        try:
            with _quiet_errors():
                proc = subprocess.Popen(
                    command, cwd=str(self.base), creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                )
        except OSError as exc:
            log.error("Lancement impossible : %s", exc)
            raise RuntimeError(START_HINT) from exc
        _LIVE.add(proc)
        started = time.monotonic()
        phase = [title]
        finished = threading.Event()
        timed_out = threading.Event()

        def beat() -> None:  # sans nouvelle ligne du programme, l'utilisateur doit quand même voir que ça avance
            while not finished.wait(HEARTBEAT_SECONDS):
                elapsed = int(time.monotonic() - started)
                progress(f"{phase[0]} — {elapsed // 60} min {elapsed % 60:02d} s")

        def stop() -> None:
            timed_out.set()
            proc.kill()

        watchdog = threading.Timer(TIMEOUT_SECONDS, stop)
        watchdog.daemon = True
        helper = threading.Thread(target=beat, daemon=True)
        watchdog.start()
        helper.start()
        tail: deque[str] = deque(maxlen=120)
        oom = gpu = False  # relevés pendant tout le calcul : un message ancien sortirait de la fin du journal
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                tail.append(line[-400:])
                lowered = line.lower()
                if "retry" not in lowered:  # « alloc failed, retrying… » : le programme s'en sort seul, ce n'est pas un échec
                    oom = oom or any(p in lowered for p in _MEMORY)
                    gpu = gpu or any(p in lowered for p in _GPU)
                label = self._phase_of(line)
                if label:
                    phase[0] = label
            code = proc.wait()
        finally:
            finished.set()
            watchdog.cancel()
            _LIVE.discard(proc)
            if proc.poll() is None:
                proc.kill()
        if _CANCEL.is_set():
            raise RuntimeError(CANCELLED)
        if timed_out.is_set():
            raise RuntimeError("Le moteur Qualité maximale a dépassé 45 minutes : il a été arrêté. Essaie la qualité Rapide.")
        if code != 0:
            self._fail(code, list(tail), oom, gpu)

    @staticmethod
    def _phase_of(line: str) -> str | None:
        text = line.lower()
        if "bg-removal" in text or "birefnet" in text:
            return "Détourage de l'image (BiRefNet)"
        if "remesh" in text or "decimat" in text or "fill_holes" in text or "fill-holes" in text:
            return "Nettoyage du maillage"
        if "uv_bake" in text or "atlas" in text or "xatlas" in text:
            return "Dépliage et textures"
        if "done in" in text:
            return "Écriture du fichier"
        return None

    @staticmethod
    def _fail(code: int, tail: list[str], oom: bool = False, gpu: bool = False) -> None:
        log.error("Le moteur Qualité maximale a échoué (code %s) :\n%s", code, "\n".join(tail))
        detail = "\n".join(tail[-40:]) or "(aucune sortie)"
        if (code & 0xFFFFFFFF) in _LOADER_FAILURES:
            raise RuntimeError(START_HINT) from WorkerOutput(detail)
        if oom:  # relevé ligne par ligne pendant le calcul (les messages « retrying » exclus)
            raise MemoryFailure(detail) from WorkerOutput(detail)
        if gpu:
            raise RuntimeError(DRIVER_HINT) from WorkerOutput(detail)
        last = tail[-1] if tail else "aucun détail"
        raise RuntimeError(
            f"Le moteur Qualité maximale a échoué (code {code}) : {last}\n\n"
            "Ouvre le journal pour voir le détail. Si le problème continue, essaie la qualité Rapide ou le moteur TripoSR."
        ) from WorkerOutput(detail)
