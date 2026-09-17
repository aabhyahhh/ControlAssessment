from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import close_pool, run_migrations
from app.routes import auth, chat, evidence, export, justification, phases, projects, upload


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    run_migrations()
    yield
    close_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ControlAssessment API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(chat.router)
    app.include_router(upload.router)
    app.include_router(evidence.router)
    app.include_router(justification.router)
    app.include_router(justification.public_router)
    app.include_router(phases.router)
    app.include_router(export.router)

    return app


app = create_app()
