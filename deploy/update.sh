#!/bin/sh
set -eu
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RELEASE_ROOT=${SUPERVISOR_RELEASE_ROOT:-/srv/supervisor/releases}
CURRENT_LINK=${SUPERVISOR_CURRENT_LINK:-/srv/supervisor/current}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
REVISION=$(git -C "$SOURCE_DIR" rev-parse --short=12 HEAD 2>/dev/null || printf 'uncommitted')
RELEASE="$RELEASE_ROOT/$STAMP-$REVISION"
test "$(id -u)" -ne 0 || { printf '%s\n' 'Run as omega, not root.' >&2; exit 1; }
mkdir "$RELEASE"
cleanup() { find "$RELEASE" -depth -delete 2>/dev/null || true; }
trap cleanup EXIT HUP INT TERM
cp -a "$SOURCE_DIR/src" "$SOURCE_DIR/docs" "$SOURCE_DIR/pyproject.toml" "$SOURCE_DIR/uv.lock" \
  "$SOURCE_DIR/README.md" "$SOURCE_DIR/INITIAL_PROMPT.md" "$SOURCE_DIR/DELEGATE_PROMPT.md" \
  "$SOURCE_DIR/COMPACTION_PROMPT.md" "$RELEASE/"
"${UV_BIN:-/home/omega/.local/bin/uv}" sync --directory "$RELEASE" --frozen --no-dev --python /usr/bin/python3
python3 - "$SOURCE_DIR" "$RELEASE/release.json" "$REVISION" <<'PY'
import hashlib
import json
import subprocess
import sys
from pathlib import Path
source, destination, revision = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
digest = hashlib.sha256()
files = [*source.glob('src/**/*.py'), *source.glob('src/**/*.html'), *source.glob('*PROMPT.md'), source/'pyproject.toml', source/'uv.lock']
for path in sorted(files):
    digest.update(str(path.relative_to(source)).encode() + b'\0' + path.read_bytes())
dirty = bool(subprocess.run(['git', '-C', str(source), 'status', '--porcelain'], capture_output=True).stdout)
destination.write_text(json.dumps({'revision': revision, 'source_sha256': digest.hexdigest(), 'dirty': dirty})+'\n')
PY
chmod -R go-w "$RELEASE"
ln -s "$RELEASE" "$(dirname "$CURRENT_LINK")/.current-$STAMP"
mv -Tf "$(dirname "$CURRENT_LINK")/.current-$STAMP" "$CURRENT_LINK"
trap - EXIT HUP INT TERM
printf 'Installed %s. Restart supervisor-agent.service as operator to load it.\n' "$RELEASE"
