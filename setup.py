"""
setup.py - compilation facultative des modules de licence (version commerciale).

Sans variable d'environnement : wheel « Python pur » habituelle (développement, intégration continue, tests).

Avec I3D_COMPILE_LICENSE=1 : les modules de licence sont COMPILÉS (Cython -> .pyd sous Windows, .so sous Linux), leurs
sources .py ne figurent PAS dans la wheel, et les valeurs de la version livrée sont écrites dans la version compilée :

    I3D_LICENSE_PUBKEYS   clés publiques de vérification, « k1=<base64> » (plusieurs : « k1=...,k2=... »)   [obligatoire]
    I3D_LICENSE_URL       adresse du serveur de licence, en https://                                        [obligatoire]
    I3D_BUY_URL           page d'achat, en https://                                                          [facultatif]

Ce que cela apporte et ce que cela ne change pas : voir docs/LICENSING.md (c'est un frein, pas une protection absolue).
Le dépôt n'est jamais modifié : la version compilée est construite à partir d'une copie dans build/license_c/.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import sys
from pathlib import Path

from setuptools import Extension, setup
from setuptools.command.build_py import build_py as _build_py

ROOT = Path(__file__).resolve().parent
PACKAGE_DIR = ROOT / "src" / "imagevers3d"
COMPILED_MODULES = ("_ed25519", "_licproto", "_license_keys", "license")
SCRATCH = ROOT / "build" / "license_c"


def compile_requested() -> bool:
    return os.environ.get("I3D_COMPILE_LICENSE", "").strip() == "1"


def release_values() -> tuple[dict[str, str], str, str]:
    """Valeurs de la version livrée, vérifiées : une erreur ici doit arrêter la construction, jamais produire un logiciel inutilisable."""
    problems = []
    keys: dict[str, str] = {}
    for item in filter(None, (part.strip() for part in os.environ.get("I3D_LICENSE_PUBKEYS", "").split(","))):
        kid, _, encoded = item.partition("=")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError:
            raw = b""
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,32}", kid) or len(raw) != 32:
            problems.append(f"clé publique invalide pour « {kid} » (attendu : identifiant=base64 de 32 octets)")
        else:
            keys[kid] = encoded
    if not keys:
        problems.append("I3D_LICENSE_PUBKEYS est vide (python tools/genkey.py fournit la clé publique ; voir docs/LICENSING.md)")
    url = os.environ.get("I3D_LICENSE_URL", "").strip().rstrip("/")
    if not url.startswith("https://"):
        problems.append("I3D_LICENSE_URL doit commencer par https://")
    buy = os.environ.get("I3D_BUY_URL", "").strip()
    if buy and not buy.startswith("https://"):
        problems.append("I3D_BUY_URL doit commencer par https://")
    if problems:
        raise SystemExit("Construction de la version commerciale impossible :\n - " + "\n - ".join(problems))
    return keys, url, buy


def prepare_scratch() -> dict[str, Path]:
    """Copie les modules à compiler dans build/license_c/ et y écrit les valeurs de la version livrée."""
    keys, url, buy = release_values()
    shutil.rmtree(SCRATCH, ignore_errors=True)
    SCRATCH.mkdir(parents=True)
    sources = {}
    for name in COMPILED_MODULES:
        target = SCRATCH / f"{name}.py"
        shutil.copy2(PACKAGE_DIR / f"{name}.py", target)
        sources[name] = target
    sources["_license_keys"].write_text(
        '"""Valeurs de la version livrée (générées par setup.py, ne pas modifier)."""\n\n'
        f"KEYS: dict[str, str] = {keys!r}\nSERVER_URL: str = {url!r}\nBUY_URL: str = {buy!r}\n",
        encoding="utf-8",
    )
    return sources


class build_py(_build_py):  # noqa: N801 - nom imposé par setuptools
    """Exclut de la wheel les sources des modules compilés."""

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        if compile_requested() and package == "imagevers3d":
            return [m for m in modules if m[1] not in COMPILED_MODULES]
        return modules


def extensions():
    if not compile_requested():
        return []
    try:
        from Cython.Build import cythonize
        from Cython.Compiler import Options
    except ImportError:
        raise SystemExit("Cython est nécessaire pour compiler les modules de licence (pip install Cython).") from None
    Options.docstrings = False  # pas de texte d'aide embarqué dans les binaires
    sources = prepare_scratch()
    link_args = ["-s"] if sys.platform.startswith("linux") else []
    modules = [Extension(f"imagevers3d.{name}", [str(path)], extra_link_args=link_args) for name, path in sources.items()]
    return cythonize(
        modules,
        compiler_directives={"language_level": 3, "embedsignature": False, "emit_code_comments": False},
        build_dir=str(SCRATCH / "c"),
        quiet=True,
    )


setup(ext_modules=extensions(), cmdclass={"build_py": build_py})
