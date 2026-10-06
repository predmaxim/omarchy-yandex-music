from types import SimpleNamespace as NS


def track(i, title=None):
    return NS(id=i, track_id=f"{i}:100", title=title or f"t{i}", artists_name=lambda: ["a"],
              albums=[NS(title="al")], cover_uri=None)


class FakeMpv:
    """Records commands and mirrors loadfile/remove on a fake playlist."""
    def __init__(self, on_load=None):
        self.calls, self.playlist = [], []
        self.pos = -1  # Current playlist position
        self.on_load = on_load

    async def command(self, *args):
        self.calls.append(args)
        if args[0] == "loadfile":
            url, mode = args[1], args[2]
            if mode == "replace":
                self.playlist = [url]
                self.pos = 0
            elif mode == "append":
                self.playlist.append(url)
            elif mode == "insert-at":
                k = args[3]
                self.playlist.insert(k, url)
                if k <= self.pos:
                    self.pos += 1
            if self.on_load:
                result = self.on_load()
                # Handle both sync and async callbacks
                import asyncio
                if asyncio.iscoroutine(result):
                    await result
        elif args[0] == "playlist-clear":
            self.playlist = self.playlist[self.pos:self.pos + 1]
            self.pos = 0
        elif args[0] == "playlist-remove":
            k = args[1]
            self.playlist.pop(k)
            if k < self.pos:
                self.pos -= 1
            elif k == self.pos:
                self.pos = min(self.pos, len(self.playlist) - 1)
        elif args[0] == "playlist-next":
            self.pos = min(self.pos + 1, len(self.playlist) - 1)
        elif args[0] == "playlist-prev":
            self.pos = max(self.pos - 1, 0)
        elif args[0] == "stop":
            self.playlist = []
            self.pos = -1
        elif args[0] == "get_property":
            if args[1] == "playlist-pos":
                return self.pos
        return None


class FakeApi:
    def __init__(self, likes=5, wave_batches=None, search_tracks=None, unavailable_ids=None):
        self.likes = [track(i) for i in range(likes)]
        self.wave_batches = wave_batches or [[track(100 + i) for i in range(5)], [track(200 + i) for i in range(5)]]
        self.feedback, self.settings, self.liked_add, self.disliked, self.searched = [], [], [], [], []
        self.rotor_calls, self.feedback_kw, self.feedback_error = [], [], None
        self.search_tracks = search_tracks or NS(results=[track(900), track(901)])
        self.unavailable_ids = unavailable_ids or set()

    async def users_likes_tracks(self):
        async def fetch(): return self.likes
        return NS(tracks=[NS(id=str(t.id)) for t in self.likes], fetch_tracks_async=fetch)

    async def rotor_station_tracks(self, station, queue=None):
        self.rotor_calls.append((station, queue))
        batch = self.wave_batches[min(len(self.rotor_calls) - 1, len(self.wave_batches) - 1)]
        return NS(batch_id=f"b{len(self.rotor_calls)}", sequence=[NS(track=t) for t in batch])

    async def rotor_station_settings2(self, station, mood, diversity, language=None):
        self.settings.append((station, mood, diversity)); self.languages = getattr(self, "languages", []) + [language]; return True

    async def rotor_station_feedback(self, station, type_, **kw):
        if self.feedback_error:
            raise self.feedback_error
        self.feedback.append((station, type_, kw.get("track_id"))); self.feedback_kw.append(kw); return True

    async def tracks_download_info(self, track_id, get_direct_links=False):
        if track_id in self.unavailable_ids:
            return [NS(codec="mp3", bitrate_in_kbps=320, preview=True, direct_link=f"preview{track_id}")]
        return [NS(codec="mp3", bitrate_in_kbps=320, preview=False, direct_link=f"url{track_id}")]

    async def users_likes_tracks_add(self, track_id): self.liked_add.append(track_id); return True
    async def users_likes_tracks_remove(self, track_id): self.liked_add.remove(track_id); return True
    async def users_dislikes_tracks_add(self, track_id): self.disliked.append(track_id); return True

    async def search(self, text, type_="all"):
        self.searched.append((text, type_))
        return NS(tracks=self.search_tracks)
