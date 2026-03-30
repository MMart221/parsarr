"""
Parsarr v2 API and webhook routes.

Webhook:
  POST /webhook/sonarr/grab   — Sonarr On Grab intake

Job management:
  GET    /api/jobs            — list all jobs
  GET    /api/jobs/{id}       — job detail (file tree, mapping, state)
  PATCH  /api/jobs/{id}/mapping — update mapping (series, target path)
  PATCH  /api/jobs/{id}/hold  — set or clear the hold flag
  POST   /api/jobs/{id}/approve — resume a held job (no-op if hold=False)

Manual intake:
  POST   /api/add             — add magnet URI, fire intake

Sonarr proxy:
  GET    /api/series          — proxy Sonarr series list for mapping UI

System:
  GET    /health              — liveness probe
  POST   /settings            — persist config values
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

import parsarr.config as _cfg_module
from ..jobs import JobState, JobStore
from ..webhook.schemas import ArrEventType, SonarrGrabWebhook

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level job store — initialised by main.py after settings are loaded.
_jobs_db: Optional[JobStore] = None


def init_job_store(db: JobStore) -> None:
    global _jobs_db
    _jobs_db = db


def _get_db() -> JobStore:
    if _jobs_db is None:
        raise RuntimeError("JobStore not initialised — call init_job_store() first")
    return _jobs_db


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "2"}


# ---------------------------------------------------------------------------
# Sonarr On Grab webhook
# ---------------------------------------------------------------------------

@router.post("/webhook/sonarr/grab")
async def webhook_sonarr_grab(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """
    Receives Sonarr's On Grab event.

    Sonarr fires this the moment it sends a release to qBittorrent,
    before any data has been downloaded.  The payload contains the
    torrent hash (``downloadId``) and series context.
    """
    body = await request.body()
    _verify_secret(request)

    payload = SonarrGrabWebhook.model_validate_json(body)
    logger.info(
        "On Grab received: eventType=%s series=%s downloadId=%s",
        payload.event_type,
        payload.series.title if payload.series else "?",
        (payload.download_id or "")[:8],
    )

    if payload.event_type == ArrEventType.TEST:
        return {"status": "ok", "message": "test event acknowledged"}

    if payload.event_type != ArrEventType.GRAB:
        return {"status": "ignored", "eventType": payload.event_type}

    if not payload.download_id:
        raise HTTPException(status_code=422, detail="downloadId is required")

    background_tasks.add_task(
        _fire_intake,
        download_id=payload.download_id,
        release_title=payload.release.title or (payload.series.title if payload.series else ""),
        sonarr_series_id=payload.series.id if payload.series else None,
    )

    return {"status": "accepted", "hash": payload.download_id[:8]}


async def _fire_intake(
    download_id: str,
    release_title: str,
    sonarr_series_id: Optional[int],
) -> None:
    from ..arr.sonarr import SonarrClient
    from ..intake import handle_grab
    from ..qb_client import QBittorrentClient

    try:
        s = _cfg_module.settings
        qb = QBittorrentClient(
            url=s.qbittorrent.url,
            username=s.qbittorrent.username,
            password=s.qbittorrent.password,
        )
        sonarr = SonarrClient(base_url=s.sonarr.url, api_key=s.sonarr.api_key)
        db = _get_db()
        await handle_grab(
            download_id=download_id,
            release_title=release_title,
            settings=s,
            jobs_db=db,
            qb=qb,
            sonarr=sonarr,
            sonarr_series_id=sonarr_series_id,
        )
    except Exception:
        logger.exception("intake error for hash=%s", download_id[:8])


# ---------------------------------------------------------------------------
# Job endpoints
# ---------------------------------------------------------------------------

@router.get("/api/jobs")
async def list_jobs(limit: int = 100, offset: int = 0) -> list[dict]:
    db = _get_db()
    jobs = await db.list_jobs(limit=limit, offset=offset)
    return [j.as_dict() for j in jobs]


@router.get("/api/jobs/{job_id}")
async def get_job(job_id: int) -> dict:
    db = _get_db()
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.as_dict()


class MappingUpdate(BaseModel):
    series_id: Optional[int] = None
    series_title: Optional[str] = None
    target_path: Optional[str] = None
    seasons: Optional[list[int]] = None


@router.patch("/api/jobs/{job_id}/mapping")
async def update_mapping(job_id: int, body: MappingUpdate) -> dict:
    db = _get_db()
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    existing = job.mapping or {}
    updated = {**existing}
    if body.series_id is not None:
        updated["series_id"] = body.series_id
    if body.series_title is not None:
        updated["series_title"] = body.series_title
    if body.seasons is not None:
        updated["seasons_detected"] = body.seasons

    target = body.target_path or job.target_path

    # Update sonarr_series_id in the job row if provided
    if body.series_id:
        with db._connect() as conn:
            conn.execute(
                "UPDATE jobs SET sonarr_series_id=? WHERE id=?",
                (body.series_id, job_id),
            )

    result = await db.update_job_mapping(job_id, updated, target)
    if result:
        await db.update_job_state(job_id, JobState.AUTO_MAPPED)
    return result.as_dict() if result else {}


class HoldUpdate(BaseModel):
    hold: bool


@router.patch("/api/jobs/{job_id}/hold")
async def set_hold(job_id: int, body: HoldUpdate) -> dict:
    db = _get_db()
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    result = await db.set_hold(job_id, body.hold)
    return result.as_dict() if result else {}


@router.post("/api/jobs/{job_id}/approve")
async def approve_job(job_id: int, background_tasks: BackgroundTasks) -> dict:
    """
    Resume a job that is paused on hold.

    This endpoint only does something when job.hold == True.
    If hold is False the job is already running automatically and this
    endpoint returns 409 Conflict.
    """
    db = _get_db()
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not job.hold:
        raise HTTPException(
            status_code=409,
            detail="Job is not on hold — it is running automatically and does not require approval",
        )

    if job.state not in (JobState.READY_TO_PROCESS, JobState.AWAITING_MANUAL_MAPPING, JobState.AUTO_MAPPED):
        raise HTTPException(
            status_code=409,
            detail=f"Job cannot be approved in state {job.state!r}",
        )

    if not job.target_path:
        raise HTTPException(
            status_code=422,
            detail="Job has no target_path — update mapping before approving",
        )

    # Clear hold and fire placement
    await db.set_hold(job_id, False)
    background_tasks.add_task(_fire_placement, job_id)
    return {"status": "approved", "job_id": job_id}


async def _fire_placement(job_id: int) -> None:
    from ..arr.sonarr import SonarrClient
    from ..placer import place_job

    db = _get_db()
    try:
        s = _cfg_module.settings
        sonarr = SonarrClient(base_url=s.sonarr.url, api_key=s.sonarr.api_key)
        job = db.get_job(job_id)
        if not job:
            return
        await place_job(job, s, sonarr, db)
    except Exception:
        logger.exception("Placement failed for job %d", job_id)
        await db.update_job_state(job_id, JobState.FAILED, error="placement error — check logs")


# ---------------------------------------------------------------------------
# Manual magnet intake
# ---------------------------------------------------------------------------

class AddRequest(BaseModel):
    magnet: str
    title: Optional[str] = None
    series_id: Optional[int] = None
    season: Optional[int] = None
    media_type: str = "tv"          # "tv" or "anime"
    hold: bool = False


@router.post("/api/add")
async def add_magnet(body: AddRequest, background_tasks: BackgroundTasks) -> dict:
    """
    Accept a magnet URI from the UI and fire the intake pipeline.

    The torrent is added to qBittorrent under the parsarr-managed category.
    The hash is extracted from the magnet URI and used to track the job.
    """
    import re

    hash_match = re.search(r"btih:([a-fA-F0-9]{40})", body.magnet, re.I)
    if not hash_match:
        raise HTTPException(status_code=422, detail="Could not extract torrent hash from magnet URI")

    torrent_hash = hash_match.group(1).lower()
    title = body.title or torrent_hash[:12]

    # Add to qBittorrent immediately; intake will poll for metadata
    from ..qb_client import QBittorrentClient
    s = _cfg_module.settings
    qb = QBittorrentClient(
        url=s.qbittorrent.url,
        username=s.qbittorrent.username,
        password=s.qbittorrent.password,
    )
    try:
        await qb.add_magnet(
            body.magnet,
            category=s.parsarr_category,
            save_path=str(s.managed_download_dir),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"qBittorrent error: {exc}")

    # Create job with optional hold flag
    db = _get_db()
    job = await db.create_job(
        hash=torrent_hash,
        title=title,
        sonarr_series_id=body.series_id,
        placement_mode=s.placement_mode,
        state=JobState.SUBMITTED,
    )
    if body.hold:
        await db.set_hold(job.id, True)

    background_tasks.add_task(
        _fire_intake,
        download_id=torrent_hash,
        release_title=title,
        sonarr_series_id=body.series_id,
    )

    return {"status": "accepted", "job_id": job.id, "hash": torrent_hash[:8]}


# ---------------------------------------------------------------------------
# Sonarr series proxy
# ---------------------------------------------------------------------------

@router.get("/api/series")
async def get_series(q: Optional[str] = None) -> list[dict]:
    """
    Return the Sonarr series list for use in the mapping UI.

    Pass ``?q=query`` to search; omit for the full library list.
    """
    from ..arr.sonarr import SonarrClient
    s = _cfg_module.settings
    if not s.sonarr.url or not s.sonarr.api_key:
        return []
    client = SonarrClient(base_url=s.sonarr.url, api_key=s.sonarr.api_key)
    try:
        if q:
            results = await client.search_series(q)
        else:
            results = await client.get_series()
        return [
            {"id": r.get("id"), "title": r.get("title"), "path": r.get("path"), "year": r.get("year")}
            for r in results
        ]
    except Exception as exc:
        logger.warning("Sonarr series proxy error: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class SettingsUpdate(BaseModel):
    sonarr_url: Optional[str] = None
    sonarr_api_key: Optional[str] = None
    qb_url: Optional[str] = None
    qb_username: Optional[str] = None
    qb_password: Optional[str] = None
    tv_root: Optional[str] = None
    anime_root: Optional[str] = None
    placement_mode: Optional[str] = None
    parsarr_category: Optional[str] = None


@router.post("/settings")
async def save_settings(body: SettingsUpdate) -> dict:
    """
    Update runtime settings.  Changes are applied in-memory immediately.
    To persist, write to config.yaml manually (or mount a writable config).
    """
    s = _cfg_module.settings
    if body.sonarr_url is not None:
        s.sonarr.url = body.sonarr_url
    if body.sonarr_api_key is not None:
        s.sonarr.api_key = body.sonarr_api_key
    if body.qb_url is not None:
        s.qbittorrent.url = body.qb_url
    if body.qb_username is not None:
        s.qbittorrent.username = body.qb_username
    if body.qb_password is not None:
        s.qbittorrent.password = body.qb_password
    if body.tv_root is not None:
        from pathlib import Path
        s.media_roots.tv = Path(body.tv_root)
    if body.anime_root is not None:
        from pathlib import Path
        s.media_roots.anime = Path(body.anime_root)
    if body.placement_mode is not None:
        if body.placement_mode not in ("move", "copy", "hardlink"):
            raise HTTPException(status_code=422, detail="placement_mode must be move, copy, or hardlink")
        s.placement_mode = body.placement_mode
    if body.parsarr_category is not None:
        s.parsarr_category = body.parsarr_category

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verify_secret(request: Request) -> None:
    s = _cfg_module.settings
    if not s.webhook_secret:
        return
    provided = request.headers.get("X-Parsarr-Secret", "")
    import hmac
    if not hmac.compare_digest(provided, s.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")
