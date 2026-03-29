"""Tests for parsarr.core.processor."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from parsarr.core import inspector, processor


def _video(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    return p


class TestDryRun:
    def test_standard_release_is_skipped(
        self, make_release: Callable, staging_dir: Path
    ) -> None:
        root = make_release("Show.S01", ["Show.S01E01.mkv", "Show.S01E02.mkv"])
        profile = inspector.inspect(root)
        result = processor.process(profile, staging_dir / "slot", dry_run=True)
        assert result.skipped
        assert not result.moved_files

    def test_multi_season_dry_run_plans_season_dirs(
        self, make_release: Callable, staging_dir: Path
    ) -> None:
        root = make_release(
            "Show.S01S02",
            [
                "Show.S01E01.mkv",
                "Show.S02E01.mkv",
            ],
        )
        profile = inspector.inspect(root)
        slot = staging_dir / "slot"
        result = processor.process(profile, slot, dry_run=True)
        assert not result.skipped
        assert not result.moved_files  # dry_run — nothing actually moved
        actions = "\n".join(result.actions)
        assert "Season 01" in actions
        assert "Season 02" in actions

    def test_extras_moved_to_extras_subdir(
        self, make_release: Callable, staging_dir: Path
    ) -> None:
        root = make_release(
            "Show.S01",
            [
                "Show.S01E01.mkv",
                "Sample.mkv",
            ],
        )
        profile = inspector.inspect(root)
        slot = staging_dir / "slot"
        result = processor.process(profile, slot, dry_run=True)
        assert not result.skipped
        actions = "\n".join(result.actions)
        assert "_extras" in actions


class TestLiveProcessing:
    def test_multi_season_files_split_into_season_dirs(
        self, make_release: Callable, staging_dir: Path
    ) -> None:
        root = make_release(
            "Show.S01S02",
            [
                "Show.S01E01.mkv",
                "Show.S01E02.mkv",
                "Show.S02E01.mkv",
            ],
        )
        profile = inspector.inspect(root)
        slot = staging_dir / "slot"
        result = processor.process(profile, slot, dry_run=False)

        assert not result.skipped
        season1 = slot / "Season 01"
        season2 = slot / "Season 02"
        assert season1.exists()
        assert season2.exists()
        assert len(list(season1.glob("*.mkv"))) == 2
        assert len(list(season2.glob("*.mkv"))) == 1

    def test_companion_files_move_with_video(
        self, make_release: Callable, staging_dir: Path
    ) -> None:
        root = make_release(
            "Show.S01S02.Subbed",
            [
                "Show.S01E01.mkv",
                "Show.S01E01.srt",
                "Show.S02E01.mkv",
                "Show.S02E01.srt",
            ],
        )
        profile = inspector.inspect(root)
        slot = staging_dir / "slot"
        processor.process(profile, slot, dry_run=False)

        assert (slot / "Season 01" / "Show.S01E01.mkv").exists()
        assert (slot / "Season 01" / "Show.S01E01.srt").exists()
        assert (slot / "Season 02" / "Show.S02E01.mkv").exists()
        assert (slot / "Season 02" / "Show.S02E01.srt").exists()

    def test_extras_quarantined_in_extras_subdir(
        self, make_release: Callable, staging_dir: Path
    ) -> None:
        root = make_release(
            "Show.S01.WithSample",
            [
                "Show.S01E01.mkv",
                "Sample.mkv",
            ],
        )
        profile = inspector.inspect(root)
        slot = staging_dir / "slot"
        processor.process(profile, slot, dry_run=False)

        assert (slot / "Season 01" / "Show.S01E01.mkv").exists()
        assert (slot / processor.EXTRAS_SUBDIR / "Sample.mkv").exists()

    def test_nested_files_flattened_into_season_dirs(
        self, make_release: Callable, staging_dir: Path
    ) -> None:
        root = make_release(
            "Badly.Nested.Show",
            [
                "outer/inner/Show.S01E01.mkv",
                "outer/inner/Show.S01E02.mkv",
            ],
        )
        profile = inspector.inspect(root)
        assert profile.needs_flatten
        slot = staging_dir / "slot"
        processor.process(profile, slot, dry_run=False)
        assert (slot / "Season 01" / "Show.S01E01.mkv").exists()
        assert (slot / "Season 01" / "Show.S01E02.mkv").exists()

    def test_staged_video_paths_returns_only_videos(
        self, make_release: Callable, staging_dir: Path
    ) -> None:
        root = make_release(
            "Show.S01S02",
            [
                "Show.S01E01.mkv",
                "Show.S01E01.srt",
                "Show.S02E01.mkv",
            ],
        )
        profile = inspector.inspect(root)
        slot = staging_dir / "slot"
        result = processor.process(profile, slot, dry_run=False)
        videos = processor.staged_video_paths(result)
        assert all(p.suffix == ".mkv" for p in videos)
        assert len(videos) == 2
