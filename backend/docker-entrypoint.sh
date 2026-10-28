#!/bin/sh
# Apply pending database migrations, then start the API.
set -e
alembic upgrade head
exec "$@"
