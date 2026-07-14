from __future__ import annotations

from fastapi.templating import Jinja2Templates

from app.config import ROOT_DIR, get_config
from app.models import now_utc

templates = Jinja2Templates(directory=str(ROOT_DIR / "app" / "templates"))
templates.env.globals["app_config"] = get_config
templates.env.globals["now_utc"] = now_utc
