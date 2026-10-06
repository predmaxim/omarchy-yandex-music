"""Queue, sources and the 3-track window kept in mpv's playlist.

mpv holds at most [previous, current, next]; self.loaded maps those playlist
positions to queue indices. Every playlist-pos change (media keys through
mpv-mpris, end of track, our own insert-at) goes through _on_pos, which slides
the window and sends wave feedback. A stream link is fetched right before it
is loaded: links expire.
"""
import asyncio
import logging
import os
import time
from . import diskcache, tracks

log = logging.getLogger("ymd")

WAVE = "user:onyourwave"
MOODS = ["all", "fun", "active", "calm", "sad"]
FADE_S = 3
FADE_IN = f"af=lavfi=[afade=t=in:d={FADE_S}]"  # per-file: mpv resets it with the next file
URL_TTL = 600
PAGE = 20
IDS_TTL = 300


class Player:
    def __init__(self, api, mpv, notify, cache_dir=None, download=None):
        self.api, self.mpv, self.notify = api, mpv, notify
        self.cache_dir, self.download = cache_dir or diskcache.DIR, download or diskcache.fetch
        self.urls, self.tasks, self.downloading = {}, set(), set()
        self.gen, self.duration, self.faded, self.radio_pending = 0, 0.0, False, False
        self.queue, self.index, self.loaded = [], -1, []
        self.source = {"type": "none", "title": "", "mood": ""}
        self.station, self.liked = None, set()
        self.playing, self.time_pos, self.last_end, self.error = False, 0.0, None, None
        self.search_text, self.results, self.search_page, self.search_total = "", [], 0, 0
        self.like_ids, self.like_ids_at, self.like_off, self.likes_page1 = [], None, 0, None
        self.loading = False
        self.lock = asyncio.Lock()

    # --- sources -----------------------------------------------------------
    async def load_likes(self):
        await self._likes_ids(True)

    async def _likes_ids(self, force=False):
        """Every liked id (cheap list); refreshed at most every 5 minutes."""
        if force or self.like_ids_at is None or time.monotonic() - self.like_ids_at > IDS_TTL:
            self.like_ids = [str(t.id) for t in (await self.api.users_likes_tracks()).tracks]
            self.like_ids_at = time.monotonic()
            self.liked = set(self.like_ids)

    async def start_likes(self):
        async with self.lock:
            self.station, self.queue = None, []
            self.source = {"type": "likes", "title": "", "mood": ""}
            await self._detach()
            self.loading = True
            self.notify()  # the source switch shows at once; the first page follows
            try:
                await self._likes_ids()
                if not self.like_ids:
                    self.error = "nothing to play"; return
                first = tuple(self.like_ids[:PAGE])
                if self.likes_page1 and self.likes_page1[0] == first:
                    self.queue, self.like_off = list(self.likes_page1[1]), len(first)
                else:
                    self.like_off = 0
                    await self._more_likes()
                    self.likes_page1 = (first, list(self.queue))
            finally:
                self.loading = False
                self.notify()

    async def _more_likes(self):
        ids = self.like_ids[self.like_off:self.like_off + PAGE]
        if ids:
            self.like_off += len(ids)
            self.queue += [tracks.info(t) for t in await self.api.tracks(ids)]

    async def _refill(self):
        """The queue is running out: next page / next rotor batch."""
        if self.station:
            await self._fetch_station()
        elif self.source["type"] == "likes":
            await self._more_likes()

    async def more(self):
        """The list was scrolled to its end: append the next page of what is shown."""
        async with self.lock:
            if self.loading or not self._has_more():
                return
            self.loading = True
            self.notify()
            try:
                if self.search_text:
                    self.search_page += 1
                    resp = await self.api.search(self.search_text, type_="track", page=self.search_page)
                    self.results += [tracks.info(t) for t in (resp.tracks.results or [])] if resp and resp.tracks else []
                else:
                    await self._refill()
            finally:
                self.loading = False
                self.notify()

    def _has_more(self):
        if self.search_text:
            return len(self.results) < self.search_total
        if self.station:
            return True
        return self.source["type"] == "likes" and self.like_off < len(self.like_ids)

    async def start_wave(self, mood):
        if mood:
            await self.api.rotor_station_settings2(WAVE, mood, "default", language="any")
        await self._start_station(WAVE, {"type": "wave", "title": "", "mood": mood or ""})

    async def start_track_wave(self, track_id):
        known = {t["id"]: t for t in self.queue + self.results}
        title = known.get(track_id, {}).get("title", "")
        await self._start_station(f"track:{track_id}", {"type": "track-wave", "title": title, "mood": ""}, play=True)

    async def _start_station(self, station, source, play=False):
        async with self.lock:
            self.station, self.queue, self.source = station, [], source
            await self._detach()
            self.loading = True
            self.notify()  # the source switch shows at once; the first batch follows
            try:
                await self._fetch_station()
            finally:
                self.loading = False
            if not self.queue:
                self.error = "nothing to play"; self.notify(); return
            self.radio_pending = True  # radioStarted goes out with the first play
            if play:
                await self._play(0)
            else:
                self.notify()

    async def _detach(self):
        """New source: forget the old window; a track that is playing keeps playing alone."""
        self.gen += 1
        self.index, self.radio_pending = -1, False
        if self.loaded:
            await self.mpv.command("playlist-clear")  # keeps only the current entry
        self.loaded = []

    async def _fetch_station(self):
        last = self.queue[-1]["id"] if self.queue else None
        r = await self.api.rotor_station_tracks(self.station, queue=last)
        self.queue += [tracks.info(s.track) for s in (r.sequence if r else None) or [] if s.track]

    async def search(self, text):
        async with self.lock:
            text = text.strip()
            self.search_text = text
            if not text:
                self.results = []
            else:
                resp = await self.api.search(text, type_="track")
                self.results = [tracks.info(t) for t in (resp.tracks.results or [])] if resp.tracks else []
                self.search_page = 0
                self.search_total = (getattr(resp.tracks, "total", 0) or 0) if resp.tracks else 0
            self.notify()

    async def play_search(self, i):
        async with self.lock:
            self.station, self.queue = None, list(self.results)
            self.source = {"type": "search", "title": self.search_text, "mood": ""}
            await self._play(i)

    # --- playback ------------------------------------------------------------
    def _spawn(self, coro):
        t = asyncio.create_task(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)

    async def settle(self):
        """Await pending background work (neighbours, feedback, prefetch, downloads)."""
        while self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
            await asyncio.sleep(0)

    def _local(self, tid):
        f = self.cache_dir / f"{tid}.mp3"
        return f if f.exists() else None

    async def _url(self, i):
        tid = self.queue[i]["id"]
        if f := self._local(tid):
            os.utime(f)  # LRU: touch on play
            return str(f)
        hit = self.urls.get(tid)
        if hit and time.monotonic() - hit[1] < URL_TTL:
            return hit[0]
        url = tracks.best_link(await self.api.tracks_download_info(tid, get_direct_links=True))
        if url is not None:
            self.urls[tid] = (url, time.monotonic())
        return url

    async def _load(self, url, mode, index=-1):
        await self.mpv.command("loadfile", url, mode, index, FADE_IN)

    async def play(self, i):
        async with self.lock:
            await self._play(i)

    async def _play(self, i, kind="skip"):
        """Internal play without lock; must be called while holding self.lock.

        Only the current track's link is fetched before it starts; neighbours,
        feedback, prefetch and the disk copy follow in _after_play.
        """
        if not 0 <= i < len(self.queue):
            self.error = "nothing to play"; self.notify(); return
        prev = (self.index, self.time_pos, self.duration)
        skip = None
        if self.station and 0 <= self.index < len(self.queue) and self.loaded:
            skip = (self.station, kind, self.queue[self.index]["fid"], self.time_pos)
        prev_gen, prev_faded = self.gen, self.faded
        self.gen += 1
        gen = self.gen
        self.index, self.error, self.time_pos, self.duration, self.last_end = i, None, 0.0, 0.0, None
        self.faded = False
        self.notify()  # the marker moves before any network call

        def restore():
            # nothing new was loaded: the old track keeps playing, with its window and marker
            self.index, self.time_pos, self.duration = prev
            self.gen, self.faded = prev_gen, prev_faded

        try:
            # Find a playable track, skipping unavailable ones
            playable_i = i
            while True:
                url = await self._url(playable_i)
                if url is not None:
                    break
                playable_i += 1
                # Fetch more tracks for stations if needed
                if playable_i >= len(self.queue):
                    await self._refill()
                if playable_i >= len(self.queue):
                    # No playable tracks found: mpv keeps what it had
                    restore()
                    self.error = "track unavailable"
                    self.notify()
                    return
            self.index = playable_i
            await self._load(url, "replace")
        except BaseException:
            restore()  # the marker follows what mpv plays
            self.notify()
            raise
        self.loaded = [playable_i]  # before anything else can fail: mpv holds exactly this
        self._spawn(self._after_play(gen, playable_i, skip))
        await self.mpv.command("set_property", "pause", False)  # pause is global in mpv
        self.playing = True
        self.notify()

    async def _after_play(self, gen, i, skip):
        try:
            if skip:
                await self._send(*skip)
            async with self.lock:
                if gen != self.gen:
                    return  # superseded by another play / source
                await self._append_next()
                if i > 0:
                    prev_url = await self._url(i - 1)
                    if prev_url is not None:
                        await self._load(prev_url, "insert-at", 0)
                        self.loaded.insert(0, i - 1)
                if self.radio_pending:
                    self.radio_pending = False
                    await self._send(self.station, "radioStarted")
                await self._feedback("trackStarted", i)
            await self._cache_liked(i)
        except Exception as e:
            log.warning("after play: %s", e)

    async def _prefetch(self, n):
        try:
            if n < len(self.queue):
                await self._url(n)
        except Exception as e:
            log.warning("prefetch: %s", e)

    async def _cache_liked(self, i):
        """Keep a disk copy of a liked track that is playing from a stream link."""
        t = self.queue[i]["id"] if 0 <= i < len(self.queue) else None
        hit = self.urls.get(t)
        if t not in self.liked or t in self.downloading or self._local(t) or not hit:
            return
        self.downloading.add(t)
        f = self.cache_dir / f"{t}.mp3"
        part = f.with_suffix(".part")
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(self.download, hit[0], str(part))
            part.rename(f)
            await asyncio.to_thread(diskcache.trim, self.cache_dir)
        except Exception as e:
            log.warning("cache %s: %s", t, e)
            part.unlink(missing_ok=True)
        finally:
            self.downloading.discard(t)

    async def reload(self):
        """mpv restarted: load the current track again."""
        if 0 <= self.index < len(self.queue):
            self.loaded = []  # no skip feedback: the old mpv playlist is gone
            await self.play(self.index)

    async def _append_next(self):
        n = self.index + 1
        if n >= len(self.queue) - 1:
            await self._refill()
        if n < len(self.queue):
            url = await self._url(n)
            if url is not None:
                await self._load(url, "append")
                self.loaded.append(n)
        self._spawn(self._prefetch(n + 1))

    async def _on_pos(self, p):
        """Internal; called with lock held from on_event."""
        if p is None or not 0 <= p < len(self.loaded) or self.loaded[p] == self.index:
            return
        old, self.index = self.index, self.loaded[p]
        if self.station and self.last_end != "error":
            await self._feedback("trackFinished" if self.last_end == "eof" else "skip", old)
        self.time_pos, self.duration, self.faded = 0.0, 0.0, False
        self.last_end = None
        if self.index > old:
            while p > 1:
                await self.mpv.command("playlist-remove", 0)
                self.loaded.pop(0)
                p -= 1
            if self.loaded[-1] == self.index:
                await self._append_next()
        else:
            while len(self.loaded) > p + 2:
                await self.mpv.command("playlist-remove", len(self.loaded) - 1)
                self.loaded.pop()
            if p == 0 and self.index > 0:
                prev_url = await self._url(self.index - 1)
                if prev_url is not None:
                    await self._load(prev_url, "insert-at", 0)
                    self.loaded.insert(0, self.index - 1)
        await self._feedback("trackStarted", self.index)
        self.notify()
        self._spawn(self._cache_liked(self.index))

    async def _feedback(self, kind, i):
        if self.station:
            await self._send(self.station, kind, self.queue[i]["fid"], self.time_pos)

    async def _send(self, station, kind, fid=None, secs=None):
        """Wave feedback must never break playback: log and carry on."""
        kw = {}
        if fid:
            kw["track_id"] = fid
        if kind in ("skip", "trackFinished"):
            kw["total_played_seconds"] = max(secs or 0, 0.1)  # the library drops a falsy 0
        try:
            await self.api.rotor_station_feedback(station, kind, **kw)
        except Exception as e:
            log.warning("feedback %s: %s", kind, e)

    async def on_event(self, msg):
        name, data = msg.get("name"), msg.get("data")
        if msg.get("event") == "end-file":
            self.last_end = msg.get("reason")
            if self.last_end == "error" and 0 <= self.index < len(self.queue):
                tid = self.queue[self.index]["id"]
                self.urls.pop(tid, None)  # stale link: refetch next time
                if f := self._local(tid):
                    f.unlink(missing_ok=True)  # maybe a bad copy
            if self.last_end == "eof" and self.loaded and self.loaded[-1] == self.index:
                async with self.lock:  # no next entry in mpv (load failed): advance ourselves
                    if self.loaded and self.loaded[-1] == self.index and self.index + 1 < len(self.queue):
                        await self._step(1, "trackFinished")
            return
        if msg.get("event") != "property-change":
            return
        if name == "playlist-pos":
            async with self.lock:
                try:
                    p = await self.mpv.command("get_property", "playlist-pos")
                except Exception:
                    return  # mpv idle/gone: nothing to slide
                await self._on_pos(p)
            return
        # Non-blocking state updates for pause/idle/time-pos
        if name == "pause":
            self.playing = data is False
        elif name == "idle-active" and data:
            self.playing = False
        elif name == "time-pos":
            self.time_pos = data or 0.0
            if (not self.faded and self.loaded and self.duration > 2 * FADE_S
                    and self.time_pos >= self.duration - FADE_S):
                self.faded = True  # once per track; a skip loads a file that resets af
                await self.mpv.command("af", "add", f"@fo:lavfi=[afade=t=out:st={self.time_pos}:d={self.duration - self.time_pos}]")
            return                                   # no state line per tick
        elif name == "duration":
            self.duration = data or 0.0
        self.notify()

    async def toggle(self):
        async with self.lock:
            if not self.loaded and not self.playing and self.queue:
                await self._play(max(self.index, 0))
            else:
                await self.mpv.command("cycle", "pause")

    async def stop(self):
        async with self.lock:
            await self.mpv.command("stop")
            self.gen += 1
            self.loaded, self.playing = [], False
            self.notify()

    async def seek(self, seconds):
        if not self.loaded:
            return
        s = min(max(seconds, 0.0), self.duration or seconds)
        await self.mpv.command("seek", s, "absolute")
        if self.faded and s < self.duration - FADE_S:
            self.faded = False
            await self.mpv.command("af", "remove", "@fo")
        self.time_pos = s
        self.notify()

    async def _step(self, d, kind="skip"):
        """Lock held. At the edge of the window (neighbour not loaded) play from the queue."""
        n = self.index + d
        if n >= 0 and (not self.loaded or self.loaded[-1 if d > 0 else 0] == self.index):
            if d > 0 and n >= len(self.queue):
                await self._refill()
            if n < len(self.queue):
                await self._play(n, kind)
                return
        await self.mpv.command("playlist-next" if d > 0 else "playlist-prev")

    async def next(self):
        async with self.lock:
            await self._step(1)

    async def prev(self):
        async with self.lock:
            await self._step(-1)

    async def like(self):
        async with self.lock:
            if not (0 <= self.index < len(self.queue)):
                return
            tid = self.queue[self.index]["id"]
            if tid in self.liked:
                await self.api.users_likes_tracks_remove(tid); self.liked.discard(tid)
                if tid in self.like_ids:
                    k = self.like_ids.index(tid); self.like_ids.remove(tid)
                    self.like_off -= k < self.like_off
            else:
                await self.api.users_likes_tracks_add(tid); self.liked.add(tid)
                if tid not in self.like_ids:
                    self.like_ids.insert(0, tid); self.like_off += 1
            self.notify()

    async def dislike(self):
        async with self.lock:
            if not (0 <= self.index < len(self.queue)):
                return
            await self.api.users_dislikes_tracks_add(self.queue[self.index]["id"])
            await self._step(1)

    # --- state ---------------------------------------------------------------
    def state(self):
        cur = self.queue[self.index] if 0 <= self.index < len(self.queue) else None
        track = dict(cur, liked=cur["id"] in self.liked) if cur else None
        row = lambda t: {"id": t["id"], "title": t["title"], "artists": t["artists"]}
        return {"source": self.source, "moods": MOODS, "playing": self.playing, "track": track,
                "queue": [row(t) for t in self.queue], "index": self.index,
                "position": self.time_pos, "duration": self.duration,
                "has_more": self._has_more(), "loading": self.loading,
                "search": {"text": self.search_text,
                           "results": [dict(row(t), album=t["album"]) for t in self.results]},
                "error": self.error}
