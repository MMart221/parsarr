"""
Intake orchestrator.

handle_grab() is the entry point for both the Sonarr On Grab webhook path
and the manual magnet path.  It:

  1. Creates a job record.
  2. Polls qBittorrent until metadata (file list) is available.
  3. Runs classify_tree on the virtual file list.
  4. If standard: marks the job passthrough and returns — torrent is left
     in Sonarr's normal qB category/path completely untouched.
  5. If problematic:
     a. Reroutes the torrent (setLocation + setCategory) into the
        managed_download_dir before the download completes.
     b. Auto-maps to a Sonarr series.
     c. Waits for the download to complete.
     d. Marks the job ready_to_process.
     e. If hold=False, immediately fires placer.place_job() in the background.
        If hold=True, stops here and waits for user approval.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from .config import Settings, remap_sonarr_path
from .core.inspector import classify_tree
from .jobs import Job, JobState, JobStore
from .mapper import auto_map
from .qb_client import QBittorrentClient, QBittorrentError

logger = logging.getLogger(__name__)

# Strong references to fire-and-forget tasks so they aren't GC'd mid-execution.
_background_tasks: set = set()


async def handle_grab(
    download_id: str,
    release_title: str,
    settings: Settings,
    jobs_db: JobStore,
    qb: QBittorrentClient,
    sonarr,                 # SonarrClient — typed as Any to avoid circular import
    sonarr_series_id: Optional[int] = None,
    placement_mode: Optional[str] = None,
) -> Job:
    """
    Main intake coroutine.  Runs as a FastAPI BackgroundTask.

    Parameters
    ----------
    download_id:
        The torrent hash, as provided by Sonarr's On Grab ``downloadId`` field
        or derived from the qBittorrent response when adding a magnet manually.
    release_title:
        Human-readable title used as the seed for auto-mapping.
    sonarr_series_id:
        Sonarr series ID from the On Grab payload.  None for manual magnets.
    placement_mode:
        Override the global placement_mode from settings for this job.
    """
    effective_placement = placement_mode or settings.placement_mode
    torrent_hash = download_id.lower()

    # Reuse an existing job if one was already created (e.g. by /api/add),
    # otherwise create a new one.
    job = await jobs_db.get_job_by_hash(torrent_hash)
    if job is None:
        job = await jobs_db.create_job(
            hash=torrent_hash,
            title=release_title,
            sonarr_series_id=sonarr_series_id,
            placement_mode=effective_placement,
            state=JobState.SUBMITTED,
        )
        logger.info(
            "Job %d created: hash=%s title=%r", job.id, torrent_hash[:8], release_title
        )
    else:
        logger.info(
            "Job %d (existing): hash=%s title=%r", job.id, torrent_hash[:8], release_title
        )

    # ------------------------------------------------------------------
    # Phase 1: wait for qBittorrent metadata
    # ------------------------------------------------------------------
    await jobs_db.update_job_state(job.id, JobState.METADATA_PENDING)
    try:
        file_paths = await qb.wait_for_metadata(torrent_hash, timeout=120)
    except QBittorrentError as exc:
        logger.error("Job %d: metadata timeout: %s", job.id, exc)
        await jobs_db.update_job_state(job.id, JobState.FAILED, error=str(exc))
        return await jobs_db.get_job(job.id)  # type: ignore[return-value]

    await jobs_db.update_file_tree(job.id, file_paths)
    await jobs_db.update_job_state(job.id, JobState.METADATA_READY)
    logger.info("Job %d: metadata ready, %d file(s)", job.id, len(file_paths))

    # ------------------------------------------------------------------
    # Phase 2: classify
    # ------------------------------------------------------------------
    profile = classify_tree(file_paths, extra_patterns=settings.extra_patterns)

    if profile.is_standard:
        logger.info(
            "Job %d: release is standard — passthrough, no action taken.", job.id
        )
        await jobs_db.update_job_state(job.id, JobState.PASSTHROUGH)
        return await jobs_db.get_job(job.id)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Phase 3: reroute problematic torrent before completion
    # ------------------------------------------------------------------
    managed_dir = str(settings.managed_download_dir)
    try:
        await qb.set_location(torrent_hash, managed_dir)
        await qb.set_category(torrent_hash, settings.parsarr_category)
    except Exception as exc:
        logger.error("Job %d: reroute failed: %s", job.id, exc)
        await jobs_db.update_job_state(job.id, JobState.FAILED, error=f"reroute: {exc}")
        return await jobs_db.get_job(job.id)  # type: ignore[return-value]

    await jobs_db.update_job_state(job.id, JobState.REROUTED_TO_STAGING)
    logger.info("Job %d: rerouted to managed_download_dir", job.id)

    # ------------------------------------------------------------------
    # Phase 4: auto-map to a Sonarr series
    # ------------------------------------------------------------------
    mapping_result = None
    if sonarr_series_id:
        # Sonarr-originated: we already know the series; fetch its path directly
        try:
            series = await sonarr.get_series_by_id(sonarr_series_id)
            target_path = remap_sonarr_path(series.get("path", ""), settings.path_maps)
            mapping_result_dict = {
                "series_id": sonarr_series_id,
                "series_title": series.get("title", release_title),
                "target_path": target_path,
                "seasons_detected": profile.seasons_found and sorted(profile.seasons_found) or [],
                "confidence": 1.0,
                "source": "sonarr_grab",
            }
            await jobs_db.update_job_mapping(job.id, mapping_result_dict, target_path)
            await jobs_db.update_job_state(job.id, JobState.AUTO_MAPPED)
            logger.info(
                "Job %d: mapped via Sonarr series %d → %r", job.id, sonarr_series_id, target_path
            )
        except Exception as exc:
            logger.warning("Job %d: could not fetch Sonarr series path: %s", job.id, exc)
            # Fall through to title-based search below
            sonarr_series_id = None

    if not sonarr_series_id:
        mapping_result = await auto_map(release_title, file_paths, sonarr)
        if mapping_result:
            mapping_dict = {
                "series_id": mapping_result.series_id,
                "series_title": mapping_result.series_title,
                "target_path": mapping_result.target_path,
                "seasons_detected": mapping_result.seasons_detected,
                "confidence": mapping_result.confidence,
                "source": "auto_map",
            }
            remapped_path = remap_sonarr_path(mapping_result.target_path, settings.path_maps)
            mapping_dict["target_path"] = remapped_path
            await jobs_db.update_job_mapping(job.id, mapping_dict, remapped_path)
            await jobs_db.update_job_state(job.id, JobState.AUTO_MAPPED)
            logger.info(
                "Job %d: auto-mapped to %r (confidence=%.2f)",
                job.id,
                mapping_result.series_title,
                mapping_result.confidence,
            )
        else:
            await jobs_db.update_job_state(job.id, JobState.AWAITING_MANUAL_MAPPING)
            logger.info("Job %d: auto-map failed — awaiting manual mapping", job.id)

    # ------------------------------------------------------------------
    # Phase 5: wait for download to complete
    # ------------------------------------------------------------------
    await jobs_db.update_job_state(job.id, JobState.DOWNLOADING)
    try:
        await qb.wait_for_completion(torrent_hash, timeout=86400)
    except QBittorrentError as exc:
        logger.error("Job %d: completion timeout: %s", job.id, exc)
        await jobs_db.update_job_state(job.id, JobState.FAILED, error=str(exc))
        return await jobs_db.get_job(job.id)  # type: ignore[return-value]

    await jobs_db.update_job_state(job.id, JobState.READY_TO_PROCESS)
    logger.info("Job %d: download complete, ready to process", job.id)

    # ------------------------------------------------------------------
    # Phase 6: place (automatic unless hold=True)
    # ------------------------------------------------------------------
    current = await jobs_db.get_job(job.id)
    if current and current.hold:
        logger.info(
            "Job %d: hold=True — pausing before placement, waiting for user approval",
            job.id,
        )
        return current

    # Kick off placement as a new task so this function can return promptly.
    # Store a reference so the task isn't garbage-collected before it runs.
    task = asyncio.create_task(_run_placement(job.id, torrent_hash, jobs_db, settings, sonarr))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return await jobs_db.get_job(job.id)  # type: ignore[return-value]


async def _run_placement(
    job_id: int,
    torrent_hash: str,
    jobs_db: JobStore,
    settings: Settings,
    sonarr,
) -> None:
    """
    Resolve the final target path, call placer.place_job, and update job state.
    Import placer here to avoid circular imports at module load.
    """
    from .placer import place_job

    job = await jobs_db.get_job(job_id)
    if not job:
        logger.error("_run_placement: job %d not found", job_id)
        return

    if not job.target_path:
        logger.error(
            "Job %d: no target_path set — cannot place without mapping", job_id
        )
        await jobs_db.update_job_state(
            job_id, JobState.FAILED, error="no target_path — manual mapping required"
        )
        return

    try:
        await place_job(job, settings, sonarr, jobs_db)
    except Exception as exc:
        logger.exception("Job %d: placement failed: %s", job_id, exc)
        await jobs_db.update_job_state(job_id, JobState.FAILED, error=str(exc))
