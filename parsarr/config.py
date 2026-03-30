from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEFAULT_EXTRA_PATTERNS = [
    "sample",
    "featurette",
    "behind-the-scenes",
    "deleted-scene",
    "interview",
    "scene",
    "short",
    "trailer",
    "bonus",
]


class SonarrConfig(BaseModel):
    url: str = ""
    api_key: str = ""


class QBittorrentConfig(BaseModel):
    url: str = ""
    username: str = "admin"
    password: str = "adminadmin"


class MediaRoots(BaseModel):
    tv: Path = Path("/media/tv")
    anime: Path = Path("/media/anime")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PARSARR_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    sonarr: SonarrConfig = SonarrConfig()
    qbittorrent: QBittorrentConfig = QBittorrentConfig()

    # qBittorrent category Parsarr uses for rerouted and manual torrents.
    # Sonarr must NOT be configured to auto-import from this category.
    parsarr_category: str = "parsarr-managed"

    # Where qBittorrent is redirected to store a problematic release while it
    # is still downloading.  Sonarr never sees this area.
    managed_download_dir: Path = Path("/media/downloads/managed")

    # Parsarr's temporary work area: files are reorganized here before being
    # placed into the final library path.
    staging_dir: Path = Path("/media/staging")

    media_roots: MediaRoots = MediaRoots()
    db_path: Path = Path("/data/parsarr.db")

    # How Parsarr moves cleaned files into the final library path.
    # Allowed values: move, copy, hardlink
    placement_mode: str = "move"

    webhook_secret: str = ""
    log_level: str = "INFO"
    port: int = 8080
    extra_patterns: list[str] = _DEFAULT_EXTRA_PATTERNS


def _load_yaml(path: Path) -> dict:
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def load_settings(config_path: Optional[Path] = None) -> Settings:
    """
    Load settings with the following precedence (highest wins):
      1. Environment variables prefixed with PARSARR_
      2. config.yaml (path from PARSARR_CONFIG env var or config_path arg)
      3. Defaults
    """
    env_config = os.environ.get("PARSARR_CONFIG")
    resolved_path: Optional[Path] = None

    if config_path and config_path.exists():
        resolved_path = config_path
    elif env_config:
        p = Path(env_config)
        if p.exists():
            resolved_path = p

    if resolved_path is None:
        candidates = [
            Path.cwd() / "config.yaml",
            Path(__file__).parent.parent / "config.yaml",
        ]
        for candidate in candidates:
            if candidate.exists():
                resolved_path = candidate
                break

    yaml_data: dict = {}
    if resolved_path:
        logger.debug("Loading config from %s", resolved_path)
        yaml_data = _load_yaml(resolved_path)

    return Settings(**yaml_data)


# Module-level singleton — replaced at startup by load_settings().
settings: Settings = Settings()
