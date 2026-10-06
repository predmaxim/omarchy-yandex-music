"""On-disk copies of liked tracks (<cache>/predmaxim.yandex-music/tracks/<id>.mp3) and of covers
(covers/<sha1 of url>.jpg), LRU by mtime."""
import os
import shutil
import time
import urllib.request
from pathlib import Path

DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "predmaxim.yandex-music" / "tracks"
LIMIT = 2 << 30
COVER_LIMIT = 200 << 20


def fetch(url, path):
    with urllib.request.urlopen(url, timeout=30) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)


def trim(d, limit=LIMIT, pattern="*.mp3"):
    """Delete the least recently used files (play touches mtime) until under the limit."""
    parts = list(d.glob("*.part"))
    for f in parts[:]:
        if time.time() - f.stat().st_mtime > 3600:  # abandoned download
            f.unlink(); parts.remove(f)
    files = sorted(d.glob(pattern), key=lambda f: f.stat().st_mtime)
    total = sum(f.stat().st_size for f in files + parts)
    for f in files:
        if total <= limit:
            break
        total -= f.stat().st_size
        f.unlink()
