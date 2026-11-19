#!/usr/bin/env sh
set -e

# Wait for Postgres to accept connections before running migrations.
python - <<'PY'
import os, time
import psycopg
from urllib.parse import urlparse

url = os.environ.get("DATABASE_URL", "")
if url.startswith("postgres"):
    parsed = urlparse(url)
    for attempt in range(30):
        try:
            with psycopg.connect(
                dbname=parsed.path.lstrip("/"),
                user=parsed.username,
                password=parsed.password,
                host=parsed.hostname,
                port=parsed.port or 5432,
                connect_timeout=2,
            ):
                break
        except Exception:
            time.sleep(1)
    else:
        raise SystemExit("Postgres did not become ready")
PY

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
    python manage.py migrate --noinput
fi

if [ "${SEED_DEMO:-0}" = "1" ]; then
    python manage.py seed_demo || true
fi

exec "$@"
