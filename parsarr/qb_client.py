"""
qBittorrent WebUI API client.

Parsarr uses qBittorrent as the download engine and metadata source.
All calls target the qBittorrent Web API v2 (/api/v2/*).

Authentication is cookie-based: POST /api/v2/auth/login once, then reuse
the SID cookie for all subsequent requests.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Torrent states reported by qBittorrent that indicate the download is complete.
_COMPLETE_STATES = frozenset({
    "uploading",
    "stalledUP",
    "checkingUP",
    "pausedUP",
    "queuedUP",
    "forcedUP",
})

# States where the torrent exists but metadata may still be pending.
_METADATA_STATES = frozenset({
    "metaDL",
    "checkingResumeData",
})


class QBittorrentError(Exception):
    pass


class QBittorrentClient:
    """Async client for the qBittorrent WebUI API."""

    def __init__(self, url: str, username: str, password: str, timeout: float = 30.0) -> None:
        self._base = url.rstrip("/")
        self._username = username
        self._password = password
        self._timeout = timeout
        self._cookie: Optional[str] = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _login(self) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/api/v2/auth/login",
                data={"username": self._username, "password": self._password},
            )
            if resp.text.strip() == "Fails.":
                raise QBittorrentError("qBittorrent login failed — check credentials")
            sid = resp.cookies.get("SID")
            if not sid:
                raise QBittorrentError("qBittorrent login returned no SID cookie")
            self._cookie = sid
            logger.debug("Authenticated with qBittorrent")

    async def _ensure_auth(self) -> None:
        if not self._cookie:
            await self._login()

    def _headers(self) -> dict[str, str]:
        return {"Cookie": f"SID={self._cookie}"}

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, **params: Any) -> Any:
        await self._ensure_auth()
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, headers=self._headers(), params=params)
            if resp.status_code == 403:
                # Session expired — re-auth and retry once
                self._cookie = None
                await self._login()
                resp = await client.get(url, headers=self._headers(), params=params)
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, data: Optional[dict] = None) -> str:
        await self._ensure_auth()
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, headers=self._headers(), data=data or {})
            if resp.status_code == 403:
                self._cookie = None
                await self._login()
                resp = await client.post(url, headers=self._headers(), data=data or {})
            resp.raise_for_status()
            return resp.text

    # ------------------------------------------------------------------
    # Torrent management
    # ------------------------------------------------------------------

    async def add_magnet(
        self,
        magnet: str,
        category: str = "",
        save_path: str = "",
    ) -> None:
        """Add a magnet link to qBittorrent."""
        data: dict[str, str] = {"urls": magnet}
        if category:
            data["category"] = category
        if save_path:
            data["savepath"] = save_path
        await self._post("/api/v2/torrents/add", data)
        logger.info("Added magnet to qBittorrent (category=%r, path=%r)", category, save_path)

    async def get_torrent_info(self, torrent_hash: str) -> Optional[dict]:
        """Return the torrent info dict for a single hash, or None if not found."""
        result = await self._get(
            "/api/v2/torrents/info", hashes=torrent_hash.lower()
        )
        if isinstance(result, list) and result:
            return result[0]
        return None

    async def get_torrent_files(self, torrent_hash: str) -> list[dict]:
        """
        Return the file list for a torrent.
        Each entry has at minimum: {"name": "path/to/file", "size": int}.
        Returns an empty list if the torrent has no metadata yet.
        """
        try:
            result = await self._get(
                "/api/v2/torrents/files", hash=torrent_hash.lower()
            )
            return result if isinstance(result, list) else []
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                # Torrent not found or metadata not ready
                return []
            raise

    async def set_location(self, torrent_hash: str, path: str) -> None:
        """Change the save location for a torrent (can be done while downloading)."""
        await self._post(
            "/api/v2/torrents/setLocation",
            {"hashes": torrent_hash.lower(), "location": path},
        )
        logger.info("Set qB save path for %s → %s", torrent_hash[:8], path)

    async def set_category(self, torrent_hash: str, category: str) -> None:
        """Change the category for a torrent."""
        await self._post(
            "/api/v2/torrents/setCategory",
            {"hashes": torrent_hash.lower(), "category": category},
        )
        logger.info("Set qB category for %s → %r", torrent_hash[:8], category)

    async def create_category(self, category: str, save_path: str = "") -> None:
        """Create a qBittorrent category if it does not exist."""
        await self._post(
            "/api/v2/torrents/createCategory",
            {"category": category, "savePath": save_path},
        )

    async def pause_torrent(self, torrent_hash: str) -> None:
        await self._post("/api/v2/torrents/pause", {"hashes": torrent_hash.lower()})

    async def resume_torrent(self, torrent_hash: str) -> None:
        await self._post("/api/v2/torrents/resume", {"hashes": torrent_hash.lower()})

    # ------------------------------------------------------------------
    # Polling helpers
    # ------------------------------------------------------------------

    async def wait_for_metadata(
        self,
        torrent_hash: str,
        timeout: int = 120,
        poll_interval: float = 2.0,
    ) -> list[str]:
        """
        Poll until qBittorrent has fetched torrent metadata (file list).

        Returns the list of file path strings from the torrent.
        Raises QBittorrentError on timeout.
        """
        deadline = time.monotonic() + timeout
        logger.info("Waiting for metadata for torrent %s...", torrent_hash[:8])

        while time.monotonic() < deadline:
            files = await self.get_torrent_files(torrent_hash)
            if files:
                paths = [f["name"] for f in files]
                logger.info(
                    "Metadata available for %s: %d file(s)", torrent_hash[:8], len(paths)
                )
                return paths
            await asyncio.sleep(poll_interval)

        raise QBittorrentError(
            f"Timeout waiting for metadata for torrent {torrent_hash[:8]}"
        )

    async def wait_for_completion(
        self,
        torrent_hash: str,
        timeout: int = 86400,
        poll_interval: float = 30.0,
    ) -> dict:
        """
        Poll until the torrent reaches a completed state.

        Returns the final torrent info dict.
        Raises QBittorrentError on timeout.
        """
        deadline = time.monotonic() + timeout
        logger.info("Waiting for completion of torrent %s...", torrent_hash[:8])

        while time.monotonic() < deadline:
            info = await self.get_torrent_info(torrent_hash)
            if info and info.get("state") in _COMPLETE_STATES:
                logger.info("Torrent %s completed (state=%s)", torrent_hash[:8], info["state"])
                return info
            await asyncio.sleep(poll_interval)

        raise QBittorrentError(
            f"Timeout waiting for completion of torrent {torrent_hash[:8]}"
        )

    async def ping(self) -> bool:
        """Return True when qBittorrent is reachable and credentials are valid."""
        try:
            await self._login()
            return True
        except Exception as exc:
            logger.warning("qBittorrent ping failed: %s", exc)
            return False
