"""Webhook Stripe : vérification de la signature (sans la bibliothèque Stripe) et traitement des événements.

Événements utilisés :
  checkout.session.completed / checkout.session.async_payment_succeeded   -> licence créée (si le paiement est réglé)
  charge.refunded (remboursement TOTAL) / charge.dispute.created           -> licence révoquée : plus de NOUVELLE activation

Idempotence : un même événement (ou une même session de paiement) n'émet jamais deux licences, même rejoué par Stripe."""

from __future__ import annotations

import hashlib
import hmac
import json

from .protocol import LicenseError
from .service import Service

SIGNATURE_TOLERANCE_SECONDS = 300


def verify_signature(payload: bytes, header: str | None, secret: str, now: float, tolerance: int = SIGNATURE_TOLERANCE_SECONDS) -> None:
    """Même vérification que stripe.Webhook.construct_event : HMAC-SHA256 de « <horodatage>.<corps> », fenêtre de 5 minutes."""
    bad = LicenseError("bad_signature", "Signature Stripe invalide.")
    if not secret or not header:
        raise bad
    timestamp = None
    signatures: list[str] = []
    for part in header.split(","):
        name, _, value = part.strip().partition("=")
        if name == "t":
            timestamp = value
        elif name == "v1":
            signatures.append(value)
    try:
        stamp = int(timestamp or "")
    except ValueError:
        raise bad from None
    if not signatures or abs(now - stamp) > tolerance:
        raise bad
    expected = hmac.new(secret.encode("utf-8"), f"{stamp}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise bad


def handle_event(service: Service, event: dict) -> str:
    """Traite un événement déjà authentifié. Renvoie une courte description (journal) ; lève une exception si Stripe doit réessayer."""
    event_id = event.get("id")
    kind = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}
    if not isinstance(event_id, str) or not isinstance(kind, str) or not isinstance(obj, dict):
        raise LicenseError("bad_request", "Événement Stripe illisible.")
    with service.db.tx() as conn:
        if conn.execute("SELECT 1 FROM stripe_events WHERE id = ?", (event_id,)).fetchone():
            return "doublon ignoré"

    if kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        result = _checkout(service, obj)
    elif kind == "charge.refunded":
        result = _refund(service, obj)
    elif kind == "charge.dispute.created":
        result = _dispute(service, obj)
    else:
        result = "événement ignoré"

    with service.db.tx() as conn:
        conn.execute("INSERT OR IGNORE INTO stripe_events(id, ts) VALUES (?, ?)", (event_id, service.now()))
    return result


def _checkout(service: Service, session: dict) -> str:
    wanted_link = service.config.stripe_payment_link
    if wanted_link and session.get("payment_link") != wanted_link:
        return "paiement d'un autre produit : ignoré"
    if session.get("mode") not in (None, "payment"):
        return "pas un paiement unique : ignoré"
    if session.get("payment_status") != "paid":
        return "paiement pas encore réglé : en attente"
    session_id = session.get("id")
    details = session.get("customer_details") or {}
    email = details.get("email") or session.get("customer_email")
    if not isinstance(session_id, str) or not email:
        raise LicenseError("bad_request", "Session de paiement sans adresse e-mail : à traiter à la main.")
    payment = session.get("payment_intent")
    _, _, created = service.create_license(
        email, source="stripe", source_ref=session_id, payment_ref=payment if isinstance(payment, str) else None
    )
    return "licence créée" if created else "licence déjà créée"


def _refund(service: Service, charge: dict) -> str:
    payment = charge.get("payment_intent")
    if not isinstance(payment, str):
        return "remboursement sans paiement associé : ignoré"
    if not charge.get("refunded"):
        return "remboursement partiel : licence conservée"
    count = service.revoke_by_payment(payment, "remboursement")
    return f"{count} licence(s) révoquée(s) (remboursement)"


def _dispute(service: Service, dispute: dict) -> str:
    payment = dispute.get("payment_intent")
    if not isinstance(payment, str):
        return "litige sans paiement associé : à traiter à la main"
    count = service.revoke_by_payment(payment, "litige bancaire")
    return f"{count} licence(s) révoquée(s) (litige)"


def parse_event(payload: bytes) -> dict:
    try:
        event = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise LicenseError("bad_request", "Corps Stripe illisible.") from exc
    if not isinstance(event, dict):
        raise LicenseError("bad_request", "Corps Stripe illisible.")
    return event
