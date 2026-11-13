#!/usr/bin/env python3
"""
fetch_vendor.py - Récupère TripoSR dans `vendor/` au commit épinglé (poste de développement).

    python scripts/fetch_vendor.py

Le commit vient de packaging/windows/versions.json : le même que dans l'installateur.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    versions = json.loads((REPO / "packaging" / "windows" / "versions.json").read_text(encoding="utf-8"))
    for name, config in versions["vendor"].items():
        target = REPO / "vendor" / name
        if (target / ".git").exists() and git("rev-parse", "HEAD", cwd=target) == config["commit"]:
            print(f"{name} : déjà au commit {config['commit'][:12]}")
            continue
        target.mkdir(parents=True, exist_ok=True)
        print(f"{name} : récupération du commit {config['commit'][:12]}…")
        git("init", "-q", cwd=target)
        remotes = git("remote", cwd=target).split()
        git("remote", "set-url" if "origin" in remotes else "add", "origin", config["repo"], cwd=target)
        git("fetch", "-q", "--depth", "1", "origin", config["commit"], cwd=target)
        git("checkout", "-q", "FETCH_HEAD", cwd=target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
