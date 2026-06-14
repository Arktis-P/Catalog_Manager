import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import catalog, characters, series
from app.routers import settings as settings_router
from app.services.seed_service import seed_demo_data


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_demo_data()
    yield


app = FastAPI(
    title="Catalogue Manager",
    description="Danbooru character image catalog management application",
    version="0.1.0",
    lifespan=lifespan,
)

allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(series.router, prefix="/api")
app.include_router(catalog.router, prefix="/api")
app.include_router(characters.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")


@app.get("/api/health")
def health_check():
    gui_dist = settings.frontend_dist_dir
    gui_ready = bool(gui_dist and gui_dist.exists() and (gui_dist / "index.html").exists())
    return {
        "status": "ok",
        "input_dir": str(settings.input_dir),
        "output_dir": str(settings.output_dir),
        "serve_gui": settings.serve_gui,
        "gui_ready": gui_ready,
    }


def mount_gui() -> None:
    dist_dir = settings.frontend_dist_dir
    if not dist_dir or not dist_dir.exists():
        return

    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def serve_index():
        return FileResponse(dist_dir / "index.html")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            return {"detail": "Not Found"}
        candidate = dist_dir / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist_dir / "index.html")


if settings.serve_gui or os.getenv("CATALOGUE_SERVE_GUI") == "1":
    settings.serve_gui = True
    mount_gui()
