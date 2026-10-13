from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .config import get_settings
from .db import dispose_engine, get_engine
from .routers import agent_api, agents, alerts, analytics, auth, jobs, live, users, vpn

log = logging.getLogger("ipf3")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        h.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'self'",
        )
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        limit = get_settings().max_payload_bytes
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > limit:
                    return JSONResponse({"detail": "Payload too large"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        # Chunked bodies without Content-Length are bounded by nginx client_max_body_size.
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # fail fast on bad configuration
    get_engine()
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Unknown Monitor",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["content-type", "x-ipf3-csrf", "authorization"],
        )

    api_prefix = "/api/v1"
    for r in (auth.router, users.router, agents.router, jobs.router, alerts.router, analytics.router, live.router, vpn.router):
        app.include_router(r, prefix=api_prefix)
    app.include_router(agent_api.router, prefix="/api")
    app.include_router(vpn.public)

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", include_in_schema=False)
    async def readyz():
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            return JSONResponse({"status": "database unavailable"}, status_code=503)
        return {"status": "ready"}

    if settings.web_root:
        root = Path(settings.web_root).resolve()
        index = root / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            candidate = (root / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(root):
                return FileResponse(candidate)
            return FileResponse(index)

    return app

