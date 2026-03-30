# Parsarr

**Media import preprocessor for the \*arr stack.**

Parsarr helps with **release structure normalization**: messy folder trees, multi-season bundles, nested paths, bonus content mixed with main files, and sidecars that don’t line up with what your library tools expect. It sits in front of Sonarr and qBittorrent. When Sonarr sends a release to qBittorrent, Parsarr can intercept it at **grab** time — before the download finishes — inspect the torrent’s file list from metadata, and decide whether the layout needs intervention.

For releases that already look **standard**, Parsarr records a passthrough and leaves Sonarr’s normal download path alone. For **problematic** structures, Parsarr takes ownership: it reroutes the torrent into a managed download area, reorganizes files after completion in a separate work staging area, places the cleaned result directly into your library path, and triggers a Sonarr rescan. Sonarr only sees the normalized result, not the raw pack layout.

A lightweight web UI is included for manual magnet intake, job monitoring, mapping overrides, and settings.

---

## Why Parsarr?

Tools like Sonarr expect a fairly predictable layout when importing: seasons in recognizable folders, main media files easy to find, subtitles and artwork paired with the right files. When a release doesn’t match that shape — because of how it was packed — the import can fail quietly, import only part of the release, or leave you fixing paths by hand.

Common patterns that cause trouble:

- **Multi-season collections** — several seasons in one tree, or per-season folders that the importer won’t split the way you need
- **Complete-series or bulk packs** — everything in one archive with a flat or uneven directory layout
- **Nested release trees** — media files buried several levels deep under extra folder layers
- **Bonus content mixed with main files** — commentaries, featurettes, extras, and menu assets sitting next to primary content with no clear separation
- **Orphaned sidecars** — subtitles, `.nfo` files, or images that won’t move with the right file unless they’re explicitly matched

Parsarr classifies and, when needed, restructures that material **before** Sonarr is left to interpret a finished download on its own.

---

## How it works

There are two intake paths.

### Path A — Sonarr-originated releases

```
Sonarr grabs a release → sends it to qBittorrent
    → Sonarr fires On Grab webhook to Parsarr
    → Parsarr reads downloadId (torrent hash) from webhook
    → Parsarr polls qBittorrent until file metadata is ready
    → Parsarr classifies the virtual file tree

    If standard:
        → job recorded as passthrough
        → torrent stays in Sonarr's normal qB category and path
        → Sonarr/qBittorrent proceed as usual — Parsarr takes no action

    If problematic:
        → Parsarr reroutes the torrent (setLocation + setCategory)
          into the managed download area before completion
        → Sonarr's Completed Download Handling does not fire
          (wrong category/path)
        → Parsarr auto-maps to the correct Sonarr series
        → Download completes under Parsarr control
        → Parsarr reorganizes files into a work staging area
        → Parsarr places cleaned files directly into the library path
        → Parsarr triggers Sonarr RescanSeries
        → Sonarr sees only the clean, correctly-organized result
```

### Path B — Manual magnet intake

```
User pastes magnet into Parsarr UI
    → Parsarr adds it to qBittorrent (parsarr-managed category)
    → Parsarr polls qBittorrent for metadata
    → Parsarr shows the file tree, classification, and proposed mapping
    → User can adjust mapping if needed, or let Parsarr proceed
    → Parsarr reorganizes, places, and triggers Sonarr rescan
```

### Default behavior and Hold

Parsarr is **automatic by default**. Once a problematic release is classified and mapped, it continues through to placement without requiring approval.

Each job has an optional **Hold** toggle. Hold is off by default. When Hold is enabled for a specific job, Parsarr pauses before final placement and waits for user approval. The Approve button only appears — and only does anything — when a job is explicitly on Hold. Approval is not a normal gate.

---

## File classification

Parsarr's inspector classifies every file in a release before touching anything:

| Role | Criteria |
|------|----------|
| **Episode** | Video file with a detectable season/episode token (`S01E01` style) |
| **Extra** | Video with no season token in a series-style release; or filename matches a bonus-content pattern |
| **Companion** | Subtitle, NFO, or artwork whose stem exactly matches an episode filename |
| **Extra asset** | Companion file with no matching episode (folder-level artwork, menu images, etc.) |

A release is **standard** when it has at most one season, no nesting beyond one subfolder, and no extras mixed in.

---

## Integration guide

### Prerequisites

- Docker and Docker Compose
- Sonarr already running in Docker
- qBittorrent with its Web UI accessible to Parsarr on the Docker network
- A shared media root volume that Parsarr, Sonarr, and qBittorrent can all access
- The Docker network your stack uses (e.g. `arr_network`)

### Step 1 — Create your config file

```bash
curl -o config.yaml \
  https://raw.githubusercontent.com/MMart221/parsarr/main/config.yaml.example
```

Open `config.yaml` and fill in your values:

```yaml
sonarr:
  url: http://sonarr:8989
  api_key: YOUR_SONARR_API_KEY

qbittorrent:
  url: http://qbittorrent:8080
  username: admin
  password: adminadmin

# Must match the category name you create in Step 2.
parsarr_category: parsarr-managed

# Adjust these paths to match your actual media layout.
managed_download_dir: /media/downloads/managed
staging_dir: /media/staging
media_roots:
  tv: /media/tv

placement_mode: move   # move, copy, or hardlink
```

### Step 2 — Create the qBittorrent category

In qBittorrent, go to **View → Categories → Add category** (or use the right-click menu in the sidebar) and create a category named `parsarr-managed`.

This is the category Parsarr uses for rerouted and manually-added torrents. Sonarr must **not** be configured to auto-import from this category.

To verify: in Sonarr, go to **Settings → Download Clients → qBittorrent** and confirm the category field there (usually `sonarr`) does not match `parsarr-managed`.

### Step 3 — Pull the image and add Parsarr to your stack

```bash
docker pull ghcr.io/mmart221/parsarr:latest
```

Add the following to your existing `docker-compose.yml` or use the provided one as a starting point:

```yaml
services:
  parsarr:
    image: ghcr.io/mmart221/parsarr:latest
    container_name: parsarr
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./config.yaml:/config/config.yaml:ro
      # Mount your full media root so Parsarr can reach
      # library paths, the managed download area, and work staging.
      # Replace /srv/media with your actual host path.
      - /srv/media:/media
      - parsarr_data:/data
    networks:
      - arr_network

volumes:
  parsarr_data:

networks:
  arr_network:
    external: true
    name: arr_network   # your actual network name
```

Start Parsarr:

```bash
docker compose up -d parsarr
```

### Step 4 — Connect Sonarr to Parsarr

1. In Sonarr, go to **Settings → Connect → + Add Connection**
2. Choose **Webhook**
3. Fill in:
   - **Name:** Parsarr
   - **Triggers:** check **On Grab** only
   - **URL:** `http://parsarr:8080/webhook/sonarr/grab`
   - **Method:** POST
   - **Secret:** paste the value from `webhook_secret` in your config (leave blank if not set)
4. Click **Test** — you should see `{"status":"ok","message":"test event acknowledged"}` in Sonarr's logs

> **Important:** The trigger must be **On Grab**, not On Import or On Download. Parsarr intercepts at grab time so it can reroute problematic releases before the download completes.

### Step 5 — Open the Parsarr UI

Navigate to `http://localhost:8080` (or the appropriate host if Parsarr is running on a remote machine).

The **Settings** page shows a webhook setup summary and lets you verify your qBittorrent and Sonarr connections.

### Step 6 — How it behaves from here

Once connected:

- **Standard releases** — Parsarr records them as passthrough and leaves them entirely to Sonarr. No intervention, no extra steps.
- **Problematic releases** — Parsarr reroutes them automatically, reorganizes after download, places the cleaned files, and triggers a rescan. You'll see the job in the queue with a state like `rerouted_to_staging → processing → completed`.
- **Jobs that need mapping** — if Parsarr can't confidently auto-map a release to a series, the job enters `awaiting_manual_mapping`. Open the job detail page to assign a series and target path, then the job continues.

---

## CLI reference

The CLI is useful for testing the inspector and processor against local folders, or for debugging a release before relying on the automatic flow.

All commands work both inside Docker and when running directly.

### `inspect <path>`

Classify a folder without modifying anything. Shows each file's detected role, season, and depth.

```bash
# Inside Docker
docker exec parsarr python -m parsarr.main inspect /media/downloads/some-release

# Or directly
python -m parsarr.main inspect /path/to/release
```

```
ReleaseProfile('My.Show.S01-S03', flags=[multi-season, has-extras], seasons=[1, 2, 3], episodes=36, extras=12)
  Episodes : 36
  Extras   : 12
  Seasons  : [1, 2, 3]
  Standard : False
  Multi-season  : True
  Needs flatten : False
  Has extras    : True

Files:
  [VIDEO    ] S01        depth=1  My Show - S01E01 - Pilot.mkv
  [VIDEO    ] S01        depth=1  My Show - S01E02 - Second Episode.mkv
  [VIDEO    ]   ?? [EXTRA]  depth=2  Behind the Scenes.mkv
  [COMPANION]   ?? [EXTRA]  depth=2  menu art.png
```

### `test <path>`

Dry-run: show every planned file operation without executing any of them.

```bash
python -m parsarr.main test /path/to/release
```

---

## Configuration reference

All settings can be provided in `config.yaml` or as environment variables prefixed with `PARSARR_` (nested keys use `__` as separator).

| Key | Default | Description |
|-----|---------|-------------|
| `sonarr.url` | — | Sonarr base URL |
| `sonarr.api_key` | — | Sonarr API key (Settings → General) |
| `qbittorrent.url` | — | qBittorrent WebUI URL |
| `qbittorrent.username` | `admin` | qBittorrent login |
| `qbittorrent.password` | `adminadmin` | qBittorrent password |
| `parsarr_category` | `parsarr-managed` | qB category for Parsarr-owned torrents; Sonarr must not watch this |
| `managed_download_dir` | `/media/downloads/managed` | Where rerouted torrents download |
| `staging_dir` | `/media/staging` | Temporary work area for reorganization |
| `media_roots.tv` | `/media/tv` | Primary library root used when placing cleaned files |
| `placement_mode` | `move` | How files are placed: `move`, `copy`, or `hardlink` |
| `db_path` | `/data/parsarr.db` | SQLite job database |
| `webhook_secret` | `""` | If set, verified against `X-Parsarr-Secret` header |
| `log_level` | `INFO` | Python log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `port` | `8080` | Port the server listens on |
| `extra_patterns` | (list) | Additional lowercase substrings that mark a file as bonus content |

### Environment variable examples

```bash
PARSARR_SONARR__API_KEY=abc123
PARSARR_QBITTORRENT__URL=http://qbittorrent:8080
PARSARR_PLACEMENT_MODE=hardlink
PARSARR_LOG_LEVEL=DEBUG
```

### Extending bonus-content detection

Parsarr includes a default set of patterns for identifying bonus content (featurettes, commentaries, production materials, etc.). To add custom patterns:

```yaml
extra_patterns:
  - "my custom pattern"
  - "another pattern"
```

Patterns are matched case-insensitively as substrings of the filename. The built-in list is always active alongside any additions.

---

## Development

```bash
git clone https://github.com/MMart221/parsarr.git
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
│   ├── main.py              # FastAPI app factory, page routes, startup
│   ├── config.py            # Settings loader (config.yaml + env vars)
│   ├── cli.py               # CLI commands: serve, inspect, test
│   ├── jobs.py              # SQLite job store and Job dataclass
│   ├── intake.py            # On Grab orchestrator: poll → classify → reroute → map
│   ├── mapper.py            # Auto-map torrent title to Sonarr series
│   ├── placer.py            # Reorganize and place files into library path
│   ├── qb_client.py         # qBittorrent WebUI API client
│   ├── api/
│   │   └── routes.py        # All REST endpoints + webhook receiver
│   ├── arr/
│   │   ├── client.py        # Shared async HTTP client (httpx)
│   │   └── sonarr.py        # Sonarr API: series lookup, RescanSeries
│   ├── core/
│   │   ├── inspector.py     # Folder scanner + classify_tree (virtual file list)
│   │   ├── processor.py     # File operations: flatten, split seasons, stage extras
│   │   └── staging.py       # Staging slot lifecycle
│   ├── frontend/
│   │   ├── templates/       # Jinja2 templates (base, queue, job_detail, add, settings)
│   │   └── static/          # main.css, main.js
│   └── webhook/
│       └── schemas.py       # Pydantic models for Sonarr On Grab payload
├── tests/
│   ├── conftest.py
│   ├── test_inspector.py
│   └── test_processor.py
├── .github/
│   └── workflows/
│       └── publish-image.yml
├── config.yaml.example
├── Dockerfile
└── docker-compose.yml
```

---

## Project status

Parsarr is a personal project built to solve a specific workflow problem. It is public in case others find it useful. Pull requests and forks are welcome.

## License

GPL-3.0-or-later
