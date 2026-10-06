from types import SimpleNamespace as NS


def track(i, title=None):
    return NS(id=i, track_id=f"{i}:100", title=title or f"t{i}", artists_name=lambda: ["a"],
              albums=[NS(title="al")], cover_uri=None)


class FakeMpv:
    """Records commands and mirrors loadfile/remove on a fake playlist."""
    def __init__(self):
        self.calls, self.playlist = [], []

    async def command(self, *args):
        self.calls.append(args)
        if args[0] == "loadfile":
            url, mode = args[1], args[2]
            if mode == "replace": self.playlist = [url]
            elif mode == "append": self.playlist.append(url)
            elif mode == "insert-at": self.playlist.insert(args[3], url)
        elif args[0] == "playlist-remove":
            self.playlist.pop(args[1])
        elif args[0] == "stop":
            self.playlist = []


class FakeApi:
    def __init__(self, likes=5, wave_batches=None):
        self.likes = [track(i) for i in range(likes)]
        self.wave_batches = wave_batches or [[track(100 + i) for i in range(5)], [track(200 + i) for i in range(5)]]
        self.feedback, self.settings, self.liked_add, self.disliked, self.searched = [], [], [], [], []
        self.rotor_calls = []

    async def users_likes_tracks(self):
        async def fetch(): return self.likes
        return NS(tracks=[NS(id=str(t.id)) for t in self.likes], fetch_tracks_async=fetch)

    async def rotor_station_tracks(self, station, queue=None):
        self.rotor_calls.append((station, queue))
        batch = self.wave_batches[min(len(self.rotor_calls) - 1, len(self.wave_batches) - 1)]
        return NS(batch_id=f"b{len(self.rotor_calls)}", sequence=[NS(track=t) for t in batch])

    async def rotor_station_settings2(self, station, mood, diversity):
        self.settings.append((station, mood, diversity)); return True

    async def rotor_station_feedback(self, station, type_, **kw):
        self.feedback.append((station, type_, kw.get("track_id"))); return True

    async def tracks_download_info(self, track_id, get_direct_links=False):
        return [NS(codec="mp3", bitrate_in_kbps=320, preview=False, direct_link=f"url{track_id}")]

    async def users_likes_tracks_add(self, track_id): self.liked_add.append(track_id); return True
    async def users_likes_tracks_remove(self, track_id): self.liked_add.remove(track_id); return True
    async def users_dislikes_tracks_add(self, track_id): self.disliked.append(track_id); return True

    async def search(self, text, type_="all"):
        self.searched.append((text, type_))
        return NS(tracks=NS(results=[track(900), track(901)]))
