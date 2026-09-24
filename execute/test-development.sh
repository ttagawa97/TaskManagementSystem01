#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Tests run inside the approved development environment using a temporary test DB.
docker compose --env-file .env.development -f compose.development.yaml exec -T app python manage.py test --noinput
