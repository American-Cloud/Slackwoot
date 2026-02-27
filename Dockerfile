# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt pyproject.toml ./
COPY src/ ./src/

# Install all dependencies including the slackwoot package
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
 && pip install --no-cache-dir --prefix=/install .

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Create a non-root user — never run as root in production
RUN addgroup --system slackwoot && adduser --system --ingroup slackwoot slackwoot

WORKDIR /app

# Copy installed packages from builder stage
COPY --from=builder /install /usr/local

# Copy application source
COPY --from=builder /build/src ./src

# Copy entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create data dir and fix ownership of ALL app files for the non-root user.
# COPY --from=builder preserves root ownership, so we must chown explicitly.
RUN mkdir -p /app/data \
 && chown -R slackwoot:slackwoot /app

# Tell Python where to find the 'app' package (src/ layout)
ENV PYTHONPATH=/app/src

RUN apt-get update && apt-get install -y sqlite3 postgresql-client && apt-get clean && rm -rf /var/lib/apt/lists/*
USER slackwoot

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
