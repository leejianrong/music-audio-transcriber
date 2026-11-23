# Audio worker runbook

How to deploy and operate `mat worker`, the process that pulls audio jobs from sibei-score, transcribes
them, and returns NoteEvents. It speaks sibei-score's "Audio worker protocol v1"
(`docs/adr/0034-hosted-web-app-primary.md` in that repo). Voice and bass only for now; any other instrument
fails the job with `unsupported-instrument`.

The worker only makes outbound calls. It has no inbound port, no database, and keeps nothing on disk
beyond one job's scratch space.

## What it needs

| Setting | Where | Notes |
|---|---|---|
| `MAT_API_URL` (or `--api-url`) | environment | The sibei-score API origin, e.g. `https://example.org`. |
| `MAT_WORKER_TOKEN` | environment only | A `sbsw_` credential. Never pass it in argv; the CLI refuses to read it from there. |
| `MAT_LOG_FORMAT` | environment | `json` for machines (compose sets it), `text` by default. |
| `--max-duration` | flag | Longest accepted audio, seconds. Default 600. Longer files fail with `audio-too-long`. |
| `--max-mb` | flag | Largest accepted upload. Default 200. |
| `--max-job-seconds` | flag | After this long the worker stops heartbeating a job. Default 1800. |
| `--wait` | flag | Long-poll seconds per claim, 0 to 30. Default 20. |

## Credentials

The operator mints and revokes them on the sibei-score server; the worker never creates one.

```sh
echo "sbsw_$(openssl rand -hex 32)"      # at least 32 characters after the prefix
```

Put it in `SBSCORE_AUDIO_WORKER_TOKENS` on the server (comma-separated; each entry is bare or
`name=sbsw_...`), and in the worker's environment as `MAT_WORKER_TOKEN`.

- **Rotate:** add the new credential to the server list, restart the server, deploy the worker with the new
  value, then remove the old entry and restart the server again.
- **Revoke:** remove the entry and restart the server. The worker's next claim is answered `401`.
- A credential works on `/v1/worker/*` only. It cannot read any user's scores or library.

## Run it

```sh
MAT_API_URL=https://example.org MAT_WORKER_TOKEN=sbsw_... \
  docker compose -f compose.worker.yaml up -d --build
docker compose -f compose.worker.yaml ps          # "healthy" within about 40 s
```

The container is non-root with a read-only root filesystem, no capabilities, `/tmp` as a 1 GB tmpfs,
4 GB memory, 2 CPUs and 256 processes. Without Docker: `uv run mat worker`.

## Sizing

Measured on this repository's synthetic clips (voice and bass, pYIN plus beat tracking), warm, on one machine:

| Measure | Value |
|---|---|
| CPU per audio-minute | about 5.3 CPU-seconds |
| Wall time per audio-minute | about 3.2 s (a 621 s clip took 33 s) |
| Peak memory | about 0.55 GB for a 79 s clip; about 2.5 GB for a 621 s clip (roughly 4 MB per audio-second) |

So one container with 2 CPUs handles very roughly 15 audio-minutes of voice or bass per wall-minute, and the
memory limit, not CPU, decides the longest clip it can take. These numbers do not cover piano, drums or
guitar, which will need their own models and probably a GPU.

## Scaling

One container runs one claim loop and one job at a time. sibei-score allows a credential at most 4 concurrent
long-polls, so run at most 4 containers per credential, or give each its own named credential. Claims give
natural back-pressure: an idle worker long-polls, a busy one does not claim.

## Network

Allow outbound HTTPS to the API host and to the object-store host (presigned URLs), and nothing else; allow
DNS. There is no inbound traffic. Compose cannot express an allowlist, so enforce it with a firewall or
network policy. The worker sends its credential only to the API host, never to the object store (the
`make e2e-sibei-s3` run asserts this from a request audit).

## Monitoring

`mat worker --healthcheck` exits 0 when the claim loop or a running job ticked in the last 90 s, and prints why
when it does not. The compose file runs it every 30 s. **Compose does not restart an unhealthy container.**
Add `willfarrell/autoheal` or an orchestrator that restarts on unhealthy, or the check only informs.

"Healthy" means the loop is alive, not that the API is reachable: while the API is down the worker backs off
(2 s doubling to 30 s) and stays healthy, so alert on repeated `claim-network-error` as well.

With `MAT_LOG_FORMAT=json` each line has `ts`, `level`, `logger`, `msg`, plus these fields where relevant:

| `event` | Meaning | Act when |
|---|---|---|
| `claimed` | A job was claimed (`job_id`, `attempt`). | `attempt` is 2 or 3 often: jobs are being lost or failing. |
| `job-finished` | `outcome` is `completed`, `failed`, `abandoned` or `cancelled`; `processing_s`. | Many `failed` or `abandoned`. |
| `auth-rejected` | The credential was refused; the worker backs off (15 s doubling to 5 min). | Always: wrong or revoked credential. |
| `claim-refused` | The API answered a claim with an error other than 401/403. | Persistent. |
| `claim-network-error` | The API could not be reached. | Persistent. |
| `job-timeout` | A job ran past `--max-job-seconds`; heartbeats stopped. | Always: a hung job. The server re-queues it and the health check goes stale. |
| `shutdown-requested` | SIGTERM or SIGINT received. | Informational. |

Logs never contain the credential, a lease token, a presigned URL, or audio. A test enforces that.

## Failure modes

| Symptom | Likely cause | What to do |
|---|---|---|
| Repeated `auth-rejected` | Token not in `SBSCORE_AUDIO_WORKER_TOKENS`, or revoked | Fix the token. Failed auth is rate limited per IP, which is why the worker backs off. |
| Jobs fail `unsupported-instrument` | User picked piano, drums or guitar | Expected until those models exist. |
| Jobs fail `audio-too-long` or `unsupported-audio` | Over the caps, or not a decodable audio or video file | Expected. The user sees the kind, not our message. |
| Jobs fail `engine-error` (retried up to 3 attempts) | A bug on some input | Find `job_id` in the logs; the worker logs the exception type only. |
| `out-of-memory` | A clip near the cap on a small memory limit | Raise `mem_limit`, or lower `--max-duration`. |
| `abandoned` | The lease was lost (slow network, restart) | Normal and self-healing: the server re-queues, up to 3 attempts, then `worker-lost`. |
| Unhealthy and no log lines | The process hung | Restart it (see Monitoring); the job is re-queued when its lease lapses (120 s). |

## Shutdown and restart

`SIGTERM` (or `docker compose stop`) lets the current job finish, then exits 0; compose waits up to 150 s. A
second signal exits immediately and the job is re-queued when its lease lapses. Nothing needs cleaning up.

## Data handling

Audio is fetched once into a temporary directory and deleted when the job ends, however it ends. Nothing is
cached or logged. sibei-score deletes the uploaded object when the job reaches a terminal state, and in any
case within 24 hours (its ADR-0034, decision 16). The audio is never a training corpus.

## Smoke test before a deploy

Needs a sibei-score checkout (`pnpm install` done) and Docker:

```sh
SIBEI_SCORE_DIR=~/projects/sibei-score make e2e-sibei        # local-disk mode
SIBEI_SCORE_DIR=~/projects/sibei-score make e2e-sibei-s3     # presigned URLs against a throwaway S3 store
```

Each submits a synthetic bass line, runs the worker once, and exports a PDF to `out/e2e/`. The S3 run also
checks that the object store received no credential.
