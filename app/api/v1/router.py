from fastapi import APIRouter

from app.api.v1 import analytics, health, tickets

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(tickets.router)
api_router.include_router(analytics.router)
