"""
parsarr CLI

Commands:
  serve   Start the HTTP server (webhook + UI)
  inspect Show the classification of a release folder without processing
  test    Dry-run: show what would happen without moving any files
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import click
import uvicorn

from .config import load_settings

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
    """parsarr — TV/anime intake and import preprocessor for the *arr stack."""
    ctx.ensure_object(dict)
    loaded = load_settings(config_path=config)
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
    """Start the webhook and UI server."""
    s = ctx.obj["settings"]
    effective_port = port or s.port
    click.echo(f"Starting parsarr on {host}:{effective_port}")
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

    s = _cfg.settings
    effective_staging = staging_dir or s.staging_dir

    profile = ins.inspect(path, extra_patterns=s.extra_patterns)
    click.echo(f"Profile: {profile.summary()}")
    click.echo("")

    if profile.is_standard:
        click.echo("Release is already standard — no processing needed.")
        return

    fake_slot = effective_staging / f"{path.name}__dryrun"
    result = proc.process(profile, fake_slot, dry_run=True)

    click.echo("Planned actions:")
    for action in result.actions:
        click.echo(f"  {action}")
