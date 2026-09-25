#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose --env-file .env.development -f compose.development.yaml exec app python manage.py create_initial_admin
