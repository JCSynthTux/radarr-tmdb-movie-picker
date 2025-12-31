#!/usr/bin/env python3
import os
import sys
import time
import argparse
from typing import Optional, List, Dict, Set, Tuple

import tmdbsimple as tmdb
from pyarr import RadarrAPI


def env(name: str, default=None, required: bool = False):
    v = os.getenv(name, default)
    if required and (v is None or str(v).strip() == ""):
        raise SystemExit(f"Missing required env var: {name}")
    return v


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
) -> List[Dict]:
    d = tmdb.Discover()
    all_results: List[Dict] = []

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
    for m in radarr.get_movie():
        tmdb_id = m.get("tmdbId")
        if isinstance(tmdb_id, int):
            ids.add(tmdb_id)
    return ids


def radarr_default_root_folder(radarr: RadarrAPI) -> str:
    roots = radarr.get_root_folder()
    if not roots:
        raise RuntimeError("Radarr has no root folders configured.")
    # Radarr has no explicit 'default' root in API; we use the first configured one.
    return roots[0]["path"]


def resolve_quality_profile_id(radarr: RadarrAPI, qp: Optional[str]) -> int:
    profiles = radarr.get_quality_profile()
    if not profiles:
        raise RuntimeError("Radarr has no quality profiles.")

    if not qp:
        # Use first profile if not specified
        return int(profiles[0]["id"])

    qp = qp.strip()
    if qp.isdigit():
        return int(qp)

    for p in profiles:
        if (p.get("name") or "").strip().lower() == qp.lower():
            return int(p["id"])

    raise RuntimeError(f"Quality profile '{qp}' not found in Radarr.")


def resolve_tag_ids(radarr: RadarrAPI, tags: List[str]) -> List[int]:
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

        try:
            created = radarr.create_tag(raw)          
        except TypeError:
            created = radarr.create_tag(label=raw)    

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


def add_movie(
    radarr: RadarrAPI,
    tmdb_id: int,
    title: str,
    year: Optional[int],
    root_folder: str,
    quality_profile_id: int,
    tag_ids: List[int],
    monitored: bool,
    search_on_add: bool,
    minimum_availability: str,
    dry_run: bool,
) -> None:
    payload = dict(
        tmdbId=tmdb_id,
        title=title,
        year=year,
        qualityProfileId=quality_profile_id,
        rootFolderPath=root_folder,
        monitored=monitored,
        minimumAvailability=minimum_availability,
        addOptions=dict(searchForMovie=search_on_add),
    )
    if tag_ids:
        payload["tags"] = tag_ids

    if dry_run:
        print(f"[DRY_RUN] Would add: {title} ({year}) tmdbId={tmdb_id}")
        return

    created = radarr.add_movie(payload)
    print(f"Added: {created.get('title')} ({created.get('year')}) tmdbId={created.get('tmdbId')}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Discover Korean horror-ish movies from TMDb and add to Radarr.")
    ap.add_argument("--dry-run", action="store_true", help="Print what would be added, but do not add to Radarr.")
    ap.add_argument("--tags", default=env("RADARR_TAGS", ""), help="Comma-separated tag names or IDs to apply in Radarr.")
    ap.add_argument("--quality-profile", default=env("RADARR_QUALITY_PROFILE", ""), help="Quality profile name or ID (default: Radarr first profile).")
    ap.add_argument("--root-folder", default=env("RADARR_ROOT_FOLDER", ""), help="Root folder path (default: Radarr first root folder).")

    # TMDb filters
    ap.add_argument("--min-vote-avg", type=float, default=float(env("MIN_VOTE_AVG", "7.0")))
    ap.add_argument("--min-vote-count", type=int, default=int(env("MIN_VOTE_COUNT", "150")))
    ap.add_argument("--year-from", type=int, default=int(env("YEAR_FROM", "2000")))
    ap.add_argument("--year-to", type=int, default=int(env("YEAR_TO", str(time.gmtime().tm_year))))
    ap.add_argument("--max-pages", type=int, default=int(env("MAX_PAGES", "3")))
    ap.add_argument("--genres", default=env("INCLUDE_GENRE_IDS", "27,53"), help="TMDb genre IDs, comma-separated.")
    ap.add_argument("--lang", default=env("ORIGINAL_LANGUAGE", "ko"), help="TMDb original language code (default: ko).")

    # Radarr add behavior
    ap.add_argument("--monitored", default=env("MONITORED", "true"), choices=["true", "false"])
    ap.add_argument("--search-on-add", default=env("SEARCH_ON_ADD", "true"), choices=["true", "false"])
    ap.add_argument("--minimum-availability", default=env("MINIMUM_AVAILABILITY", "released"))

    args = ap.parse_args()

    tmdb.API_KEY = env("TMDB_API_KEY", required=True)
    radarr = RadarrAPI(env("RADARR_URL", required=True).rstrip("/"), env("RADARR_API_KEY", required=True))

    root_folder = args.root_folder.strip() or radarr_default_root_folder(radarr)
    quality_profile_id = resolve_quality_profile_id(radarr, args.quality_profile.strip() or None)
    tag_ids = resolve_tag_ids(radarr, [t for t in args.tags.split(",") if t.strip()])

    monitored = args.monitored == "true"
    search_on_add = args.search_on_add == "true"

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

        title = m.get("title") or m.get("original_title") or f"tmdb:{tmdb_id}"
        release_date = m.get("release_date") or "????-??-??"
        year = parse_year(m.get("release_date") or "")

        if tmdb_id in existing:
            # Already present
            continue

        to_add.append((tmdb_id, title, year, release_date))

    print(f"Movies to add: {len(to_add)}\n")
    for tmdb_id, title, year, release_date in to_add:
        print(f"{release_date} | {title} | tmdbId={tmdb_id}")
        add_movie(
            radarr=radarr,
            tmdb_id=tmdb_id,
            title=title,
            year=year,
            root_folder=root_folder,
            quality_profile_id=quality_profile_id,
            tag_ids=tag_ids,
            monitored=monitored,
            search_on_add=search_on_add,
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