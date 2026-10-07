from __future__ import annotations

import os
from pathlib import Path


def _get_root_dir() -> Path:
    """Return the project root, preferring APP_ROOT_DIR (set by launcher.py for EXE mode)."""
    env_root = os.environ.get("APP_ROOT_DIR", "").strip()
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[1]


def _load_env() -> dict[str, str]:
    env_path = _get_root_dir() / ".env"
    values = {
        "BASE_URL": "https://bdtyg.cugb.edu.cn/service/appointment/appointment",
        "TOKEN": "",
        "AES_KEY_ASCII": "0102030405060708",
        "AES_IV_ASCII": "0102030405060708",
        "PAY_PASSWORD": "",
        "APP_TIMEZONE": "Asia/Shanghai",
    }
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name in values:
            values[name] = value
    return values


_ENV = _load_env()

BASE_URL = _ENV["BASE_URL"].rstrip("/")
TOKEN = _ENV["TOKEN"].strip()
AES_KEY_ASCII = _ENV["AES_KEY_ASCII"]
AES_IV_ASCII = _ENV["AES_IV_ASCII"]
PAY_PASSWORD = _ENV["PAY_PASSWORD"].strip()
APP_TIMEZONE = _ENV["APP_TIMEZONE"].strip() or "Asia/Shanghai"

DEFAULT_NODEID = "889772856316272640"
PAYWAY = "77"
