from __future__ import annotations

from datetime import datetime

from fastapi.templating import Jinja2Templates

from app.config import ROOT_DIR, get_config
from app.models import ensure_utc_aware, now_utc


def elapsed_seconds(value: datetime | None) -> int:
    if not value:
        return 0
    return int((now_utc() - ensure_utc_aware(value)).total_seconds())


templates = Jinja2Templates(directory=str(ROOT_DIR / "app" / "templates"))
templates.env.globals["app_config"] = get_config
templates.env.globals["elapsed_seconds"] = elapsed_seconds
