import asyncio, json
from yandex_music.exceptions import UnauthorizedError
from ymd.server import Daemon
from ymd import auth
from tests.fakes import FakeApi, FakeMpv
from ymd.player import Player


def daemon(tmp_path, token="tok"):
    if token: auth.save_token(token, tmp_path / "token")
    api = FakeApi()
    async def make_client(tok): return api
    d = Daemon(make_client, lambda c: Player(c, FakeMpv(), lambda: None, cache_dir=tmp_path / "tracks", download=lambda u, p: 1 / 0), tmp_path / "token", str(tmp_path / "qr.png"))
    return d, api


async def test_no_token_means_auth_none(tmp_path):
    d, _ = daemon(tmp_path, token=None)
    await d.boot()
    assert d.state()["auth"] == "none" and d.state()["track"] is None


async def test_commands_reach_player(tmp_path):
    d, api = daemon(tmp_path)
    await d.boot()
    await d.handle('{"cmd":"wave","mood":"fun"}')
    assert api.settings[-1][1] == "fun" and d.state()["source"]["type"] == "wave"
    await d.handle('{"cmd":"wave-track","id":"101"}')
    assert d.state()["source"]["type"] == "track-wave"
    await d.handle('{"cmd":"search","text":"кино"}')
    await d.handle('{"cmd":"play-search","index":0}')
    assert d.state()["source"]["type"] == "search"


async def test_bad_line_keeps_connection(tmp_path):
    d, _ = daemon(tmp_path)
    await d.boot()
    await d.handle("{broken")
    await d.handle('{"cmd":"nope"}')
    assert d.state()["error"] == "unknown command"


async def test_unauthorized_drops_token(tmp_path):
    d, api = daemon(tmp_path)
    await d.boot()
    async def boom(*a, **k): raise UnauthorizedError("401")
    api.users_likes_tracks = boom
    d.player.like_ids_at = None   # ids older than 5 minutes are refetched
    await d.handle('{"cmd":"playlist"}')
    assert d.state()["auth"] == "none" and auth.load_token(tmp_path / "token") is None


async def test_socket_subscribe_gets_state(tmp_path):
    d, _ = daemon(tmp_path)
    await d.boot()
    sock = str(tmp_path / "ymd.sock")
    server = await d.serve(sock)
    r, w = await asyncio.open_unix_connection(sock)
    w.write(b'{"cmd":"subscribe"}\n'); await w.drain()
    first = json.loads(await asyncio.wait_for(r.readline(), 2))
    assert first["auth"] == "ok"
    w.write(b'{"cmd":"playlist"}\n'); await w.drain()
    nxt = json.loads(await asyncio.wait_for(r.readline(), 2))
    assert nxt["source"]["type"] == "likes"
    w.close(); server.close()


async def test_login_survives_qr_failure(tmp_path, monkeypatch):
    d, api = daemon(tmp_path, token=None)
    def bad_qr(url, path): raise OSError("no qrencode")
    async def fake_login(client, shown):
        shown("http://u", "CODE"); return "newtok"
    monkeypatch.setattr(auth, "qr", bad_qr)
    monkeypatch.setattr(auth, "login", fake_login)
    await d._login()
    assert d.auth == "ok" and auth.load_token(tmp_path / "token") == "newtok"


async def test_mpv_error_keeps_connection(tmp_path):
    from ymd.mpv import MpvError
    d, _ = daemon(tmp_path)
    await d.boot()
    async def boom(*a): raise MpvError("mpv not running")
    d.player.mpv.command = boom
    sock = str(tmp_path / "ymd.sock")
    server = await d.serve(sock)
    r, w = await asyncio.open_unix_connection(sock)
    w.write(b'{"cmd":"subscribe"}\n'); await r.readline()
    w.write(b'{"cmd":"next"}\n'); await w.drain()
    assert "mpv" in json.loads(await asyncio.wait_for(r.readline(), 2))["error"]
    w.write(b'{"cmd":"logout"}\n'); await w.drain()
    assert json.loads(await asyncio.wait_for(r.readline(), 2))["auth"] == "none"
    assert auth.load_token(tmp_path / "token") is None
    w.close(); server.close()


async def test_boot_unauthorized_drops_token(tmp_path):
    d, _ = daemon(tmp_path)
    async def make_client(tok): raise UnauthorizedError("401")
    d.make_client = make_client
    await d.boot()
    assert d.auth == "none" and auth.load_token(tmp_path / "token") is None and d.retry_task is None


async def test_boot_network_error_retries(tmp_path):
    from yandex_music.exceptions import NetworkError
    d, api = daemon(tmp_path)
    d.retry_s = 0.01
    fail = [True]
    async def make_client(tok):
        if fail[0]: raise NetworkError("down")
        return api
    d.make_client = make_client
    await d.boot()
    assert d.auth == "none" and d.error and auth.load_token(tmp_path / "token") == "tok"
    fail[0] = False
    await asyncio.wait_for(d.retry_task, 2)
    assert d.auth == "ok" and d.error is None


async def test_invalid_utf8_line_survives(tmp_path):
    d, _ = daemon(tmp_path)
    await d.boot()
    sock = str(tmp_path / "ymd.sock")
    server = await d.serve(sock)
    r, w = await asyncio.open_unix_connection(sock)
    w.write(b'{"cmd":"subscribe"}\n'); await r.readline()
    w.write(b'\xff\xfe\n'); await w.drain()
    assert json.loads(await asyncio.wait_for(r.readline(), 2))["error"] == "unknown command"
    w.write(b'{"cmd":"playlist"}\n'); await w.drain()
    assert json.loads(await asyncio.wait_for(r.readline(), 2))["source"]["type"] == "likes"
    w.close(); server.close()


async def test_relogin_stops_old_player(tmp_path):
    d, api = daemon(tmp_path)
    await d.boot()
    old = d.player
    async def fake_login(client, shown): return "new"
    orig, auth.login = auth.login, fake_login
    try:
        await d._login()
    finally:
        auth.login = orig
    assert ("stop",) in old.mpv.calls and d.player is not old and d.state()["auth"] == "ok"


async def test_login_expired_code_message(tmp_path):
    from yandex_music.exceptions import DeviceAuthError
    d, api = daemon(tmp_path, token=None)
    async def bad(client, shown): raise DeviceAuthError("invalid_grant")
    orig, auth.login = auth.login, bad
    try:
        await d._login()
    finally:
        auth.login = orig
    assert d.state()["error"] == "login code expired, try again"


async def test_seek_command_and_state_fields(tmp_path):
    d, _ = daemon(tmp_path)
    await d.boot()
    await d.handle('{"cmd":"playlist"}'); await d.handle('{"cmd":"play","index":0}')
    await d.handle('{"cmd":"seek","seconds":42.5}')
    assert ("seek", 42.5, "absolute") in d.player.mpv.calls
    assert d.state()["position"] == 42.5 and "duration" in d.state() and d.state()["error"] is None
