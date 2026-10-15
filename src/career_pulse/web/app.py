"""
CareerPulse Local FastAPI Application.
"""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from career_pulse.config import settings
from career_pulse.db.session import Database
from career_pulse.web.routes.companies import router as companies_router
from career_pulse.web.routes.filters import router as filters_router
from career_pulse.web.routes.jobs import router as jobs_router
from career_pulse.web.routes.scan import router as scan_router
from career_pulse.web.routes.telegram import router as telegram_router
from career_pulse.web.routes.scheduler import router as scheduler_router, get_global_scheduler

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables and WAL mode on startup
    db = Database(settings.db_path)
    await db.init_schema()

    # Start background scheduler
    scheduler = get_global_scheduler()
    scheduler.start()

    yield

    # Clean shutdown
    await scheduler.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="CareerPulse Dashboard",
        description="Local career portal monitor and Telegram alerting system",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount static assets
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Include REST API routers
    app.include_router(companies_router)
    app.include_router(filters_router)
    app.include_router(jobs_router)
    app.include_router(scan_router)
    app.include_router(telegram_router)
    app.include_router(scheduler_router)

    # Dashboard Shell Route
    @app.get("/", response_class=HTMLResponse)
    async def index():
        html_file = TEMPLATES_DIR / "index.html"
        if html_file.exists():
            return html_file.read_text(encoding="utf-8")
        return "<h1>CareerPulse</h1><p>Dashboard UI loading...</p>"

    return app


app = create_app()
