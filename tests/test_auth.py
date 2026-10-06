import os, stat
from types import SimpleNamespace as NS
from ymd import auth


def test_token_roundtrip_with_private_mode(tmp_path):
    p = tmp_path / "d" / "token"
    assert auth.load_token(p) is None
    auth.save_token("abc", p)
    assert auth.load_token(p) == "abc"
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(p.parent).st_mode) == 0o700
    auth.drop_token(p)
    assert auth.load_token(p) is None
    auth.drop_token(p)                    # twice is fine


class FakeClient:
    def __init__(self, pending=2):
        self.pending, self.polls = pending, 0

    async def request_device_code(self, device_name=None):
        return NS(device_code="dc", user_code="K7Q2MX", verification_url="https://ya.ru/device", interval=5, expires_in=300)

    async def poll_device_token(self, device_code):
        assert device_code == "dc"
        self.polls += 1
        return None if self.polls <= self.pending else NS(access_token="tok")


async def test_login_polls_until_token():
    shown, slept = [], []
    async def sleep(s): slept.append(s)
    tok = await auth.login(FakeClient(), lambda url, code: shown.append((url, code)), sleep)
    assert tok == "tok" and shown == [("https://ya.ru/device", "K7Q2MX")] and slept == [5, 5]


async def test_login_gives_up_after_expiry():
    async def sleep(s): pass
    import pytest
    with pytest.raises(TimeoutError):
        await auth.login(FakeClient(pending=10**6), lambda *a: None, sleep)
