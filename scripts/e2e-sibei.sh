#!/usr/bin/env bash
# audio -> mat worker -> sibei-score draft -> PDF, against a throwaway local sibei-score server.
#   SIBEI_SCORE_DIR=~/projects/sibei-score scripts/e2e-sibei.sh [audio-file] [bass|voice]
# With no audio file it renders a seeded synthetic bass line. Output: out/e2e/<name>.pdf
# S3=1 also starts a throwaway S3-compatible store (versitygw, as sibei-score's own tests do) and points
# the server at it, so the worker downloads by presigned URL. It then asserts, from the worker's audit
# log, that the storage host was contacted and never received an Authorization header.
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
S3_CONTAINER=""
cleanup() {
  [ -n "$PGID" ] && kill -- "-$PGID" 2>/dev/null || true
  [ -n "$S3_CONTAINER" ] && docker rm -f "$S3_CONTAINER" >/dev/null 2>&1 || true
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

# Secrets reach the server and the gateway through their environment only, never argv or output.
S3_ENV=()
if [ "${S3:-0}" = "1" ]; then
  S3_PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
  S3_KEY="e2e$(openssl rand -hex 6)"
  S3_SECRET="$(openssl rand -hex 24)"
  S3_CONTAINER="mat-e2e-s3-$$"
  ROOT_ACCESS_KEY="$S3_KEY" ROOT_SECRET_KEY="$S3_SECRET" docker run -d --rm --name "$S3_CONTAINER" \
    -p "127.0.0.1:$S3_PORT:7070" -e ROOT_ACCESS_KEY -e ROOT_SECRET_KEY --tmpfs /data \
    ghcr.io/versity/versitygw:latest posix /data >/dev/null
  for _ in $(seq 1 60); do curl -s -o /dev/null "http://127.0.0.1:$S3_PORT/" && break; sleep 0.5; done
  # "localhost" for storage vs "127.0.0.1" for the API: the audit log can tell the hosts apart.
  # Create the bucket with sibei-score's own S3 adapter (credentials via env, never argv).
  (
    cd "$SIBEI_SCORE_DIR"
    SBSCORE_S3_ENDPOINT="http://localhost:$S3_PORT" SBSCORE_S3_ACCESS_KEY_ID="$S3_KEY" \
      SBSCORE_S3_SECRET_ACCESS_KEY="$S3_SECRET" pnpm -s exec tsx -e "
        import('./packages/api/src/index.ts').then(async (m) => {
          await m.openS3BlobStore({
            endpoint: process.env.SBSCORE_S3_ENDPOINT,
            accessKeyId: process.env.SBSCORE_S3_ACCESS_KEY_ID,
            secretAccessKey: process.env.SBSCORE_S3_SECRET_ACCESS_KEY,
            region: 'us-east-1',
            bucket: 'mat-e2e',
          }).ensureBucket();
        });"
  )
  S3_ENV=(SBSCORE_S3_ENDPOINT="http://localhost:$S3_PORT" SBSCORE_S3_BUCKET=mat-e2e
    SBSCORE_S3_ACCESS_KEY_ID="$S3_KEY" SBSCORE_S3_SECRET_ACCESS_KEY="$S3_SECRET" SBSCORE_S3_REGION=us-east-1)
fi
(
  cd "$SIBEI_SCORE_DIR"
  env SBSCORE_AUDIO_WORKER_TOKENS="$TOKEN" "${S3_ENV[@]}" setsid pnpm -s sbscore serve \
    --port "$PORT" --data "$WORK/lib.sqlite" >"$WORK/server.log" 2>&1 &
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
AUDIT="$WORK/audit.jsonl"
MAT_WORKER_TOKEN="$TOKEN" uv run mat worker --api-url "$SBSCORE_URL" --once --wait 10 \
  --audit-file "$AUDIT" --liveness-file "$WORK/alive"
SHOW="$(cd "$SIBEI_SCORE_DIR" && pnpm -s sbscore audio show "$JOB")"
echo "$SHOW" | grep -v '^\$'
DRAFT="$(echo "$SHOW" | sed -n 's/.*draft: \([^ ]*\).*/\1/p' | head -1)"
[ -n "$DRAFT" ] || {
  echo "no draft was produced" >&2
  exit 1
}
if [ "${S3:-0}" = "1" ]; then
  uv run python - "$AUDIT" "$PORT" "$S3_PORT" <<'PY'
import json
import sys

rows = [json.loads(line) for line in open(sys.argv[1])]
api, s3 = int(sys.argv[2]), int(sys.argv[3])
to_s3 = [r for r in rows if r["port"] == s3]
to_api = [r for r in rows if r["port"] == api]
assert to_s3, "the worker never contacted the object store: the presigned path was not exercised"
assert not any(r["authorization"] for r in to_s3), "the worker token was sent to the object store"
assert any(r["authorization"] for r in to_api), "no authenticated call reached the API"
print(f"audit ok: {len(to_s3)} storage request(s) without a token, {len(to_api)} API request(s)")
PY
fi
NAME="$(basename "${AUDIO%.*}")"
(cd "$SIBEI_SCORE_DIR" && pnpm -s sbscore export "$DRAFT" --pdf -o "$OUT/$NAME.pdf") | tail -1
