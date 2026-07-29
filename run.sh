#!/bin/bash
# Called by the Shortcut. Loads credentials from .env (see .env.example),
# then hands the dictated song/album/artist text off to play_spotify.py.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$DIR/.env" ]; then
    set -a
    source "$DIR/.env"
    set +a
else
    echo "Missing .env file. Copy .env.example to .env and fill in your Spotify credentials." >&2
    exit 1
fi

"$DIR/venv/bin/python" "$DIR/play_spotify.py" "$@"
