"""User-level credential storage, independent of the current checkout."""
import fcntl
import json
import os
import stat
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


def credential_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    if not root.is_absolute():
        raise ValueError("XDG_CONFIG_HOME must be an absolute path.")
    return root / "reviso" / "credentials.json"


def read_credentials() -> dict:
    try:
        fd = os.open(credential_path(), os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {}
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Reviso credentials must be an owner-only regular file (chmod 600).")
        data = json.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get("servers", {}), dict):
        raise ValueError("Invalid Reviso credentials file; repair or remove it before login.")
    return data


@contextmanager
def credential_lock():
    path = credential_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("Reviso credential directory must be owned and writable only by you.")
    fd = os.open(path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Another Reviso process is updating credentials; retry.") from None
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


def write_credentials(data: dict) -> None:
    path = credential_path()
    fd, name = tempfile.mkstemp(prefix=".credentials-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)
