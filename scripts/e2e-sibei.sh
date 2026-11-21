#!/usr/bin/env bash
# audio -> mat worker -> sibei-score draft -> PDF, against a throwaway local sibei-score server.
#   SIBEI_SCORE_DIR=~/projects/sibei-score scripts/e2e-sibei.sh [audio-file] [bass|voice]
# With no audio file it renders a seeded synthetic bass line. Output: out/e2e/<name>.pdf
set -euo pipefail
: "${SIBEI_SCORE_DIR:?set SIBEI_SCORE_DIR to a sibei-score checkout (pnpm install done)}"
cd "$(dirname "$0")/.."
INSTRUMENT="${2:-bass}"
WORK="$(mktemp -d)"
OUT="$PWD/out/e2e"
mkdir -p "$OUT"
PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
TOKEN="sbsw_$(openssl rand -hex 24)"
PGID=""
cleanup() {
  [ -n "$PGID" ] && kill -- "-$PGID" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

AUDIO="${1:-}"
if [ -z "$AUDIO" ]; then
  uv run python - "$WORK" <<'PY'
import sys
from pathlib import Path

from mat.synth.generate import build_clip, write_clip
from mat.synth.recipe import Recipe

recipe = Recipe(seed=4, instrument="bass", kind="melody", n_notes=14, patch="pluck")
write_clip(build_clip(recipe), Path(sys.argv[1]), "synthetic-bass")
PY
  AUDIO="$WORK/synthetic-bass.wav"
fi

# The token reaches the server through its environment only, never argv or output.
(
  cd "$SIBEI_SCORE_DIR"
  SBSCORE_AUDIO_WORKER_TOKENS="$TOKEN" setsid pnpm -s sbscore serve --port "$PORT" \
    --data "$WORK/lib.sqlite" >"$WORK/server.log" 2>&1 &
  echo $! >"$WORK/pid"
)
PGID="$(cat "$WORK/pid")"
for _ in $(seq 1 60); do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/" && break
  sleep 0.5
done

export SBSCORE_URL="http://127.0.0.1:$PORT"
JOB="$(cd "$SIBEI_SCORE_DIR" && pnpm -s sbscore audio submit "$AUDIO" --instrument "$INSTRUMENT" |
  grep -oE '[0-9a-f]{8}-[0-9a-f-]{27}' | head -1)"
MAT_WORKER_TOKEN="$TOKEN" uv run mat worker --api-url "$SBSCORE_URL" --once --wait 10
SHOW="$(cd "$SIBEI_SCORE_DIR" && pnpm -s sbscore audio show "$JOB")"
echo "$SHOW" | grep -v '^\$'
DRAFT="$(echo "$SHOW" | sed -n 's/.*draft: \([^ ]*\).*/\1/p' | head -1)"
[ -n "$DRAFT" ] || {
  echo "no draft was produced" >&2
  exit 1
}
NAME="$(basename "${AUDIO%.*}")"
(cd "$SIBEI_SCORE_DIR" && pnpm -s sbscore export "$DRAFT" --pdf -o "$OUT/$NAME.pdf") | tail -1
