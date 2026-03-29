"""
Radarr-specific API interactions.

Radarr API v3 reference: https://radarr.video/#downloads-v3-docker
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from .client import ArrClient

logger = logging.getLogger(__name__)


class RadarrClient(ArrClient):

    async def manual_import(
        self,
        paths: list[Path],
        import_mode: str = "Move",
        movie_id: Optional[int] = None,
    ) -> dict:
        """
        Trigger a ManualImport command for the given file paths.

        Radarr v3 expects:
          POST /api/v3/command
          {
            "name": "ManualImport",
            "files": [{"path": "...", "movieId": ...}],
            "importMode": "Move"
          }
        """
        files_payload: list[dict[str, Any]] = []
        for p in paths:
            entry: dict[str, Any] = {"path": str(p)}
            if movie_id is not None:
                entry["movieId"] = movie_id
            files_payload.append(entry)

        payload = {
            "name": "ManualImport",
            "files": files_payload,
            "importMode": import_mode,
        }
        logger.info(
            "Triggering Radarr ManualImport for %d file(s), mode=%s",
            len(paths),
            import_mode,
        )
        return await self.post("/api/v3/command", payload)

    async def rescan_movie(self, movie_id: int) -> dict:
        """Trigger a RescanMovie command so Radarr picks up moved files."""
        return await self.send_command("RescanMovie", movieId=movie_id)

    async def get_movies(self) -> list[dict]:
        """Return all movies known to Radarr."""
        return await self.get("/api/v3/movie")

    async def get_queue(self) -> dict:
        """Return the current download queue."""
        return await self.get("/api/v3/queue")
