"""
parsarr CLI

Commands:
  serve   Start the webhook HTTP server
  run     Process a release folder and trigger import (live)
  test    Dry-run: show what would happen without moving any files
  inspect Show the classification of a release folder without processing
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import click
import uvicorn

from .config import load_settings, settings as _default_settings

logger = logging.getLogger(__name__)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------

@click.group()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=False, path_type=Path),
    default=None,
    help="Path to config.yaml (overrides PARSARR_CONFIG env var).",
)
@click.pass_context
def cli(ctx: click.Context, config: Optional[Path]) -> None:
    """parsarr — *arr-stack file parser and import helper."""
    ctx.ensure_object(dict)
    loaded = load_settings(config_path=config)
    # Mutate the module-level singleton so all sub-commands share the same
    # settings without having to pass it through Click context explicitly.
    import parsarr.config as _cfg
    _cfg.settings = loaded
    ctx.obj["settings"] = loaded
    _setup_logging(loaded.log_level)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--host", default="0.0.0.0", show_default=True, help="Bind host.")
@click.option("--port", default=None, type=int, help="Bind port (overrides config).")
@click.pass_context
def serve(ctx: click.Context, host: str, port: Optional[int]) -> None:
    """Start the webhook HTTP server."""
    s = ctx.obj["settings"]
    effective_port = port or s.port
    click.echo(f"Starting parsarr server on {host}:{effective_port}")
    uvicorn.run(
        "parsarr.main:app",
        host=host,
        port=effective_port,
        log_level=s.log_level.lower(),
    )


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------

@cli.command(name="inspect")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
def inspect_cmd(path: Path) -> None:
    """Show the classification of a release folder without processing it."""
    from .core import inspector as ins

    import parsarr.config as _cfg
    profile = ins.inspect(path, extra_patterns=_cfg.settings.extra_patterns)
    click.echo(profile.summary())
    click.echo(f"  Episodes : {len(profile.episode_files)}")
    click.echo(f"  Extras   : {len(profile.extra_files)}")
    click.echo(f"  Seasons  : {sorted(profile.seasons_found)}")
    click.echo(f"  Standard : {profile.is_standard}")
    click.echo(f"  Multi-season  : {profile.is_multi_season}")
    click.echo(f"  Needs flatten : {profile.needs_flatten}")
    click.echo(f"  Has extras    : {profile.has_extras}")
    click.echo("")
    click.echo("Files:")
    for f in profile.files:
        tag = "VIDEO" if f.is_video else ("COMPANION" if f.is_companion else "OTHER")
        extra = " [EXTRA]" if f.is_extra else ""
        season = f"S{f.season:02d}" if f.season is not None else "  ??"
        click.echo(f"  [{tag:9s}] {season}{extra}  depth={f.depth}  {f.path.name}")


# ---------------------------------------------------------------------------
# test  (dry-run)
# ---------------------------------------------------------------------------

@cli.command(name="test")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--staging-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Override staging_dir from config.",
)
def test_cmd(path: Path, staging_dir: Optional[Path]) -> None:
    """
    Dry-run: show every file operation that WOULD be performed without
    moving anything.  Useful for testing a release before going live.
    """
    import parsarr.config as _cfg
    from .core import inspector as ins
    from .core import processor as proc
    from .core import staging as stg

    s = _cfg.settings
    effective_staging = staging_dir or s.staging_dir

    profile = ins.inspect(path, extra_patterns=s.extra_patterns)
    click.echo(f"Profile: {profile.summary()}")
    click.echo("")

    if profile.is_standard:
        click.echo("Release is already standard — no processing needed.")
        return

    # Use a fake slot path for display purposes
    fake_slot = effective_staging / f"{path.name}__dryrun"
    result = proc.process(profile, fake_slot, dry_run=True)

    click.echo("Planned actions:")
    for action in result.actions:
        click.echo(f"  {action}")


# ---------------------------------------------------------------------------
# run  (live)
# ---------------------------------------------------------------------------

@cli.command(name="run")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--staging-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Override staging_dir from config.",
)
@click.option(
    "--app",
    type=click.Choice(["sonarr", "radarr", "none"], case_sensitive=False),
    default="none",
    show_default=True,
    help="Which *arr app to trigger ManualImport on after processing.",
)
@click.option(
    "--series-id",
    type=int,
    default=None,
    help="Sonarr series ID (optional, lets Sonarr auto-match if omitted).",
)
@click.option(
    "--movie-id",
    type=int,
    default=None,
    help="Radarr movie ID (optional, lets Radarr auto-match if omitted).",
)
@click.option(
    "--import-mode",
    type=click.Choice(["Move", "Copy", "HardLink"], case_sensitive=True),
    default="Move",
    show_default=True,
)
def run_cmd(
    path: Path,
    staging_dir: Optional[Path],
    app: str,
    series_id: Optional[int],
    movie_id: Optional[int],
    import_mode: str,
) -> None:
    """
    Process a release folder and (optionally) trigger a ManualImport in
    Sonarr or Radarr.  Use --app=none to only reorganise files.
    """
    import parsarr.config as _cfg
    from .core import inspector as ins
    from .core import processor as proc
    from .core import staging as stg

    s = _cfg.settings
    effective_staging = staging_dir or s.staging_dir

    # Inspect
    profile = ins.inspect(path, extra_patterns=s.extra_patterns)
    click.echo(f"Profile: {profile.summary()}")

    if profile.is_standard:
        click.echo("Release is already standard — no processing needed.")
        return

    # Stage & process
    slot = stg.make_staging_slot(effective_staging, path.name)
    click.echo(f"Staging slot: {slot}")
    result = proc.process(profile, slot)

    for action in result.actions:
        click.echo(f"  {action}")

    if result.skipped:
        stg.cleanup_staging_slot(slot)
        return

    video_paths = proc.staged_video_paths(result)
    click.echo(f"\n{len(video_paths)} video file(s) staged.")

    if app == "none" or not video_paths:
        click.echo("Skipping import trigger (--app=none or no videos).")
        return

    # Trigger import
    asyncio.run(_trigger_import(app, video_paths, series_id, movie_id, import_mode, s))


async def _trigger_import(
    app: str,
    video_paths: list[Path],
    series_id: Optional[int],
    movie_id: Optional[int],
    import_mode: str,
    s,
) -> None:
    if app == "sonarr":
        from .arr.sonarr import SonarrClient

        client = SonarrClient(base_url=s.sonarr.url, api_key=s.sonarr.api_key)
        resp = await client.manual_import(video_paths, import_mode=import_mode, series_id=series_id)
        click.echo(f"Sonarr responded: {resp}")
    elif app == "radarr":
        from .arr.radarr import RadarrClient

        client = RadarrClient(base_url=s.radarr.url, api_key=s.radarr.api_key)
        resp = await client.manual_import(video_paths, import_mode=import_mode, movie_id=movie_id)
        click.echo(f"Radarr responded: {resp}")
