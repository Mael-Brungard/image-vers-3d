"""
creations.py - liste « Mes créations » : les modèles que l'utilisateur a enregistrés, avec une vignette et quelques faits.

Rien n'est inventé : chaque entrée correspond à un fichier réellement écrit par « Enregistrer sous… ». La liste est un petit
fichier JSON dans le dossier de données ; les vignettes sont de petites images (l'image de départ). Retirer une entrée
n'efface jamais le modèle enregistré. Ce module n'importe pas Qt : il se teste seul.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import paths

log = logging.getLogger("creations")

LIMIT = 60
THUMB_SIZE = 320
FIELDS = ("id", "name", "path", "format", "engine", "created", "size", "thumb", "info")


@dataclass
class Creation:
    id: str
    name: str  # nom du fichier sans dossier, ex. « tasse.glb »
    path: str  # chemin complet du modèle enregistré
    format: str = "glb"  # glb ou obj
    engine: str = ""  # nom lisible du moteur (« TRELLIS.2 »)
    created: float = field(default_factory=time.time)
    size: int = 0  # octets à l'enregistrement
    thumb: str = ""  # nom du fichier de vignette dans le dossier des créations ("" si aucune)
    info: str = ""  # une ligne de faits (« 1024 · 412 380 sommets »)

    def exists(self) -> bool:
        return Path(self.path).is_file()


class CreationStore:
    """Liste persistante, plus récente d'abord, limitée à LIMIT entrées (les plus anciennes disparaissent, leurs vignettes aussi)."""

    def __init__(self, folder: Path | None = None, limit: int = LIMIT) -> None:
        self.folder = Path(folder) if folder is not None else paths.CREATIONS_DIR
        self.limit = limit
        self.file = self.folder / "creations.json"

    # ---- lecture -----------------------------------------------------------
    def load(self) -> list[Creation]:
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items: list[Creation] = []
        for entry in raw if isinstance(raw, list) else []:
            if not isinstance(entry, dict) or not entry.get("id") or not entry.get("path"):
                continue  # entrée abîmée : ignorée plutôt que de tout perdre
            fields = {k: entry[k] for k in FIELDS if k in entry}
            fields.setdefault("name", Path(str(entry["path"])).name)
            try:
                items.append(Creation(**fields))
            except TypeError:
                continue
        return sorted(items, key=lambda c: c.created, reverse=True)

    def thumb_path(self, creation: Creation) -> Path | None:
        if not creation.thumb:
            return None
        path = self.folder / creation.thumb
        return path if path.is_file() else None

    # ---- écriture ----------------------------------------------------------
    def _write(self, items: list[Creation]) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(c) for c in items], ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.file)  # remplacement d'un bloc : un arrêt brutal ne laisse jamais un fichier à moitié écrit

    def add(self, path: str | Path, engine: str = "", info: str = "", thumbnail=None) -> Creation | None:
        """Enregistre une création. `thumbnail` : image PIL (vignette) ou None. Ne lève jamais : renvoie None si le disque refuse
        (la liste est un confort, elle ne doit pas faire échouer un enregistrement réussi)."""
        path = Path(path)
        try:
            items = self.load()
            items = [c for c in items if Path(c.path) != path]  # même fichier réenregistré : une seule entrée
            ident = uuid.uuid4().hex[:12]
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            creation = Creation(id=ident, name=path.name, path=str(path), format=path.suffix.lstrip(".").lower(),
                                engine=engine, size=size, info=info)
            if thumbnail is not None:
                creation.thumb = self._save_thumb(thumbnail, ident)
            items.insert(0, creation)
            for old in items[self.limit:]:
                self._drop_thumb(old)
            self._write(items[: self.limit])
            return creation
        except Exception:  # noqa: BLE001
            log.warning("Liste « Mes créations » non mise à jour", exc_info=True)
            return None

    def remove(self, ident: str) -> bool:
        try:
            items = self.load()
            keep = [c for c in items if c.id != ident]
            if len(keep) == len(items):
                return False
            for gone in items:
                if gone.id == ident:
                    self._drop_thumb(gone)
            self._write(keep)
            return True
        except Exception:  # noqa: BLE001
            log.warning("Entrée de « Mes créations » non retirée", exc_info=True)
            return False

    def _save_thumb(self, image, ident: str) -> str:
        try:
            thumb = image.convert("RGB")
            thumb.thumbnail((THUMB_SIZE, THUMB_SIZE))
            self.folder.mkdir(parents=True, exist_ok=True)
            name = f"{ident}.jpg"
            thumb.save(self.folder / name, "JPEG", quality=88)
            return name
        except Exception:  # noqa: BLE001 - sans vignette, la carte garde son illustration par défaut
            return ""

    def _drop_thumb(self, creation: Creation) -> None:
        if creation.thumb:
            try:
                (self.folder / creation.thumb).unlink()
            except OSError:
                pass


def format_size(size: int) -> str:
    """« 4,2 Mo », « 812 Ko » : tailles lisibles en français."""
    if size >= 1_000_000:
        return f"{size / 1_000_000:.1f} Mo".replace(".", ",")
    if size >= 1000:
        return f"{round(size / 1000)} Ko"
    return f"{size} o"


def format_when(created: float, now: float | None = None) -> str:
    """« Aujourd'hui, 14:32 », « Hier, 09:05 » ou « 12/11/2026 »."""
    now = time.time() if now is None else now
    day = time.localtime(created)
    today = time.localtime(now)
    clock = time.strftime("%H:%M", day)
    if (day.tm_year, day.tm_yday) == (today.tm_year, today.tm_yday):
        return f"Aujourd'hui, {clock}"
    yesterday = time.localtime(now - 86400)
    if (day.tm_year, day.tm_yday) == (yesterday.tm_year, yesterday.tm_yday):
        return f"Hier, {clock}"
    return time.strftime("%d/%m/%Y", day)
