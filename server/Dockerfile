# Self-hosted TGTG watcher.
#
# Note the two-stage shape: the `tgtg` client is installed from git (the
# released version still points at the retired item/v8 endpoint), so the build
# stage needs git and a compiler, neither of which belong in the runtime image.

FROM python:3.12-slim AS builder

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir --prefix=/install .


FROM python:3.12-slim

# tzdata so pickup windows and log timestamps are readable rather than UTC.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Run unprivileged. The data volume is the only thing this needs to write.
RUN useradd --create-home --uid 10001 tgtg
WORKDIR /home/tgtg

ENV TGTG_DATA_DIR=/data \
    PYTHONUNBUFFERED=1

RUN mkdir -p /data && chown tgtg:tgtg /data
VOLUME ["/data"]
USER tgtg

EXPOSE 8787

# Default to serving both the API and the poller; `--only api` / `--only poller`
# splits them across containers if you prefer.
ENTRYPOINT ["tgtg-alert"]
CMD ["serve"]
