"""FastAPI application factory.

Run an instance with ``./run.sh <instance>`` (see README). Uvicorn builds the
app with ``app.main:create_app --factory`` so settings are read at start-up,
not at import time.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, load_settings
from app.db import create_db_engine, get_session, make_session_factory
from app.migrate import current_revision, ensure_contact_types, upgrade_to_head
from app.models import Contact

APP_DIR = Path(__file__).resolve().parent

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # N-04: no third-party assets — everything is served from this origin.
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
}

SessionDep = Annotated[Session, Depends(get_session)]


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
        yield
        engine.dispose()

    app = FastAPI(
        title=f"Contacts · {settings.instance_name}",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory

    templates = Jinja2Templates(directory=APP_DIR / "templates")
    templates.env.globals["instance"] = settings
    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.get("/healthz")
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

    @app.get("/instance.css", name="instance_css")
    def instance_css() -> Response:
        """Per-instance colors (I-03), served as a stylesheet so the CSP needs no inline styles."""
        css = f":root {{ --instance-color: {settings.instance_color}; }}\n"
        return Response(css, media_type="text/css", headers={"Cache-Control": "no-cache"})

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, session: SessionDep) -> HTMLResponse:
        contacts = session.scalars(
            select(Contact)
            .where(Contact.archived_at.is_(None))
            .order_by(Contact.display_name)
            .limit(200)
        ).all()
        return templates.TemplateResponse(request, "index.html", {"contacts": contacts})

    return app
