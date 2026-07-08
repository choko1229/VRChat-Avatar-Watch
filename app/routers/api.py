from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ErrorLog
from app.security import require_admin

router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/admin/health")
def admin_health(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    return {"ok": True, "admin": True}
