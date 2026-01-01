# Radarr TMDb Movie Picker

A small, opinionated automation tool that discovers movies from **TMDb** based on custom criteria (language, genre, ratings, year, etc.) and adds them to **Radarr**.

Designed to run **headlessly** as a Docker container and **periodically** as a Kubernetes CronJob.

This project was built to solve a common gap in the *arr ecosystem:  
**reliable, curated, and fully controllable “wanted media” automation without relying on public lists.**

---

## ✨ Features

- Discover movies via **TMDb Discover API**
- Filter by:
  - Original language (e.g. Korean)
  - Genre IDs (e.g. Horror, Thriller)
  - Minimum rating & vote count
  - Release year range
- De-duplicate against existing Radarr library (via TMDb ID)
- Add movies to Radarr with:
  - Quality profile (by name or ID)
  - Root folder (or Radarr default)
  - Tags (auto-created if missing)
- **Dry-run mode** for safe testing
- Fully configurable via **environment variables**
- Works cleanly with:
  - Docker
  - Kubernetes CronJobs
  - FluxCD / GitOps workflows

---

## 🧱 Tech Stack

- Python 3.12
- [`tmdbsimple`](https://github.com/celiao/tmdbsimple) – TMDb API client
- [`pyarr`](https://github.com/lokenx/pyarr) – Radarr API client
- Docker / Kubernetes

---

## 🚀 How It Works

1. Query TMDb Discover API for candidate movies
2. Apply rating, vote count, language, genre, and year filters
3. Compare TMDb IDs against movies already present in Radarr
4. Lookup missing movies in Radarr (`tmdb:<id>`)
5. Add them with your chosen Radarr settings

No public lists. No RSS hacks. Full control.

---

## 🔧 Configuration

All configuration is done via **environment variables** (CLI flags override env vars if used).

### Required

| Variable | Description |
|--------|------------|
| `TMDB_API_KEY` | TMDb API key |
| `RADARR_URL` | Radarr base URL (must include `http://`) |
| `RADARR_API_KEY` | Radarr API key |

---

### Radarr Options

| Variable | Default | Description |
|--------|--------|------------|
| `RADARR_ROOT_FOLDER` | Radarr default | Root folder for added movies |
| `RADARR_QUALITY_PROFILE` | Radarr default | Profile **name or ID** |
| `RADARR_TAGS` | none | Comma-separated tag names or IDs |
| `MONITORED` | `true` | Whether movies are monitored |
| `MINIMUM_AVAILABILITY` | `released` | Radarr minimum availability |
| `DRY_RUN` | `false` | Print actions without adding |

---

### TMDb Filters

| Variable | Default | Description |
|--------|--------|------------|
| `ORIGINAL_LANGUAGE` | `ko` | Original language (ISO-639-1) |
| `INCLUDE_GENRE_IDS` | `27,53` | TMDb genre IDs (Horror, Thriller) |
| `MIN_VOTE_AVG` | `7.0` | Minimum rating |
| `MIN_VOTE_COUNT` | `150` | Minimum number of votes |
| `YEAR_FROM` | `2000` | Earliest release year |
| `YEAR_TO` | current year | Latest release year |
| `MAX_PAGES` | `3` | TMDb result pages to scan |

---

## 🧪 Local Usage

```bash
pip install tmdbsimple pyarr

export TMDB_API_KEY=...
export RADARR_URL=http://localhost:7878
export RADARR_API_KEY=...

export DRY_RUN=true

python main.py