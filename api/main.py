"""
FastAPI application factory for the Deadline Manager REST API.

The app is created by `create_app()` so it can be imported in tests without
triggering side effects.  `bot.py` calls `create_app()` and passes the result
to uvicorn alongside the Discord bot.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import deadlines, guild


def create_app() -> FastAPI:
    app = FastAPI(
        title="Deadline Manager API",
        description=(
            "REST API for the Deadline Manager Discord bot. "
            "Authenticate with a Discord OAuth2 Bearer token."
        ),
        version="1.0.0",
    )

    # Allow requests from any origin so the Raycast extension (which has no
    # fixed origin) can reach the API regardless of where it is deployed.
    app.add_middleware(
        CORSMiddleware,  # ty: ignore[invalid-argument-type]
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(deadlines.router)
    app.include_router(guild.router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
