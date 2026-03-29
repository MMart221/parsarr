"""
Inspect a release folder and classify what processing (if any) is needed.

Classification result is a ReleaseProfile, which the Processor uses to decide
which operations to perform.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Extensions considered to be playable video files.
VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mkv", ".mp4", ".avi", ".m4v", ".ts", ".wmv", ".mov", ".flv", ".webm"}
)

# Extensions that travel alongside a video as companion files.
COMPANION_EXTENSIONS: frozenset[str] = frozenset(
    {".srt", ".ass", ".ssa", ".sub", ".idx", ".nfo", ".jpg", ".jpeg", ".png", ".nfo"}
)

# Regex that matches a standard Sonarr season/episode token anywhere in the name.
_SEASON_RE = re.compile(r"[Ss](\d{2})", re.IGNORECASE)
_EPISODE_RE = re.compile(r"[Ss]\d{2}[Ee]\d{2}", re.IGNORECASE)

# Default extra patterns — augmented from config at runtime.
# Matched case-insensitively as substrings of the full filename.
_DEFAULT_EXTRA_PATTERNS: list[str] = [
    # Generic quality markers
    "sample",
    "trailer",
    "teaser",
    # Standard Plex/Jellyfin extra folder names
    "featurette",
    "behind-the-scenes",
    "behind the scenes",
    "deleted-scene",
    "deleted scene",
    "interview",
    "scene",
    "short",
    "bonus",
    # Commentary tracks
    "commentary",
    # Promotional / convention footage
    "comic-con",
    "comic con",
    "san diego",
    "panel",
    "press",
    # Production documentaries
    "making of",
    "making-of",
    "the making",
    "inside the",
    "behind the",
    "on location",
    "production",
    # Raw production materials
    "animatic",
    "pencil test",
    "pencil-test",
    "storyboard",
    "concept art",
    "menu art",
    "promo",
    # Misc bonus content
    "graphic novel",
    "music video",
    "bloopers",
    "outtakes",
    "gag reel",
    "web exclusive",
]


@dataclass
class FileInfo:
    path: Path
    is_video: bool
    is_companion: bool
    season: Optional[int]  # None = no season token detected (e.g. movie / extra)
    is_extra: bool
    depth: int  # folder depth relative to the release root (0 = directly inside)


@dataclass
class ReleaseProfile:
    root: Path

    # All files discovered under the root
    files: list[FileInfo] = field(default_factory=list)

    # Derived flags used by the Processor
    is_standard: bool = False
    is_multi_season: bool = False
    needs_flatten: bool = False
    has_extras: bool = False
    seasons_found: set[int] = field(default_factory=set)

    @property
    def video_files(self) -> list[FileInfo]:
        """All video files, including extras."""
        return [f for f in self.files if f.is_video]

    @property
    def episode_files(self) -> list[FileInfo]:
        """Main episode/movie files only — excludes extras."""
        return [f for f in self.files if f.is_video and not f.is_extra]

    @property
    def extra_files(self) -> list[FileInfo]:
        """All files classified as extras (videos and companions)."""
        return [f for f in self.files if f.is_extra]

    @property
    def companion_files(self) -> list[FileInfo]:
        """Companion files (subs, nfo, artwork) matched to main episodes."""
        return [f for f in self.files if f.is_companion and not f.is_extra]

    def summary(self) -> str:
        flags = []
        if self.is_standard:
            flags.append("standard")
        if self.is_multi_season:
            flags.append("multi-season")
        if self.needs_flatten:
            flags.append("needs-flatten")
        if self.has_extras:
            flags.append("has-extras")
        seasons = sorted(self.seasons_found)
        return (
            f"ReleaseProfile({self.root.name!r}, "
            f"flags=[{', '.join(flags)}], "
            f"seasons={seasons}, "
            f"episodes={len(self.episode_files)}, "
            f"extras={len(self.extra_files)})"
        )


def _is_extra(name_lower: str, extra_patterns: list[str]) -> bool:
    for pattern in extra_patterns:
        if pattern in name_lower:
            return True
    return False


def _scan_files(root: Path, extra_patterns: list[str]) -> list[FileInfo]:
    infos: list[FileInfo] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        depth = len(path.relative_to(root).parts) - 1
        name_lower = path.name.lower()
        suffix = path.suffix.lower()
        is_video = suffix in VIDEO_EXTENSIONS
        is_companion = suffix in COMPANION_EXTENSIONS
        season_match = _SEASON_RE.search(path.name)
        season = int(season_match.group(1)) if season_match else None
        extra = _is_extra(name_lower, extra_patterns)
        infos.append(
            FileInfo(
                path=path,
                is_video=is_video,
                is_companion=is_companion,
                season=season,
                is_extra=extra,
                depth=depth,
            )
        )
    return infos


def inspect(
    root: Path,
    extra_patterns: Optional[list[str]] = None,
) -> ReleaseProfile:
    """
    Scan *root* and return a fully populated ReleaseProfile.

    Args:
        root: Path to the release folder (or a single file's parent).
        extra_patterns: Lowercase strings whose presence in a filename marks it
            as an extra.  Defaults to the built-in list.
    """
    if extra_patterns is None:
        extra_patterns = _DEFAULT_EXTRA_PATTERNS

    if not root.exists():
        raise FileNotFoundError(f"Release root does not exist: {root}")

    if root.is_file():
        root = root.parent

    profile = ReleaseProfile(root=root)
    profile.files = _scan_files(root, extra_patterns)

    if not profile.video_files:
        logger.warning("No video files found under %s", root)
        profile.is_standard = True
        return profile

    # --- Pass 1: season detection (using only pattern-classified extras) ---
    seasons: set[int] = set()
    for vf in profile.video_files:
        if vf.season is not None and not vf.is_extra:
            seasons.add(vf.season)
    profile.seasons_found = seasons

    # --- Pass 2: promote seasonless videos to extras ---
    # In a show release any video with no SxxExx token is bonus/extra content,
    # regardless of filename.  Mutating is_extra here means the ReleaseProfile
    # is the single source of truth — the processor never needs to re-classify.
    if seasons:
        for f in profile.files:
            if f.is_video and not f.is_extra and f.season is None:
                f.is_extra = True
                logger.debug(
                    "Promoted to extra (no season token in show): %s", f.path.name
                )

    # --- Derived flags (computed after all is_extra mutations) ---
    episode_files = profile.episode_files  # non-extra videos

    profile.has_extras = len(episode_files) < len(profile.video_files)

    # "Nested" means any main-episode video is more than 1 subfolder deep.
    max_episode_depth = max((vf.depth for vf in episode_files), default=0)
    profile.needs_flatten = max_episode_depth > 1

    profile.is_multi_season = len(seasons) > 1

    # Standard: single season (or none), flat structure, no extras.
    profile.is_standard = (
        not profile.is_multi_season
        and not profile.needs_flatten
        and not profile.has_extras
    )

    logger.debug("Inspection result: %s", profile.summary())
    return profile
