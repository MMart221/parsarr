"""
parsarr application factory.

Uvicorn entry point:
  uvicorn parsarr.main:app

CLI entry point:
  python -m parsarr.main serve
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __version__
from .config import load_settings
from .jobs import JobStore

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "frontend" / "templates"
_STATIC_DIR = Path(__file__).parent / "frontend" / "static"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def create_app() -> FastAPI:
    import parsarr.config as _cfg

    _cfg.settings = load_settings()
    s = _cfg.settings

    logging.basicConfig(
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        level=getattr(logging, s.log_level.upper(), logging.INFO),
    )

    app = FastAPI(
        title="parsarr",
        description="TV/anime intake and import preprocessor for the *arr stack.",
        version=__version__,
        docs_url="/api/docs",
        redoc_url=None,
    )

    # ------------------------------------------------------------------
    # Job store
    # ------------------------------------------------------------------
    db = JobStore(s.db_path)
    from .api.routes import init_job_store
    init_job_store(db)

    # ------------------------------------------------------------------
    # API + webhook routes
    # ------------------------------------------------------------------
    from .api.routes import router as api_router
    app.include_router(api_router)

    # ------------------------------------------------------------------
    # Static files
    # ------------------------------------------------------------------
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # ------------------------------------------------------------------
    # Frontend page routes
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def queue_page(request: Request):
        jobs = await db.list_jobs(limit=200)
        return templates.TemplateResponse(
            request,
            "queue.html",
            {"jobs": jobs, "active": "queue"},
        )

    @app.get("/add", response_class=HTMLResponse)
    async def add_page(request: Request):
        return templates.TemplateResponse(
            request,
            "add.html",
            {"active": "add"},
        )

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        return templates.TemplateResponse(
            request,
            "settings.html",
            {"settings": s, "active": "settings"},
        )

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_detail_page(request: Request, job_id: int):
        from .core.inspector import classify_tree
        import parsarr.config as _cfg

        job = await db.get_job(job_id)
        if not job:
            return HTMLResponse(content="<h1>404 — Job not found</h1>", status_code=404)
        profile = None
        if job.file_tree:
            profile = classify_tree(job.file_tree, extra_patterns=_cfg.settings.extra_patterns)
        return templates.TemplateResponse(
            request,
            "job_detail.html",
            {"job": job, "active": "queue", "profile": profile},
        )

    # ------------------------------------------------------------------
    # Generic exception handler
    # ------------------------------------------------------------------

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app


app = create_app()

if __name__ == "__main__":
    from .cli import cli
    cli()
