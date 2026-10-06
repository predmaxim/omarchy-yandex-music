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
    d = Daemon(make_client, lambda c: Player(c, FakeMpv(), lambda: None), tmp_path / "token", str(tmp_path / "qr.png"))
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
