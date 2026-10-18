# One container for Render / Railway: FalkorDB + the Lore app + the graph data.
# Build context = repo root. Dockerfile path = deploy/Dockerfile
FROM falkordb/falkordb:latest

USER root
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY web/ web/
COPY docs/ docs/
COPY scripts/ scripts/
COPY deploy/start.sh deploy/start.sh
COPY deploy/dump.rdb deploy/dump.rdb

# Windows line endings would break the script
RUN sed -i 's/\r$//' /app/deploy/start.sh && chmod +x /app/deploy/start.sh

EXPOSE 10000
ENTRYPOINT ["bash", "/app/deploy/start.sh"]
