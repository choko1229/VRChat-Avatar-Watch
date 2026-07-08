from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import ROOT_DIR, get_config
from app.database import init_db, session_scope
from app.routers import admin, api, auth, public, setup
from app.services.crawl_log_service import mark_stale_running_logs
from app.services.scheduler import start_scheduler
from app.services.seed import seed_defaults
from app.templating import templates

SETUP_ALLOWED_PATHS = {"/setup", "/api/health", "/favicon.ico"}


def should_redirect_to_setup(path: str, setup_complete: bool) -> bool:
    if setup_complete:
        return False
    if path in SETUP_ALLOWED_PATHS:
        return False
    return not path.startswith("/static/")


def create_app() -> FastAPI:
    config = get_config()
    app = FastAPI(title=config.site_name)
    app.add_middleware(SessionMiddleware, secret_key=config.session_secret, same_site="lax", https_only=False)
    app.mount("/static", StaticFiles(directory=str(ROOT_DIR / "app" / "static")), name="static")
    app.include_router(setup.router)
    app.include_router(auth.router)
    app.include_router(public.router)
    app.include_router(admin.router)
    app.include_router(api.router)

    @app.middleware("http")
    async def setup_gate(request: Request, call_next):
        if should_redirect_to_setup(request.url.path, get_config().setup_complete):
            return RedirectResponse("/setup", status_code=303)
        return await call_next(request)

    @app.on_event("startup")
    def startup() -> None:
        init_db()
        with session_scope() as db:
            mark_stale_running_logs(db)
            seed_defaults(db)
        if get_config().setup_complete:
            start_scheduler()

    @app.exception_handler(404)
    async def not_found(request: Request, exc) -> HTMLResponse:
        return templates.TemplateResponse(request, "error.html", {"message": "ページが見つかりません"}, status_code=404)

    return app


app = create_app()
