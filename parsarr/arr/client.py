"""
Shared base HTTP client for *arr applications.

All API calls use httpx with a shared base URL and X-Api-Key header.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ArrClient:
    """Thin async httpx wrapper pre-configured for an *arr service."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        if not base_url:
            raise ValueError("base_url must not be empty")
        if not api_key:
            raise ValueError("api_key must not be empty")
        self._base = base_url.rstrip("/")
        self._headers = {"X-Api-Key": api_key, "Content-Type": "application/json"}
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    async def get(self, path: str, **params: Any) -> Any:
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(url, headers=self._headers, params=params)
            resp.raise_for_status()
            return resp.json()

    async def post(self, path: str, payload: dict) -> Any:
        url = f"{self._base}{path}"
        logger.debug("POST %s %s", url, payload)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, headers=self._headers, json=payload)
            resp.raise_for_status()
            return resp.json()

    async def put(self, path: str, payload: dict) -> Any:
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.put(url, headers=self._headers, json=payload)
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    async def send_command(self, name: str, **kwargs: Any) -> dict:
        """POST /api/v3/command with {name, **kwargs}."""
        return await self.post("/api/v3/command", {"name": name, **kwargs})

    async def ping(self) -> bool:
        """Return True when the service is reachable and the key is valid."""
        try:
            result = await self.get("/api/v3/system/status")
            return isinstance(result, dict)
        except Exception as exc:
            logger.warning("Ping failed: %s", exc)
            return False
