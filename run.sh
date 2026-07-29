#!/bin/bash
# Called by the Shortcut. Fills in your Spotify app credentials below,
# then hands the dictated song name off to play_spotify.py.

export SPOTIFY_CLIENT_ID=""
export SPOTIFY_CLIENT_SECRET=""
export SPOTIFY_REDIRECT_URI="http://127.0.0.1:8888/callback"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$DIR/venv/bin/python" "$DIR/play_spotify.py" "$@"
