#!/usr/bin/env bash
# Starts FalkorDB (private, inside the container) with the graph loaded, then the web app.
set -u

DATA_DIR=/tmp/falkor-data
mkdir -p "$DATA_DIR"
cp /app/deploy/dump.rdb "$DATA_DIR/dump.rdb"

FALKOR_SO="$(find /var/lib/falkordb /usr/lib /usr/local -name 'falkordb.so' 2>/dev/null | head -n 1)"
REDIS_BIN="$(command -v redis-server || true)"
if [ -z "$FALKOR_SO" ] || [ -z "$REDIS_BIN" ]; then
  echo "ERROR: could not find redis-server or falkordb.so" >&2
  exit 1
fi
echo "Using $REDIS_BIN with $FALKOR_SO"

"$REDIS_BIN" --loadmodule "$FALKOR_SO" \
  --bind 127.0.0.1 --port 6379 \
  --dir "$DATA_DIR" --dbfilename dump.rdb \
  --save "" --appendonly no --protected-mode no &

# wait up to 2 minutes for the graph to load
for i in $(seq 1 120); do
  if redis-cli -h 127.0.0.1 -p 6379 ping 2>/dev/null | grep -q PONG; then
    echo "FalkorDB is up after ${i}s"
    break
  fi
  sleep 1
done

export FALKORDB_HOST=127.0.0.1
export FALKORDB_PORT=6379

cd /app
exec /opt/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}"
