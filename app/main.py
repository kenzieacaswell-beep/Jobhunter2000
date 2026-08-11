import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.background import BackgroundScheduler

from .api import router
from .config import FRONTEND_DIST
from .db import get_settings, init_db
from .ingestion import refresh_all
from .gmail import connected as gmail_connected, send_digest

scheduler=BackgroundScheduler()

def scheduled_refresh():
    asyncio.run(refresh_all())
    recipient=get_settings().get("digest_recipient","")
    if recipient and gmail_connected():
        try: send_digest(recipient)
        except Exception: pass  # Recorded/visible connection state must not block ingestion.

@asynccontextmanager
async def lifespan(app:FastAPI):
    init_db(); hour=int(get_settings()["daily_run_hour"])
    scheduler.add_job(scheduled_refresh,"cron",hour=hour,id="daily-refresh",replace_existing=True,misfire_grace_time=86400)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)

app=FastAPI(title="Job Tracker",version="0.1.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173"],allow_methods=["*"],allow_headers=["*"])
app.include_router(router)

@app.get("/api/health")
def health(): return {"status":"ok"}

if FRONTEND_DIST.exists():
    app.mount("/assets",StaticFiles(directory=FRONTEND_DIST/"assets"),name="assets")
    @app.get("/{path:path}")
    def frontend(path:str):
        target=FRONTEND_DIST/path
        return FileResponse(target if target.is_file() else FRONTEND_DIST/"index.html")
