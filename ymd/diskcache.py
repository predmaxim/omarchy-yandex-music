"""On-disk copies of liked tracks: <cache>/predmaxim.yandex-music/tracks/<id>.mp3, LRU by mtime."""
import os
import shutil
import urllib.request
from pathlib import Path

DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "predmaxim.yandex-music" / "tracks"
LIMIT = 2 << 30


def fetch(url, path):
    with urllib.request.urlopen(url, timeout=30) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)


def trim(d, limit=LIMIT):
    """Delete the least recently used files (play touches mtime) until under the limit."""
    files = sorted((f for f in d.glob("*.mp3")), key=lambda f: f.stat().st_mtime)
    total = sum(f.stat().st_size for f in files)
    for f in files:
        if total <= limit:
            break
        total -= f.stat().st_size
        f.unlink()
