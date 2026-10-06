import asyncio
import logging
import os

from yandex_music import ClientAsync

from . import auth
from .mpv import Mpv
from .player import Player
from .server import Daemon

RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")


async def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    async def on_event(msg):
        if daemon.player:
            await daemon.player.on_event(msg)

    mpv = Mpv(f"{RUN}/ymd-mpv.sock", on_event)

    async def make_client(token):
        return await ClientAsync(token).init() if token else ClientAsync()

    daemon = Daemon(make_client, lambda c: Player(c, mpv, lambda: None), auth.TOKEN_PATH, f"{RUN}/ymd-login.png")
    await daemon.boot()
    sock = f"{RUN}/ymd.sock"
    if os.path.exists(sock):
        os.unlink(sock)
    await daemon.serve(sock)

    async def restarted():
        try:
            if daemon.player:
                await daemon.player.reload()
        except Exception:
            logging.getLogger("ymd").exception("reload after mpv restart failed")

    await mpv.run_forever(restarted)  # starts mpv itself, retrying until it is up


asyncio.run(main())
