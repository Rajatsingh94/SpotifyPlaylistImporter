#!/usr/bin/env python3
import argparse
import html
import os
import sys
import time
from pathlib import Path

import pandas as pd
import plistlib
import spotipy
from spotipy.oauth2 import SpotifyOAuth


def load_apple_xml(xml_path: Path, preferred_playlist: str | None):
    """
    Reads the Apple Music/iTunes XML (plist).
    Returns a list of dicts: [{"name": ..., "artist": ..., "year": ...}, ...]
    If preferred_playlist is provided and exists, only items from that playlist are used.
    Otherwise, falls back to all tracks under 'Tracks'.
    """
    with open(xml_path, "rb") as f:
        pl = plistlib.load(f)

    # Map id -> track dict
    tracks_dict = pl.get("Tracks", {})
    id_to_track = {}
    for _id, t in tracks_dict.items():
        id_to_track[int(t.get("Track ID", _id))] = t

    def normalize_track(t):
        name = html.unescape(t.get("Name", "")).strip()
        artist = html.unescape(t.get("Artist", "")).strip()
        year = t.get("Year")
        return {"name": name, "artist": artist, "year": int(year) if isinstance(year, int) else None}

    items = []

    # If there is a Playlists section and user named a playlist, use that
    playlists = pl.get("Playlists", [])
    selected = None
    if preferred_playlist:
        for p in playlists:
            if p.get("Name", "").strip().lower() == preferred_playlist.strip().lower():
                selected = p
                break

    if selected:
        for it in selected.get("Playlist Items", []):
            tid = it.get("Track ID")
            if tid and tid in id_to_track:
                items.append(normalize_track(id_to_track[tid]))
    else:
        # No playlist name found: use all tracks
        for t in id_to_track.values():
            items.append(normalize_track(t))

    # Deduplicate while keeping order
    seen = set()
    unique = []
    for it in items:
        key = (it["name"].lower(), it["artist"].lower())
        if it["name"] and it["artist"] and key not in seen:
            seen.add(key)
            unique.append(it)

    return unique


def spotify_client(scope: str = "playlist-modify-public playlist-modify-private"):
    auth = SpotifyOAuth(scope=scope)
    return spotipy.Spotify(auth_manager=auth)


def create_playlist(sp: spotipy.Spotify, playlist_name: str, public: bool = False, description: str = ""):
    me = sp.current_user()
    uid = me["id"]
    playlist = sp.user_playlist_create(uid, playlist_name, public=public, description=description)
    return playlist["id"]


def search_track(sp: spotipy.Spotify, name: str, artist: str, year: int | None):
    """
    Do a couple of search passes for better hit rate.
    Returns a Spotify track id or None.
    """
    candidates = []

    queries = [
        f'track:"{name}" artist:"{artist}"',
    ]
    if year:
        queries.insert(0, f'track:"{name}" artist:"{artist}" year:{year}')
    # A more flexible fallback (artist without quotes to handle features)
    queries.append(f'{name} {artist}')

    for q in queries:
        try:
            res = sp.search(q=q, type="track", limit=3)
        except spotipy.SpotifyException as e:
            # Handle transient rate limits
            if e.http_status == 429:
                retry = int(e.headers.get("Retry-After", "2"))
                time.sleep(retry + 1)
                res = sp.search(q=q, type="track", limit=3)
            else:
                raise

        items = (res.get("tracks") or {}).get("items", [])
        for it in items:
            candidates.append(it)

        # If we get an exact-ish match quickly, return
        for it in items:
            tname = it["name"].strip().lower()
            anames = {a["name"].strip().lower() for a in it["artists"]}
            if name.strip().lower() == tname and artist.strip().lower() in anames:
                return it["id"]

        if items:
            # Return first result of this pass if we found anything
            return items[0]["id"]

    return None


def add_tracks_in_batches(sp: spotipy.Spotify, playlist_id: str, track_ids: list[str]):
    for i in range(0, len(track_ids), 100):
        chunk = track_ids[i : i + 100]
        sp.playlist_add_items(playlist_id, chunk)

def find_user_playlist_by_name(sp, name: str):
    """Find a playlist by exact name (case-insensitive) in the current user's library."""
    name_lc = name.strip().lower()
    me = sp.current_user()
    uid = me["id"]

    limit = 50
    offset = 0
    candidate = None
    while True:
        page = sp.current_user_playlists(limit=limit, offset=offset)
        items = page.get("items", [])
        if not items:
            break
        for p in items:
            if p.get("name", "").strip().lower() == name_lc:
                if p.get("owner", {}).get("id") == uid:
                    return p["id"]
                if candidate is None:
                    candidate = p["id"]
        offset += len(items)
        if len(items) < limit:
            break
    return candidate

def clear_playlist(sp, playlist_id: str):
    """Remove all items from a playlist (Spotify doesn’t have a direct 'clear' call)."""
    uris = []
    limit = 100
    offset = 0
    while True:
        resp = sp.playlist_items(playlist_id, fields="items(track(uri)),next", limit=limit, offset=offset)
        items = resp.get("items", [])
        if not items:
            break
        for it in items:
            track = it.get("track") or {}
            uri = track.get("uri")
            if uri:
                uris.append(uri)
        if not resp.get("next"):
            break
        offset += limit

    for i in range(0, len(uris), 100):
        sp.playlist_remove_all_occurrences_of_items(playlist_id, uris[i:i+100])


def main():
    ap = argparse.ArgumentParser(description="Create a Spotify playlist from an Apple Music XML export.")
    ap.add_argument("--xml", required=True, help="Path to Apple Music XML (playlist export or full library).")
    ap.add_argument("--apple-playlist", help="Name of the Apple Music playlist inside the XML (if using full library).")
    ap.add_argument("--spotify-name", help="Name for the new Spotify playlist (ignored if --use-existing is set).")
    ap.add_argument("--public", action="store_true", help="Make the Spotify playlist public (default: private).")
    ap.add_argument("--log-not-found", default="not_found.csv", help="CSV file to log tracks that were not found.")
    ap.add_argument("--use-existing", help="Use an existing Spotify playlist by name instead of creating a new one.")
    ap.add_argument("--mode", choices=["append", "replace"], default="append", help="How to modify the existing playlist: append (default) or replace its contents.")
    args = ap.parse_args()

    # Check Spotify env vars exist
    for var in ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "SPOTIPY_REDIRECT_URI"):
        if not os.getenv(var):
            print(f"ERROR: environment variable {var} is not set.", file=sys.stderr)
            sys.exit(2)

    items = load_apple_xml(Path(args.xml), args.apple_playlist)
    if not items:
        print("No tracks found in XML (check file and playlist name).")
        sys.exit(1)

    sp = spotify_client()
    playlist_id = create_playlist(
        sp,
        playlist_name=args.spotify_name,
        public=args.public,
        description="Imported from Apple Music XML",
    )

    if args.use_existing:
        playlist_id = find_user_playlist_by_name(sp, args.use_existing)
        if not playlist_id:
            print(f"Playlist '{args.use_existing}' not found in your account.", file=sys.stderr)
            sys.exit(1)
        print(f"Using existing playlist: {args.use_existing}")
        if args.mode == "replace":
            print("Clearing existing playlist contents...")
            clear_playlist(sp, playlist_id)
    elif args.spotify_name:
        playlist_id = create_playlist(
            sp,
            playlist_name=args.spotify_name,
            public=args.public,
            description="Imported from Apple Music XML",
        )
        print(f"Created new playlist: {args.spotify_name}")
    else:
        print("You must provide either --spotify-name or --use-existing.", file=sys.stderr)
        sys.exit(1)

    found_ids, misses = [], []

    for it in items:
        sid = search_track(sp, it["name"], it["artist"], it["year"])
        if sid:
            found_ids.append(sid)
            print(f"✓ {it['name']} — {it['artist']}")
        else:
            misses.append(it)
            print(f"✗ NOT FOUND: {it['name']} — {it['artist']}")

    if found_ids:
        add_tracks_in_batches(sp, playlist_id, found_ids)

    print(f"\nDone. Added {len(found_ids)} tracks to '{args.spotify_name}'.")
    if misses:
        df = pd.DataFrame(misses)
        df.to_csv(args.log_not_found, index=False)
        print(f"{len(misses)} not found → logged to {args.log_not_found}")


if __name__ == "__main__":
    main()

