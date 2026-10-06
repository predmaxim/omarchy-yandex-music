import asyncio
from ymd.mpv import Mpv, MpvError
import pytest

async def test_command_and_events(tmp_path):
    events = []
    async def on_event(e): events.append(e)
    mpv = Mpv(str(tmp_path / "mpv.sock"), on_event)
    await mpv.start()
    try:
        assert await mpv.command("get_property", "idle-active") is True
        with pytest.raises(MpvError):
            await mpv.command("get_property", "no-such-property")
        await mpv.command("set_property", "pause", True)
        await asyncio.sleep(0.2)
        assert any(e.get("name") == "pause" and e.get("data") is True for e in events)
    finally:
        await mpv.stop()
