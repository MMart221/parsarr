"""
Manage the staging directory lifecycle.

A staging slot is a subdirectory of the global staging_dir, named after the
release.  It is created before processing starts and can be cleaned up once
Sonarr/Radarr have completed the import.
"""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


def make_staging_slot(staging_dir: Path, release_name: str) -> Path:
    """
    Create and return a unique subdirectory under *staging_dir* for this release.

    A short UUID suffix is appended to avoid collisions when the same release
    name is processed more than once concurrently.
    """
    staging_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize(release_name)
    slot = staging_dir / f"{safe_name}__{uuid.uuid4().hex[:8]}"
    slot.mkdir(parents=True, exist_ok=True)
    logger.debug("Created staging slot: %s", slot)
    return slot


def cleanup_staging_slot(slot: Path) -> None:
    """
    Remove a staging slot directory and all of its contents.

    Called after a successful import so that the staging area stays tidy.
    Silently ignores slots that have already been removed.
    """
    if slot.exists():
        shutil.rmtree(slot)
        logger.info("Cleaned up staging slot: %s", slot)
    else:
        logger.debug("Staging slot already gone: %s", slot)


def list_staging_slots(staging_dir: Path) -> list[Path]:
    """Return all slot directories currently present in *staging_dir*."""
    if not staging_dir.exists():
        return []
    return sorted(p for p in staging_dir.iterdir() if p.is_dir())


def _sanitize(name: str) -> str:
    """Replace filesystem-unsafe characters with underscores."""
    safe = ""
    for ch in name:
        if ch.isalnum() or ch in ("-", "_", ".", " "):
            safe += ch
        else:
            safe += "_"
    return safe.strip().replace(" ", "_")
