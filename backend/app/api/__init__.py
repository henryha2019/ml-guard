from fastapi import APIRouter
from app.api import events, metrics, projects

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(events.router)
api_router.include_router(metrics.router)
api_router.include_router(projects.router)