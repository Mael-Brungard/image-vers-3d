#!/usr/bin/env python3
"""
build_stage.py - Prépare le dossier `build/stage` qui alimente l'installateur Windows (Inno Setup).

Contenu produit :
    bin/uv.exe                      programme qui crée l'environnement Python chez l'utilisateur (somme SHA-256 vérifiée)
    vendor/TripoSR/                 code de TripoSR au commit épinglé (le strict nécessaire, sans .git ni exemples)
    wheels/imagevers3d-*.whl        le logiciel lui-même
    requirements/windows-py311.lock dépendances verrouillées (avec sommes de contrôle)
    setup_runtime.bat, setup_config.bat, icon.ico, licenses/, EULA.fr.txt

Utilisation (depuis la racine du dépôt) — version COMMERCIALE (modules de licence compilés, voir docs/LICENSING.md) :
    I3D_COMPILE_LICENSE=1 I3D_LICENSE_PUBKEYS=k1=<base64> I3D_LICENSE_URL=https://... python -m build --wheel
    python packaging/build_stage.py --wheel dist/imagevers3d-0.1.0-*.whl --import-check

Le script REFUSE une wheel dont les modules de licence ne sont pas compilés (--allow-uncompiled : développement seulement,
le résultat ne doit jamais être distribué).

Fonctionne sous Linux comme sous Windows (utile pour tester le contenu sans compiler l'installateur).
TripoSG n'est volontairement PAS inclus : sa licence exclut l'Union européenne (voir docs/LICENSES.md).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_wheel import check_wheel  # noqa: E402

WINDOWS = Path(__file__).resolve().parent / "windows"
DEFAULT_STAGE = REPO / "build" / "stage"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def run(*cmd: str, cwd: Path | None = None) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def fetch_uv(config: dict, stage: Path, cache: Path) -> None:
    url = config["url"].format(version=config["version"])
    archive = cache / f"uv-{config['version']}-windows.zip"
    if not archive.exists():
        print(f"Téléchargement de uv {config['version']}…")
        cache.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as out:  # noqa: S310
            shutil.copyfileobj(response, out)
    found = sha256(archive)
    if found != config["sha256"]:
        archive.unlink(missing_ok=True)
        raise SystemExit(f"Somme SHA-256 de uv inattendue : {found} (attendue : {config['sha256']})")
    target = stage / "bin"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for name in ("uv.exe",):  # uvw/uvx ne servent pas ici
            if name in zf.namelist():
                (target / name).write_bytes(zf.read(name))
    if not (target / "uv.exe").exists():
        raise SystemExit("uv.exe est absent de l'archive téléchargée.")


def fetch_vendor(name: str, config: dict, stage: Path, cache: Path) -> None:
    work = cache / f"{name}-{config['commit'][:12]}"
    if not (work / ".git").exists():
        print(f"Récupération de {name} au commit {config['commit'][:12]}…")
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        run("git", "init", "-q", cwd=work)
        run("git", "remote", "add", "origin", config["repo"], cwd=work)
        run("git", "fetch", "-q", "--depth", "1", "origin", config["commit"], cwd=work)
        run("git", "checkout", "-q", "FETCH_HEAD", cwd=work)
    head = run("git", "rev-parse", "HEAD", cwd=work)
    if head != config["commit"]:
        raise SystemExit(f"{name} : commit {head} au lieu de {config['commit']}")
    target = stage / "vendor" / name
    target.mkdir(parents=True)
    for item in config["keep"]:
        source = work / item
        if source.is_dir():
            shutil.copytree(source, target / item, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(source, target / item)


def write_setup_config(versions: dict, stage: Path) -> None:
    """Valeurs lues par setup_runtime.bat (un fichier .bat de simples « set », facile à relire)."""
    torch = versions["torch"]
    lines = [
        "@rem Genere par packaging/build_stage.py - ne pas modifier a la main.",
        f"set \"PYTHON_VERSION={versions['python']}\"",
        f"set \"TORCH_VERSION={torch['version']}\"",
        f"set \"TORCH_INDEX_CUDA={torch['index_cuda']}\"",
        f"set \"TORCH_INDEX_CPU={torch['index_cpu']}\"",
    ]
    (stage / "setup_config.bat").write_text("\r\n".join(lines) + "\r\n", encoding="ascii")


def copy_documents(stage: Path) -> None:
    licenses = stage / "licenses"
    licenses.mkdir(parents=True)
    shutil.copy2(REPO / "THIRD_PARTY_NOTICES.md", licenses / "THIRD_PARTY_NOTICES.md")
    shutil.copy2(REPO / "LICENSE", licenses / "LICENSE.txt")
    shutil.copy2(stage / "vendor" / "TripoSR" / "LICENSE", licenses / "TripoSR-LICENSE.txt")
    assets = REPO / "src" / "imagevers3d" / "assets"
    shutil.copy2(assets / "fonts" / "OFL.txt", licenses / "Inter-OFL.txt")
    shutil.copy2(assets / "LUCIDE-LICENSE.txt", licenses / "Lucide-ISC.txt")
    shutil.copy2(WINDOWS / "EULA.fr.txt", stage / "EULA.fr.txt")
    shutil.copy2(REPO / "src" / "imagevers3d" / "assets" / "icon.ico", stage / "icon.ico")
    shutil.copy2(WINDOWS / "setup_runtime.bat", stage / "setup_runtime.bat")
    (stage / "requirements").mkdir()
    shutil.copy2(REPO / "requirements" / "windows-py311.lock", stage / "requirements" / "windows-py311.lock")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wheel", required=True, type=Path, help="Wheel du logiciel (python -m build --wheel).")
    parser.add_argument("--stage", type=Path, default=DEFAULT_STAGE, help="Dossier de sortie (recréé).")
    parser.add_argument("--cache", type=Path, default=REPO / "build" / "cache", help="Dossier de téléchargements.")
    parser.add_argument("--import-check", action="store_true", help="Charger la version compilée pour vérifier clé publique et adresse (même plateforme que la construction).")
    parser.add_argument("--allow-uncompiled", action="store_true", help="DÉVELOPPEMENT : accepter une wheel sans modules de licence compilés.")
    args = parser.parse_args()

    versions = json.loads((WINDOWS / "versions.json").read_text(encoding="utf-8"))
    wheel = args.wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise SystemExit(f"Wheel introuvable : {wheel}")

    problems = check_wheel(wheel, require_compiled=not args.allow_uncompiled, import_check=args.import_check and not args.allow_uncompiled)
    if problems:
        raise SystemExit("Wheel refusée (version commerciale) :\n - " + "\n - ".join(problems))
    if args.allow_uncompiled:
        print("ATTENTION : wheel NON compilée acceptée (--allow-uncompiled). Ne distribue jamais le résultat.", file=sys.stderr)

    stage = args.stage.resolve()
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)

    fetch_uv(versions["uv"], stage, args.cache)
    for name, config in versions["vendor"].items():
        fetch_vendor(name, config, stage, args.cache)
    (stage / "wheels").mkdir()
    shutil.copy2(wheel, stage / "wheels" / wheel.name)
    write_setup_config(versions, stage)
    copy_documents(stage)

    size = sum(f.stat().st_size for f in stage.rglob("*") if f.is_file()) / 1e6
    print(f"Dossier prêt : {stage} ({size:.0f} Mo)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
