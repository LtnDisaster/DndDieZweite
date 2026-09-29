"""D&D VTT — FastAPI entry point."""
import asyncio
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, rooms, ws
from .room import net

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

logging.basicConfig(
    level=os.environ.get("VTT_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("vtt")

app = FastAPI(title="D&D VTT")


@app.on_event("startup")
async def startup():
    db.init_db()
    os.makedirs(os.path.join(STATIC_DIR, "uploads"), exist_ok=True)
    net.LOOP = asyncio.get_running_loop()


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    # Full trace goes to the server log; the client only ever sees a generic error.
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})



app.include_router(rooms.router)
app.include_router(ws.router)
app.mount("/uploads", StaticFiles(directory=os.path.join(STATIC_DIR, "uploads")), name="uploads")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health")
def health():
    return {"ok": True}
