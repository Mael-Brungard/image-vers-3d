"""Pages HTML de l'espace client (français, sans JavaScript, accessibles, mêmes couleurs que le logiciel)."""

from __future__ import annotations

import time
from html import escape

CSS = """
:root{color-scheme:light dark;--bg:#F4F5F7;--panel:#fff;--raised:#F0F2F5;--border:#D5DAE1;--strong:#6C7685;--text:#16191F;--text2:#434C5A;--muted:#566170;
--accent:#F2A33A;--accent-h:#E8940F;--on-accent:#1B1305;--accent-text:#8A4F00;--soft:#FDF0DC;--focus:#A85F00;--ok:#17703F;--danger:#B3261E}
@media (prefers-color-scheme:dark){:root{--bg:#12141A;--panel:#1A1D23;--raised:#232831;--border:#303741;--strong:#7C8695;--text:#ECEEF2;--text2:#B0B8C4;--muted:#98A1AE;
--accent-h:#F7B55C;--accent-text:#F5B351;--soft:#2E2616;--focus:#F7B55C;--ok:#5BCB8E;--danger:#F47C74}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 system-ui,"Segoe UI",sans-serif}
main{max-width:46rem;margin:0 auto;padding:2.5rem 1rem 4rem}
h1{font-size:1.6rem;line-height:1.2;margin:0 0 .4rem}h2{font-size:1.15rem;margin:2rem 0 .6rem}
p{margin:.5rem 0;color:var(--text2)}.brand{display:flex;gap:.6rem;align-items:center;margin-bottom:1.6rem;font-weight:650}
.mark{width:1.6rem;height:1.6rem;border-radius:.45rem;background:var(--accent)}
.card{background:var(--panel);border:1px solid var(--border);border-radius:.9rem;padding:1.2rem 1.3rem;margin:1rem 0}
label{display:block;font-weight:600;margin:.9rem 0 .35rem}
input[type=email],input[type=text]{width:100%;padding:.7rem .8rem;border:1px solid var(--strong);border-radius:.6rem;background:var(--raised);color:var(--text);font:inherit}
input.code{letter-spacing:.35em;font-size:1.3rem;text-align:center;max-width:15rem}
button,.btn{display:inline-block;margin-top:1rem;padding:.65rem 1.1rem;border:1px solid transparent;border-radius:.6rem;background:var(--accent);color:var(--on-accent);font:inherit;font-weight:650;cursor:pointer;text-decoration:none}
button:hover,.btn:hover{background:var(--accent-h)}button.quiet{background:transparent;color:var(--text);border-color:var(--strong);margin-top:0;padding:.35rem .7rem;font-weight:600}
button.quiet:hover{background:var(--raised)}
:focus-visible{outline:3px solid var(--focus);outline-offset:2px}
code.key{display:block;font:600 1.1rem ui-monospace,Consolas,monospace;background:var(--raised);border:1px solid var(--border);border-radius:.5rem;padding:.6rem .8rem;margin:.4rem 0;overflow-wrap:anywhere;user-select:all}
.badge{display:inline-block;font-size:.8rem;font-weight:650;padding:.1rem .55rem;border-radius:99px;background:var(--soft);color:var(--accent-text)}
.badge.bad{color:var(--danger);background:transparent;border:1px solid var(--danger)}
table{width:100%;border-collapse:collapse;margin:.5rem 0}th,td{text-align:left;padding:.5rem .4rem;border-bottom:1px solid var(--border);vertical-align:middle}th{font-size:.85rem;color:var(--muted);font-weight:600}
.notice{border-left:4px solid var(--accent);background:var(--soft);padding:.7rem 1rem;border-radius:.3rem;color:var(--text)}
.error{border-left-color:var(--danger)}.muted{color:var(--muted);font-size:.92rem}a{color:var(--accent-text)}
form.inline{display:inline}footer{margin-top:3rem;color:var(--muted);font-size:.9rem}
@media (max-width:30rem){th:nth-child(3),td:nth-child(3){display:none}}
"""


def _date(ts: int) -> str:
    return time.strftime("%d/%m/%Y", time.gmtime(ts))


def layout(title: str, body: str, product: str, support: str = "") -> str:
    contact = f' · <a href="mailto:{escape(support)}">{escape(support)}</a>' if support else ""
    return (
        "<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(title)} · {escape(product)}</title><meta name=\"robots\" content=\"noindex\">"
        f"<style>{CSS}</style></head><body><main><div class=\"brand\"><span class=\"mark\" aria-hidden=\"true\"></span>{escape(product)}</div>"
        f"{body}<footer>Espace client{contact}</footer></main></body></html>"
    )


def notice(message: str, error: bool = False) -> str:
    cls = "notice error" if error else "notice"
    role = "alert" if error else "status"
    return f'<p class="{cls}" role="{role}">{escape(message)}</p>'


def login_page(product: str, support: str, buy_url: str, message: str = "", error: bool = False) -> str:
    buy = f'<p class="muted">Pas encore de licence ? <a href="{escape(buy_url)}">Acheter {escape(product)}</a>.</p>' if buy_url else ""
    body = (
        "<h1>Ton espace client</h1>"
        "<p>Retrouve ta clé de licence et gère tes ordinateurs. Pas de mot de passe : on t'envoie un code par e-mail.</p>"
        f"{notice(message, error) if message else ''}"
        '<form class="card" method="post" action="/login">'
        '<label for="email">Adresse e-mail utilisée pour l\'achat</label>'
        '<input id="email" name="email" type="email" autocomplete="email" required autofocus>'
        "<button type=\"submit\">Recevoir un code</button></form>"
        f"{buy}"
    )
    return layout("Connexion", body, product, support)


def code_page(product: str, support: str, email: str, message: str = "", error: bool = False) -> str:
    body = (
        "<h1>Entre ton code</h1>"
        f"<p>Si une licence existe pour <strong>{escape(email)}</strong>, un code à 8 chiffres vient d'être envoyé. Il est valable 10 minutes.</p>"
        f"{notice(message, error) if message else ''}"
        '<form class="card" method="post" action="/verify">'
        f'<input type="hidden" name="email" value="{escape(email)}">'
        '<label for="code">Code à 8 chiffres</label>'
        '<input id="code" class="code" name="code" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 ]{8,10}" maxlength="10" required autofocus>'
        "<br><button type=\"submit\">Se connecter</button></form>"
        '<p class="muted"><a href="/">Changer d\'adresse ou demander un nouveau code</a></p>'
    )
    return layout("Code de connexion", body, product, support)


def account_page(product: str, support: str, download_url: str, email: str, licenses: list[dict], csrf: str, message: str = "", error: bool = False) -> str:
    parts = ["<h1>Ton espace client</h1>", f'<p class="muted">Connecté avec {escape(email)}</p>']
    if message:
        parts.append(notice(message, error))
    for lic in licenses:
        active = lic["status"] == "active"
        badge = '<span class="badge">Active</span>' if active else '<span class="badge bad">Remboursée ou annulée</span>'
        rows = []
        for device in lic["devices"]:
            rows.append(
                f"<tr><td>{escape(device['name'] or 'Ordinateur')}</td><td>{_date(device['created_at'])}</td><td>{_date(device['last_seen_at'])}</td><td>"
                '<form class="inline" method="post" action="/account/release">'
                f'<input type="hidden" name="csrf" value="{escape(csrf)}"><input type="hidden" name="license" value="{escape(lic["id"])}">'
                f'<input type="hidden" name="did" value="{escape(device["did"])}">'
                f'<button class="quiet" type="submit" aria-label="Libérer {escape(device["name"] or "cet ordinateur")}">Libérer</button></form></td></tr>'
            )
        table = (
            "<table><thead><tr><th>Ordinateur</th><th>Activé le</th><th>Dernière activation</th><th></th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
            if rows
            else '<p class="muted">Aucun ordinateur activé pour le moment.</p>'
        )
        parts.append(
            '<section class="card">'
            f"<h2 style=\"margin-top:0\">Licence {badge}</h2>"
            f'<p class="muted">Achetée le {_date(lic["created_at"])} · {len(lic["devices"])} / {lic["max_devices"]} ordinateurs</p>'
            f'<code class="key">{escape(lic["key"])}</code>'
            f"{table}"
            f'<p class="muted">Libérer une place permet d\'activer un autre ordinateur ({lic["transfers_left"]} libération(s) restante(s) sur les 12 prochains mois). '
            "Libérer ne désinstalle rien : retire d'abord la licence dans le logiciel (Réglages → Licence → Désactiver cet ordinateur).</p>"
            "</section>"
        )
    if download_url:
        parts.append(f'<p><a class="btn" href="{escape(download_url)}">Télécharger le logiciel</a></p>')
    parts.append(
        '<form method="post" action="/logout">' f'<input type="hidden" name="csrf" value="{escape(csrf)}">' '<button class="quiet" type="submit">Se déconnecter</button></form>'
    )
    return layout("Mon compte", "".join(parts), product, support)


def message_page(product: str, support: str, title: str, text: str) -> str:
    return layout(title, f"<h1>{escape(title)}</h1><p>{escape(text)}</p><p><a href=\"/\">Retour</a></p>", product, support)
