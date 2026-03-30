"""
Pydantic models for Sonarr webhook payloads.

Only the On Grab event is handled in v2.  Fields used by Parsarr:
  - eventType   — must equal "Grab"
  - downloadId  — the torrent hash
  - series.id   — Sonarr series ID (used to look up the library path)
  - release.title — human-readable release name (seed for auto-mapping)

Extra fields are silently ignored via model_config extra='ignore'.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ArrEventType(str, Enum):
    GRAB = "Grab"
    DOWNLOAD = "Download"
    RENAME = "Rename"
    SERIES_ADD = "SeriesAdd"
    SERIES_DELETE = "SeriesDelete"
    EPISODE_FILE_DELETE = "EpisodeFileDelete"
    HEALTH = "Health"
    TEST = "Test"
    MANUAL_INTERACTION_REQUIRED = "ManualInteractionRequired"


class WebhookBase(BaseModel):
    model_config = {"extra": "ignore"}

    event_type: ArrEventType = Field(..., alias="eventType")
    instance_name: Optional[str] = Field(None, alias="instanceName")


# ---------------------------------------------------------------------------
# Sonarr On Grab
# ---------------------------------------------------------------------------

class SonarrGrabSeries(BaseModel):
    model_config = {"extra": "ignore"}

    id: int
    title: str
    path: Optional[str] = None
    tvdb_id: Optional[int] = Field(None, alias="tvdbId")
    type: Optional[str] = None


class SonarrGrabRelease(BaseModel):
    model_config = {"extra": "ignore"}

    title: str = ""
    quality: Optional[str] = None
    size: Optional[int] = None
    indexer: Optional[str] = None


class SonarrGrabWebhook(WebhookBase):
    """
    Payload for Sonarr's 'On Grab' event.

    Key fields Parsarr uses:
      download_id  — torrent hash (primary key for qBittorrent lookups)
      series.id    — Sonarr series ID
      release.title — release name (auto-mapping seed)
    """
    download_id: Optional[str] = Field(None, alias="downloadId")
    download_client: Optional[str] = Field(None, alias="downloadClient")
    series: Optional[SonarrGrabSeries] = None
    release: SonarrGrabRelease = Field(default_factory=SonarrGrabRelease)
