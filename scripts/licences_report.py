#!/usr/bin/env python3
"""
licences_rapport.py - Liste les licences de tous les paquets Python installés dans l'environnement qui
exécute ce script, et signale ceux qui demandent une vérification avant une revente.

Utilisation (une fois par environnement) :
    .venv\\Scripts\\python licences_rapport.py
    .venv-triposg\\Scripts\\python licences_rapport.py        (si TripoSG est installé)
Le rapport est écrit dans le dossier `licences/` de la racine du dépôt.

Aucune dépendance : seule la bibliothèque standard de Python est utilisée. Le script lit les métadonnées
que chaque paquet déclare ; une métadonnée absente ou vague (« UNKNOWN ») signifie qu'il faut ouvrir le
dépôt du paquet. Ce rapport aide à vérifier, il ne remplace pas la lecture des licences ni un avis juridique.
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # racine du dépôt : le rapport va dans licences/ (ignoré par git)
OWN_PACKAGES = {"imagevers3d"}  # notre propre logiciel : licence propriétaire voulue, rien à vérifier

# Motifs qui demandent une vérification avant de vendre un logiciel qui embarque ce paquet.
AGPL = re.compile(r"\bAGPL|Affero", re.I)
GPL = re.compile(r"(?<!L)GPL|(?<!Lesser )(?<!Library )General Public License")  # GPL « forte » (LGPL exclue)
LGPL = re.compile(r"LGPL|Lesser General|Library General", re.I)
NON_COMMERCIAL = re.compile(r"non[- ]?commercial|\bBY-NC|research (use )?only|academic use only", re.I)
PROPRIETARY = re.compile(r"proprietary|NVIDIA", re.I)
UNKNOWN = re.compile(r"^(UNKNOWN|None|)$", re.I)


def assess(licence: str) -> tuple[str, str] | None:
    """Renvoie (niveau, raison) si la licence demande de l'attention, sinon None.
    Niveaux : « verifier » (peut bloquer une revente) ou « conditions » (permis, avec obligations)."""
    if NON_COMMERCIAL.search(licence):
        return "verifier", "usage non commercial"
    if AGPL.search(licence):
        return "verifier", "AGPL : oblige à publier le code source, même pour un service en ligne"
    # « A OR B » : tu choisis une des licences ; seule compte la plus permissive.
    alternatives = re.split(r"\s+OR\s+", licence, flags=re.I)
    if len(alternatives) > 1 and not all(GPL.search(a) for a in alternatives):
        best = [a for a in alternatives if not GPL.search(a)]
        if any(LGPL.search(a) for a in best) and not any(not LGPL.search(a) for a in best):
            return "conditions", "double licence : choisir la LGPL (bibliothèque séparée, texte de licence, source de la bibliothèque)"
        return None
    if GPL.search(licence):
        if ";" in licence:
            return "verifier", "plusieurs licences déclarées dont une GPL : vérifier laquelle s'applique"
        return "verifier", "GPL : oblige à publier le code source de ton logiciel"
    if LGPL.search(licence):
        return "conditions", "LGPL : permis en logiciel fermé (bibliothèque séparée, texte de licence, source de la bibliothèque)"
    if PROPRIETARY.search(licence):
        return "verifier", "licence propriétaire : relire les conditions de redistribution"
    return None


def declared_license(dist: metadata.Distribution) -> str:
    meta = dist.metadata
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    licence = (meta.get("License") or "").strip()
    if licence and len(licence) < 120 and not UNKNOWN.match(licence):
        return licence.splitlines()[0]
    classifiers = [c.split("::")[-1].strip() for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
    classifiers = [c for c in classifiers if c and c != "OSI Approved"]
    if classifiers:
        return " ; ".join(classifiers)
    if licence and not UNKNOWN.match(licence):
        return licence.splitlines()[0][:120] + " (texte long : voir le paquet)"
    return "UNKNOWN"


def main() -> int:
    rows = []
    for dist in metadata.distributions():
        name = dist.metadata.get("Name") or "?"
        rows.append((name.lower(), name, dist.version or "?", declared_license(dist)))
    rows.sort()

    flagged, conditions, unknown = [], [], []
    lines = [f"Environnement : {sys.prefix}", f"Python {sys.version.split()[0]}", f"{len(rows)} paquets", ""]
    for _, name, version, licence in rows:
        lines.append(f"{name} {version}  |  {licence}")
        if name.lower() in OWN_PACKAGES:
            continue
        if UNKNOWN.match(licence):
            unknown.append((name, version))
            continue
        verdict = assess(licence)
        if verdict is not None:
            (flagged if verdict[0] == "verifier" else conditions).append((name, version, licence, verdict[1]))

    lines += ["", "=== A VERIFIER AVANT UNE REVENTE ==="]
    lines += [f"{n} {v}  |  {lic}  ->  {why}" for n, v, lic, why in flagged] or ["(aucun)"]
    lines += ["", "=== PERMIS AVEC OBLIGATIONS (LGPL : joindre le texte de licence, garder la bibliothèque séparée) ==="]
    lines += [f"{n} {v}  |  {lic}" for n, v, lic, _ in conditions] or ["(aucun)"]
    lines += ["", "=== LICENCE NON DECLAREE (ouvrir le dépôt du paquet) ==="]
    lines += [f"{n} {v}" for n, v in unknown] or ["(aucun)"]
    lines += [
        "",
        "Rappel : les poids des modèles d'IA ont leurs propres licences, indépendantes de celles des paquets.",
        "Voir THIRD_PARTY_NOTICES.md.",
    ]

    out_dir = ROOT / "licences"
    out_dir.mkdir(exist_ok=True)
    label = Path(sys.prefix).name.strip(".") or "python"
    report = out_dir / f"licences_{label}.txt"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"{len(rows)} paquets analysés dans {sys.prefix}")
    print(f"A verifier : {len(flagged)} | LGPL (obligations) : {len(conditions)} | licence non declaree : {len(unknown)}")
    for n, v, lic, why in flagged:
        print(f"  - {n} {v} ({lic}) : {why}")
    for n, v in unknown:
        print(f"  - {n} {v} : licence non déclarée (ouvrir le dépôt du paquet)")
    print(f"Rapport complet : {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
