#!/bin/sh
# Fix data volume permissions then run as non-root worker user
chown -R worker:worker /data 2>/dev/null || true
exec su worker -c "$*"
