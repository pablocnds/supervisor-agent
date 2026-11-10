#!/bin/sh
set -eu
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec /srv/supervisor/current/.venv/bin/python "$SOURCE_DIR/deploy/clean_start.py" "$@"
