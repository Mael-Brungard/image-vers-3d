#!/usr/bin/env python3
"""
verify_wheel.py - contrôle qu'une wheel du logiciel est bien une version COMMERCIALE : modules de licence compilés,
sources absentes, clé publique et adresse du serveur présentes, réglages de développement sans effet.

    python packaging/verify_wheel.py dist/imagevers3d-*.whl --require-compiled --import-check

--import-check charge réellement la version compilée dans un sous-processus : il n'a de sens que sur la même plateforme et
la même version de Python que la construction (c'est le cas dans le workflow de release). Code de sortie 1 au moindre défaut.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

COMPILED_MODULES = ("_ed25519", "_licproto", "_license_keys", "license")

IMPORT_CHECK = r"""
import os, sys
sys.path.insert(0, sys.argv[1])
os.environ["IMAGEVERS3D_DEV_LICENSE_PUBKEY"] = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
os.environ["IMAGEVERS3D_LICENSE_URL"] = "http://127.0.0.1:1"
from imagevers3d import license as lic, _license_keys as keys
problems = []
if not lic.is_compiled():
    problems.append("le module license n'est pas compilé")
if not keys.KEYS or any(len(__import__("base64").b64decode(v)) != 32 for v in keys.KEYS.values()):
    problems.append("aucune clé publique valide n'est embarquée")
if not keys.SERVER_URL.startswith("https://"):
    problems.append("l'adresse du serveur de licence n'est pas en https://")
if "dev" in lic.public_keys():
    problems.append("la clé de développement est acceptée par la version compilée")
if lic.server_url() != keys.SERVER_URL.rstrip("/"):
    problems.append("l'adresse du serveur peut être remplacée par une variable d'environnement")
print("\n".join(problems))
sys.exit(1 if problems else 0)
"""


def check_wheel(wheel: Path, require_compiled: bool = True, import_check: bool = False) -> list[str]:
    problems: list[str] = []
    if not wheel.is_file() or wheel.suffix != ".whl":
        return [f"wheel introuvable : {wheel}"]
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    if require_compiled:
        if wheel.name.endswith("-py3-none-any.whl"):
            problems.append("la wheel est « Python pur » : les modules de licence n'ont pas été compilés (I3D_COMPILE_LICENSE=1)")
        for module in COMPILED_MODULES:
            binary = [n for n in names if re.fullmatch(rf"imagevers3d/{module}\.[^/]*\.(pyd|so)", n)]
            if not binary:
                problems.append(f"module compilé absent : imagevers3d/{module}.*.pyd|so")
            for leftover in (f"imagevers3d/{module}.py", f"imagevers3d/{module}.c", f"imagevers3d/{module}.pyx"):
                if leftover in names:
                    problems.append(f"source livrée par erreur : {leftover}")
        for name in names:
            if name.endswith((".c", ".pyx")) or "license_c" in name:
                problems.append(f"fichier de compilation livré par erreur : {name}")
    if import_check and not problems:
        with tempfile.TemporaryDirectory(prefix="i3d_verify_") as folder:
            with zipfile.ZipFile(wheel) as archive:
                archive.extractall(folder)
            result = subprocess.run([sys.executable, "-I", "-c", IMPORT_CHECK, folder], capture_output=True, text=True)
            if result.returncode != 0:
                detail = (result.stdout + result.stderr).strip().splitlines()
                problems.extend(detail or ["le contrôle d'import a échoué sans message"])
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--require-compiled", action="store_true", help="refuser une wheel dont les modules de licence ne sont pas compilés")
    parser.add_argument("--import-check", action="store_true", help="charger la version compilée et vérifier ses valeurs")
    args = parser.parse_args()
    problems = check_wheel(args.wheel.resolve(), args.require_compiled, args.import_check)
    for problem in problems:
        print("ECHEC :", problem, file=sys.stderr)
    if not problems:
        print("OK :", args.wheel.name)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
