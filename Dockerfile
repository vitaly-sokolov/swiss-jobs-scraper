# App image: Python 3.12, Chromium + chromedriver, supercronic (§10).
FROM python:3.12-slim-bookworm

ARG SUPERCRONIC_VERSION=v0.2.33
ARG TARGETARCH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Zurich \
    JOBS_CONFIG_DIR=/app/config \
    JOBS_ALEMBIC_INI=/app/alembic.ini \
    JOBS_CHROME_BIN=/usr/bin/chromium \
    JOBS_CHROMEDRIVER=/usr/bin/chromedriver

RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium chromium-driver ca-certificates curl tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && arch="${TARGETARCH:-amd64}" \
    && curl -fsSLo /usr/local/bin/supercronic \
       "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-${arch}" \
    && chmod +x /usr/local/bin/supercronic

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install .

COPY alembic.ini ./
COPY migrations ./migrations
COPY docker/crontab docker/entrypoint.sh ./docker/

RUN useradd --system --uid 10001 --home /app jobs && chmod +x docker/entrypoint.sh
USER jobs

# config/ (config.yaml with secrets + vocabulary YAMLs) is mounted read-only at runtime.
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["supercronic", "-passthrough-logs", "/app/docker/crontab"]
