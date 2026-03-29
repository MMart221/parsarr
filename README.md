# Parsarr

**Media import preprocessor for the \*arr stack.**

Parsarr sits between your completed media folders and Sonarr/Radarr. When a completed download lands on disk, it inspects the folder structure and normalizes it into the layout those tools expect — then hands it back for import automatically.

It is designed for one specific problem: **media folder structures that Sonarr and Radarr cannot reliably import on their own.** These are typically complete-series or multi-season releases, folders with bonus content mixed in alongside episodes, or deeply nested directory trees where the actual video files are buried several levels down.

---

## Why Parsarr?

Sonarr and Radarr expect a fairly predictable structure when they import files. A single season in a single folder, video files at the top level, subtitles alongside the video they belong to. When a folder doesn't match that shape, the import either fails silently or requires manual intervention.

Common structures that cause problems:

- **Multi-season collections** — all seasons in one folder, or one top-level folder with per-season subfolders that Sonarr won't split automatically
- **Nested release trees** — video files buried two or three directories deep inside a folder hierarchy
- **Bonus content mixed with episodes** — commentary files, featurettes, making-of videos, interview clips, and menu art all sitting alongside the actual episodes with no separation
- **Orphaned sidecars** — subtitle files, `.nfo` metadata, or artwork that won't follow the video through a move unless explicitly paired

Parsarr handles all of these before the import is triggered. Sonarr and Radarr receive a clean, organized staging folder rather than the raw download.

---

## What it does

```
Download completes
    → Sonarr/Radarr fires a webhook to parsarr
    → parsarr inspects the folder structure
    → if already well-formed: acknowledge and do nothing
    → if reorganization is needed:
        → create an isolated staging folder
        → split episodes into Season XX/ subdirectories
        → flatten any deeply nested tree
        → move bonus content to _extras/ (preserving its own subfolder structure)
        → pair subtitles, NFO files, and artwork with their matching episode
        → trigger ManualImport back in Sonarr/Radarr pointing at the staging folder
```

A CLI is also included so you can run the same logic manually — useful for testing, dry-running against a folder before committing, or cleaning up a backlog.

---

## Classification logic

Parsarr's inspector classifies every incoming folder before touching anything. Each file gets a role:

| Role | Criteria |
|------|----------|
| **Episode** | Video file with a detectable season/episode token (`S01E01` style) |
| **Extra** | Video with no season token in a show release; or filename matches a bonus-content pattern (featurette, commentary, making-of, etc.) |
| **Companion** | Subtitle, NFO, or artwork whose stem exactly matches an episode filename |
| **Extra asset** | Companion file with no matching episode (e.g. folder-level artwork, menu images) |

A folder is considered **standard** (no action needed) when it has at most one season, no nesting beyond one subfolder, and no extras mixed in. Standard releases are acknowledged and skipped — parsarr only acts when it finds something to fix.

---

## Integration guide

### Prerequisites

- Docker and Docker Compose
- Sonarr and/or Radarr running in Docker (or accessible over the network)
- A shared volume path that parsarr, Sonarr, and Radarr can all read and write

### Step 1 — Clone and configure

```bash
git clone https://github.com/youruser/parsarr.git
cd parsarr
cp config.yaml.example config.yaml
```

Open `config.yaml` and fill in your values:

```yaml
# Where parsarr writes reorganized files before import.
# This path must be accessible to Sonarr and Radarr as well.
staging_dir: /data/staging

sonarr:
  url: http://sonarr:8989
  api_key: YOUR_SONARR_API_KEY   # Settings → General → API Key

radarr:
  url: http://radarr:7878
  api_key: YOUR_RADARR_API_KEY

# Optional: a shared secret to verify webhooks come from your own Sonarr/Radarr.
# Set this here, then add the same value in Sonarr/Radarr webhook settings.
webhook_secret: ""

log_level: INFO
port: 8080
```

### Step 2 — Add parsarr to your Docker Compose stack

Add the parsarr service to the same `docker-compose.yml` that runs your other \*arr services, or use the one included in this repo as a starting point. The critical requirements are:

1. **Same Docker network** as Sonarr and Radarr so they can reach each other by service name
2. **Shared staging volume** so Sonarr/Radarr can access the files parsarr stages for import
3. **Shared downloads volume** so parsarr can read and reorganize your completed downloads

```yaml
services:
  parsarr:
    build: .
    container_name: parsarr
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./config.yaml:/config/config.yaml:ro
      - /data/staging:/data/staging
      - /data/downloads:/data/downloads
    networks:
      - arr_network

  sonarr:
    image: lscr.io/linuxserver/sonarr:latest
    # ... your existing sonarr config ...
    volumes:
      - /data/downloads:/data/downloads
      - /data/staging:/data/staging    # must match parsarr's staging_dir
    networks:
      - arr_network

  radarr:
    image: lscr.io/linuxserver/radarr:latest
    # ... your existing radarr config ...
    volumes:
      - /data/downloads:/data/downloads
      - /data/staging:/data/staging
    networks:
      - arr_network

networks:
  arr_network:
    name: arr_network
```

Start the service:

```bash
docker compose up -d parsarr
```

### Step 3 — Connect Sonarr to parsarr

1. In Sonarr, go to **Settings → Connect → + (Add Connection)**
2. Choose **Webhook**
3. Fill in:
   - **Name:** parsarr
   - **URL:** `http://parsarr:8080/webhook/sonarr`
   - **Method:** POST
   - **Triggers:** check **On Import** (and **On Upgrade** if you want upgrades processed too)
   - **Secret:** paste the same value as `webhook_secret` in your config (leave blank if not using one)
4. Click **Test** — you should see `{"status":"ok","message":"test event acknowledged"}` in the Sonarr log and parsarr's log

### Step 4 — Connect Radarr to parsarr

Same steps as above, but:
- **URL:** `http://parsarr:8080/webhook/radarr`

### Step 5 — Verify with a dry run

Before relying on the automatic flow, test parsarr against a real folder from your library:

```bash
# Inspect without touching anything
docker exec parsarr python -m parsarr.main inspect /data/downloads/some-folder

# See exactly what would be moved where
docker exec parsarr python -m parsarr.main test /data/downloads/some-folder
```

If the dry-run output looks right, the live webhook flow will produce identical results.

### Step 6 — Normal workflow from here

Once connected, the flow is fully automatic:

1. Your download client finishes a download
2. Sonarr or Radarr picks it up and fires a webhook to parsarr
3. Parsarr inspects the folder — if it's already clean, nothing happens
4. If it needs work, parsarr reorganizes the files into a staging slot and calls Sonarr/Radarr's ManualImport API
5. Sonarr/Radarr completes the import from the staging folder as if you had triggered it manually

---

## CLI reference

All commands are available both inside Docker (`docker exec parsarr python -m parsarr.main <cmd>`) and directly if you're running outside a container.

### `inspect <path>`

Classify a folder without modifying anything. Shows each file's detected role, season, and depth.

```bash
python -m parsarr.main inspect /data/downloads/My.Show.Complete.Series
```

```
ReleaseProfile('My.Show.Complete.Series', flags=[multi-season, has-extras], seasons=[1, 2, 3], episodes=36, extras=12)
  Episodes : 36
  Extras   : 12
  Seasons  : [1, 2, 3]
  Standard : False
  Multi-season  : True
  Needs flatten : False
  Has extras    : True

Files:
  [VIDEO    ] S01        depth=1  My Show - S01E01 - Pilot.mkv
  [VIDEO    ] S01        depth=1  My Show - S01E02 - Episode Two.mkv
  ...
  [VIDEO    ]   ?? [EXTRA]  depth=2  Behind the Scenes.mkv
  [COMPANION]   ?? [EXTRA]  depth=2  menu art.png
```

### `test <path>`

Dry-run: show every planned file operation without executing any of them.

```bash
python -m parsarr.main test /data/downloads/My.Show.Complete.Series
```

### `run <path>`

Process a folder live. Use `--app` to trigger import in Sonarr or Radarr afterward.

```bash
# Reorganize only, no import trigger
python -m parsarr.main run /data/downloads/My.Show.Complete.Series --app=none

# Reorganize and trigger Sonarr import
python -m parsarr.main run /data/downloads/My.Show.Complete.Series \
    --app=sonarr \
    --import-mode=Move

# Reorganize and trigger Radarr import, with a specific movie ID
python -m parsarr.main run /data/downloads/My.Movie.2024 \
    --app=radarr \
    --movie-id=42
```

### `serve`

Start the webhook HTTP server (this is what the Docker container runs by default).

```bash
python -m parsarr.main serve --host 0.0.0.0 --port 8080
```

---

## Configuration reference

| Key | Default | Description |
|-----|---------|-------------|
| `staging_dir` | `/data/staging` | Directory where reorganized files are placed before import |
| `sonarr.url` | — | Sonarr base URL |
| `sonarr.api_key` | — | Sonarr API key (Settings → General) |
| `radarr.url` | — | Radarr base URL |
| `radarr.api_key` | — | Radarr API key (Settings → General) |
| `webhook_secret` | `""` | If set, verified against the `X-Parsarr-Secret` request header |
| `log_level` | `INFO` | Python log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `port` | `8080` | Port the webhook server listens on |
| `extra_patterns` | (list) | Additional lowercase substrings that identify a file as bonus content |

All settings can be provided as environment variables prefixed with `PARSARR_`. Nested keys use double-underscore as separator:

```bash
PARSARR_SONARR__API_KEY=abc123
PARSARR_STAGING_DIR=/mnt/staging
PARSARR_LOG_LEVEL=DEBUG
```

### Extending extra detection

Parsarr ships with a broad set of patterns for bonus content (featurettes, commentaries, making-of videos, animatics, etc.). If a specific content type in your library isn't being caught, add it to `config.yaml`:

```yaml
extra_patterns:
  - "my custom pattern"
  - "another pattern"
```

Patterns are matched case-insensitively as substrings of the filename. The built-in list is always active alongside any additions.

---

## Development

```bash
git clone https://github.com/youruser/parsarr.git
cd parsarr

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

pytest tests/ -v
```

---

## Project layout

```
parsarr/
├── parsarr/
│   ├── main.py              # FastAPI app factory and CLI entry point
│   ├── config.py            # Settings loader (config.yaml + environment variables)
│   ├── cli.py               # CLI commands: serve, inspect, test, run
│   ├── webhook/
│   │   ├── routes.py        # POST /webhook/sonarr, /webhook/radarr, GET /health
│   │   └── schemas.py       # Pydantic models for Sonarr and Radarr webhook payloads
│   ├── core/
│   │   ├── inspector.py     # Folder scanner and release classifier (single source of truth)
│   │   ├── processor.py     # File operations: flatten, split seasons, stage extras
│   │   └── staging.py       # Staging directory lifecycle (create, list, cleanup)
│   └── arr/
│       ├── client.py        # Shared async HTTP client (httpx)
│       ├── sonarr.py        # Sonarr API: ManualImport, RescanSeries
│       └── radarr.py        # Radarr API: ManualImport, RescanMovie
├── tests/
│   ├── conftest.py          # Shared fixtures (temporary release folders, staging dirs)
│   ├── test_inspector.py    # Classification logic tests
│   └── test_processor.py    # File operation tests (dry-run and live)
├── config.yaml.example
├── Dockerfile
└── docker-compose.yml
```

## Project status

Parsarr is primarily a personal project built to solve my own workflow. It is public in case others find it useful. Pull requests and forks are welcome.


## License

GPL-3.0-or-later