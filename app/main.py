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
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import api, web, web_admin, web_depth, web_kit, web_lists, web_privacy
from app.appearance import THEME_CHOICES, current_appearance, text_on
from app.backup import BackupFile, ensure_recent_backup
from app.config import Settings, load_settings
from app.contacts import ContactError, ContactNotFound
from app.db import create_db_engine, make_session_factory
from app.embedder import Embedder
from app.keep_in_touch import INTERVAL_LABELS, count_due
from app.links import display_phone, slack_handle_display
from app.migrate import current_revision, ensure_contact_types, upgrade_to_head
from app.privacy import (
    COOKIE,
    PRESENTING,
    Presenting,
    current_privacy,
    is_blocked,
    is_presenting,
    is_unlocked,
    presenting,
)
from app.saved_searches import describe_query
from app.semantic import SemanticService, mark_changed

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


SEMANTIC_IDLE_SECONDS = 3.0
SEMANTIC_RECHECK_SECONDS = 3600.0


async def semantic_loop(service: SemanticService, session_factory: Any) -> None:
    """S-08: load the model, then keep every contact's embeddings current (ADR-0013)."""
    if not await asyncio.to_thread(service.load):
        log.info("search by meaning unavailable: %s", service.unavailable)
        return
    last_recheck = -SEMANTIC_RECHECK_SECONDS

    def step(recheck: bool) -> int:
        with session_factory() as session:
            if recheck and service.model_id:
                mark_changed(session, service.model_id)
            done = service.index_pending(session)
            session.commit()
            if service.model_id:
                service.index.sync(session, service.model_id)  # warm the cache
            return done

    while True:
        now = asyncio.get_running_loop().time()
        recheck = now - last_recheck >= SEMANTIC_RECHECK_SECONDS
        try:
            done = await asyncio.to_thread(step, recheck)
            service.last_error = None
            if recheck:
                last_recheck = now
            delay = 0.1 if done else SEMANTIC_IDLE_SECONDS
        except Exception as exc:  # keep the app running; show the problem in Settings
            log.exception("search-by-meaning indexing failed")
            service.last_error = str(exc)
            delay = 30.0
        await asyncio.sleep(delay)


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
    templates.env.filters["search_summary"] = describe_query
    return templates


def _reconnect_count(app: FastAPI) -> int:
    """S-11: people due within a week, for the navigation; 0 if the database is unavailable."""
    try:
        with app.state.session_factory() as session:
            return count_due(session, today=date.today())
    except SQLAlchemyError:
        return 0


def create_app(
    settings: Settings | None = None,
    *,
    run_migrations: bool = True,
    embedder: Embedder | None = None,
    background_indexing: bool = True,
) -> FastAPI:
    """``embedder`` and ``background_indexing`` exist for tests (search by meaning, S-08)."""
    settings = settings or load_settings()
    semantic = SemanticService(settings, embedder=embedder)
    engine = create_db_engine(settings)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if run_migrations:
            upgrade_to_head(settings)  # I-04: raises -> the instance does not start
            with session_factory() as session:
                ensure_contact_types(session, settings.contact_types)
        tasks = []
        if settings.auto_backup_enabled:
            tasks.append(asyncio.create_task(auto_backup_loop(settings, app.state.backup_status)))
        if background_indexing and semantic.enabled:
            tasks.append(asyncio.create_task(semantic_loop(semantic, session_factory)))
        yield
        for task in tasks:
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
    app.state.semantic = semantic
    app.state.templates = build_templates(settings)
    app.state.appearance = None  # loaded on first render (A-03)
    app.state.templates.env.globals["appearance"] = lambda: current_appearance(app.state)
    app.state.templates.env.globals["theme_choices"] = THEME_CHOICES
    app.state.templates.env.globals["kit_intervals"] = INTERVAL_LABELS
    app.state.templates.env.globals["reconnect_count"] = lambda: _reconnect_count(app)
    app.state.privacy = None  # loaded on first request (P-03)
    app.state.templates.env.globals["presenting"] = presenting
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    # Registered before security_and_csrf, so it runs inside it (CSRF token already set).
    @app.middleware("http")
    async def presenting_mode(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """P-01 to P-07: while presenting, every query and template sees the presentable view."""
        privacy = await asyncio.to_thread(current_privacy, app.state)
        if not is_presenting(request.cookies, privacy):
            return await call_next(request)
        path = request.url.path
        token = PRESENTING.set(
            Presenting(privacy, filter_queries=request.method in {"GET", "HEAD"})
        )
        try:
            if privacy.view == "locked" and not is_unlocked(path):
                response = _unavailable(request, "privacy/locked.html", path)
            elif is_blocked(path):
                response = _unavailable(request, "privacy/unavailable.html", path)
            else:
                response = await call_next(request)
        finally:
            PRESENTING.reset(token)
        if COOKIE not in request.cookies:  # P-07: this instance starts presenting
            web_privacy.set_presenting_cookie(response, True, privacy)
        return response

    def _unavailable(request: Request, template: str, path: str) -> Response:
        accept = request.headers.get("accept", "")
        if path.startswith("/api/") or ("json" in accept and "html" not in accept):
            return JSONResponse({"detail": "Not available while presenting"}, status_code=403)
        templates: Jinja2Templates = app.state.templates
        return templates.TemplateResponse(request, template, {}, status_code=403)

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
        color = settings.instance_color
        css = f":root {{ --instance-color: {color}; --instance-on: {text_on(color)}; }}\n"
        return Response(css, media_type="text/css", headers={"Cache-Control": "no-cache"})

    app.include_router(api.router)
    app.include_router(api.write_router)
    app.include_router(web.router)
    app.include_router(web_lists.router)
    app.include_router(web_admin.router)
    app.include_router(web_depth.router)
    app.include_router(web_kit.router)
    app.include_router(web_privacy.router)
    return app
