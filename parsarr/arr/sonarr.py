"""
Sonarr-specific API interactions.

Sonarr API v3 reference: https://sonarr.tv/#downloads-v3-docker
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from .client import ArrClient

logger = logging.getLogger(__name__)


class SonarrClient(ArrClient):

    async def manual_import(
        self,
        paths: list[Path],
        import_mode: str = "Move",
        series_id: Optional[int] = None,
    ) -> dict:
        """
        Trigger a ManualImport command for the given file paths.

        Sonarr v3 expects:
          POST /api/v3/command
          {
            "name": "ManualImport",
            "files": [{"path": "...", "seriesId": ..., "seasonNumber": ...}],
            "importMode": "Move"
          }

        When series_id is not provided parsarr leaves it to Sonarr to match
        automatically based on path and naming.
        """
        files_payload: list[dict[str, Any]] = []
        for p in paths:
            entry: dict[str, Any] = {"path": str(p)}
            if series_id is not None:
                entry["seriesId"] = series_id
            files_payload.append(entry)

        payload = {
            "name": "ManualImport",
            "files": files_payload,
            "importMode": import_mode,
        }
        logger.info(
            "Triggering Sonarr ManualImport for %d file(s), mode=%s",
            len(paths),
            import_mode,
        )
        return await self.post("/api/v3/command", payload)

    async def rescan_series(self, series_id: int) -> dict:
        """Trigger a RescanSeries command so Sonarr picks up moved files."""
        return await self.send_command("RescanSeries", seriesId=series_id)

    async def get_series(self) -> list[dict]:
        """Return all series known to Sonarr."""
        return await self.get("/api/v3/series")

    async def get_queue(self) -> dict:
        """Return the current download queue."""
        return await self.get("/api/v3/queue")
