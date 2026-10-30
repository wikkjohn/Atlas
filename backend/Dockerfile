FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
RUN pip install .

COPY alembic.ini ./
COPY alembic ./alembic
COPY docker-entrypoint.sh ./
# The archive directory exists (owned by the app user) so a fresh named volume inherits it.
RUN chmod +x docker-entrypoint.sh && useradd --create-home atlas \
    && mkdir -p /app/var/simulation-archive && chown -R atlas /app/var
USER atlas

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
