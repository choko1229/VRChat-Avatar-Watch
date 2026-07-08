from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import URL


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
RUNTIME_CONFIG_PATH = DATA_DIR / "runtime_config.json"
SESSION_SECRET_PATH = DATA_DIR / "session_secret"


@dataclass(frozen=True)
class AppConfig:
    site_name: str
    web_port: int
    database_url: str
    session_secret: str
    setup_complete: bool


def _load_dotenv_port() -> int:
    env_path = ROOT_DIR / ".env"
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if line.startswith("WEB_PORT="):
                os.environ.setdefault("WEB_PORT", line.split("=", 1)[1].strip())
    # Pterodactyl eggs commonly expose SERVER_PORT or PORT. WEB_PORT remains the
    # documented .env key, but these fallbacks make the app easier to run there.
    return int(os.getenv("WEB_PORT") or os.getenv("SERVER_PORT") or os.getenv("PORT") or "49175")


def _load_runtime_config() -> dict:
    if not RUNTIME_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _session_secret() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SESSION_SECRET_PATH.exists():
        return SESSION_SECRET_PATH.read_text(encoding="utf-8").strip()
    secret = secrets.token_urlsafe(48)
    SESSION_SECRET_PATH.write_text(secret, encoding="utf-8")
    return secret


def mysql_url(host: str, port: str, database: str, user: str, password: str) -> str:
    return URL.create(
        "mysql+pymysql",
        username=user,
        password=password,
        host=host,
        port=int(port),
        database=database,
        query={"charset": "utf8mb4"},
    ).render_as_string(hide_password=False)


def get_config() -> AppConfig:
    runtime = _load_runtime_config()
    database_url = runtime.get("database_url") or f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}"
    return AppConfig(
        site_name=runtime.get("site_name", "VRChat Avatar Watch"),
        web_port=_load_dotenv_port(),
        database_url=database_url,
        session_secret=_session_secret(),
        setup_complete=bool(runtime.get("setup_complete")),
    )


def save_runtime_config(payload: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    current = _load_runtime_config()
    current.update(payload)
    RUNTIME_CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
