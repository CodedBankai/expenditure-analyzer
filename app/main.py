from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.core.session_store import session_store
from app.routes import analysis, session, upload

BASE_DIR = Path(__file__).resolve().parent
CLEANUP_INTERVAL_SECONDS = 60


async def _cleanup_loop():
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        session_store.purge_expired()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()


app = FastAPI(title="Expenditure Analyzer", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.include_router(upload.router)
app.include_router(session.router)
app.include_router(analysis.router)


@app.get("/health")
async def health():
    return {"status": "ok", "active_sessions": session_store.count()}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})
