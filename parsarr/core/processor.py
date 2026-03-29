"""
Execute file operations described by a ReleaseProfile.

All operations are optionally dry-run: pass dry_run=True and no files will be
moved or created — instead, each planned action is logged and returned as a
list of human-readable strings.
"""
from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .inspector import FileInfo, ReleaseProfile

logger = logging.getLogger(__name__)

_SEASON_RE = re.compile(r"[Ss](\d{2})", re.IGNORECASE)

EXTRAS_SUBDIR = "_extras"


@dataclass
class ProcessResult:
    source_root: Path
    staging_root: Path
    actions: list[str] = field(default_factory=list)
    moved_files: list[Path] = field(default_factory=list)
    skipped: bool = False
    dry_run: bool = False

    def add_action(self, msg: str) -> None:
        self.actions.append(msg)
        logger.info("[%s] %s", "DRY-RUN" if self.dry_run else "ACTION", msg)


def _season_dir_name(season: int) -> str:
    return f"Season {season:02d}"


def _find_companion(video: FileInfo, all_files: list[FileInfo]) -> list[FileInfo]:
    """
    Return companion files (subs, nfo, artwork) whose stem exactly matches
    *video*.  Folder-level companions (e.g. tvshow.nfo, folder.jpg) whose stem
    does not match any video stem are handled by a separate pass in process().
    """
    stem = video.path.stem.lower()
    companions = []
    for f in all_files:
        if f.is_companion and not f.is_extra and f.path != video.path:
            if f.path.stem.lower() == stem:
                companions.append(f)
    return companions


def _extra_dest(f: FileInfo, release_root: Path, extras_dir: Path) -> Path:
    """
    Compute the destination path for a file going into _extras/, preserving
    the file's original subfolder structure relative to the release root.

    Examples:
      root/Extras/Making Of/file.mkv  →  _extras/Extras/Making Of/file.mkv
      root/file.mkv                   →  _extras/file.mkv

    This avoids flat-folder collisions when two files share the same name
    but live in different source subdirectories.
    """
    try:
        rel_parent = f.path.parent.relative_to(release_root)
    except ValueError:
        rel_parent = Path()
    return extras_dir / rel_parent / f.path.name


def _move(src: Path, dst: Path, dry_run: bool) -> None:
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        logger.debug("Destination already exists, skipping move: %s", dst)
        return
    shutil.move(str(src), str(dst))


def process(
    profile: ReleaseProfile,
    staging_root: Path,
    dry_run: bool = False,
) -> ProcessResult:
    """
    Apply the operations described by *profile*, writing output to *staging_root*.

    Returns a ProcessResult with every action taken (or planned, in dry-run mode).
    """
    result = ProcessResult(
        source_root=profile.root,
        staging_root=staging_root,
        dry_run=dry_run,
    )

    if profile.is_standard:
        result.skipped = True
        result.add_action(f"SKIP — release is already standard: {profile.root.name}")
        return result

    # Inspector is the single source of truth for classification.
    extra_files = list(profile.extra_files)
    video_files = list(profile.episode_files)
    is_show = len(profile.seasons_found) > 0

    # --- Step 1: determine per-video destination paths ---
    moves: list[tuple[FileInfo, Path]] = []

    for vf in video_files:
        season_match = _SEASON_RE.search(vf.path.name)
        if season_match:
            season_num = int(season_match.group(1))
            dest_dir = staging_root / _season_dir_name(season_num)
        else:
            # Movie (no season context) — drop flat into staging root
            dest_dir = staging_root

        dest = dest_dir / vf.path.name
        moves.append((vf, dest))

    # --- Step 2: companion files ---
    companion_moves: list[tuple[FileInfo, Path]] = []
    assigned_companions: set[Path] = set()

    for vf, vf_dest in moves:
        companions = _find_companion(vf, profile.files)
        for comp in companions:
            if comp.path in assigned_companions:
                continue
            assigned_companions.add(comp.path)
            comp_dest = vf_dest.parent / comp.path.name
            companion_moves.append((comp, comp_dest))

    extras_dir = staging_root / EXTRAS_SUBDIR

    # --- Step 3: extras — preserve original subdir structure to avoid collisions ---
    extra_moves: list[tuple[FileInfo, Path]] = []
    for ef in extra_files:
        extra_moves.append((ef, _extra_dest(ef, profile.root, extras_dir)))

    # --- Step 4: companion files not matched to any main episode ---
    # A true sidecar (subtitle, NFO, artwork) belongs next to its episode.
    # A companion with no matching episode is an extra asset:
    #   - In a show context: route to _extras/ (preserving subdir structure)
    #   - In a movie context: keep at staging root (may be legit movie artwork)
    episode_stems = {vf.path.stem.lower() for vf in video_files}
    for cf in profile.companion_files:
        if cf.path in assigned_companions:
            continue
        assigned_companions.add(cf.path)
        if is_show:
            extra_moves.append((cf, _extra_dest(cf, profile.root, extras_dir)))
        else:
            companion_moves.append((cf, staging_root / cf.path.name))

    # --- Execute ---
    if not dry_run:
        staging_root.mkdir(parents=True, exist_ok=True)

    for vf, dest in moves:
        result.add_action(f"MOVE video  {vf.path} -> {dest}")
        _move(vf.path, dest, dry_run)
        if not dry_run:
            result.moved_files.append(dest)

    for cf, dest in companion_moves:
        result.add_action(f"MOVE companion {cf.path} -> {dest}")
        _move(cf.path, dest, dry_run)
        if not dry_run:
            result.moved_files.append(dest)

    for ef, dest in extra_moves:
        result.add_action(f"MOVE extra  {ef.path} -> {dest}")
        _move(ef.path, dest, dry_run)

    if not video_files:
        result.add_action("WARNING: no non-extra video files found to process")

    return result


def staged_video_paths(result: ProcessResult) -> list[Path]:
    """Return only the video file paths from a ProcessResult for import."""
    from .inspector import VIDEO_EXTENSIONS

    return [p for p in result.moved_files if p.suffix.lower() in VIDEO_EXTENSIONS]
