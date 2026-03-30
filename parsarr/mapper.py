"""
Release auto-mapper.

Given a torrent title and file path list, attempts to identify the correct
Sonarr series and compute the final library target path.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Tokens commonly appended to release names that are not part of the show title.
# Stripped before sending to Sonarr's search endpoint.
_NOISE_PATTERNS = [
    re.compile(r"\b(19|20)\d{2}\b"),                    # year — but only if not the title
    re.compile(r"\bS\d{2}(E\d{2})?(-E\d{2})?\b", re.I),  # SxxExx tokens
    re.compile(r"\b(Complete|Series|Season|Pack|Batch)\b", re.I),
    re.compile(r"\b(1080p|720p|480p|2160p|4K|UHD|HDR|SDR)\b", re.I),
    re.compile(r"\b(BluRay|BDRip|WEB-DL|WEBRip|HDTV|DVDRip|REMUX)\b", re.I),
    re.compile(r"\b(x264|x265|H\.264|H\.265|HEVC|AVC|AV1)\b", re.I),
    re.compile(r"\b(AAC|AC3|DTS|TrueHD|FLAC|DD5\.1|Atmos)\b", re.I),
    re.compile(r"\b(PROPER|REPACK|EXTENDED|UNCUT|REMASTERED|DUBBED|MULTI)\b", re.I),
    re.compile(r"[\[\(][^\]\)]+[\]\)]"),                 # anything in brackets
    re.compile(r"[-_.]{2,}"),                            # double separators
]


@dataclass
class MappingResult:
    series_id: int
    series_title: str
    target_path: str                  # Sonarr's library path for the show
    seasons_detected: list[int] = field(default_factory=list)
    confidence: float = 0.0           # 0.0–1.0; 1.0 = exact title match in library


def _clean_title(raw: str) -> str:
    """Strip noise tokens from a release title to get a searchable show name."""
    result = raw
    for pattern in _NOISE_PATTERNS:
        result = pattern.sub(" ", result)
    # Replace separators with spaces, strip, collapse whitespace
    result = re.sub(r"[._-]", " ", result)
    result = re.sub(r"\s{2,}", " ", result).strip()
    return result


def _score_match(query: str, candidate_title: str) -> float:
    """Return a simple similarity score between 0 and 1."""
    q = query.lower().split()
    c = candidate_title.lower().split()
    if not q:
        return 0.0
    hits = sum(1 for word in q if word in c)
    return hits / max(len(q), len(c))


async def auto_map(
    torrent_title: str,
    file_paths: list[str],
    sonarr_client,  # SonarrClient — typed as Any to avoid circular import
) -> Optional[MappingResult]:
    """
    Attempt to auto-map a torrent to a Sonarr series.

    Strategy:
    1. Clean the torrent title to a bare show name.
    2. Query Sonarr's series/lookup endpoint.
    3. Prefer an exact match already in the library (has a ``path`` field).
    4. Fall back to the highest-scoring candidate from the search results.

    Returns None if no plausible match is found (confidence < 0.3).
    """
    cleaned = _clean_title(torrent_title)
    if not cleaned:
        logger.warning("auto_map: could not clean title %r", torrent_title)
        return None

    logger.debug("auto_map: searching Sonarr for %r (raw: %r)", cleaned, torrent_title)

    try:
        candidates = await sonarr_client.search_series(cleaned)
    except Exception as exc:
        logger.warning("auto_map: Sonarr search failed: %s", exc)
        return None

    if not candidates:
        logger.info("auto_map: no Sonarr candidates for %r", cleaned)
        return None

    # Score candidates; prioritise ones already in the library (have a path)
    best: Optional[dict] = None
    best_score: float = 0.0

    for c in candidates:
        score = _score_match(cleaned, c.get("title", ""))
        # Library entries get a small bonus so they beat equal-score lookups
        if c.get("path"):
            score = min(1.0, score + 0.1)
        if score > best_score:
            best_score = score
            best = c

    if best is None or best_score < 0.3:
        logger.info(
            "auto_map: best score %.2f below threshold for %r", best_score, cleaned
        )
        return None

    # Determine library path — use existing path or construct from rootFolderPath
    target_path: str = best.get("path") or ""
    if not target_path:
        root = best.get("rootFolderPath", "")
        folder = best.get("folder") or best.get("title", "")
        if root and folder:
            target_path = str((root.rstrip("/") + "/" + folder))

    # Detect seasons from file paths
    _SEASON_RE = re.compile(r"[Ss](\d{2})")
    seasons: set[int] = set()
    for fp in file_paths:
        m = _SEASON_RE.search(fp)
        if m:
            seasons.add(int(m.group(1)))

    logger.info(
        "auto_map: matched %r → %r (score=%.2f, path=%r)",
        torrent_title,
        best.get("title"),
        best_score,
        target_path,
    )

    return MappingResult(
        series_id=best.get("id", 0),
        series_title=best.get("title", ""),
        target_path=target_path,
        seasons_detected=sorted(seasons),
        confidence=best_score,
    )
