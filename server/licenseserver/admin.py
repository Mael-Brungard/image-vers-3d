"""Outil d'administration en ligne de commande (à lancer sur le serveur, avec les mêmes variables d'environnement).

    python -m licenseserver.admin genkey                 nouvelle paire de clés de signature (à faire UNE fois)
    python -m licenseserver.admin create --email a@b.c   crée une licence (vente hors Stripe, cadeau, presse) et envoie la clé
    python -m licenseserver.admin list [--email a@b.c]   liste les licences
    python -m licenseserver.admin show L123…|CLÉ         détail : appareils, événements
    python -m licenseserver.admin revoke L123… [--reason texte]   bloque les nouvelles activations
    python -m licenseserver.admin restore L123…          annule un blocage
    python -m licenseserver.admin release L123… DID      libère une place sans consommer le quota du client
    python -m licenseserver.admin resend L123…           renvoie la clé par e-mail
    python -m licenseserver.admin stats                  chiffres d'ensemble
"""

from __future__ import annotations

import argparse
import base64
import sys
import time

from .config import Config, ConfigError
from .db import Database
from .mail import Mailer
from .protocol import LicenseError, proto
from .service import Service
from .signing import Signer, generate_seed


def _fmt(ts: int | None) -> str:
    return "-" if ts is None else time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts))


def build_service(config: Config | None = None) -> Service:
    config = config or Config.from_env()
    return Service(config, Database(config.db_path), Signer(config.signing_seed, config.kid), Mailer(config))


def cmd_genkey(_args, _service=None, out=print) -> int:
    seed = generate_seed()
    signer = Signer(seed, "k1")
    out("Clé PRIVÉE (à mettre dans I3D_SIGNING_KEY sur le serveur, à ne JAMAIS commiter ni envoyer) :")
    out("  " + base64.b64encode(seed).decode("ascii"))
    out("")
    out("Clé PUBLIQUE (publique : elle est écrite dans le logiciel) :")
    out("  " + signer.public_key_b64)
    out("")
    out("Valeur de la variable de dépôt GitHub I3D_LICENSE_PUBKEYS (voir docs/LICENSING.md) : k1=" + signer.public_key_b64)
    out("")
    out("Sauvegarde la clé privée dans un gestionnaire de mots de passe : sans elle, aucune nouvelle licence ne peut être émise.")
    return 0


def _find(service: Service, ref: str) -> dict | None:
    lic = service.get_license(ref)
    if lic is None:
        body = proto.normalize_key(ref)
        if body is not None:
            with service.db.tx() as conn:
                row = conn.execute("SELECT * FROM licenses WHERE key_hash = ?", (proto.key_lookup_hash(service._pepper, body),)).fetchone()
            lic = dict(row) if row else None
    return lic


def cmd_create(args, service: Service, out=print) -> int:
    lic, key, created = service.create_license(args.email, source="admin", note=args.note, send_mail=not args.no_mail)
    out(f"Licence {lic['id']} pour {lic['email']}")
    out(f"Clé : {key}")
    out("E-mail envoyé." if created and not args.no_mail else "Aucun e-mail envoyé.")
    return 0


def cmd_list(args, service: Service, out=print) -> int:
    query = "SELECT l.*, (SELECT COUNT(*) FROM activations a WHERE a.license_id = l.id AND a.released_at IS NULL) AS used FROM licenses l"
    params: tuple = ()
    if args.email:
        query += " WHERE l.email = ?"
        params = (args.email.strip().lower(),)
    with service.db.tx() as conn:
        rows = conn.execute(query + " ORDER BY l.created_at DESC LIMIT 200", params).fetchall()
    for r in rows:
        out(f"{r['id']}  {_fmt(r['created_at'])}  {r['status']:<8} {r['used']}/{r['max_devices']}  {r['source']:<6} {r['email']}")
    out(f"{len(rows)} licence(s).")
    return 0


def cmd_show(args, service: Service, out=print) -> int:
    lic = _find(service, args.ref)
    if lic is None:
        out("Licence introuvable.")
        return 1
    out(f"{lic['id']}  {lic['status']}  {lic['email']}  créée {_fmt(lic['created_at'])}  source {lic['source']}")
    if lic["revoked_reason"]:
        out(f"Motif : {lic['revoked_reason']}")
    with service.db.tx() as conn:
        for a in conn.execute("SELECT * FROM activations WHERE license_id = ? ORDER BY created_at", (lic["id"],)):
            state = "libéré " + _fmt(a["released_at"]) if a["released_at"] else "actif"
            out(f"  appareil {a['did']}  {a['name'] or '?'}  v{a['app_version'] or '?'}  activé {_fmt(a['created_at'])}  {state}")
        for e in conn.execute("SELECT * FROM audit WHERE license_id = ? ORDER BY id DESC LIMIT 20", (lic["id"],)):
            out(f"  {_fmt(e['ts'])}  {e['kind']}  {e['detail'] or ''}")
    return 0


def cmd_revoke(args, service: Service, out=print) -> int:
    done = service.revoke(args.id, args.reason)
    out("Licence bloquée (nouvelles activations refusées ; les ordinateurs déjà activés restent valables)." if done else "Rien à faire (introuvable ou déjà bloquée).")
    return 0 if done else 1


def cmd_restore(args, service: Service, out=print) -> int:
    done = service.restore(args.id)
    out("Licence rétablie." if done else "Rien à faire (introuvable ou déjà active).")
    return 0 if done else 1


def cmd_release(args, service: Service, out=print) -> int:
    done = service.admin_release(args.id, args.did)
    out("Place libérée." if done else "Aucun appareil actif correspondant.")
    return 0 if done else 1


def cmd_resend(args, service: Service, out=print) -> int:
    lic = service.get_license(args.id)
    if lic is None:
        out("Licence introuvable.")
        return 1
    service.mailer.send_license(lic["email"], service.key_display(lic["id"]))
    out("E-mail envoyé.")
    return 0


def cmd_stats(_args, service: Service, out=print) -> int:
    queries = (
        ("licences actives", "SELECT COUNT(*) FROM licenses WHERE status = 'active'"),
        ("licences bloquées", "SELECT COUNT(*) FROM licenses WHERE status = 'revoked'"),
        ("appareils activés", "SELECT COUNT(*) FROM activations WHERE released_at IS NULL"),
        ("essais démarrés", "SELECT COUNT(*) FROM trials"),
    )
    with service.db.tx() as conn:
        for label, sql in queries:
            out(f"{label} : {conn.execute(sql).fetchone()[0]}")
    return 0


def main(argv: list[str] | None = None, out=print) -> int:
    parser = argparse.ArgumentParser(prog="licenseserver.admin", description="Administration du serveur de licences.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("genkey", help="génère une paire de clés de signature")
    p = sub.add_parser("create", help="crée une licence")
    p.add_argument("--email", required=True)
    p.add_argument("--note", default=None)
    p.add_argument("--no-mail", action="store_true", help="ne pas envoyer la clé par e-mail")
    p = sub.add_parser("list", help="liste les licences")
    p.add_argument("--email")
    p = sub.add_parser("show", help="détail d'une licence (identifiant ou clé)")
    p.add_argument("ref")
    p = sub.add_parser("revoke", help="bloque les nouvelles activations")
    p.add_argument("id")
    p.add_argument("--reason", default="décision administrateur")
    p = sub.add_parser("restore", help="annule un blocage")
    p.add_argument("id")
    p = sub.add_parser("release", help="libère une place")
    p.add_argument("id")
    p.add_argument("did")
    p = sub.add_parser("resend", help="renvoie la clé par e-mail")
    p.add_argument("id")
    sub.add_parser("stats", help="chiffres d'ensemble")
    args = parser.parse_args(argv)
    if args.command == "genkey":
        return cmd_genkey(args, out=out)
    try:
        service = build_service()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    handler = {
        "create": cmd_create, "list": cmd_list, "show": cmd_show, "revoke": cmd_revoke,
        "restore": cmd_restore, "release": cmd_release, "resend": cmd_resend, "stats": cmd_stats,
    }[args.command]
    try:
        return handler(args, service, out=out)
    except LicenseError as exc:
        print(exc.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
