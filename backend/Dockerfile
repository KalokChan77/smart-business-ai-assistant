FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup --home /app appuser

COPY pyproject.toml ./
COPY app ./app
RUN python -m pip install --upgrade pip \
    && python -m pip install .

COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY docker-entrypoint.sh /usr/local/bin/smart-business-entrypoint

RUN chmod +x /usr/local/bin/smart-business-entrypoint \
    && mkdir -p /app/.data/knowledge_documents \
    && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

ENTRYPOINT ["smart-business-entrypoint"]
