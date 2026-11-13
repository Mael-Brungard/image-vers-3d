"""Lancement : python -m licenseserver  (en production : uvicorn licenseserver.web:app via la fabrique, voir Dockerfile)."""

import os

import uvicorn

from .web import create_app


def main() -> None:
    app = create_app()
    uvicorn.run(
        app,
        host=os.environ.get("I3D_HOST", "127.0.0.1"),
        port=int(os.environ.get("I3D_PORT", "8000")),
        proxy_headers=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
