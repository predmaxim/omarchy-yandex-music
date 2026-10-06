"""A child mpv driven over its JSON IPC socket.

Properties the player follows are observed once on connect; their changes and
mpv events (end-file, …) go to on_event. mpv-mpris is loaded explicitly
(--no-config skips /etc/mpv/scripts), so media keys reach this mpv as player
"mpv" via playerctl.
"""
import asyncio
import json
import logging
import os

logger = logging.getLogger("ymd")

MPRIS = "/usr/lib/mpv-mpris/mpris.so"
OBSERVED = ["playlist-pos", "pause", "time-pos", "idle-active"]


class MpvError(Exception):
    pass


class Mpv:
    def __init__(self, sock_path, on_event):
        self.sock_path, self.on_event = sock_path, on_event
        self.proc = self.reader = self.writer = self.task = self.dispatcher = None
        self.pending, self.next_id = {}, 0
        self.event_queue = asyncio.Queue()

    async def start(self):
        if self.writer:
            self.writer.close()
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.dispatcher and not self.dispatcher.done():
            self.dispatcher.cancel()
            try:
                await self.dispatcher
            except asyncio.CancelledError:
                pass
        self.task = None
        self.dispatcher = None
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
        self.event_queue = asyncio.Queue()
        self.task = asyncio.create_task(self._read())
        self.dispatcher = asyncio.create_task(self._dispatch_events())
        for n, name in enumerate(OBSERVED, 1):
            await self.command("observe_property", n, name)

    async def command(self, *args):
        if not self.task or self.task.done():
            raise MpvError("mpv not running")
        self.next_id += 1
        rid = self.next_id
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        try:
            self.writer.write((json.dumps({"command": list(args), "request_id": rid}) + "\n").encode())
            await self.writer.drain()
        except Exception as e:
            self.pending.pop(rid, None)
            raise MpvError(f"mpv not running: {e}")
        return await fut

    async def _read(self):
        try:
            while line := await self.reader.readline():
                try:
                    msg = json.loads(line)
                    if "event" in msg:
                        await self.event_queue.put(msg)
                    elif (fut := self.pending.pop(msg.get("request_id"), None)) and not fut.done():
                        if msg.get("error") == "success":
                            fut.set_result(msg.get("data"))
                        else:
                            fut.set_exception(MpvError(f"{msg.get('error')}"))
                except (json.JSONDecodeError, Exception) as e:
                    logger.warning(f"Error processing mpv response: {e}")
        finally:
            for fut in self.pending.values():
                if not fut.done():
                    fut.set_exception(MpvError("mpv exited"))
            self.pending.clear()

    async def _dispatch_events(self):
        """Dispatch events from the queue to on_event, catching exceptions."""
        try:
            while True:
                msg = await self.event_queue.get()
                try:
                    await self.on_event(msg)
                except Exception as e:
                    logger.exception(f"Error in on_event: {e}")
        except asyncio.CancelledError:
            pass

    async def run_forever(self, on_restart):
        """Restart mpv whenever it dies; on_restart re-loads the current track.

        Note: cancel run_forever before calling stop() to avoid orphaned mpv processes.
        """
        while True:
            # Ensure mpv is started initially
            if not self.proc:
                while True:
                    try:
                        await self.start()
                        break
                    except Exception as e:
                        logger.warning(f"Failed to start mpv: {e}, retrying in 1s")
                        await asyncio.sleep(1)

            await self.proc.wait()
            await asyncio.sleep(1)

            # Restart after crash
            while True:
                try:
                    await self.start()
                    break
                except Exception as e:
                    logger.warning(f"Failed to start mpv: {e}, retrying in 1s")
                    await asyncio.sleep(1)
            await on_restart()

    async def stop(self):
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            await self.proc.wait()
