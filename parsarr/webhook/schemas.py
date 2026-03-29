"""
Pydantic models for Sonarr and Radarr webhook payloads.

Both apps send JSON bodies whose shape depends on the event type.  We model
only the fields parsarr actually uses; extra fields are silently ignored via
model_config extra='ignore'.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------

class ArrEventType(str, Enum):
    GRAB = "Grab"
    DOWNLOAD = "Download"
    RENAME = "Rename"
    SERIES_ADD = "SeriesAdd"
    SERIES_DELETE = "SeriesDelete"
    EPISODE_FILE_DELETE = "EpisodeFileDelete"
    MOVIE_ADD = "MovieAdd"
    MOVIE_DELETE = "MovieDelete"
    MOVIE_FILE_DELETE = "MovieFileDelete"
    HEALTH = "Health"
    TEST = "Test"
    MANUAL_INTERACTION_REQUIRED = "ManualInteractionRequired"


class WebhookBase(BaseModel):
    model_config = {"extra": "ignore"}

    event_type: ArrEventType = Field(..., alias="eventType")
    instance_name: Optional[str] = Field(None, alias="instanceName")


# ---------------------------------------------------------------------------
# Sonarr
# ---------------------------------------------------------------------------

class SonarrEpisodeFile(BaseModel):
    model_config = {"extra": "ignore"}

    id: Optional[int] = None
    relative_path: Optional[str] = Field(None, alias="relativePath")
    path: Optional[str] = None
    quality: Optional[str] = None


class SonarrSeries(BaseModel):
    model_config = {"extra": "ignore"}

    id: int
    title: str
    path: str
    tvdb_id: Optional[int] = Field(None, alias="tvdbId")
    type: Optional[str] = None


class SonarrEpisode(BaseModel):
    model_config = {"extra": "ignore"}

    id: int
    episode_number: int = Field(..., alias="episodeNumber")
    season_number: int = Field(..., alias="seasonNumber")
    title: str
    quality: Optional[str] = None


class SonarrWebhook(WebhookBase):
    series: Optional[SonarrSeries] = None
    episodes: list[SonarrEpisode] = Field(default_factory=list)
    episode_file: Optional[SonarrEpisodeFile] = Field(None, alias="episodeFile")
    is_upgrade: bool = Field(False, alias="isUpgrade")
    download_id: Optional[str] = Field(None, alias="downloadId")
    download_client: Optional[str] = Field(None, alias="downloadClient")


# ---------------------------------------------------------------------------
# Radarr
# ---------------------------------------------------------------------------

class RadarrMovieFile(BaseModel):
    model_config = {"extra": "ignore"}

    id: Optional[int] = None
    relative_path: Optional[str] = Field(None, alias="relativePath")
    path: Optional[str] = None
    quality: Optional[str] = None


class RadarrMovie(BaseModel):
    model_config = {"extra": "ignore"}

    id: int
    title: str
    file_path: Optional[str] = Field(None, alias="folderPath")
    tmdb_id: Optional[int] = Field(None, alias="tmdbId")


class RadarrWebhook(WebhookBase):
    movie: Optional[RadarrMovie] = None
    movie_file: Optional[RadarrMovieFile] = Field(None, alias="movieFile")
    is_upgrade: bool = Field(False, alias="isUpgrade")
    download_id: Optional[str] = Field(None, alias="downloadId")
    download_client: Optional[str] = Field(None, alias="downloadClient")
