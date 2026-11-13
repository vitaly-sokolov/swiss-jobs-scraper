#!/bin/sh
# Pull-based deploy, run every few minutes by swiss-jobs-deploy.timer.
# Fast-forwards the checkout (compose file, config vocabularies), pulls the CI-built
# image from GHCR and recreates only the containers whose image or config changed.
# The body is a function so sh parses all of it before git pull can rewrite this file.
set -eu

main() {
    cd "$(dirname "$0")/.."

    # Recreating the scheduler mid-run would kill the daily scrape; retry on the next tick.
    if docker compose top scheduler 2>/dev/null | grep -qE 'jobs-(scrape|notify|cleanup|migrate)'; then
        echo "scheduler job running, skipping"
        return 0
    fi

    git fetch --quiet origin main
    if [ "$(git rev-parse HEAD)" != "$(git rev-parse FETCH_HEAD)" ]; then
        git merge --ff-only --quiet FETCH_HEAD
        echo "checkout at $(git rev-parse --short HEAD)"
    fi

    before=$(docker compose images -q scheduler 2>/dev/null || true)
    docker compose pull --quiet scheduler
    docker compose up -d --quiet-pull --remove-orphans
    after=$(docker compose images -q scheduler 2>/dev/null || true)

    if [ "$before" != "$after" ]; then
        echo "scheduler image ${before:-none} -> $after"
        docker image prune -f >/dev/null
    fi
}

main "$@"
