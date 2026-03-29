"""
FastAPI webhook routes.

POST /webhook/sonarr  — receives Sonarr download events
POST /webhook/radarr  — receives Radarr download events
GET  /health          — liveness probe
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from ..arr.radarr import RadarrClient
from ..arr.sonarr import SonarrClient
from ..config import settings
from ..core import inspector, processor, staging
from .schemas import ArrEventType, RadarrWebhook, SonarrWebhook

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_secret(request: Request, body: bytes) -> None:
    """Reject requests that don't match the configured webhook_secret."""
    if not settings.webhook_secret:
        return
    provided = request.headers.get("X-Parsarr-Secret") or request.headers.get(
        "Authorization", ""
    ).removeprefix("Bearer ")
    if not hmac.compare_digest(provided, settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


def _resolve_download_path(path_str: Optional[str]) -> Optional[Path]:
    if not path_str:
        return None
    p = Path(path_str)
    # Accept both a file path and a folder path — if the path is a file, use
    # its parent so the Inspector can scan the full release folder.
    return p.parent if p.is_file() else p


async def _process_and_import_sonarr(
    release_path: Path,
    release_name: str,
    series_id: Optional[int],
) -> None:
    """Background task: inspect → stage → process → trigger ManualImport."""
    try:
        profile = inspector.inspect(
            release_path, extra_patterns=settings.extra_patterns
        )
        logger.info("Sonarr release profile: %s", profile.summary())

        if profile.is_standard:
            logger.info("Release is standard — no action needed.")
            return

        slot = staging.make_staging_slot(settings.staging_dir, release_name)
        result = processor.process(profile, slot)

        if result.skipped or not result.moved_files:
            staging.cleanup_staging_slot(slot)
            return

        video_paths = processor.staged_video_paths(result)
        if not video_paths:
            logger.warning("No video files in staging slot after processing.")
            staging.cleanup_staging_slot(slot)
            return

        client = SonarrClient(
            base_url=settings.sonarr.url, api_key=settings.sonarr.api_key
        )
        await client.manual_import(video_paths, series_id=series_id)
        logger.info(
            "Sonarr ManualImport triggered for %d file(s)", len(video_paths)
        )

    except Exception:
        logger.exception("Error processing Sonarr release: %s", release_path)


async def _process_and_import_radarr(
    release_path: Path,
    release_name: str,
    movie_id: Optional[int],
) -> None:
    """Background task: inspect → stage → process → trigger ManualImport."""
    try:
        profile = inspector.inspect(
            release_path, extra_patterns=settings.extra_patterns
        )
        logger.info("Radarr release profile: %s", profile.summary())

        if profile.is_standard:
            logger.info("Release is standard — no action needed.")
            return

        slot = staging.make_staging_slot(settings.staging_dir, release_name)
        result = processor.process(profile, slot)

        if result.skipped or not result.moved_files:
            staging.cleanup_staging_slot(slot)
            return

        video_paths = processor.staged_video_paths(result)
        if not video_paths:
            logger.warning("No video files in staging slot after processing.")
            staging.cleanup_staging_slot(slot)
            return

        client = RadarrClient(
            base_url=settings.radarr.url, api_key=settings.radarr.api_key
        )
        await client.manual_import(video_paths, movie_id=movie_id)
        logger.info(
            "Radarr ManualImport triggered for %d file(s)", len(video_paths)
        )

    except Exception:
        logger.exception("Error processing Radarr release: %s", release_path)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.post("/webhook/sonarr")
async def webhook_sonarr(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    body = await request.body()
    _verify_secret(request, body)

    payload = SonarrWebhook.model_validate_json(body)
    logger.info("Sonarr webhook received: eventType=%s", payload.event_type)

    # Only act on completed downloads
    if payload.event_type == ArrEventType.TEST:
        return {"status": "ok", "message": "test event acknowledged"}

    if payload.event_type != ArrEventType.DOWNLOAD:
        return {"status": "ignored", "eventType": payload.event_type}

    # Resolve the release folder from the episode file path
    file_path_str = (
        payload.episode_file.path if payload.episode_file else None
    )
    release_path = _resolve_download_path(file_path_str)

    if not release_path:
        # Fall back to the series root if no file path is available
        if payload.series:
            release_path = Path(payload.series.path)
        else:
            logger.warning("Cannot determine release path from Sonarr webhook")
            return {"status": "error", "message": "no release path found"}

    release_name = payload.series.title if payload.series else release_path.name
    series_id = payload.series.id if payload.series else None

    background_tasks.add_task(
        _process_and_import_sonarr,
        release_path,
        release_name,
        series_id,
    )

    return {"status": "accepted", "path": str(release_path)}


@router.post("/webhook/radarr")
async def webhook_radarr(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    body = await request.body()
    _verify_secret(request, body)

    payload = RadarrWebhook.model_validate_json(body)
    logger.info("Radarr webhook received: eventType=%s", payload.event_type)

    if payload.event_type == ArrEventType.TEST:
        return {"status": "ok", "message": "test event acknowledged"}

    if payload.event_type != ArrEventType.DOWNLOAD:
        return {"status": "ignored", "eventType": payload.event_type}

    file_path_str = payload.movie_file.path if payload.movie_file else None
    release_path = _resolve_download_path(file_path_str)

    if not release_path:
        if payload.movie and payload.movie.file_path:
            release_path = Path(payload.movie.file_path)
        else:
            logger.warning("Cannot determine release path from Radarr webhook")
            return {"status": "error", "message": "no release path found"}

    release_name = payload.movie.title if payload.movie else release_path.name
    movie_id = payload.movie.id if payload.movie else None

    background_tasks.add_task(
        _process_and_import_radarr,
        release_path,
        release_name,
        movie_id,
    )

    return {"status": "accepted", "path": str(release_path)}
