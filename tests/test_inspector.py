"""Tests for parsarr.core.inspector."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from parsarr.core.inspector import inspect


class TestStandardRelease:
    def test_single_season_flat(self, make_release: Callable) -> None:
        root = make_release(
            "Show.S01.1080p",
            [
                "Show.S01E01.mkv",
                "Show.S01E02.mkv",
                "Show.S01E03.mkv",
            ],
        )
        profile = inspect(root)
        assert profile.is_standard
        assert not profile.is_multi_season
        assert not profile.needs_flatten
        assert not profile.has_extras
        assert profile.seasons_found == {1}

    def test_single_season_one_subfolder(self, make_release: Callable) -> None:
        root = make_release(
            "Show.S02.1080p",
            [
                "Show.S02/Show.S02E01.mkv",
                "Show.S02/Show.S02E02.mkv",
            ],
        )
        profile = inspect(root)
        assert profile.is_standard
        assert profile.seasons_found == {2}

    def test_no_video_files(self, make_release: Callable) -> None:
        root = make_release("EmptyRelease", ["readme.nfo"])
        profile = inspect(root)
        assert profile.is_standard
        assert len(profile.video_files) == 0


class TestMultiSeasonRelease:
    def test_two_seasons(self, make_release: Callable) -> None:
        root = make_release(
            "Show.S01S02.PACK",
            [
                "Show.S01E01.mkv",
                "Show.S01E02.mkv",
                "Show.S02E01.mkv",
                "Show.S02E02.mkv",
            ],
        )
        profile = inspect(root)
        assert profile.is_multi_season
        assert profile.seasons_found == {1, 2}
        assert not profile.is_standard

    def test_three_seasons_nested(self, make_release: Callable) -> None:
        root = make_release(
            "Show.S01-S03.Complete",
            [
                "Season 1/Show.S01E01.mkv",
                "Season 1/Show.S01E02.mkv",
                "Season 2/Show.S02E01.mkv",
                "Season 3/Show.S03E01.mkv",
            ],
        )
        profile = inspect(root)
        assert profile.is_multi_season
        assert profile.seasons_found == {1, 2, 3}


class TestNestedRelease:
    def test_deeply_nested_video(self, make_release: Callable) -> None:
        root = make_release(
            "Badly.Packed.Show",
            [
                "outer/inner/Show.S01E01.mkv",
                "outer/inner/Show.S01E02.mkv",
            ],
        )
        profile = inspect(root)
        assert profile.needs_flatten
        assert not profile.is_standard

    def test_single_subfolder_not_flagged(self, make_release: Callable) -> None:
        root = make_release(
            "Normal.Show",
            ["Show/Show.S01E01.mkv"],
        )
        profile = inspect(root)
        assert not profile.needs_flatten


class TestExtras:
    def test_sample_file_detected(self, make_release: Callable) -> None:
        root = make_release(
            "Show.S01",
            [
                "Show.S01E01.mkv",
                "Sample.mkv",
            ],
        )
        profile = inspect(root)
        assert profile.has_extras
        assert not profile.is_standard

    def test_featurette_detected(self, make_release: Callable) -> None:
        root = make_release(
            "Movie.2024",
            [
                "Movie.mkv",
                "Movie-featurette.mkv",
            ],
        )
        profile = inspect(root)
        assert profile.has_extras

    def test_no_extras_on_clean_release(self, make_release: Callable) -> None:
        root = make_release(
            "Clean.Show.S01",
            ["Clean.Show.S01E01.mkv", "Clean.Show.S01E02.mkv"],
        )
        profile = inspect(root)
        assert not profile.has_extras


class TestCompanionFiles:
    def test_srt_included(self, make_release: Callable) -> None:
        root = make_release(
            "Subbed.Show",
            [
                "Show.S01E01.mkv",
                "Show.S01E01.srt",
                "Show.S01E01.nfo",
            ],
        )
        profile = inspect(root)
        assert len(profile.companion_files) == 2

    def test_file_not_found_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            inspect(Path("/nonexistent/path/that/does/not/exist"))
