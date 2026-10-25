FROM python:3.12-slim-trixie@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704

ARG WORKSPACE_BASE_VERSION=2026.10.25-1
LABEL com.momobot.workspace.base-version="${WORKSPACE_BASE_VERSION}" \
      com.momobot.workspace.managed="true"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git jq nodejs npm ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 momo \
    && useradd --uid 10001 --gid momo --no-create-home momo \
    && mkdir -p /mnt/data /work \
    && chown -R momo:momo /mnt/data /work

COPY job_runner.py /opt/momobot/job_runner.py
RUN chmod 0555 /opt/momobot/job_runner.py

USER 10001:10001
WORKDIR /work
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD ["python3", "-c", "import os; os.path.isfile('/opt/momobot/job_runner.py') or exit(1)"]
CMD ["sleep", "infinity"]
