# ============================================================
# Stage 1 — builder
# Build context: repo root (jonas-data-platform/)
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install --upgrade pip hatchling

COPY services/api/pyproject.toml .
COPY services/api/src/ src/

RUN pip wheel --no-deps --wheel-dir /build/dist .


# ============================================================
# Stage 2 — runtime
# ============================================================
FROM python:3.11-slim AS runtime

RUN groupadd --gid 1001 appgroup \
 && useradd --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

COPY --from=builder /build/dist/*.whl /tmp/
RUN pip install --no-cache-dir --upgrade pip setuptools \
 && pip install --no-cache-dir /tmp/*.whl \
 && rm /tmp/*.whl

# Application source
COPY services/api/src/ src/

# DDL migrations (read-only at runtime; used by db/init.py on startup)
COPY db/ db/

# Data directories (overridden by volume mounts)
RUN mkdir -p /app/data/db /app/data/parquet \
 && chown -R appuser:appgroup /app

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    DUCKDB_PATH=/app/data/db/jonas.duckdb \
    PARQUET_ROOT=/app/data/parquet

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
