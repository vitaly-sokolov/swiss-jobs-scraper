#!/bin/sh
# Apply migrations before anything else (§7), then hand over to the CMD.
set -eu

if [ ! -r "${JOBS_CONFIG_DIR}/config.yaml" ]; then
    echo "missing ${JOBS_CONFIG_DIR}/config.yaml (copy config.example.yaml)" >&2
    exit 1
fi

jobs-migrate
exec "$@"
