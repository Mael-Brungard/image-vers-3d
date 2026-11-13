"""
dev_license.py - licence de DÉVELOPPEMENT, pour les tests, les captures d'écran et l'intégration continue.

Fabrique une paire de clés jetable et un jeton de licence valable pour CET ordinateur, écrit `license.json` dans le dossier
de données voulu et renvoie la clé publique à placer dans IMAGEVERS3D_DEV_LICENSE_PUBKEY. Cette clé n'est reconnue que par
une version NON compilée du logiciel : elle ne débloque rien dans une version livrée (voir docs/LICENSING.md).

    python tools/dev_license.py --data-dir /chemin/dossier-de-donnees            affiche les variables d'environnement à définir
    python tools/dev_license.py --data-dir ... --github-env                      les ajoute à $GITHUB_ENV (workflows)
    python tools/dev_license.py --data-dir ... --trial-days 3                    jeton d'essai de 3 jours au lieu d'une licence

Nécessite le paquet « cryptography » (extra de développement).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))


def make_dev_license(data_dir: Path | str, *, trial_days: int | None = None, now: int | None = None) -> dict:
    """Écrit `license.json` dans `data_dir` et renvoie {"pubkey": base64, "token": ..., "did": ...}."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from imagevers3d import _licproto as proto
    from imagevers3d import license as lic

    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    did = proto.make_device_id(lic.read_machine_id(data_dir))
    issued = int(time.time()) if now is None else now
    trial = trial_days is not None
    payload = {
        "v": 1,
        "kid": "dev",
        "typ": "trial" if trial else "license",
        "lid": "trial" if trial else "L-DEV",
        "did": did,
        "iat": issued,
        "exp": issued + trial_days * 86400 if trial else None,
        "plan": proto.PLAN,
        "dev": 1 if trial else proto.MAX_DEVICES,
    }
    payload_bytes = proto.canonical_json(payload)
    token = proto.encode_token(payload_bytes, private.sign(proto.signing_message(payload_bytes)))
    (data_dir / lic.STATE_FILE_NAME).write_text(json.dumps({"token": token}), encoding="utf-8")
    return {"pubkey": base64.b64encode(public).decode("ascii"), "token": token, "did": did}


def install(data_dir: Path | str, **kwargs) -> dict:
    """Comme make_dev_license, et définit IMAGEVERS3D_DEV_LICENSE_PUBKEY (et IMAGEVERS3D_DATA) pour ce processus et ses enfants."""
    info = make_dev_license(data_dir, **kwargs)
    os.environ["IMAGEVERS3D_DATA"] = str(data_dir)
    os.environ["IMAGEVERS3D_DEV_LICENSE_PUBKEY"] = info["pubkey"]
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", required=True, help="dossier de données du logiciel (IMAGEVERS3D_DATA)")
    parser.add_argument("--trial-days", type=int, default=None, help="jeton d'essai de N jours au lieu d'une licence")
    parser.add_argument("--github-env", action="store_true", help="ajoute les variables à $GITHUB_ENV")
    args = parser.parse_args()
    info = make_dev_license(args.data_dir, trial_days=args.trial_days)
    lines = {"IMAGEVERS3D_DATA": str(Path(args.data_dir).resolve()), "IMAGEVERS3D_DEV_LICENSE_PUBKEY": info["pubkey"]}
    if args.github_env:
        target = os.environ.get("GITHUB_ENV")
        if not target:
            print("GITHUB_ENV n'est pas défini : option réservée aux workflows GitHub.", file=sys.stderr)
            return 2
        with open(target, "a", encoding="utf-8") as stream:
            for name, value in lines.items():
                stream.write(f"{name}={value}\n")
    else:
        for name, value in lines.items():
            print(f"{name}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
