from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Avatar, ErrorLog
from app.security import require_admin
from app.templating import templates

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/avatars/suggest", response_class=HTMLResponse)
def avatars_suggest(request: Request, hint: str = "", db: Session = Depends(get_db)):
    hint = hint.strip()
    avatars = []
    if hint:
        like = f"%{hint}%"
        avatars = db.scalars(
            select(Avatar)
            .where(Avatar.is_active.is_(True), or_(Avatar.name.ilike(like), Avatar.slug.ilike(like)))
            .order_by(Avatar.name)
            .limit(10)
        ).all()
    return templates.TemplateResponse(request, "avatars/suggest_list.html", {"avatars": avatars, "hint": hint})


@router.get("/admin/health")
def admin_health(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    return {"ok": True, "admin": True}
