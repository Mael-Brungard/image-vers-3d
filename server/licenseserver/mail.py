"""Envoi des e-mails (code de connexion, clé de licence). Trois moteurs : smtp (production), console et memory (développement, tests)."""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from .config import Config


@dataclass
class Mail:
    to: str
    subject: str
    text: str


class Mailer:
    def __init__(self, config: Config):
        self._config = config
        self.sent: list[Mail] = []  # moteur « memory » : les tests lisent ici

    def send(self, to: str, subject: str, text: str) -> None:
        mail = Mail(to, subject, text)
        backend = self._config.mail_backend
        if backend == "memory":
            self.sent.append(mail)
        elif backend == "console":
            print(f"\n--- e-mail pour {to} ---\nObjet : {subject}\n\n{text}\n--- fin ---\n", flush=True)
            self.sent.append(mail)
        else:
            self._send_smtp(mail)

    def _send_smtp(self, mail: Mail) -> None:
        c = self._config
        message = EmailMessage()
        message["From"] = c.mail_from
        message["To"] = mail.to
        message["Subject"] = mail.subject
        message["Date"] = formatdate(localtime=False)
        message["Message-ID"] = make_msgid()
        message.set_content(mail.text)
        context = ssl.create_default_context()
        if c.smtp_security == "ssl":
            client = smtplib.SMTP_SSL(c.smtp_host, c.smtp_port, timeout=20, context=context)
        else:
            client = smtplib.SMTP(c.smtp_host, c.smtp_port, timeout=20)
        with client:
            if c.smtp_security == "starttls":
                client.starttls(context=context)
            if c.smtp_user:
                client.login(c.smtp_user, c.smtp_password)
            client.send_message(message)

    # -- textes (en français, sobres : pas de lien « cliquez ici » trompeur)
    def send_license(self, email: str, key_display: str) -> None:
        c = self._config
        lines = [
            f"Merci pour ton achat de {c.product_name} !",
            "",
            "Ta clé de licence :",
            f"    {key_display}",
            "",
            f"Elle fonctionne sur {c.max_devices} ordinateurs au maximum. Garde cet e-mail : tu peux aussi retrouver ta clé à tout moment",
            f"dans ton espace client : {c.base_url}/",
            "",
        ]
        if c.download_url:
            lines += ["Télécharger le logiciel :", f"    {c.download_url}", ""]
        lines += [
            "Dans le logiciel : « Activer ma licence », colle la clé, c'est tout. L'activation se fait une seule fois, ensuite le logiciel",
            "fonctionne sans connexion Internet.",
        ]
        if c.support_email:
            lines += ["", f"Une question ? Écris à {c.support_email}."]
        self.send(email, f"Ta licence {c.product_name}", "\n".join(lines))

    def send_code(self, email: str, code: str) -> None:
        c = self._config
        text = (
            f"Ton code de connexion à l'espace client {c.product_name} : {code}\n\n"
            "Il est valable 10 minutes et ne sert qu'une fois. Si tu n'as rien demandé, ignore ce message : personne ne peut "
            "se connecter sans ce code."
        )
        self.send(email, f"Code de connexion : {code}", text)
