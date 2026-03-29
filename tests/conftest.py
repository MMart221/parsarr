"""
Shared pytest fixtures.

The `release_factory` fixture builds temporary release directories on disk
so tests can exercise the real filesystem-walking code paths.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest


@pytest.fixture()
def tmp_releases(tmp_path: Path) -> Path:
    """Return a base directory under which release folders can be created."""
    base = tmp_path / "releases"
    base.mkdir()
    return base


@pytest.fixture()
def make_release(tmp_releases: Path) -> Callable[..., Path]:
    """
    Factory that creates a release folder with the given file structure.

    Usage:
        root = make_release("Show.Name.S01-S03.PACK", [
            "Show.Name.S01E01.mkv",
            "Show.Name.S01E02.mkv",
            "Show.Name.S02E01.mkv",
            "subdir/Show.Name.S03E01.mkv",
            "Sample.mkv",
        ])
    """

    def _factory(release_name: str, file_paths: list[str]) -> Path:
        root = tmp_releases / release_name
        root.mkdir(parents=True, exist_ok=True)
        for rel in file_paths:
            full = root / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.touch()
        return root

    return _factory


@pytest.fixture()
def staging_dir(tmp_path: Path) -> Path:
    d = tmp_path / "staging"
    d.mkdir()
    return d
