

# Parsarr

---

<p align="center">
  <img src="./parsarr/frontend/static/logo/11821b16-26c0-43a6-9613-a344827b4f37.png" alt="Parsarr" width="128" />
</p>

**Media import preprocessor for the \*arr stack.**

Parsarr helps with **release structure normalization**: messy folder trees, multi-season bundles, nested paths, bonus content mixed with main files, and sidecars that don't line up with what your library tools expect. It sits in front of Sonarr and qBittorrent. When Sonarr sends a release to qBittorrent, Parsarr can intercept it at **grab** time — before the download finishes — inspect the release's file list from metadata, and decide whether the layout needs intervention.

For releases that already look **standard**, Parsarr records a passthrough and leaves Sonarr's normal download path alone. For **problematic** structures, Parsarr takes ownership: it reroutes the download into a managed area, reorganizes files after completion in a separate work staging area, places the cleaned result directly into your library path, and triggers a Sonarr rescan. Sonarr only sees the normalized result, not the raw pack layout.

A lightweight web UI is included for manual intake, job monitoring, mapping overrides, and settings.



## Why Parsarr?

Tools like Sonarr expect a fairly predictable layout when importing: seasons in recognizable folders, main media files easy to find, subtitles and artwork paired with the right files. When a release doesn't match that shape — because of how it was packed — the import can fail quietly, import only part of the release, or leave you fixing paths by hand.

Common patterns that cause trouble:

- **Multi-season collections** — several seasons in one tree, or per-season folders that the importer won't split the way you need
- **Complete-series or bulk packs** — everything in one archive with a flat or uneven directory layout
- **Nested release trees** — media files buried several levels deep under extra folder layers
- **Bonus content mixed with main files** — commentaries, featurettes, extras, and menu assets sitting next to primary content with no clear separation
- **Orphaned sidecars** — subtitles, `.nfo` files, or images that won't move with the right file unless they're explicitly matched

Parsarr classifies and, when needed, restructures that material **before** Sonarr is left to interpret a finished download on its own.

---

## How it works

There are two intake paths.

### Path A — Sonarr-originated releases

```
Sonarr grabs a release → sends it to qBittorrent
    → Sonarr fires On Grab webhook to Parsarr
    → Parsarr reads the download ID from webhook
    → Parsarr polls qBittorrent until file metadata is ready
    → Parsarr classifies the virtual file tree

    If standard:
        → job recorded as passthrough
        → download stays in Sonarr's normal qB category and path
        → Sonarr/qBittorrent proceed as usual — Parsarr takes no action

    If problematic:
        → Parsarr reroutes the download (setLocation + setCategory)
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

### Path B — Manual intake

```
User pastes a download link into Parsarr UI
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

In qBittorrent, go to **View → Categories → Add category** and create a category named `parsarr-managed`.

This is the category Parsarr uses for rerouted and manually-added downloads. Sonarr must **not** be configured to auto-import from this category.

To verify: in Sonarr, go to **Settings → Download Clients → qBittorrent** and confirm the category field there (usually `sonarr`) does not match `parsarr-managed`.

### Step 3 — Pull the image and add Parsarr to your stack

```bash
docker pull ghcr.io/mmart221/parsarr:latest
```

Add the following to your existing `docker-compose.yml`:

```yaml
services:
  parsarr:
    image: ghcr.io/mmart221/parsarr:latest
    container_name: parsarr
    restart: unless-stopped
    ports:---

```bash
docker compose up -d parsarr
```

### Step 4 — Connect Sonarr to Parsarr

1. In Sonarr, go to **Settings → Connect → + Add Connection**
2. Choose **Webhook**
3. Fill in:
   - **Name:** Parsarr
   - **Triggers:** check **On Grab** only
   - **URL:** `http://YOUR_HOST_IP:8080/webhook/sonarr/grab`
   - **Method:** POST
   - **Secret:** paste the value from `webhook_secret` in your config (leave blank if not set)
4. Click **Test**

> **Important:** The trigger must be **On Grab** only. Parsarr intercepts at grab time so it can reroute problematic releases before the download completes.

### Step 5 — Open the Parsarr UI

Navigate to `http://localhost:8080` (or your host IP if running remotely).

### Step 6 — How it behaves from here

- **Standard releases** — recorded as passthrough, left entirely to Sonarr.
- **Problematic releases** — rerouted automatically, reorganized after download, placed, and rescanned. You'll see the job progress through states like `rerouted → processing → completed`.
- **Jobs needing mapping** — if Parsarr can't auto-map a release to a series, the job enters `awaiting_manual_mapping`. Open the job detail page to assign a series and continue.

---

## CLI reference

### `inspect <path>`

Classify a folder without modifying anything.

```bash
docker exec parsarr python -m parsarr.main inspect /media/downloads/some-release
```

### `test <path>`

Dry-run: show every planned file operation without executing any of them.

```bash
python -m parsarr.main test /path/to/release
```

---

## Configuration reference

| Key | Default | Description |
|-----|---------|-------------|
| `sonarr.url` | — | Sonarr base URL |
| `sonarr.api_key` | — | Sonarr API key (Settings → General) |
| `qbittorrent.url` | — | qBittorrent WebUI URL |
| `qbittorrent.username` | `admin` | qBittorrent login |
| `qbittorrent.password` | `adminadmin` | qBittorrent password |
| `parsarr_category` | `parsarr-managed` | qB category for Parsarr-owned downloads; Sonarr must not watch this |
| `managed_download_dir` | `/media/downloads/managed` | Where rerouted downloads land |
| `staging_dir` | `/media/staging` | Temporary work area for reorganization |
| `media_roots.tv` | `/media/tv` | Primary library root for placement |
| `placement_mode` | `move` | How files are placed: `move`, `copy`, or `hardlink` |
| `db_path` | `/data/parsarr.db` | SQLite job database |
| `webhook_secret` | `""` | If set, verified against `X-Parsarr-Secret` header |
| `log_level` | `INFO` | Python log level |
| `port` | `8080` | Port the server listens on |
| `extra_patterns` | (list) | Additional substrings that mark a file as bonus content |

### Environment variable examples

```bash
PARSARR_SONARR__API_KEY=abc123
PARSARR_QBITTORRENT__URL=http://qbittorrent:8080
PARSARR_PLACEMENT_MODE=hardlink
PARSARR_LOG_LEVEL=DEBUG
```

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
│   ├── main.py
│   ├── config.py
│   ├── cli.py
│   ├── jobs.py
│   ├── intake.py
│   ├── mapper.py
│   ├── placer.py
│   ├── qb_client.py
│   ├── api/routes.py
│   ├── arr/client.py
│   ├── arr/sonarr.py
│   ├── core/inspector.py
│   ├── core/processor.py
│   ├── core/staging.py
│   ├── frontend/templates/
│   └── frontend/static/
├── tests/
├── config.yaml.example
├── Dockerfile
└── docker-compose.yml
```

---

## Project status

Parsarr is a personal project built to solve a specific workflow problem. It is public in case others find it useful. Pull requests and forks are welcome. I might work on it in the future, but probably infrequently. 



## License

GPL-3.0-or-later
