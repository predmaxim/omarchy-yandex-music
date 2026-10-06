"""Queue, sources and the 3-track window kept in mpv's playlist.

mpv holds at most [previous, current, next]; self.loaded maps those playlist
positions to queue indices. Every playlist-pos change (media keys through
mpv-mpris, end of track, our own insert-at) goes through _on_pos, which slides
the window and sends wave feedback. A stream link is fetched right before it
is loaded: links expire.
"""
import asyncio
from . import tracks

WAVE = "user:onyourwave"
MOODS = ["all", "fun", "active", "calm", "sad"]


class Player:
    def __init__(self, api, mpv, notify):
        self.api, self.mpv, self.notify = api, mpv, notify
        self.queue, self.index, self.loaded = [], -1, []
        self.source = {"type": "none", "title": "", "mood": ""}
        self.station, self.liked = None, set()
        self.playing, self.time_pos, self.last_end, self.error = False, 0.0, None, None
        self.search_text, self.results = "", []
        self.lock = asyncio.Lock()

    # --- sources -----------------------------------------------------------
    async def load_likes(self):
        self.liked = {str(t.id) for t in (await self.api.users_likes_tracks()).tracks}

    async def start_likes(self):
        tl = await self.api.users_likes_tracks()
        self.liked = {str(t.id) for t in tl.tracks}
        async with self.lock:
            self.station, self.queue = None, [tracks.info(t) for t in await tl.fetch_tracks_async()]
            self.source = {"type": "likes", "title": "", "mood": ""}
            await self._play(0)

    async def start_wave(self, mood):
        if mood:
            await self.api.rotor_station_settings2(WAVE, mood, "default")
        await self._start_station(WAVE, {"type": "wave", "title": "", "mood": mood or ""})

    async def start_track_wave(self, track_id):
        known = {t["id"]: t for t in self.queue + self.results}
        title = known.get(track_id, {}).get("title", "")
        await self._start_station(f"track:{track_id}", {"type": "track-wave", "title": title, "mood": ""})

    async def _start_station(self, station, source):
        async with self.lock:
            self.station, self.queue, self.source, self.loaded = station, [], source, []
            await self._fetch_station()
            await self.api.rotor_station_feedback(station, "radioStarted")
            await self._play(0)

    async def _fetch_station(self):
        last = self.queue[-1]["id"] if self.queue else None
        r = await self.api.rotor_station_tracks(self.station, queue=last)
        self.queue += [tracks.info(s.track) for s in r.sequence if s.track]

    async def search(self, text):
        async with self.lock:
            text = text.strip()
            self.search_text = text
            if not text:
                self.results = []
            else:
                resp = await self.api.search(text, type_="track")
                self.results = [tracks.info(t) for t in (resp.tracks.results or [])] if resp.tracks else []
            self.notify()

    async def play_search(self, i):
        async with self.lock:
            self.station, self.queue = None, list(self.results)
            self.source = {"type": "search", "title": self.search_text, "mood": ""}
            await self._play(i)

    # --- playback ------------------------------------------------------------
    async def _url(self, i):
        return tracks.best_link(await self.api.tracks_download_info(self.queue[i]["id"], get_direct_links=True))

    async def play(self, i):
        async with self.lock:
            await self._play(i)

    async def _play(self, i):
        """Internal play without lock; must be called while holding self.lock."""
        if self.station and 0 <= self.index < len(self.queue) and self.loaded:
            await self._feedback("skip", self.index)
        self.index, self.error, self.time_pos, self.last_end = i, None, 0.0, None

        # Find a playable track, skipping unavailable ones
        playable_i = i
        while True:
            url = await self._url(playable_i)
            if url is not None:
                break
            playable_i += 1
            # Fetch more tracks for stations if needed
            if self.station and playable_i >= len(self.queue):
                await self._fetch_station()
            if playable_i >= len(self.queue):
                # No playable tracks found
                self.index, self.error = i, "track unavailable"
                self.notify()
                return

        self.index = playable_i
        await self.mpv.command("loadfile", url, "replace")
        self.loaded = [playable_i]
        await self._append_next()
        if playable_i > 0:
            prev_url = await self._url(playable_i - 1)
            if prev_url is not None:
                await self.mpv.command("loadfile", prev_url, "insert-at", 0)
                self.loaded.insert(0, playable_i - 1)
        await self._feedback("trackStarted", playable_i)
        self.notify()

    async def reload(self):
        """mpv restarted: load the current track again."""
        if 0 <= self.index < len(self.queue):
            await self.play(self.index)

    async def _append_next(self):
        n = self.index + 1
        if self.station and n >= len(self.queue) - 1:
            await self._fetch_station()
        if n < len(self.queue):
            url = await self._url(n)
            if url is not None:
                await self.mpv.command("loadfile", url, "append")
                self.loaded.append(n)

    async def _on_pos(self, p):
        """Internal; called with lock held from on_event."""
        if p is None or not 0 <= p < len(self.loaded) or self.loaded[p] == self.index:
            return
        old, self.index = self.index, self.loaded[p]
        if self.station and self.last_end != "error":
            await self._feedback("trackFinished" if self.last_end == "eof" else "skip", old)
        self.time_pos = 0.0
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
                    await self.mpv.command("loadfile", prev_url, "insert-at", 0)
                    self.loaded.insert(0, self.index - 1)
        await self._feedback("trackStarted", self.index)
        self.notify()

    async def _feedback(self, kind, i):
        if self.station:
            kw = {"track_id": self.queue[i]["fid"]}
            if kind in ("skip", "trackFinished"):
                kw["total_played_seconds"] = self.time_pos
            await self.api.rotor_station_feedback(self.station, kind, **kw)

    async def on_event(self, msg):
        name, data = msg.get("name"), msg.get("data")
        if msg.get("event") == "end-file":
            self.last_end = msg.get("reason")
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
            return                                   # no state line per tick
        self.notify()

    async def toggle(self):
        async with self.lock:
            if not self.loaded and 0 <= self.index < len(self.queue):
                await self._play(self.index)
            else:
                await self.mpv.command("cycle", "pause")

    async def stop(self):
        async with self.lock:
            await self.mpv.command("stop")
            self.loaded, self.playing = [], False
            self.notify()

    async def next(self):
        await self.mpv.command("playlist-next")

    async def prev(self):
        await self.mpv.command("playlist-prev")

    async def like(self):
        async with self.lock:
            if not (0 <= self.index < len(self.queue)):
                return
            tid = self.queue[self.index]["id"]
            if tid in self.liked:
                await self.api.users_likes_tracks_remove(tid); self.liked.discard(tid)
            else:
                await self.api.users_likes_tracks_add(tid); self.liked.add(tid)
            self.notify()

    async def dislike(self):
        async with self.lock:
            if not (0 <= self.index < len(self.queue)):
                return
            await self.api.users_dislikes_tracks_add(self.queue[self.index]["id"])
            await self.mpv.command("playlist-next")

    # --- state ---------------------------------------------------------------
    def state(self):
        cur = self.queue[self.index] if 0 <= self.index < len(self.queue) else None
        track = dict(cur, liked=cur["id"] in self.liked) if cur else None
        row = lambda t: {"id": t["id"], "title": t["title"], "artists": t["artists"]}
        return {"source": self.source, "moods": MOODS, "playing": self.playing, "track": track,
                "queue": [row(t) for t in self.queue], "index": self.index,
                "search": {"text": self.search_text,
                           "results": [dict(row(t), album=t["album"]) for t in self.results]},
                "error": self.error}
