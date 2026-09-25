# Someless Mail 1.0.0
# Debian trixie base, the same Debian as the official Stalwart image, so the Stalwart
# mail engine can be added to this image in the next step.
FROM python:3.13-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SOMELESS_DATA_DIR=/data/someless

COPY app/requirements.txt /opt/someless/requirements.txt
RUN pip install --no-cache-dir --root-user-action=ignore -r /opt/someless/requirements.txt

COPY app/someless /opt/someless/app/someless
COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/someless-entrypoint

# The app runs as its own user (2001), never as root. The entrypoint switches to it with
# setpriv (util-linux, part of every Debian image; checked here so a build without it fails).
RUN groupadd --system --gid 2001 someless \
 && useradd --system --uid 2001 --gid someless --shell /usr/sbin/nologin --no-create-home someless \
 && mkdir -p /data/someless \
 && chown -R someless:someless /data \
 && setpriv --version

WORKDIR /opt/someless/app
VOLUME ["/data"]
EXPOSE 17080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:17080/healthz', timeout=4)"]

# --preload builds the app once before the workers start, so first-start setup
# (secret key, default admin) runs exactly once.
# --worker-class gthread: browsers open connections ahead of time and may leave them idle.
# Threaded workers set those aside until they send something; plain workers would sit on
# them until killed for "timing out", and the request caught in them got gunicorn's bare
# "Internal Server Error" page.
# --no-control-socket: we don't use gunicornc, and its socket would need a home folder.
# The entrypoint starts as root only to hand the data folder to the someless user, then runs
# this command as that user (docker/entrypoint.sh).
ENTRYPOINT ["someless-entrypoint"]
CMD ["gunicorn", "--bind", "0.0.0.0:17080", "--workers", "2", "--worker-class", "gthread", "--threads", "4", "--preload", "--no-control-socket", "--access-logfile", "-", "someless:create_app()"]
