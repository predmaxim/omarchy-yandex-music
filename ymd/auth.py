"""OAuth token on disk (0600, never in git) and the device-code login."""
import asyncio
import os
import shutil
import subprocess
from pathlib import Path

TOKEN_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "predmaxim.yandex-music" / "token"


def load_token(path=TOKEN_PATH):
    try:
        return Path(path).read_text().strip() or None
    except FileNotFoundError:
        return None


def save_token(token, path=TOKEN_PATH):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)


def drop_token(path=TOKEN_PATH):
    Path(path).unlink(missing_ok=True)


async def login(client, on_code, sleep=asyncio.sleep):
    code = await client.request_device_code(device_name="Omarchy")
    on_code(code.verification_url, code.user_code)
    for _ in range(max(1, code.expires_in // code.interval)):
        token = await client.poll_device_token(code.device_code)
        if token:
            return token.access_token
        await sleep(code.interval)
    raise TimeoutError("device code expired")


def qr(url, path):
    if not shutil.which("qrencode"):
        return ""
    subprocess.run(["qrencode", "-o", path, "-s", "6", "-m", "1", url], check=True)
    return path
