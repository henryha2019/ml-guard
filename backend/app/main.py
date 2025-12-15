from fastapi import FastAPI
from app.api import api_router
from app.db.models import Base
from app.db.session import engine

def create_app() -> FastAPI:
    app = FastAPI(
        title="ML Guard",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    @app.on_event("startup")
    def _startup():
        Base.metadata.create_all(bind=engine)

    app.include_router(api_router)
    return app

app = create_app()
