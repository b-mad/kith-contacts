# Kith Contacts app image (I-10, ADR-0019).
# Built on each person's computer by "Start Kith Contacts" (docker compose up --build).
# PYTHON_IMAGE, PG_MAJOR and WITH_MODEL exist for `make container-test`; keep the defaults.
ARG PYTHON_IMAGE=python:3.12-slim-trixie

FROM ${PYTHON_IMAGE} AS base
ARG PG_MAJOR=17
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# PostgreSQL client tools for backups and restores, same major version as the server (ADR-0011).
RUN apt-get update \
 && apt-get install -y --no-install-recommends "postgresql-client-${PG_MAJOR}" \
 && rm -rf /var/lib/apt/lists/*

FROM base AS build
ARG UV_VERSION=0.11.32
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1
RUN python3 -m pip install --no-cache-dir "uv==${UV_VERSION}"
WORKDIR /opt/contacts
# Exact versions from uv.lock; no development tools.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
# Search by meaning (S-08): fetch the pinned model and check every file's SHA-256 (ADR-0013).
# The download is cached between builds. If it fails, the app works without search by meaning.
COPY app/ app/
COPY scripts/ scripts/
ARG WITH_MODEL=1
RUN --mount=type=cache,target=/var/cache/contacts-model \
    mkdir -p /opt/model \
 && if [ "$WITH_MODEL" = "1" ]; then \
      if /opt/venv/bin/python -m scripts.semantic model --dest /var/cache/contacts-model; then \
        cp -R /var/cache/contacts-model/. /opt/model/; \
      else \
        echo "WARNING: the search-by-meaning model could not be downloaded; search by meaning will be off."; \
      fi; \
    fi
# The program files, readable by the app user whatever permissions they had on disk.
COPY alembic.ini ./
COPY migrations/ migrations/
RUN chmod -R a+rX,go-w /opt/contacts /opt/model

FROM base
ARG APP_VERSION=dev
LABEL org.opencontainers.image.title="Kith Contacts" \
      org.opencontainers.image.description="Find people by context: team, manager, project, tags." \
      org.opencontainers.image.version="${APP_VERSION}"
RUN useradd --system --uid 10001 --user-group --home-dir /nonexistent --no-create-home \
      --shell /usr/sbin/nologin contacts \
 && mkdir -p /run/contacts/db /run/contacts/instance \
      /run/contacts/instances/work /run/contacts/instances/personal /backups \
 && chown -R contacts:contacts /run/contacts /backups
COPY --from=build /opt/venv /opt/venv
COPY --from=build /opt/model /opt/model
COPY --from=build /opt/contacts /opt/contacts
WORKDIR /opt/contacts
ENV PATH=/opt/venv/bin:$PATH \
    HOME=/tmp \
    HOST=0.0.0.0 \
    MODEL_DIR=/opt/model \
    BACKUP_DIR=/backups \
    BACKUP_TOOL=local \
    INSTALL_KIND=container
USER contacts
EXPOSE 5170
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "-m", "app.container", "health"]
ENTRYPOINT ["python", "-m", "app.container"]
CMD ["serve"]
