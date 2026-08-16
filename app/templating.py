from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import ROOT_DIR, get_config
from app.models import ensure_utc_aware, now_utc

_WHITESPACE_RE = re.compile(r"\s+")


def elapsed_seconds(value: datetime | None) -> int:
    if not value:
        return 0
    return int((now_utc() - ensure_utc_aware(value)).total_seconds())


def comma(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,}"
    return value


def truncate_text(value: str | None, length: int = 110) -> str:
    # For <meta name="description"> / OGP description - collapses newlines
    # so multi-line BOOTH item descriptions become one clean line, then cuts
    # to `length` chars (Google truncates around ~120 chars anyway).
    if not value:
        return ""
    collapsed = _WHITESPACE_RE.sub(" ", value).strip()
    if len(collapsed) <= length:
        return collapsed
    return collapsed[:length].rstrip() + "…"


def canonical_url(request: Request) -> str:
    # Drops query params (?sort=/?offset=/?q=...) so paginated/filtered
    # variants of the same listing all point at one canonical URL instead of
    # each being indexed as a separate page.
    return f"{request.url.scheme}://{request.url.netloc}{request.url.path}"


def json_ld(value) -> str:
    # Escaping "</" prevents a title/description containing "</script>" from
    # breaking out of the <script type="application/ld+json"> block.
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


templates = Jinja2Templates(directory=str(ROOT_DIR / "app" / "templates"))
templates.env.globals["app_config"] = get_config
templates.env.globals["elapsed_seconds"] = elapsed_seconds
templates.env.globals["canonical_url"] = canonical_url
templates.env.filters["comma"] = comma
templates.env.filters["truncate_text"] = truncate_text
templates.env.filters["json_ld"] = json_ld
