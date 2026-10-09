# Opt-in private workflow workers on an explicitly reviewed Gateway image.
# The normal backend/Dockerfile and its publication pipeline remain unchanged.
ARG MOMOBOT_GATEWAY_IMAGE
ARG PYTHON_WORKER_IMAGE=python:3.13-slim-bookworm@sha256:2325bb286ec344af3e5898cc224b5844e2707ac6e26b1632516fd3edc84a5e26
ARG NODE_WORKER_IMAGE=node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6
FROM ${MOMOBOT_GATEWAY_IMAGE} AS gateway-base
FROM ${NODE_WORKER_IMAGE} AS worker-node
FROM ${PYTHON_WORKER_IMAGE} AS worker-builder

COPY --from=gateway-base /usr/local/bin/uv /usr/local/bin/uv
COPY --from=worker-node /usr/local/bin/node /usr/bin/node
COPY --from=worker-node /usr/local/lib/node_modules/npm /usr/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/bin/npm \
    && apt-get update \
    && apt-get install -y --no-install-recommends build-essential git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY workers/browser-teams/package.json workers/browser-teams/package-lock.json workers/browser-teams/tsconfig.json ./workers/browser-teams/
COPY workers/browser-teams/src/*.ts ./workers/browser-teams/src/
COPY workers/browser-teams/test/*.ts ./workers/browser-teams/test/
COPY workers/browser-teams/python/pyproject.toml workers/browser-teams/python/uv.lock workers/browser-teams/python/worker.py ./workers/browser-teams/python/
COPY workers/agno-team/pyproject.toml workers/agno-team/uv.lock workers/agno-team/worker.py ./workers/agno-team/
COPY workers/inngest-team/package.json workers/inngest-team/package-lock.json workers/inngest-team/worker.js ./workers/inngest-team/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-managed-python --python /usr/local/bin/python3.13 --project workers/browser-teams/python \
    && uv sync --frozen --no-dev --no-managed-python --python /usr/local/bin/python3.13 --project workers/agno-team
RUN --mount=type=cache,target=/root/.npm \
    cd workers/browser-teams \
    && npm ci --ignore-scripts --no-audit --no-fund \
    && npm run check && npm run build && npm test \
    && npm prune --omit=dev --ignore-scripts --no-audit --no-fund \
    && cd ../inngest-team \
    && npm ci --omit=dev --ignore-scripts --no-audit --no-fund \
    && npm run check

FROM gateway-base AS workflow-runtime
ARG MOMOBOT_GATEWAY_IMAGE
ARG MOMOBOT_WORKER_SOURCE_REVISION=unrecorded
LABEL io.momobot.gateway.base="${MOMOBOT_GATEWAY_IMAGE}" \
      io.momobot.worker.source-revision="${MOMOBOT_WORKER_SOURCE_REVISION}"
# Only the versioned worker interpreter is added. The Gateway's Python3.12,
# virtualenv and locked OpenAI dependency remain those of the reviewed base.
COPY --from=worker-builder /usr/local/bin/python3.13 /usr/local/bin/python3.13
COPY --from=worker-builder /usr/local/lib/python3.13 /usr/local/lib/python3.13
COPY --from=worker-builder /usr/local/lib/libpython3.13.so.1.0 /usr/local/lib/libpython3.13.so.1.0
COPY --from=worker-node /usr/local/bin/node /usr/bin/node
COPY --from=worker-node /usr/local/lib/node_modules/npm /usr/lib/node_modules/npm
COPY --from=worker-builder /app/workers /app/workers
COPY backend/scripts/verify_workflow_workers.py /app/backend/scripts/verify_workflow_workers.py
RUN ldconfig
WORKDIR /app
# Inherit the reviewed base CMD. Adding packages does not enable a workflow,
# schedule, model key, provider call or another worker controller.
