"""FastAPI application factory.

Run an instance with ``./run.sh <instance>`` (see README). Uvicorn builds the
app with ``app.main:create_app --factory`` so settings are read at start-up,
not at import time.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import api, web, web_admin, web_lists
from app.backup import BackupFile, ensure_recent_backup
from app.config import Settings, load_settings
from app.contacts import ContactError, ContactNotFound
from app.db import create_db_engine, make_session_factory
from app.links import display_phone, slack_handle_display
from app.migrate import current_revision, ensure_contact_types, upgrade_to_head

APP_DIR = Path(__file__).resolve().parent
AUTO_BACKUP_INTERVAL_SECONDS = 3600
log = logging.getLogger(__name__)


@dataclass
class BackupStatus:
    """Shown on the settings page (I-06)."""

    enabled: bool
    last_check: datetime | None = None
    last_made: BackupFile | None = None
    last_error: str | None = None


async def auto_backup_loop(settings: Settings, status: BackupStatus) -> None:
    """Daily backups while the instance runs (I-06, N-06, ADR-0011)."""
    while True:
        try:
            made = await asyncio.to_thread(ensure_recent_backup, settings)
            status.last_error = None
            if made is not None:
                status.last_made = made
        except Exception as exc:  # keep the app running; surface the problem instead
            log.exception("automatic backup failed")
            status.last_error = str(exc)
        status.last_check = datetime.now(UTC)
        await asyncio.sleep(AUTO_BACKUP_INTERVAL_SECONDS)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # N-04: no third-party assets — everything is served from this origin.
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'"
    ),
}


def initials(name: str) -> str:
    """Placeholder for a missing photo (C-09): up to two initials."""
    honorifics = {"dr", "mr", "mrs", "ms", "mx", "prof", "sir", "dame"}
    words = [
        w for w in name.replace(".", " ").split() if w[:1].isalpha() and w.lower() not in honorifics
    ]
    return (
        "".join(w[0].upper() for w in (words[:1] + words[-1:] if len(words) > 1 else words)) or "?"
    )


def build_templates(settings: Settings) -> Jinja2Templates:
    templates = Jinja2Templates(directory=APP_DIR / "templates")
    templates.env.globals["instance"] = settings
    templates.env.globals["csrf_field"] = web.CSRF_FIELD
    templates.env.filters["phone"] = display_phone
    templates.env.filters["slack_handle"] = slack_handle_display
    templates.env.filters["initials"] = initials
    return templates


def create_app(settings: Settings | None = None, *, run_migrations: bool = True) -> FastAPI:
    settings = settings or load_settings()
    engine = create_db_engine(settings)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if run_migrations:
            upgrade_to_head(settings)  # I-04: raises -> the instance does not start
            with session_factory() as session:
                ensure_contact_types(session, settings.contact_types)
        task = (
            asyncio.create_task(auto_backup_loop(settings, app.state.backup_status))
            if settings.auto_backup_enabled
            else None
        )
        yield
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        engine.dispose()

    app = FastAPI(
        title=f"Contacts · {settings.instance_name}",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
        openapi_url="/openapi.json" if not settings.is_production else None,
    )
    app.state.settings = settings
    app.state.backup_status = BackupStatus(enabled=settings.auto_backup_enabled)
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.templates = build_templates(settings)
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    @app.middleware("http")
    async def security_and_csrf(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        token = request.cookies.get(web.CSRF_COOKIE) or secrets.token_urlsafe(32)
        request.state.csrf_token = token
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if web.CSRF_COOKIE not in request.cookies:
            response.set_cookie(web.CSRF_COOKIE, token, httponly=True, samesite="strict", path="/")
        return response

    @app.exception_handler(ContactError)
    async def contact_error(request: Request, exc: ContactError) -> JSONResponse:
        return api.error_body(exc.message, exc.field)

    @app.exception_handler(ContactNotFound)
    async def contact_not_found(request: Request, exc: ContactNotFound) -> JSONResponse:
        return JSONResponse({"detail": "Contact not found"}, status_code=404)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> JSONResponse:
        body: dict[str, Any] = {
            "instance": settings.instance_name,
            "env": settings.app_env,
        }
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            body |= {"status": "ok", "database": "ok", "revision": current_revision(engine)}
            return JSONResponse(body)
        except SQLAlchemyError:
            body |= {"status": "error", "database": "unreachable"}
            return JSONResponse(body, status_code=503)

    @app.get("/instance.css", name="instance_css", include_in_schema=False)
    def instance_css() -> Response:
        """Per-instance colors (I-03), served as a stylesheet so the CSP needs no inline styles."""
        css = f":root {{ --instance-color: {settings.instance_color}; }}\n"
        return Response(css, media_type="text/css", headers={"Cache-Control": "no-cache"})

    app.include_router(api.router)
    app.include_router(api.write_router)
    app.include_router(web.router)
    app.include_router(web_lists.router)
    app.include_router(web_admin.router)
    return app
