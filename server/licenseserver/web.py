"""Application web (FastAPI) : API du logiciel (/v1/*), webhook Stripe et espace client (pages HTML, sans mot de passe)."""

from __future__ import annotations

import hmac
import json
import logging
import random
import time
from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from . import stripe_hooks, views
from .config import Config
from .db import Database
from .mail import Mailer
from .protocol import LicenseError
from .service import Service, normalize_email
from .signing import Signer

log = logging.getLogger("licenseserver")

COOKIE = "i3d_session"
API_BODY_LIMIT = 8 * 1024
FORM_BODY_LIMIT = 8 * 1024
STRIPE_BODY_LIMIT = 512 * 1024

STATUS = {
    "bad_request": 400,
    "invalid_key_format": 400,
    "invalid_token": 400,
    "bad_signature": 400,
    "unknown_key": 400,
    "not_a_license": 400,
    "invalid_email": 400,
    "invalid_code": 403,
    "invalid_key": 403,
    "revoked": 403,
    "trial_refused": 403,
    "not_found": 404,
    "device_limit": 409,
    "transfer_limit": 409,
    "rate_limited": 429,
}

FLASH = {
    "released": ("Place libérée. Tu peux maintenant activer un autre ordinateur avec ta clé.", False),
    "nothing": ("Cet ordinateur n'était déjà plus activé.", False),
    "transfer_limit": ("Tu as atteint le nombre de libérations autorisées cette année. Écris au support pour un cas particulier.", True),
    "error": ("L'opération n'a pas pu être faite. Réessaie, ou écris au support.", True),
}


def client_ip(request: Request, trust_proxy: bool) -> str | None:
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()[:64] or None  # dernier saut = celui que NOTRE proxy a observé
    return request.client.host if request.client else None


async def read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise LicenseError("bad_request", "Requête trop volumineuse.")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise LicenseError("bad_request", "Requête trop volumineuse.")
    return bytes(body)


async def read_json(request: Request) -> dict:
    try:
        data = json.loads((await read_body(request, API_BODY_LIMIT)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise LicenseError("bad_request", "Requête invalide.") from exc
    if not isinstance(data, dict):
        raise LicenseError("bad_request", "Requête invalide.")
    return data


async def read_form(request: Request) -> dict[str, str]:
    try:
        raw = (await read_body(request, FORM_BODY_LIMIT)).decode("utf-8")
        return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True, max_num_fields=20).items()}
    except (UnicodeDecodeError, ValueError) as exc:
        raise LicenseError("bad_request", "Requête invalide.") from exc


def create_app(config: Config | None = None, *, clock: Callable[[], float] = time.time, mailer: Mailer | None = None) -> FastAPI:
    config = config or Config.from_env()
    db = Database(config.db_path)
    signer = Signer(config.signing_seed, config.kid)
    service = Service(config, db, signer, mailer or Mailer(config), clock)
    service.purge()
    secure_cookie = config.base_url.startswith("https://")
    base_host = urlsplit(config.base_url).netloc
    product, support = config.product_name, config.support_email

    app = FastAPI(title="Serveur de licences", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = service
    app.state.config = config
    app.state.signer = signer

    # -------------------------------------------------------------- sécurité commune
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        if secure_cookie:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.exception_handler(LicenseError)
    async def license_error(request: Request, exc: LicenseError):
        return JSONResponse({"error": exc.code, "message": exc.message}, status_code=STATUS.get(exc.code, 400))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception("erreur inattendue sur %s", request.url.path)
        return JSONResponse({"error": "server_error", "message": "Erreur du serveur. Réessaie dans quelques minutes."}, status_code=500)

    def same_origin(request: Request) -> None:
        origin = request.headers.get("origin")
        if origin and origin != "null" and urlsplit(origin).netloc != base_host:
            raise LicenseError("bad_request", "Requête refusée.")
        if origin == "null":
            raise LicenseError("bad_request", "Requête refusée.")

    def html(page: str, status: int = 200) -> HTMLResponse:
        return HTMLResponse(page, status_code=status)

    # -------------------------------------------------------------- santé
    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    # -------------------------------------------------------------- API du logiciel
    @app.post("/v1/activate")
    async def api_activate(request: Request):
        data = await read_json(request)
        token = await run_in_threadpool(
            service.activate, data.get("key"), data.get("did"), data.get("name"), data.get("app"), client_ip(request, config.trust_proxy)
        )
        return {"token": token}

    @app.post("/v1/trial")
    async def api_trial(request: Request):
        data = await read_json(request)
        token = await run_in_threadpool(service.trial, data.get("did"), data.get("app"), client_ip(request, config.trust_proxy))
        return {"token": token}

    @app.post("/v1/deactivate")
    async def api_deactivate(request: Request):
        data = await read_json(request)
        done = await run_in_threadpool(service.deactivate_with_token, data.get("token"))
        return {"ok": True, "released": done}

    # -------------------------------------------------------------- Stripe
    @app.post("/stripe/webhook")
    async def stripe_webhook(request: Request):
        if not config.stripe_webhook_secret:
            return JSONResponse({"error": "disabled", "message": "Webhook Stripe non configuré."}, status_code=503)
        payload = await read_body(request, STRIPE_BODY_LIMIT)
        stripe_hooks.verify_signature(payload, request.headers.get("stripe-signature"), config.stripe_webhook_secret, clock())
        event = stripe_hooks.parse_event(payload)
        result = await run_in_threadpool(stripe_hooks.handle_event, service, event)
        log.info("stripe %s : %s", event.get("type"), result)
        return {"ok": True, "result": result}

    # -------------------------------------------------------------- espace client
    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        if await run_in_threadpool(service.session, request.cookies.get(COOKIE)):
            return RedirectResponse("/account", status_code=303)
        return html(views.login_page(product, support, config.buy_url))

    @app.post("/login", response_class=HTMLResponse)
    async def login(request: Request):
        same_origin(request)
        form = await read_form(request)
        email_raw = form.get("email", "")
        try:
            email = normalize_email(email_raw)
            if random.random() < 0.01:
                await run_in_threadpool(service.purge)
            await run_in_threadpool(service.request_code, email, client_ip(request, config.trust_proxy))
        except LicenseError as exc:
            if exc.code in ("invalid_email", "rate_limited"):
                return html(views.login_page(product, support, config.buy_url, exc.message, error=True), 429 if exc.code == "rate_limited" else 400)
            raise
        except Exception:  # noqa: BLE001 - e-mail en panne : même réponse neutre, détail dans le journal
            log.exception("envoi du code impossible")
        return html(views.code_page(product, support, email))

    @app.post("/verify", response_class=HTMLResponse)
    async def verify(request: Request):
        same_origin(request)
        form = await read_form(request)
        try:
            email = normalize_email(form.get("email", ""))
            cookie, _csrf, _email, expires = await run_in_threadpool(
                service.verify_code, email, form.get("code", ""), client_ip(request, config.trust_proxy)
            )
        except LicenseError as exc:
            email = form.get("email", "")[:254]
            status = 429 if exc.code == "rate_limited" else 400
            return html(views.code_page(product, support, email, exc.message, error=True), status)
        response = RedirectResponse("/account", status_code=303)
        response.set_cookie(COOKIE, cookie, max_age=expires - service.now(), httponly=True, secure=secure_cookie, samesite="lax", path="/")
        return response

    async def current_session(request: Request) -> dict | None:
        return await run_in_threadpool(service.session, request.cookies.get(COOKIE))

    @app.get("/account", response_class=HTMLResponse)
    async def account(request: Request, m: str = ""):
        session = await current_session(request)
        if session is None:
            return RedirectResponse("/", status_code=303)
        licenses = await run_in_threadpool(service.account, session["email"])
        message, error = FLASH.get(m, ("", False))
        return html(views.account_page(product, support, config.download_url, session["email"], licenses, session["csrf"], message, error))

    @app.post("/account/release")
    async def release(request: Request):
        same_origin(request)
        session = await current_session(request)
        if session is None:
            return RedirectResponse("/", status_code=303)
        form = await read_form(request)
        if not hmac.compare_digest(form.get("csrf", ""), session["csrf"]):
            raise LicenseError("bad_request", "Requête refusée.")
        try:
            done = await run_in_threadpool(service.release_from_portal, session["email"], form.get("license", ""), form.get("did", ""))
            flash = "released" if done else "nothing"
        except LicenseError as exc:
            flash = "transfer_limit" if exc.code == "transfer_limit" else "error"
        return RedirectResponse(f"/account?m={flash}", status_code=303)

    @app.post("/logout")
    async def logout(request: Request):
        same_origin(request)
        session = await current_session(request)
        form = await read_form(request)
        if session is None:
            return RedirectResponse("/", status_code=303)
        if not hmac.compare_digest(form.get("csrf", ""), session["csrf"]):
            return RedirectResponse("/account", status_code=303)  # jeton absent ou faux : on ne déconnecte pas
        await run_in_threadpool(service.logout, request.cookies.get(COOKIE))
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.get("/robots.txt")
    async def robots():
        return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")

    return app
