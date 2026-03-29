"""
parsarr entry point.

Running as a module:
  python -m parsarr.main serve
  python -m parsarr.main run /path/to/release
  python -m parsarr.main test /path/to/release
  python -m parsarr.main inspect /path/to/release

The FastAPI `app` object is also importable by uvicorn:
  uvicorn parsarr.main:app
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from . import __version__
from .config import load_settings
from .webhook.routes import router as webhook_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Factory used by uvicorn and tests alike."""
    import parsarr.config as _cfg

    _cfg.settings = load_settings()

    logging.basicConfig(
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        level=getattr(logging, _cfg.settings.log_level.upper(), logging.INFO),
    )

    application = FastAPI(
        title="parsarr",
        description=(
            "Webhook-driven *arr-stack file parser — cleans multi-season packs "
            "and messy releases so Sonarr, Radarr, and Jellyfin can ingest them."
        ),
        version=__version__,
    )

    application.include_router(webhook_router)

    @application.exception_handler(Exception)
    async def generic_exception_handler(request, exc):
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return application


# Module-level app instance — used by uvicorn and when imported directly.
app = create_app()


if __name__ == "__main__":
    from .cli import cli

    cli()
