FROM python:3.12-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.16 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev
# A read-only root filesystem: scratch space is /tmp (a tmpfs in compose), and nothing may write bytecode.
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 NUMBA_CACHE_DIR=/tmp/numba HOME=/tmp
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin worker
USER 10001:10001
# MAT_API_URL and MAT_WORKER_TOKEN come from the environment at run time; the token is never baked in.
ENTRYPOINT ["mat", "worker"]
