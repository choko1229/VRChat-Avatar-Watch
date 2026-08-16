from __future__ import annotations

from xml.sax.saxutils import escape

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.config import ROOT_DIR, get_config
from app.database import get_db, init_db, session_scope
from app.models import Avatar, BaseBody, FacetTag, Item, ensure_utc_aware
from app.routers import admin, api, auth, public, setup
from app.services.crawl_log_service import mark_stale_running_logs
from app.services.scheduler import start_scheduler
from app.services.seed import seed_defaults
from app.templating import templates

SETUP_ALLOWED_PATHS = {"/setup", "/api/health", "/favicon.ico", "/sw.js", "/robots.txt", "/sitemap.xml"}


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

    @app.get("/sw.js")
    def service_worker() -> FileResponse:
        # Served from root (not /static/sw.js) so its default scope covers
        # the whole site - a service worker can only control pages under
        # its own script's path unless the response also sets
        # Service-Worker-Allowed, which we set here too for good measure.
        return FileResponse(
            ROOT_DIR / "app" / "static" / "sw.js",
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
        )

    @app.get("/robots.txt")
    def robots_txt(request: Request) -> Response:
        base = f"{request.url.scheme}://{request.url.netloc}"
        body = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /me\n"
            "Disallow: /admin\n"
            "Disallow: /api/\n"
            f"Sitemap: {base}/sitemap.xml\n"
        )
        return Response(content=body, media_type="text/plain")

    @app.get("/sitemap.xml")
    def sitemap_xml(request: Request, db: Session = Depends(get_db)) -> Response:
        # Kept as a single file for now - Google's sitemap limit is 50,000
        # URLs / 50MB. If the item count ever approaches that, split this
        # into a sitemap index + per-range sitemap-items-N.xml files instead.
        base = f"{request.url.scheme}://{request.url.netloc}"
        urls: list[tuple[str, object]] = [
            ("/", None),
            ("/search", None),
            ("/sales", None),
            ("/free", None),
            ("/tools", None),
            ("/avatars", None),
            ("/base-bodies", None),
            ("/tags", None),
        ]
        for slug, updated_at in db.execute(select(Avatar.slug, Avatar.updated_at).where(Avatar.is_active.is_(True))):
            urls.append((f"/avatars/{slug}", updated_at))
        for slug, updated_at in db.execute(select(BaseBody.slug, BaseBody.updated_at)):
            urls.append((f"/base-bodies/{slug}", updated_at))
        for slug, updated_at in db.execute(select(FacetTag.slug, FacetTag.updated_at)):
            urls.append((f"/tags/{slug}", updated_at))
        for item_id, updated_at in db.execute(select(Item.id, Item.updated_at)):
            urls.append((f"/items/{item_id}", updated_at))

        entries = []
        for path, updated_at in urls:
            lastmod = f"<lastmod>{ensure_utc_aware(updated_at).date().isoformat()}</lastmod>" if updated_at else ""
            entries.append(f"<url><loc>{escape(base + path)}</loc>{lastmod}</url>")
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(entries)
            + "\n</urlset>"
        )
        return Response(content=xml, media_type="application/xml")

    return app


app = create_app()
