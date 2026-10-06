"""ymd: the socket, subscribers and command dispatch.

Every state change is sent to all subscribers as one JSON line. API errors
never kill the daemon: 401 drops the token and asks to log in again, anything
else lands in `error` for the window's subtitle.
"""
import asyncio
import json
import logging
import subprocess

from yandex_music.exceptions import UnauthorizedError, YandexMusicError

from . import auth

log = logging.getLogger("ymd")


class Daemon:
    def __init__(self, make_client, player_factory, token_path=auth.TOKEN_PATH, qr_path=""):
        self.make_client, self.player_factory = make_client, player_factory
        self.token_path, self.qr_path = token_path, qr_path
        self.player, self.auth, self.login_info = None, "none", None
        self.subscribers, self.login_task, self.error = set(), None, None

    async def boot(self):
        token = auth.load_token(self.token_path)
        if not token:
            self.auth = "none"
            return
        self.player = self.player_factory(await self.make_client(token))
        self.player.notify = self.broadcast
        self.auth = "ok"
        try:
            await self.player.load_likes()
        except UnauthorizedError:
            self._logged_out()

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

    def _logged_out(self):
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
            self.auth = "pending"; self.broadcast()
            token = await auth.login(await self.make_client(None), shown)
            auth.save_token(token, self.token_path)
            self.login_info = None
            await self.boot()
        except Exception as e:
            log.warning("login failed: %s", e)
            self.auth, self.login_info, self.error = "none", None, str(e)
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
                if self.player: await self.player.stop()
                self._logged_out()
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
            self._logged_out()
        except (YandexMusicError, OSError) as e:
            log.warning("%s: %s", line.strip(), e)
            self.error = str(e)
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            self.error = "unknown command"
        self.broadcast()

    async def serve(self, sock_path):
        async def client(reader, writer):
            try:
                while line := await reader.readline():
                    if line.strip() == b'{"cmd":"subscribe"}':
                        self.subscribers.add(writer)
                        writer.write((json.dumps(self.state(), ensure_ascii=False) + "\n").encode())
                        continue
                    await self.handle(line.decode())
            except ConnectionError:
                pass
            finally:
                self.subscribers.discard(writer)
                writer.close()
        return await asyncio.start_unix_server(client, path=sock_path)
