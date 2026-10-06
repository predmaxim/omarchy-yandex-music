"""Sources, the play queue and the 3-track window kept in mpv's playlist.

The window shows one Feed (self.feed: a source's list and how it pages), the
play queue is another (self.play_feed); they are the same object while the window
shows the playing source, so a page fetched by either is in both. Browsing
never touches mpv: only playing a row makes its feed the play queue.
mpv holds at most [previous, current, next]; self.loaded maps those playlist
positions to play-queue indices. Every playlist-pos change (media keys through
mpv-mpris, end of track, our own insert-at) goes through _on_pos, which slides
the window and sends wave feedback. A stream link is fetched right before it
is loaded: links expire.
"""
import asyncio
import hashlib
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
MAX_STATION_ROWS = 100  # the list stops growing from scrolling here
IDS_TTL = 300


class Feed:
    """A track list and where its next page comes from."""
    def __init__(self, source, station=None):
        self.source, self.station, self.tracks, self.started = source, station, [], False  # started: radioStarted sent
        self.off = 0  # likes: ids already fetched


class Player:
    def __init__(self, api, mpv, notify, cache_dir=None, download=None):
        self.api, self.mpv, self.notify = api, mpv, notify
        self.cache_dir, self.download = cache_dir or diskcache.DIR, download or diskcache.fetch
        self.covers_dir = self.cache_dir.parent / diskcache.COVERS.name
        self.urls, self.tasks, self.downloading = {}, set(), set()
        self.gen, self.duration, self.faded, self.wave_mood = 0, 0.0, False, None
        self.feed = self.play_feed = Feed({"type": "none", "title": "", "mood": ""})
        self.index, self.loaded, self.liked = -1, [], set()  # index: of the audible track in the play queue
        self.playing, self.time_pos, self.last_end, self.error = False, 0.0, None, None
        self.search_text, self.results, self.search_page, self.search_total = "", [], 0, 0
        self.like_ids, self.like_ids_at, self.likes_page1 = [], None, None
        self.loading, self.now = False, None  # now: the track mpv plays (play_queue[index])
        self.lock = asyncio.Lock()

    queue = property(lambda self: self.feed.tracks)
    source = property(lambda self: self.feed.source)
    play_queue = property(lambda self: self.play_feed.tracks)
    play_source = property(lambda self: self.play_feed.source)

    # --- sources -----------------------------------------------------------
    async def load_likes(self):
        await self._likes_ids(True)

    async def _likes_ids(self, force=False):
        """Every liked id (cheap list); refreshed at most every 5 minutes."""
        if force or self.like_ids_at is None or time.monotonic() - self.like_ids_at > IDS_TTL:
            self.like_ids = [str(t.id) for t in (await self.api.users_likes_tracks()).tracks]
            self.like_ids_at = time.monotonic()
            self.liked = set(self.like_ids)

    def _show(self, source, station=None, reuse=True):
        """Lock held. Point the window at a source; the playing one is shown as is (True: nothing to fetch)."""
        same = reuse and (self.play_feed.source, self.play_feed.station) == (source, station)
        self.feed = self.play_feed if same else Feed(source, station)
        self.loading = not same
        self.notify()  # the source switch shows at once; the first page follows
        return same

    async def start_likes(self):
        async with self.lock:
            if self._show({"type": "likes", "title": "", "mood": ""}):
                return
            try:
                await self._likes_ids()
                if not self.like_ids:
                    self.error = "nothing to play"; return
                first = tuple(self.like_ids[:PAGE])
                if self.likes_page1 and self.likes_page1[0] == first:
                    self.feed.tracks, self.feed.off = list(self.likes_page1[1]), len(first)
                else:
                    await self._more_likes(self.feed)
                    self.likes_page1 = (first, list(self.feed.tracks))
            finally:
                self.loading = False
                self.notify()

    async def _more_likes(self, f):
        ids = self.like_ids[f.off:f.off + PAGE]
        if ids:
            f.off += len(ids)
            f.tracks += [tracks.info(t) for t in await self.api.tracks(ids)]

    async def _extend(self, f):
        """Next page / next rotor batch of a feed (the play queue running out, or the window scrolled)."""
        if f.station:
            await self._fetch_station(f)
        elif f.source["type"] == "likes":
            await self._more_likes(f)

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
                    page = [tracks.info(t) for t in (resp.tracks.results or [])] if resp and resp.tracks else []
                    self.results += page
                    if not page:
                        self.search_total = len(self.results)
                else:
                    await self._extend(self.feed)
            finally:
                self.loading = False
                self.notify()

    def _has_more(self):
        if self.search_text:
            return len(self.results) < self.search_total
        if self.feed.station:
            return len(self.queue) < MAX_STATION_ROWS
        return self.source["type"] == "likes" and self.feed.off < len(self.like_ids)

    async def start_wave(self, mood):
        await self._start_station(WAVE, {"type": "wave", "title": "", "mood": mood or ""})

    async def start_track_wave(self, track_id):
        known = {t["id"]: t for t in self.queue + self.results}
        title = known.get(track_id, {}).get("title", "")
        await self._start_station(f"track:{track_id}", {"type": "track-wave", "title": title, "mood": ""}, fresh=True)

    async def _start_station(self, station, source, fresh=False):
        """fresh: play it from scratch now (wave by a track). Another mood of the playing station plays at once too."""
        async with self.lock:
            if self._show(source, station, reuse=not fresh):
                return
            play = fresh or self.play_feed.station == station
            try:
                await self._fetch_station(self.feed)
            finally:
                self.loading = False
            if not self.queue:
                self.error = "nothing to play"; self.notify(); return
            if play:
                await self._play(0, feed=self.feed)
            else:
                self.notify()

    async def _fetch_station(self, f):
        mood = f.source["mood"]
        if f.station == WAVE and mood and mood != self.wave_mood:  # one station, two moods: browsed and playing
            await self.api.rotor_station_settings2(WAVE, mood, "default", language="any")
            self.wave_mood = mood
        last = f.tracks[-1]["id"] if f.tracks else None
        r = await self.api.rotor_station_tracks(f.station, queue=last)
        f.tracks += [tracks.info(s.track) for s in (r.sequence if r else None) or [] if s.track]

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
            self.feed = Feed({"type": "search", "title": self.search_text, "mood": ""})
            self.feed.tracks = list(self.results)
            await self._play(i, feed=self.feed)

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
        tid = self.play_queue[i]["id"]
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
        """Row i of the window: its feed becomes the play queue."""
        async with self.lock:
            await self._play(i, feed=self.feed)

    async def _play(self, i, kind="skip", feed=None):
        """Internal play without lock; must be called while holding self.lock.

        Plays row i of `feed` (it becomes the play queue) or of the play queue.
        Only the current track's link is fetched before it starts; neighbours,
        feedback, prefetch and the disk copy follow in _after_play.
        """
        feed = feed or self.play_feed
        if not 0 <= i < len(feed.tracks):
            self.error = "nothing to play"; self.notify(); return
        prev = (self.play_feed, self.index)
        skip = None
        if self.play_feed.station and 0 <= self.index < len(self.play_queue) and self.loaded:
            skip = (self.play_feed.station, kind, self.play_queue[self.index]["fid"], self.time_pos)
        prev_gen = self.gen
        self.gen += 1
        gen = self.gen
        self.play_feed = feed
        self.index, self.error, self.last_end = i, None, None
        self.notify()  # the marker moves before any network call; now, position, duration: the old track's still

        def restore():
            # nothing new was loaded: the old track keeps playing, with its queue, window and marker
            self.play_feed, self.index = prev
            self.gen = prev_gen

        try:
            # Find a playable track, skipping unavailable ones
            playable_i = i
            while True:
                url = await self._url(playable_i)
                if url is not None:
                    break
                playable_i += 1
                # Fetch more tracks for stations if needed
                if playable_i >= len(self.play_queue) and playable_i - i < PAGE:
                    await self._extend(self.play_feed)
                if playable_i >= len(self.play_queue) or playable_i - i >= PAGE:
                    # No playable track within a page (a station may never end): mpv keeps what it had
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
        self.now, self.time_pos, self.duration, self.faded = self.play_queue[playable_i], 0.0, 0.0, False  # mpv has it
        self.loaded = [playable_i]  # before anything else can fail: mpv holds exactly this
        self._spawn(self._fetch_covers(self.now))
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
                if self.play_feed.station and not self.play_feed.started:  # radioStarted goes out with the first play
                    self.play_feed.started = True
                    await self._send(self.play_feed.station, "radioStarted")
                await self._feedback("trackStarted", i)
                tid = self.play_queue[i]["id"]
            await self._cache_liked(tid)
        except Exception as e:
            log.warning("after play: %s", e)

    async def _prefetch(self, n):
        try:
            if n < len(self.play_queue):
                await self._url(n)
        except Exception as e:
            log.warning("prefetch: %s", e)

    async def _cache_liked(self, t):
        """Keep a disk copy of a liked track that is playing from a stream link."""
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

    def _cover_file(self, url):
        return self.covers_dir / (hashlib.sha1(url.encode()).hexdigest() + ".jpg")

    def _cover(self, url):
        """The disk copy of a cover once downloaded (the shell shows it at once), else the URL."""
        f = url and self._cover_file(url)
        return f"file://{f}" if f and f.exists() else url

    async def _fetch_covers(self, t):
        """Download a track's covers (header 200x200, My Wave 600x600) into the disk cache."""
        got = False
        for url in (t["cover"], t["cover_big"]):
            f = url and self._cover_file(url)
            if not f or url in self.downloading:
                continue
            if f.exists():
                os.utime(f)  # LRU: touch on play
                continue
            self.downloading.add(url)
            part = f.with_suffix(".part")
            try:
                self.covers_dir.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(self.download, url, str(part))
                part.rename(f)
                got = True
            except Exception as e:
                log.warning("cover %s: %s", url, e)
                part.unlink(missing_ok=True)
            finally:
                self.downloading.discard(url)
        if got and self.now is t:
            self.notify()  # the window switches to the local copy
        if got:
            try:
                await asyncio.to_thread(diskcache.trim, self.covers_dir, diskcache.COVER_LIMIT, "*.jpg")
            except OSError as e:  # a parallel download renamed its .part under it: the next trim catches up
                log.warning("trim covers: %s", e)

    async def reload(self):
        """mpv restarted: load the current track again."""
        async with self.lock:
            if 0 <= self.index < len(self.play_queue):
                self.loaded = []  # no skip feedback: the old mpv playlist is gone
                await self._play(self.index)

    async def _append_next(self):
        n = self.index + 1
        if n >= len(self.play_queue) - 1:
            await self._extend(self.play_feed)
        if n < len(self.play_queue):
            url = await self._url(n)
            if url is not None:
                await self._load(url, "append")
                self.loaded.append(n)
            self._spawn(self._fetch_covers(self.play_queue[n]))  # the next track's covers, ready when it starts
        self._spawn(self._prefetch(n + 1))

    async def _on_pos(self, p):
        """Internal; called with lock held from on_event."""
        if p is None or not 0 <= p < len(self.loaded) or self.loaded[p] == self.index:
            return
        old, self.index = self.index, self.loaded[p]
        self.now = self.play_queue[self.index]
        if self.play_feed.station and self.last_end != "error":
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
        self._spawn(self._cache_liked(self.now["id"]))
        self._spawn(self._fetch_covers(self.now))

    async def _feedback(self, kind, i):
        if self.play_feed.station:
            await self._send(self.play_feed.station, kind, self.play_queue[i]["fid"], self.time_pos)

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
            if self.last_end == "error" and self.now:
                tid = self.now["id"]
                self.urls.pop(tid, None)  # stale link: refetch next time
                if f := self._local(tid):
                    f.unlink(missing_ok=True)  # maybe a bad copy
            if self.last_end == "eof" and self.index >= 0:
                ended = self.loaded  # _play always makes a new list
                async with self.lock:  # mpv has nothing after this track (or went idle): advance ourselves
                    if self.loaded is not ended:
                        return  # a play while this waited for the lock: the track that ended is gone
                    n = self.index + 1
                    edge = self.loaded[-1:] == [self.index]
                    if edge and n >= len(self.play_queue):
                        await self._extend(self.play_feed)
                    if n < len(self.play_queue) and (edge or await self._idle()):
                        await self._play(n, "trackFinished")
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
            if (not self.faded and self.now and self.duration > 2 * FADE_S
                    and self.time_pos >= self.duration - FADE_S):
                self.faded = True  # once per track; a skip loads a file that resets af
                await self.mpv.command("af", "add", f"@fo:lavfi=[afade=t=out:st={self.time_pos}:d={self.duration - self.time_pos}]")
            return                                   # no state line per tick
        elif name == "duration":
            self.duration = data or 0.0
        self.notify()

    async def _idle(self):
        try:
            return bool(await self.mpv.command("get_property", "idle-active"))
        except Exception:
            return False

    async def toggle(self):
        async with self.lock:
            if not await self._idle():
                await self.mpv.command("cycle", "pause")  # mpv still holds a track
            elif self.now:
                await self._play(self.index)  # mpv is idle: the audible track again, with its window
            elif self.queue:
                await self._play(0, feed=self.feed)

    async def stop(self):
        async with self.lock:
            await self.mpv.command("stop")
            self.gen += 1
            self.loaded, self.playing = [], False
            self.notify()

    async def seek(self, seconds):
        if not self.now:
            return
        s = min(max(seconds, 0.0), self.duration or seconds)
        await self.mpv.command("seek", s, "absolute")
        if self.faded and s < self.duration - FADE_S:
            self.faded = False
            await self.mpv.command("af", "remove", "@fo")
        self.time_pos = s
        self.notify()

    async def _step(self, d, kind="skip"):
        """Lock held. At the edge of the window (neighbour not loaded) play from the play queue."""
        n = self.index + d
        if n >= 0 and (not self.loaded or self.loaded[-1 if d > 0 else 0] == self.index):
            if d > 0 and n >= len(self.play_queue):
                await self._extend(self.play_feed)
            if n < len(self.play_queue):
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
            if not self.now:
                return
            tid = self.now["id"]
            feeds = [f for f in {self.feed, self.play_feed} if f.source["type"] == "likes"]  # paged over like_ids
            if tid in self.liked:
                await self.api.users_likes_tracks_remove(tid); self.liked.discard(tid)
                if tid in self.like_ids:
                    k = self.like_ids.index(tid); self.like_ids.remove(tid)
                    for f in feeds:
                        f.off -= k < f.off
            else:
                await self.api.users_likes_tracks_add(tid); self.liked.add(tid)
                if tid not in self.like_ids:
                    self.like_ids.insert(0, tid)
                    for f in feeds:
                        f.off += 1
            self.notify()

    async def dislike(self):
        async with self.lock:
            if not self.now:
                return
            await self.api.users_dislikes_tracks_add(self.now["id"])
            await self._step(1)

    # --- state ---------------------------------------------------------------
    def state(self):
        cur = self.now
        track = dict(cur, liked=cur["id"] in self.liked, cover=self._cover(cur["cover"]),
                     cover_big=self._cover(cur["cover_big"])) if cur else None
        row = lambda t: {"id": t["id"], "title": t["title"], "artists": t["artists"]}
        return {"source": self.source, "play_source": self.play_source, "moods": MOODS,
                "playing": self.playing, "track": track, "queue": [row(t) for t in self.queue],
                "index": self.index if self.feed is self.play_feed else -1,  # the audible row, if the window shows it
                "position": self.time_pos, "duration": self.duration,
                "has_more": self._has_more(), "loading": self.loading,
                "search": {"text": self.search_text,
                           "results": [dict(row(t), album=t["album"]) for t in self.results]},
                "error": self.error}
