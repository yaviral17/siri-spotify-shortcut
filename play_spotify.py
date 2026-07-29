#!/usr/bin/env python3
import os
import re
import subprocess
import sys
import time

import spotipy
from spotipy.oauth2 import SpotifyOAuth

CACHE_PATH = os.path.expanduser("~/.cache/spotify_siri_token")
SCOPE = (
    "user-read-playback-state user-modify-playback-state "
    "user-library-read user-follow-read "
    "playlist-read-private playlist-read-collaborative"
)

MY_TRIGGERS = ("my ",)
ALBUM_TRIGGERS = ("album ", "the album ")
ARTIST_TRIGGERS = ("artist ", "songs by ", "music by ", "some ")

LIKED_SONGS_ALIASES = {
    "liked songs",
    "liked music",
    "liked tracks",
    "favorites",
    "favourite songs",
    "favourites",
}

SEARCH_LIMIT = 10
LIKED_SONGS_PLAY_LIMIT = 200


def best_match(items, query, fallback_to_popularity=True):
    """Spotify's search ranking is unreliable with small `limit` values,
    so fetch several candidates and pick the best one ourselves.

    fallback_to_popularity picks a "closest enough" item when nothing matches
    by name. That's the right call for Spotify search results (already
    filtered to relevant candidates), but wrong for scanning a user's own
    library, where an unrelated item has no business being "close enough" —
    there it should mean no match, so callers can try the next lookup.
    """
    if not items:
        return None
    query_lower = query.lower().strip()

    for item in items:
        if item["name"].lower() == query_lower:
            return item
    for item in items:
        if item["name"].lower().startswith(query_lower):
            return item
    word_boundary = re.compile(r"\b" + re.escape(query_lower) + r"\b")
    for item in items:
        if word_boundary.search(item["name"].lower()):
            return item
    if fallback_to_popularity:
        return max(items, key=lambda item: item.get("popularity", 0))
    return None


def get_client():
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.environ.get(
        "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"
    )
    if not client_id or not client_secret:
        print("Missing SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET env vars")
        sys.exit(1)

    auth_manager = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=SCOPE,
        cache_path=CACHE_PATH,
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def fetch_saved_albums(sp):
    albums = []
    offset = 0
    while True:
        page = sp.current_user_saved_albums(limit=50, offset=offset)
        items = page.get("items", [])
        if not items:
            break
        albums.extend(item["album"] for item in items)
        offset += 50
        if offset >= page.get("total", 0):
            break
    return albums


def fetch_followed_artists(sp):
    artists = []
    after = None
    while True:
        page = sp.current_user_followed_artists(limit=50, after=after)
        artists_page = page.get("artists", {})
        items = artists_page.get("items", [])
        artists.extend(items)
        after = artists_page.get("cursors", {}).get("after")
        if not after or not items:
            break
    return artists


def fetch_user_playlists(sp):
    playlists = []
    offset = 0
    while True:
        page = sp.current_user_playlists(limit=50, offset=offset)
        items = page.get("items", [])
        if not items:
            break
        playlists.extend(items)
        offset += 50
        if offset >= page.get("total", 0):
            break
    return playlists


def fetch_saved_tracks(sp, max_items=500):
    tracks = []
    offset = 0
    while len(tracks) < max_items:
        page = sp.current_user_saved_tracks(limit=50, offset=offset)
        items = page.get("items", [])
        if not items:
            break
        tracks.extend(item["track"] for item in items)
        offset += 50
        if offset >= page.get("total", 0):
            break
    return tracks[:max_items]


def wait_for_device(sp):
    for _ in range(5):
        devices = sp.devices().get("devices", [])
        computer = next((d for d in devices if d["type"] == "Computer"), None)
        if computer:
            return computer["id"]
        time.sleep(1)
    return None


def ensure_spotify_open():
    subprocess.run(["open", "-a", "Spotify"])
    time.sleep(2)


def play_context(sp, context_uri, label):
    ensure_spotify_open()
    device_id = wait_for_device(sp)
    sp.start_playback(device_id=device_id, context_uri=context_uri)
    print(f"Playing {label}")


def play_track_uri(sp, uri, label):
    ensure_spotify_open()
    device_id = wait_for_device(sp)
    try:
        if device_id:
            sp.start_playback(device_id=device_id, uris=[uri])
        else:
            sp.start_playback(uris=[uri])
        print(f"Playing: {label}")
    except spotipy.SpotifyException as e:
        print(f"start_playback failed ({e}), opening URI instead")
        subprocess.run(["open", uri])


def handle_album(sp, query):
    saved = best_match(fetch_saved_albums(sp), query, fallback_to_popularity=False)
    if saved:
        play_context(sp, saved["uri"], f"saved album: {saved['name']}")
        return

    results = sp.search(q=query, type="album", limit=SEARCH_LIMIT)
    albums = results.get("albums", {}).get("items", [])
    album = best_match(albums, query)
    if not album:
        print(f"No album found for: {query}")
        sys.exit(1)
    play_context(
        sp, album["uri"], f"album: {album['name']} — {album['artists'][0]['name']}"
    )


def handle_artist(sp, query):
    followed = best_match(fetch_followed_artists(sp), query, fallback_to_popularity=False)
    if followed:
        play_context(sp, followed["uri"], f"followed artist: {followed['name']}")
        return

    results = sp.search(q=query, type="artist", limit=SEARCH_LIMIT)
    artists = results.get("artists", {}).get("items", [])
    artist = best_match(artists, query)
    if not artist:
        print(f"No artist found for: {query}")
        sys.exit(1)
    play_context(sp, artist["uri"], f"artist: {artist['name']}")


def handle_track(sp, query):
    tracks = []
    match_name = query
    m = re.match(r"^(.*)\s+by\s+(.*)$", query, re.IGNORECASE)
    if m:
        track_name, artist_name = m.group(1).strip(), m.group(2).strip()
        match_name = track_name
        field_query = f'track:"{track_name}" artist:"{artist_name}"'
        results = sp.search(q=field_query, type="track", limit=SEARCH_LIMIT)
        tracks = results.get("tracks", {}).get("items", [])

    if not tracks:
        results = sp.search(q=query, type="track", limit=SEARCH_LIMIT)
        tracks = results.get("tracks", {}).get("items", [])

    track = best_match(tracks, match_name)
    if not track:
        print(f"No track found for: {query}")
        sys.exit(1)

    label = f"{track['name']} — {track['artists'][0]['name']}"
    play_track_uri(sp, track["uri"], label)


def play_liked_songs(sp):
    tracks = fetch_saved_tracks(sp, max_items=LIKED_SONGS_PLAY_LIMIT)
    if not tracks:
        print("No liked songs found in your library.")
        sys.exit(1)
    uris = [t["uri"] for t in tracks]
    ensure_spotify_open()
    device_id = wait_for_device(sp)
    sp.start_playback(device_id=device_id, uris=uris)
    print(f"Playing your Liked Songs ({len(uris)} tracks)")


def handle_mine(sp, remainder):
    remainder_lower = remainder.lower().strip()

    if remainder_lower in LIKED_SONGS_ALIASES:
        play_liked_songs(sp)
        return

    playlist = best_match(fetch_user_playlists(sp), remainder, fallback_to_popularity=False)
    if playlist:
        play_context(sp, playlist["uri"], f"playlist: {playlist['name']}")
        return

    album = best_match(fetch_saved_albums(sp), remainder, fallback_to_popularity=False)
    if album:
        play_context(
            sp,
            album["uri"],
            f"saved album: {album['name']} — {album['artists'][0]['name']}",
        )
        return

    artist = best_match(fetch_followed_artists(sp), remainder, fallback_to_popularity=False)
    if artist:
        play_context(sp, artist["uri"], f"followed artist: {artist['name']}")
        return

    track = best_match(fetch_saved_tracks(sp), remainder, fallback_to_popularity=False)
    if track:
        label = f"{track['name']} — {track['artists'][0]['name']} (liked song)"
        play_track_uri(sp, track["uri"], label)
        return

    print(
        f"Couldn't find '{remainder}' in your playlists, saved albums, "
        "followed artists, or liked songs. Falling back to a general search."
    )
    handle_track(sp, remainder)


def main():
    if len(sys.argv) < 2:
        print("Usage: play_spotify.py <song/album/artist query>")
        sys.exit(1)

    query = " ".join(sys.argv[1:]).strip()
    sp = get_client()
    lowered = query.lower()

    for trigger in MY_TRIGGERS:
        if lowered.startswith(trigger):
            handle_mine(sp, query[len(trigger):].strip())
            return

    for trigger in ALBUM_TRIGGERS:
        if lowered.startswith(trigger):
            handle_album(sp, query[len(trigger):].strip())
            return

    for trigger in ARTIST_TRIGGERS:
        if lowered.startswith(trigger):
            handle_artist(sp, query[len(trigger):].strip())
            return

    handle_track(sp, query)


if __name__ == "__main__":
    main()
