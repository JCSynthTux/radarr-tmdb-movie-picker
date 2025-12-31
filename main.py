#!/usr/bin/env python3
import os
import sys
import time
import argparse
from typing import Optional, List, Dict, Set, Tuple, Any

import tmdbsimple as tmdb
from pyarr import RadarrAPI


def env(name: str, default: Optional[str] = None, required: bool = False) -> str:
    v = os.getenv(name, default)
    if required and (v is None or str(v).strip() == ""):
        raise SystemExit(f"Missing required env var: {name}")
    return str(v)


def parse_year(date_str: str) -> Optional[int]:
    if not date_str:
        return None
    y = date_str.split("-")[0]
    return int(y) if y.isdigit() else None


def discover_movies(
    original_language: str,
    include_genre_ids: str,
    min_vote_avg: float,
    min_vote_count: int,
    year_from: int,
    year_to: int,
    max_pages: int,
) -> List[Dict[str, Any]]:
    d = tmdb.Discover()
    all_results: List[Dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        data = d.movie(
            sort_by="primary_release_date.desc",
            include_adult=False,
            include_video=False,
            page=page,
            with_original_language=original_language,
            with_genres=include_genre_ids,
            vote_average_gte=min_vote_avg,
            vote_count_gte=min_vote_count,
            primary_release_date_gte=f"{year_from}-01-01",
            primary_release_date_lte=f"{year_to}-12-31",
        )

        results = data.get("results") or []
        if not results:
            break

        all_results.extend(results)

        total_pages = int(data.get("total_pages", page))
        if page >= total_pages:
            break

        time.sleep(0.25)

    return all_results


def radarr_existing_tmdb_ids(radarr: RadarrAPI) -> Set[int]:
    ids: Set[int] = set()
    for m in radarr.get_movie() or []:
        tmdb_id = m.get("tmdbId")
        if isinstance(tmdb_id, int):
            ids.add(tmdb_id)
    return ids


def radarr_default_root_folder(radarr: RadarrAPI) -> str:
    roots = radarr.get_root_folder() or []
    if not roots:
        raise RuntimeError("Radarr has no root folders configured.")
    # Radarr has no explicit 'default root' in API; first configured root is a good default.
    path = roots[0].get("path")
    if not path:
        raise RuntimeError("Radarr root folder object missing 'path'.")
    return path


def resolve_quality_profile_id(radarr: RadarrAPI, qp: Optional[str]) -> int:
    profiles = radarr.get_quality_profile() or []
    if not profiles:
        raise RuntimeError("Radarr has no quality profiles.")

    if not qp:
        return int(profiles[0]["id"])

    qp = qp.strip()
    if qp.isdigit():
        return int(qp)

    for p in profiles:
        if (p.get("name") or "").strip().lower() == qp.lower():
            return int(p["id"])

    raise RuntimeError(f"Quality profile '{qp}' not found in Radarr.")


def resolve_tag_ids(radarr: RadarrAPI, tags: List[str]) -> List[int]:
    """
    Accepts tag names or numeric IDs. Creates missing tags by name.
    Uses pyarr.create_tag(label) / create_tag(label=...) rather than passing a dict,
    to avoid Radarr 400 JSON type errors in some pyarr versions.
    """
    if not tags:
        return []

    existing = radarr.get_tag() or []
    name_to_id = {(t.get("label") or "").lower(): int(t["id"]) for t in existing if "id" in t}

    resolved: List[int] = []
    for raw in tags:
        raw = raw.strip()
        if not raw:
            continue

        if raw.isdigit():
            resolved.append(int(raw))
            continue

        key = raw.lower()
        if key in name_to_id:
            resolved.append(name_to_id[key])
            continue

        # Create tag if missing
        try:
            created = radarr.create_tag(raw)          # common pyarr signature
        except TypeError:
            created = radarr.create_tag(label=raw)    # alternate signature

        resolved.append(int(created["id"]))
        name_to_id[key] = int(created["id"])

    # dedupe while preserving order
    out: List[int] = []
    seen = set()
    for tid in resolved:
        if tid not in seen:
            out.append(tid)
            seen.add(tid)
    return out


def radarr_lookup_movie_by_tmdb(radarr: RadarrAPI, tmdb_id: int) -> Dict[str, Any]:
    """
    Radarr lookup endpoint supports term=tmdb:<id>.
    Different pyarr versions expose lookup_movie with different parameter names,
    so we try a few variants.
    """
    term = f"tmdb:{tmdb_id}"

    # Try keyword 'term='
    try:
        res = radarr.lookup_movie(term=term)
    except TypeError:
        res = None

    # Try positional (term as first arg)
    if res is None:
        try:
            res = radarr.lookup_movie(term)
        except TypeError:
            res = None

    # Try keyword 'query='
    if res is None:
        try:
            res = radarr.lookup_movie(query=term)
        except TypeError:
            res = None

    if res is None:
        raise RuntimeError("pyarr RadarrAPI.lookup_movie signature not compatible (term/query/positional all failed).")

    if isinstance(res, list):
        if not res:
            raise RuntimeError(f"Radarr lookup returned no results for term={term}")
        return res[0]

    if isinstance(res, dict):
        return res

    raise RuntimeError(f"Unexpected lookup_movie() return type: {type(res)}")


def add_movie_to_radarr(
    radarr: RadarrAPI,
    tmdb_id: int,
    title: str,
    year: Optional[int],
    root_folder: str,
    quality_profile_id: int,
    tag_ids: List[int],
    monitored: bool,
    minimum_availability: str,
    dry_run: bool,
) -> None:
    if dry_run:
        print(f"[DRY_RUN] Would add: {title} ({year}) tmdbId={tmdb_id}")
        return

    movie_obj = radarr_lookup_movie_by_tmdb(radarr, tmdb_id)

    # Your pyarr expects: add_movie(movie_dict, root_dir, quality_profile_id, ...)
    created = radarr.add_movie(
        movie_obj,
        root_folder,
        quality_profile_id,
        monitored=monitored,
        tags=tag_ids if tag_ids else None,
        minimum_availability=minimum_availability,
    )

    if isinstance(created, dict):
        print(
            f"Added: {created.get('title', title)} ({created.get('year', year)}) "
            f"tmdbId={created.get('tmdbId', tmdb_id)} radarrId={created.get('id')}"
        )
    else:
        print(f"Added: {title} ({year}) tmdbId={tmdb_id} (Radarr response type: {type(created)})")


def main() -> int:
    ap = argparse.ArgumentParser(description="Discover Korean horror-ish movies from TMDb and add to Radarr (tmdbsimple + pyarr).")

    # Radarr options
    ap.add_argument("--dry-run", action="store_true", default=(env("DRY_RUN", "false").lower() == "true"),
                    help="Print what would be added, but do not add to Radarr.")
    ap.add_argument("--tags", default=env("RADARR_TAGS", ""),
                    help="Comma-separated tag names or IDs to apply in Radarr.")
    ap.add_argument("--quality-profile", default=env("RADARR_QUALITY_PROFILE", ""),
                    help="Quality profile name or ID (default: Radarr first profile).")
    ap.add_argument("--root-folder", default=env("RADARR_ROOT_FOLDER", ""),
                    help="Root folder path (default: Radarr first root folder).")
    ap.add_argument("--monitored", default=env("MONITORED", "true"), choices=["true", "false"],
                    help="Whether added movies are monitored.")
    ap.add_argument("--minimum-availability", default=env("MINIMUM_AVAILABILITY", "released"),
                    help="released|announced|inCinemas|preDB (Radarr minimum availability).")

    # TMDb filters
    ap.add_argument("--min-vote-avg", type=float, default=float(env("MIN_VOTE_AVG", "7.0")))
    ap.add_argument("--min-vote-count", type=int, default=int(env("MIN_VOTE_COUNT", "150")))
    ap.add_argument("--year-from", type=int, default=int(env("YEAR_FROM", "2000")))
    ap.add_argument("--year-to", type=int, default=int(env("YEAR_TO", str(time.gmtime().tm_year))))
    ap.add_argument("--max-pages", type=int, default=int(env("MAX_PAGES", "3")))
    ap.add_argument("--genres", default=env("INCLUDE_GENRE_IDS", "27,53"),
                    help="TMDb genre IDs, comma-separated. Horror=27 Thriller=53.")
    ap.add_argument("--lang", default=env("ORIGINAL_LANGUAGE", "ko"),
                    help="TMDb original language code (default: ko).")

    args = ap.parse_args()

    # Required env
    tmdb.API_KEY = env("TMDB_API_KEY", required=True)
    radarr_url = env("RADARR_URL", required=True).rstrip("/")
    radarr_key = env("RADARR_API_KEY", required=True)

    # Radarr client
    radarr = RadarrAPI(radarr_url, radarr_key)

    # Resolve config
    root_folder = args.root_folder.strip() or radarr_default_root_folder(radarr)
    quality_profile_id = resolve_quality_profile_id(radarr, args.quality_profile.strip() or None)
    tag_ids = resolve_tag_ids(radarr, [t for t in args.tags.split(",") if t.strip()])
    monitored = args.monitored == "true"

    print(f"Radarr root folder: {root_folder}")
    print(f"Radarr qualityProfileId: {quality_profile_id}")
    print(f"Radarr tags: {tag_ids if tag_ids else 'none'}")
    print(f"Dry run: {args.dry_run}\n")

    existing = radarr_existing_tmdb_ids(radarr)
    print(f"Radarr currently has {len(existing)} movies with tmdbId.\n")

    candidates = discover_movies(
        original_language=args.lang,
        include_genre_ids=args.genres,
        min_vote_avg=args.min_vote_avg,
        min_vote_count=args.min_vote_count,
        year_from=args.year_from,
        year_to=args.year_to,
        max_pages=args.max_pages,
    )

    print(f"TMDb candidates fetched: {len(candidates)}")

    seen: Set[int] = set()
    to_add: List[Tuple[int, str, Optional[int], str]] = []

    for m in candidates:
        tmdb_id = m.get("id")
        if not isinstance(tmdb_id, int) or tmdb_id in seen:
            continue
        seen.add(tmdb_id)

        if tmdb_id in existing:
            continue

        title = m.get("title") or m.get("original_title") or f"tmdb:{tmdb_id}"
        release_date = m.get("release_date") or "????-??-??"
        year = parse_year(m.get("release_date") or "")
        to_add.append((tmdb_id, title, year, release_date))

    print(f"Movies to add: {len(to_add)}\n")

    for tmdb_id, title, year, release_date in to_add:
        print(f"{release_date} | {title} | tmdbId={tmdb_id}")
        add_movie_to_radarr(
            radarr=radarr,
            tmdb_id=tmdb_id,
            title=title,
            year=year,
            root_folder=root_folder,
            quality_profile_id=quality_profile_id,
            tag_ids=tag_ids,
            monitored=monitored,
            minimum_availability=args.minimum_availability,
            dry_run=args.dry_run,
        )

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)