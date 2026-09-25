#!/bin/sh
# Starts Someless Mail. Its data folder usually comes from the host (the "data" folder next
# to docker-compose.yml), and Docker creates that folder owned by root. Anything in it that
# isn't the app's yet is handed to the someless user, then the server runs as that user,
# never as root.
set -e

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data/someless
    find /data ! -user someless -exec chown someless:someless {} +
    exec setpriv --reuid=2001 --regid=2001 --clear-groups "$@"
fi

exec "$@"
