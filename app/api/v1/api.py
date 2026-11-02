from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin_apps,
    admin_auth,
    articles_brief,
    chat_models,
    health,
    ingest_query,
    targets,
    webhook,
)

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(targets.router, tags=["targets"])
api_router.include_router(ingest_query.router, tags=["ingest_query"])
api_router.include_router(articles_brief.router, tags=["articles_brief"])
api_router.include_router(webhook.router, tags=["webhook"])
api_router.include_router(admin_auth.router, tags=["admin_auth"])
api_router.include_router(admin_apps.router, tags=["admin_apps"])
api_router.include_router(chat_models.router, tags=["chat_models"])
