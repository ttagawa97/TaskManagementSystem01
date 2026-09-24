#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env.development ]]; then
  echo '先に python3 execute/prepare-development.py を実行してください。' >&2
  exit 1
fi
docker compose --env-file .env.development -f compose.development.yaml up --build -d --wait
echo '開発画面: http://127.0.0.1:8000'
