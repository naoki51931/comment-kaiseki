from fastapi import APIRouter

from app.api.routes import admin, auth, comments, games, health, rewards, search, skill_estimation, subscriptions


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/api/auth", tags=["auth"])
api_router.include_router(games.router, prefix="/api/games", tags=["games"])
api_router.include_router(comments.router, prefix="/api/games", tags=["comments"])
api_router.include_router(admin.router, prefix="/api/admin", tags=["admin"])
api_router.include_router(rewards.router, prefix="/api/rewards", tags=["rewards"])
api_router.include_router(subscriptions.router, prefix="/api/ai-access", tags=["ai-access"])
api_router.include_router(search.router, prefix="/api/search", tags=["search"])
api_router.include_router(skill_estimation.router, prefix="/api/skill-estimation", tags=["skill-estimation"])
