# Serveur de licences Image vers 3D. À construire DEPUIS LA RACINE du dépôt :
#     docker build -f server/Dockerfile -t image-vers-3d-licences .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    I3D_HOST=0.0.0.0 \
    I3D_PORT=8000 \
    I3D_DB_PATH=/data/licenses.db

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin licence \
    && mkdir -p /app /data \
    && chown licence /data

WORKDIR /app
COPY server/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY server/licenseserver /app/licenseserver
# Le protocole est écrit UNE seule fois (dans le logiciel) ; le serveur en reçoit une copie à la construction.
COPY src/imagevers3d/_licproto.py src/imagevers3d/_ed25519.py /app/licenseserver/

USER licence
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('I3D_PORT','8000'), timeout=4)"
CMD ["python", "-m", "licenseserver"]
