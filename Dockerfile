# Someless Mail 1.0.0: the panel and its mail engine, Stalwart, in one image.
# Stalwart is built from its open-source code by .github/workflows/stalwart.yml (run it first
# after changing stalwart/VERSION); this image copies the result.
ARG STALWART_IMAGE=ghcr.io/boyoftime/someless-stalwart:v0.16.23
FROM ${STALWART_IMAGE} AS stalwart

# Debian trixie, the same Debian Stalwart is built on
FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SOMELESS_DATA_DIR=/data/someless \
    SOMELESS_ENGINE=1 \
    SOMELESS_STALWART=/usr/local/bin/stalwart

COPY app/requirements.txt /opt/someless/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r /opt/someless/requirements.txt

# The mail engine, with its licence (AGPL-3.0) and where its source is
COPY --from=stalwart /usr/local/bin/stalwart /usr/local/bin/stalwart
COPY --from=stalwart /usr/share/doc/stalwart /usr/share/doc/stalwart

COPY app/someless /opt/someless/app/someless
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/someless-entrypoint
COPY --chmod=755 docker/someless-run /usr/local/bin/someless-run

# The app runs as its own user (2001), never as root. The entrypoint switches to it with
# setpriv (util-linux, part of every Debian image; checked here so a build without it fails).
# Stalwart runs as that user too, which is why it listens on high ports (17587, 17465):
# Docker maps 587 and 465 on the server to them.
RUN groupadd --system --gid 2001 someless \
 && useradd --system --uid 2001 --gid someless --shell /usr/sbin/nologin --no-create-home someless \
 && mkdir -p /data/someless /data/stalwart \
 && chown -R someless:someless /data \
 && setpriv --version \
 && stalwart --version

WORKDIR /opt/someless/app
VOLUME ["/data"]
# 17080: the panel. 17587 and 17465: apps sending mail (STARTTLS, and TLS from the start).
# 17081: Let's Encrypt's check of the server name (nothing else answers there).
EXPOSE 17080 17587 17465 17081

# The first start sets the mail engine up before the panel starts: give it a minute.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:17080/healthz', timeout=4)"]

# The entrypoint starts as root only to hand the data folder to the someless user, then runs
# this command as that user (docker/entrypoint.sh): Stalwart and the panel, side by side
# (docker/someless-run, app/someless/engine/supervisor.py).
ENTRYPOINT ["someless-entrypoint"]
CMD ["someless-run"]
