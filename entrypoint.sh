#!/bin/sh
set -e

echo "Running database migrations..."
alembic upgrade head

# Optional: simple wait-for DB port if you uncomment postgres service later
# until nc -z postgres 5432; do
#   echo "Waiting for PostgreSQL..."
#   sleep 2
# done

echo "Starting application..."
exec "$@"   # runs whatever CMD is set (uvicorn app.main:app ...)
