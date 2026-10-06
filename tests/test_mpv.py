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

async def test_command_after_mpv_killed(tmp_path):
    """Command raises MpvError promptly after mpv is killed."""
    events = []
    async def on_event(e): events.append(e)
    mpv = Mpv(str(tmp_path / "mpv.sock"), on_event)
    await mpv.start()
    try:
        mpv.proc.kill()
        await asyncio.sleep(0.1)
        with pytest.raises(MpvError):
            await asyncio.wait_for(mpv.command("get_property", "idle-active"), timeout=2.0)
    finally:
        await mpv.stop()

async def test_run_forever_restarts(tmp_path):
    """run_forever restarts mpv after process dies and calls on_restart."""
    events = []
    restarts = []
    async def on_event(e): events.append(e)
    async def on_restart(): restarts.append(True)

    mpv = Mpv(str(tmp_path / "mpv.sock"), on_event)

    # Start mpv first, before creating run_forever task
    await mpv.start()
    initial_pid = mpv.proc.pid

    # Now create the run_forever supervisor
    run_task = asyncio.create_task(mpv.run_forever(on_restart))

    try:
        await asyncio.sleep(0.2)

        # Kill mpv and wait for restart
        mpv.proc.kill()
        await asyncio.sleep(0.2)

        # Wait for restart callback to be called
        for _ in range(100):
            if restarts:
                break
            await asyncio.sleep(0.1)

        assert len(restarts) >= 1
        # After restart, proc should be running
        assert mpv.proc is not None
        assert mpv.proc.returncode is None
        assert mpv.proc.pid != initial_pid
    finally:
        run_task.cancel()
        try:
            await run_task
        except asyncio.CancelledError:
            pass
        await mpv.stop()

async def test_dispatcher_catches_exceptions(tmp_path):
    """Dispatcher catches and logs exceptions from on_event without stopping."""
    events = []

    async def on_event(e):
        events.append(e)
        if len(events) == 1:
            raise ValueError("test error")

    mpv = Mpv(str(tmp_path / "mpv.sock"), on_event)
    await mpv.start()
    try:
        await mpv.command("set_property", "pause", True)
        await asyncio.sleep(0.2)
        await mpv.command("set_property", "pause", False)
        await asyncio.sleep(0.2)
        # Even though first event raised, second event should still fire
        assert len(events) >= 2
    finally:
        await mpv.stop()

async def test_on_event_awaits_command_completes(tmp_path):
    """on_event can await mpv.command during property-change event without deadlock."""
    command_completed = asyncio.Event()

    async def on_event(e):
        if e.get("event") == "property-change" and e.get("name") == "pause":
            # on_event awaits a command — should complete without deadlock
            result = await mpv.command("get_property", "idle-active")
            assert result is True
            command_completed.set()

    mpv = Mpv(str(tmp_path / "mpv.sock"), on_event)
    await mpv.start()
    try:
        await mpv.command("set_property", "pause", True)
        # Wait for on_event's command to complete (timeout proves no deadlock)
        await asyncio.wait_for(command_completed.wait(), timeout=3.0)
    finally:
        await mpv.stop()
