"""
Sonarr API v3 client.

Parsarr uses Sonarr for:
- Looking up series by ID or search query (to determine library destination)
- Triggering RescanSeries after direct placement
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .client import ArrClient

logger = logging.getLogger(__name__)


class SonarrClient(ArrClient):
    """Sonarr-specific API interactions."""

    # ------------------------------------------------------------------
    # Series lookup
    # ------------------------------------------------------------------

    async def get_series(self) -> list[dict]:
        """Return all series in the Sonarr library."""
        return await self.get("/api/v3/series")

    async def get_series_by_id(self, series_id: int) -> dict:
        """Return a single series record by its Sonarr ID."""
        return await self.get(f"/api/v3/series/{series_id}")

    async def search_series(self, query: str) -> list[dict]:
        """
        Search for a series by name using Sonarr's lookup endpoint.

        Returns a list of candidates (may include entries not yet in library).
        Each entry has at minimum: id, title, titleSlug, year, path (if in library).
        """
        results = await self.get("/api/v3/series/lookup", term=query)
        return results if isinstance(results, list) else []

    async def get_series_path(self, series_id: int) -> Optional[str]:
        """
        Return the root folder path Sonarr has assigned to a series, or None.

        The returned path is the show's library folder
        (e.g. "/media/tv/Show Name (2020)").
        """
        try:
            series = await self.get_series_by_id(series_id)
            return series.get("path")
        except Exception as exc:
            logger.warning("Could not fetch path for series %s: %s", series_id, exc)
            return None

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def rescan_series(self, series_id: int) -> dict:
        """Trigger a RescanSeries command for the given series."""
        logger.info("Triggering RescanSeries for series_id=%s", series_id)
        return await self.send_command("RescanSeries", seriesId=series_id)

    async def refresh_series(self, series_id: int) -> dict:
        """Trigger a RefreshSeries command (re-fetches metadata + rescans)."""
        logger.info("Triggering RefreshSeries for series_id=%s", series_id)
        return await self.send_command("RefreshSeries", seriesId=series_id)

    async def get_queue(self) -> list[dict]:
        """Return the current Sonarr import/download queue."""
        result = await self.get("/api/v3/queue")
        if isinstance(result, dict):
            return result.get("records", [])
        return result if isinstance(result, list) else []
