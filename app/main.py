"""D&D VTT — FastAPI entry point."""
import asyncio
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import buildinfo, db, rooms, ws
from .room import net

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
# User uploads live in the PERSISTENT data tree, never in the (replaceable)
# app tree / container filesystem. Same public URL (/uploads/...) as before.
UPLOADS_DIR = os.path.join(db.DATA_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

logging.basicConfig(
    level=os.environ.get("VTT_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("vtt")

app = FastAPI(title="D&D VTT")


@app.on_event("startup")
async def startup():
    db.init_db()
    net.LOOP = asyncio.get_running_loop()
    # The running frontend generation must be identifiable from server log,
    # /api/build and the browser console (D78 — mixed-bundle black-canvas saga).
    log.info("BUILD %s", buildinfo.token())


@app.middleware("http")
async def no_cache_frontend(request: Request, call_next):
    # Bootstrap HTML and app assets are cheap to revalidate; caching them is
    # exactly what let browsers mix script generations after a rebuild (D78).
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    # Full trace goes to the server log; the client only ever sees a generic error.
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})



app.include_router(rooms.router)
app.include_router(ws.router)
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    # index.html carries the __BUILDTOKEN__ placeholder in every asset URL and
    # in the inline window.__BUILD__ stamp; replacing it binds the page to this
    # exact frontend generation (D78). The placeholder must not appear inside
    # the identifier window.__BUILD__ itself, hence the distinct spelling.
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    return HTMLResponse(html.replace("__BUILDTOKEN__", buildinfo.token()))


@app.get("/api/build")
def build():
    # Diagnostic identity only: build token + content hashes of owned assets.
    # No paths, sizes, environment or runtime data.
    return {"build": buildinfo.token(), "files": buildinfo.file_hashes()}


@app.get("/api/health")
def health():
    return {"ok": True}
