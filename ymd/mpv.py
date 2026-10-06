"""A child mpv driven over its JSON IPC socket.

Properties the player follows are observed once on connect; their changes and
mpv events (end-file, …) go to on_event. mpv-mpris is loaded explicitly
(--no-config skips /etc/mpv/scripts), so media keys reach this mpv as player
"mpv" via playerctl.
"""
import asyncio
import json
import os

MPRIS = "/usr/lib/mpv-mpris/mpris.so"
OBSERVED = ["playlist-pos", "pause", "time-pos", "idle-active"]


class MpvError(Exception):
    pass


class Mpv:
    def __init__(self, sock_path, on_event):
        self.sock_path, self.on_event = sock_path, on_event
        self.proc = self.reader = self.writer = self.task = None
        self.pending, self.next_id = {}, 0

    async def start(self):
        if os.path.exists(self.sock_path):
            os.unlink(self.sock_path)
        args = ["mpv", "--idle=yes", "--no-video", "--no-config", "--no-terminal",
                f"--input-ipc-server={self.sock_path}", "--title=ymd"]
        if os.path.exists(MPRIS):
            args.append(f"--script={MPRIS}")
        self.proc = await asyncio.create_subprocess_exec(*args)
        for _ in range(100):
            if os.path.exists(self.sock_path):
                break
            await asyncio.sleep(0.05)
        self.reader, self.writer = await asyncio.open_unix_connection(self.sock_path)
        self.task = asyncio.create_task(self._read())
        for n, name in enumerate(OBSERVED, 1):
            await self.command("observe_property", n, name)

    async def command(self, *args):
        self.next_id += 1
        rid = self.next_id
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        self.writer.write((json.dumps({"command": list(args), "request_id": rid}) + "\n").encode())
        await self.writer.drain()
        return await fut

    async def _read(self):
        while line := await self.reader.readline():
            msg = json.loads(line)
            if "event" in msg:
                await self.on_event(msg)
            elif (fut := self.pending.pop(msg.get("request_id"), None)) and not fut.done():
                if msg.get("error") == "success":
                    fut.set_result(msg.get("data"))
                else:
                    fut.set_exception(MpvError(f"{msg.get('error')}"))
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(MpvError("mpv exited"))
        self.pending.clear()

    async def run_forever(self, on_restart):
        """Restart mpv whenever it dies; on_restart re-loads the current track."""
        while True:
            await self.proc.wait()
            await asyncio.sleep(1)
            await self.start()
            await on_restart()

    async def stop(self):
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            await self.proc.wait()
