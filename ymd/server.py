"""ymd: the socket, subscribers and command dispatch.

Every state change is sent to all subscribers as one JSON line. API errors
never kill the daemon: 401 drops the token and asks to log in again, anything
else lands in `error` for the window's subtitle.
"""
import asyncio
import json
import logging
import subprocess

from yandex_music.exceptions import DeviceAuthError, UnauthorizedError, YandexMusicError

from . import auth
from .mpv import MpvError

log = logging.getLogger("ymd")


class Daemon:
    def __init__(self, make_client, player_factory, token_path=auth.TOKEN_PATH, qr_path=""):
        self.make_client, self.player_factory = make_client, player_factory
        self.token_path, self.qr_path = token_path, qr_path
        self.player, self.auth, self.login_info = None, "none", None
        self.subscribers, self.login_task, self.error = set(), None, None
        self.retry_task, self.retry_s = None, 10

    async def boot(self):
        self._cancel_retry()
        if not await self._try_boot():
            self.retry_task = asyncio.create_task(self._retry())

    def _cancel_retry(self):
        if self.retry_task and self.retry_task is not asyncio.current_task():
            self.retry_task.cancel()
        self.retry_task = None

    async def _retry(self):
        while True:
            await asyncio.sleep(self.retry_s)
            if await self._try_boot():
                self.broadcast()
                return

    async def _try_boot(self):
        """True when done (booted, no token, or 401); False when worth retrying."""
        token = auth.load_token(self.token_path)
        if not token:
            self.auth = "none"
            return True
        try:
            self.player = self.player_factory(await self.make_client(token))
            self.player.notify = self.broadcast
            await self.player.load_likes()
        except UnauthorizedError:
            await self._logged_out()
            return True
        except (YandexMusicError, OSError) as e:
            log.warning("boot failed, will retry: %s", e)
            self.player, self.auth, self.error = None, "none", str(e)
            return False
        self.auth, self.error = "ok", None
        return True

    def state(self):
        base = self.player.state() if self.player else {
            "source": {"type": "none", "title": "", "mood": ""}, "moods": [], "playing": False, "track": None,
            "queue": [], "index": -1, "search": {"text": "", "results": []}, "error": None}
        return dict(base, auth=self.auth, login=self.login_info, error=self.error or base["error"])

    def broadcast(self):
        line = (json.dumps(self.state(), ensure_ascii=False) + "\n").encode()
        for w in list(self.subscribers):
            try:
                w.write(line)
            except Exception:
                self.subscribers.discard(w)

    async def _logged_out(self):
        self._cancel_retry()
        if self.player:
            try:
                await self.player.mpv.command("stop")
            except Exception as e:
                log.warning("stop on logout failed: %s", e)
        auth.drop_token(self.token_path)
        self.auth, self.player = "none", None

    async def _login(self):
        def shown(url, code):
            try:
                qr = auth.qr(url, self.qr_path) if self.qr_path else ""
            except (subprocess.CalledProcessError, OSError) as e:
                log.warning("qr failed: %s", e)
                qr = ""
            self.login_info = {"url": url, "code": code, "qr": qr}
            self.broadcast()
        try:
            self._cancel_retry()
            if self.player:  # re-login: don't stack a second session on the old playlist
                try:
                    await self.player.mpv.command("stop")
                except Exception as e:
                    log.warning("stop on re-login failed: %s", e)
                self.player = None
            self.auth = "pending"; self.broadcast()
            token = await auth.login(await self.make_client(None), shown)
            auth.save_token(token, self.token_path)
            self.login_info = None
            await self.boot()
        except Exception as e:
            log.warning("login failed: %s", e)
            self.auth, self.login_info = "none", None
            self.error = "login code expired, try again" if isinstance(e, (DeviceAuthError, TimeoutError)) else str(e)
        self.broadcast()

    async def handle(self, line):
        self.error = None
        try:
            msg = json.loads(line)
            cmd = msg.get("cmd")
            if cmd == "login":
                if not self.login_task or self.login_task.done():
                    self.login_task = asyncio.create_task(self._login())
                return
            if cmd == "logout":
                await self._logged_out()
            elif not self.player:
                self.error = "not logged in"
            else:
                p = self.player
                actions = {
                    "play": lambda: p.play(int(msg["index"])),
                    "toggle": p.toggle, "stop": p.stop, "next": p.next, "prev": p.prev,
                    "like": p.like, "dislike": p.dislike,
                    "wave": lambda: p.start_wave(msg.get("mood")),
                    "wave-track": lambda: p.start_track_wave(str(msg["id"])),
                    "playlist": p.start_likes,
                    "search": lambda: p.search(str(msg.get("text", ""))),
                    "play-search": lambda: p.play_search(int(msg["index"])),
                }
                if cmd not in actions:
                    self.error = "unknown command"
                else:
                    await actions[cmd]()
        except UnauthorizedError:
            await self._logged_out()
        except (YandexMusicError, OSError, MpvError) as e:
            log.warning("%s: %s", line.strip(), e)
            self.error = str(e)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            self.error = "unknown command"
        self.broadcast()

    async def serve(self, sock_path):
        async def client(reader, writer):
            try:
                while line := await reader.readline():  # ValueError: over-limit line
                    if line.strip() == b'{"cmd":"subscribe"}':
                        self.subscribers.add(writer)
                        writer.write((json.dumps(self.state(), ensure_ascii=False) + "\n").encode())
                        continue
                    await self.handle(line.decode(errors="replace"))
            except (ConnectionError, ValueError):  # ValueError: line over the stream limit
                pass
            finally:
                self.subscribers.discard(writer)
                writer.close()
        return await asyncio.start_unix_server(client, path=sock_path)
