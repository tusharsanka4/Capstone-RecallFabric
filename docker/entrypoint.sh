#!/bin/sh
set -e

PORT="${PORT:-8000}"
WORKERS="${RECALLFABRIC_WORKERS:-1}"

echo "Starting RecallFabric API on port ${PORT} with ${WORKERS} worker(s)..."

# 1. Wait for database readiness
echo "Waiting for database connection..."
python - << 'EOF'
import sys
import time
from recallfabric.core.config import Settings
from recallfabric.db.connection import create_database_engine
from sqlalchemy import text

try:
    settings = Settings()
    engine = create_database_engine(settings)
except Exception as exc:
    print(f"Error initializing database engine: {exc}", file=sys.stderr)
    sys.exit(1)

max_attempts = 30
retry_delay = 2

for attempt in range(1, max_attempts + 1):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            print(f"Database reachable after {attempt} attempt(s).")
            sys.exit(0)
    except Exception as exc:
        print(f"Database connection attempt {attempt}/{max_attempts} failed ({exc.__class__.__name__}). Retrying in {retry_delay}s...")
        time.sleep(retry_delay)

print("Error: Timed out waiting for database connection.", file=sys.stderr)
sys.exit(1)
EOF

# 2. Run migrations if enabled
case "${RECALLFABRIC_RUN_MIGRATIONS}" in
    [Tt][Rr][Uu][Ee]|1|[Yy][Ee][Ss])
        echo "RECALLFABRIC_RUN_MIGRATIONS is enabled. Running 'alembic upgrade head'..."
        alembic upgrade head
        echo "Database migrations completed."
        ;;
    *)
        echo "RECALLFABRIC_RUN_MIGRATIONS is disabled. Skipping database migrations."
        ;;
esac

# 3. Start uvicorn
echo "Executing uvicorn server..."
exec uvicorn recallfabric.main:create_app \
    --factory \
    --host 0.0.0.0 \
    --port "$PORT" \
    --workers "$WORKERS" \
    --proxy-headers \
    --forwarded-allow-ips "*"
