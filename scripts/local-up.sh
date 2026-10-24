#!/usr/bin/env bash
# Load the sample sales table and print the two process commands.
# Postgres is expected on 127.0.0.1:5432 (a local cluster or a published compose port).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://agentrt:agentrt@127.0.0.1:5432/agentrt}"
export SALES_ADMIN_URL="${SALES_ADMIN_URL:-postgresql://agentrt:agentrt@127.0.0.1:5432/sales}"
export SALES_DATABASE_URL="${SALES_DATABASE_URL:-postgresql://sales_ro:sales_ro@127.0.0.1:5432/sales}"
ROWS="${SEED_SALES_ROWS:-20000}"
"$PY" "$ROOT/scripts/generate_sales.py" --database-url "$SALES_ADMIN_URL" --rows "$ROWS" --grant-read-only
echo "Satış tablosu hazır (${ROWS} satır veya mevcut tablo)."
echo "Kontrol düzlemi:  cd $ROOT && set -a && source .env && set +a && .venv/bin/python -m control_plane"
echo "Arayüz:           cd $ROOT/ui && CONTROL_PLANE_URL=http://127.0.0.1:8841 npm run dev"
