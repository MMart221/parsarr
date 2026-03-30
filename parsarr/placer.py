"""
Placer — post-processing and final library placement.

place_job() is called automatically when hold=False, or manually by the
approve endpoint when hold=True and the user clicks Approve.

Flow:
  1. Determine the raw download directory for this torrent.
  2. Run inspector.inspect() on it to get a ReleaseProfile.
  3. Call processor.process() to reorganize into a staging work slot.
  4. Move/copy/hardlink each Season NN/ directory into the final library path.
  5. Trigger Sonarr RescanSeries.
  6. Update job state throughout.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from .config import Settings
from .core import inspector, processor, staging
from .jobs import Job, JobState, JobStore

logger = logging.getLogger(__name__)


async def place_job(
    job: Job,
    settings: Settings,
    sonarr,          # SonarrClient — typed as Any to avoid circular import
    jobs_db: JobStore,
) -> Path:
    """
    Reorganize a completed download and place it into the library.

    Returns the final placement path.
    Raises on error (caller should catch and update job state to FAILED).
    """
    if not job.target_path:
        raise ValueError(f"Job {job.id} has no target_path — mapping required before placement")

    target = Path(job.target_path)

    # ------------------------------------------------------------------
    # Step 1: locate the raw files on disk
    # ------------------------------------------------------------------
    # qBittorrent was redirected to managed_download_dir; the torrent's root
    # folder lives there under the release title (or torrent name).
    # We scan the managed_download_dir for a directory whose name contains the
    # torrent hash or matches the job title.
    raw_dir = _find_raw_dir(job, settings)
    if raw_dir is None or not raw_dir.exists():
        raise FileNotFoundError(
            f"Job {job.id}: raw download directory not found under {settings.managed_download_dir}"
        )

    logger.info("Job %d: raw dir = %s", job.id, raw_dir)

    # ------------------------------------------------------------------
    # Step 2: inspect
    # ------------------------------------------------------------------
    await jobs_db.update_job_state(job.id, JobState.PROCESSING)
    profile = inspector.inspect(raw_dir, extra_patterns=settings.extra_patterns)
    logger.info("Job %d: profile = %s", job.id, profile.summary())

    # ------------------------------------------------------------------
    # Step 3: process into a staging work slot
    # ------------------------------------------------------------------
    work_slot = staging.make_staging_slot(settings.staging_dir, job.title)
    result = processor.process(profile, work_slot)

    if result.skipped or not result.moved_files:
        staging.cleanup_staging_slot(work_slot)
        raise RuntimeError(f"Job {job.id}: processor produced no output")

    # ------------------------------------------------------------------
    # Step 4: place files into the final library path
    # ------------------------------------------------------------------
    target.mkdir(parents=True, exist_ok=True)
    mode = job.placement_mode or settings.placement_mode

    _place_slot(work_slot, target, mode)
    logger.info("Job %d: placed into %s (mode=%s)", job.id, target, mode)
    await jobs_db.update_job_state(job.id, JobState.PLACED)
    await jobs_db.set_target_path(job.id, str(target))

    # Clean up the work slot after successful placement
    try:
        staging.cleanup_staging_slot(work_slot)
    except Exception as exc:
        logger.warning("Job %d: could not clean up work slot: %s", job.id, exc)

    # ------------------------------------------------------------------
    # Step 5: trigger Sonarr rescan
    # ------------------------------------------------------------------
    if job.sonarr_series_id:
        try:
            await sonarr.rescan_series(job.sonarr_series_id)
            await jobs_db.update_job_state(job.id, JobState.RESCAN_TRIGGERED)
            logger.info(
                "Job %d: RescanSeries triggered for series_id=%d",
                job.id,
                job.sonarr_series_id,
            )
        except Exception as exc:
            logger.warning(
                "Job %d: RescanSeries failed (files are placed, but rescan did not fire): %s",
                job.id,
                exc,
            )
    else:
        logger.info(
            "Job %d: no sonarr_series_id — skipping RescanSeries (manual rescan may be needed)",
            job.id,
        )

    await jobs_db.update_job_state(job.id, JobState.COMPLETED)
    logger.info("Job %d: completed → %s", job.id, target)
    return target


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_raw_dir(job: Job, settings: Settings) -> Path | None:
    """
    Locate the torrent's download directory inside managed_download_dir.

    qBittorrent places the torrent content under its own internal name, which
    we don't reliably know.  We scan one level deep and return the first
    directory whose name is a case-insensitive substring match for the job
    title, or fall back to the most recently modified entry.
    """
    base = settings.managed_download_dir
    if not base.exists():
        return None

    candidates = [p for p in base.iterdir() if p.is_dir()]
    if not candidates:
        return None

    title_lower = job.title.lower()
    for c in candidates:
        if title_lower[:20] in c.name.lower() or c.name.lower() in title_lower:
            return c

    # Fallback: most recently modified directory
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _place_slot(work_slot: Path, target: Path, mode: str) -> None:
    """
    Transfer all contents of work_slot into target using the specified mode.

    Season NN/ directories and loose files are moved/copied/hardlinked
    directly into target/.
    """
    for item in work_slot.iterdir():
        dest = target / item.name
        if mode == "move":
            shutil.move(str(item), str(dest))
        elif mode == "copy":
            if item.is_dir():
                shutil.copytree(str(item), str(dest), dirs_exist_ok=True)
            else:
                shutil.copy2(str(item), str(dest))
        elif mode == "hardlink":
            if item.is_dir():
                _hardlink_tree(item, dest)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.link(item, dest)
        else:
            raise ValueError(f"Unknown placement_mode: {mode!r}")


def _hardlink_tree(src: Path, dst: Path) -> None:
    """Recursively hardlink a directory tree."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        if item.is_file():
            rel = item.relative_to(src)
            target_file = dst / rel
            target_file.parent.mkdir(parents=True, exist_ok=True)
            os.link(item, target_file)
