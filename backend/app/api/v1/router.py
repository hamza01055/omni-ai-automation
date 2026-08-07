"""API v1 router assembly.

Routes are added here as each implementation step lands, so the mounted
surface always reflects what is actually built.
"""

from fastapi import APIRouter

from app.api.v1 import auth, conversations, internal

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(conversations.router)
api_router.include_router(internal.router)
