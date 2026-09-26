#!/bin/sh
# Starts Someless Mail. Its data folder usually comes from the host (the "data" folder next
# to docker-compose.yml), and Docker creates that folder owned by root. Anything in it that
# isn't the app's yet is handed to the someless user, then the panel and the mail engine run
# as that user, never as root: the panel's data in data/someless, the engine's in data/stalwart.
set -e

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data/someless /data/stalwart
    find /data ! -user someless -exec chown someless:someless {} +
    exec setpriv --reuid=2001 --regid=2001 --clear-groups "$@"
fi

exec "$@"
